def _validate_plan_structure(plan_text):

    if plan_text.strip().startswith("```"):
        plines = plan_text.strip().splitlines()
        if plines[0].startswith("```"):
            plines = plines[1:]
        if plines and plines[-1].startswith("```"):
            plines = plines[:-1]
        plan_text = "\n".join(plines).strip()
    import re
    required_headers = ["TARGET FILES", "TARGET SYMBOL", "ACCEPTANCE CRITERIA", "TARGETED TEST"]

    known_headers = ["TARGET FILES", "TARGET SYMBOL", "ACCEPTANCE CRITERIA", "TARGETED TEST", "IMPLEMENTATION STEPS", "RISKS", "OPEN QUESTIONS", "GOAL", "UNDERSTANDING", "PLAN"]
    headers_regex = "|".join(rf"^(?:#+\s+)?\**{h}s?\**[*:?]*" for h in known_headers)
    lookahead = rf"(?:^#+\s+|{headers_regex}|\Z)"
    
    def check_exists(text, req):
        # Match on the first significant word(s) to tolerate minor typos like
        # "CRITERA" vs "CRITERIA"; require at least the first two words to match.
        first_words = req.split()[:2]
        pattern = r"\s+".join(rf"(?:{w}\w*)" for w in first_words)
        return bool(re.search(rf"^(?:#+\s+)?\**{pattern}", text, re.IGNORECASE | re.MULTILINE))

    missing = [req for req in required_headers if not check_exists(plan_text, req)]
    if missing:
        raise ValueError(f"Plan is missing required explicit sections: {', '.join(missing)}")

    # Check semantic meaning (non-empty and not generic placeholders)
    def extract_section(text, header):
        # Use same fuzzy first-two-words pattern as check_exists
        first_words = header.split()[:2]
        pattern = r"\s+".join(rf"(?:{w}\w*)" for w in first_words)
        match = re.search(rf"^(?:#+\s+)?\**{pattern}\S*\s*(.*?)(?={lookahead})", text, re.DOTALL | re.MULTILINE | re.IGNORECASE)
        return match.group(1).strip() if match else ""

    for header in required_headers:
        val = extract_section(plan_text, header)
        if not val or val.lower() in ["none", "n/a", "unknown", "test/*", "run tests", "verify it works"]:
            if header == "TARGET SYMBOL" and val.lower() in ["n/a", "none"]:
                continue # Target symbol might not be applicable
            raise ValueError(f"Plan section {header} contains insufficient or generic content: '{val}'")

        if header == "TARGETED TEST":
            # Strip any trailing code-fence lines the model might have appended
            stripped_val = "\n".join(
                ln for ln in val.splitlines() if not ln.strip().startswith("```")
            ).strip()
            if "\n" in stripped_val:
                raise ValueError(f"TARGETED TEST must be a single executable command line, but found multiple lines:\n{stripped_val}")
            val = stripped_val  # use cleaned value for further checks

            val_lower = val.lower()
            if any(val_lower.startswith(w) for w in ["perform", "run", "execute", "use", "test "]):
                raise ValueError(f"TARGETED TEST must be a raw shell command, but starts with conversational prose: '{val}'")

            if "```" in val or "`" in val:
                raise ValueError(f"TARGETED TEST must be a raw shell command without markdown backticks: '{val}'")

            if val.startswith("#"):
                raise ValueError(f"TARGETED TEST cannot be a markdown heading: '{val}'")

import os
import json
import shutil
import yaml
import subprocess
from pathlib import Path
from src.database import get_connection
from src.workspace_manager import WORKSPACES_ROOT, create_worktree
from src.sandbox_runner import discover_and_run_tests

class OllamaUnavailableError(RuntimeError):
    pass


def list_local_models():
    """Return installed Ollama models as name/size records."""
    import requests

    try:
        resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
        if resp.status_code != 200:
            raise OllamaUnavailableError(
                f"Ollama model inventory failed with {resp.status_code}: {resp.text}"
            )
        return [
            {
                "name": model.get("name"),
                "size": model.get("size"),
            }
            for model in resp.json().get("models", [])
        ]
    except requests.exceptions.RequestException as exc:
        raise OllamaUnavailableError(
            f"Ollama model inventory is unreachable: {exc}"
        )


def select_local_model(available_memory_mb, models=None):
    """Select the default local model (llama3.2:3b) when it fits the memory budget.

    qwen3.5:9b is intentionally never selected by the automated path under any
    memory condition; it remains available only for explicit manual --model use.
    """
    if models is None:
        models = list_local_models()

    model_names = {model.get("name") for model in models}

    if "llama3.2:3b" in model_names and available_memory_mb >= 3072:
        return "llama3.2:3b"

    return None


def verify_local_provider():
    config_path = os.path.expanduser("~/.hermes/config.yaml")
    if not os.path.exists(config_path):
        raise RuntimeError("Hermes config not found. Please ensure Hermes is installed and configured.")

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    model_conf = config.get("model", {})
    if model_conf.get("default") != "llama3.2:3b":
        raise RuntimeError(f"Safety Error: Hermes model is not llama3.2:3b. Currently set to: {model_conf.get('default')}")

    provider = model_conf.get("provider", "")
    if provider not in ("custom", "local"):
        raise RuntimeError(f"Safety Error: Hermes provider is not local/custom. Currently set to: {provider}")

    base_url = model_conf.get("base_url", "http://127.0.0.1:11434/v1")
    model_name = model_conf.get("default")

    # Standardize the base URL for Ollama API by removing /v1 if present
    ollama_api_base = base_url.replace("/v1", "")

    import requests
    try:
        resp = requests.get(f"{ollama_api_base}/api/tags", timeout=5)
        if resp.status_code != 200:
            raise OllamaUnavailableError(f"Hermes inference provider failed with {resp.status_code}: {resp.text}")

        tags = resp.json().get("models", [])
        if not any(t.get("name") == model_name or t.get("name") == f"{model_name}:latest" for t in tags):
            raise RuntimeError(f"Model {model_name} is not installed in local Ollama.")

    except requests.exceptions.RequestException as e:
        raise OllamaUnavailableError(f"Hermes inference provider is unreachable at {ollama_api_base}: {e}")

def get_issue_context(issue_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM issues WHERE issue_number = ? OR url = ? OR url LIKE ?", (issue_id, issue_id, f"%/{issue_id}"))
        row = cursor.fetchone()
        if not row:
            return None
        columns = [col[0] for col in cursor.description]
        return dict(zip(columns, row))

def get_issue_context_by_url(issue_url):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM issues WHERE url = ?", (issue_url,))
        row = cursor.fetchone()
        if not row:
            return None
        columns = [col[0] for col in cursor.description]
        return dict(zip(columns, row))


def get_repo_analysis(repo_name):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM repository_analysis WHERE repo_name = ?", (repo_name,))
        row = cursor.fetchone()
        if not row:
            return None
        columns = [col[0] for col in cursor.description]
        return dict(zip(columns, row))

def get_reports_dir(org, repo, issue_id):
    reports_dir = WORKSPACES_ROOT / org / repo / "reports" / str(issue_id)
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir

def _hermes_runtime_home():
    """Workspace-local Hermes runtime home for the sandboxed child process.

    The DSH execution sandbox (workspace-write) only lets Hermes write under
    the session workspace, so ``~/.hermes/logs`` is EPERM for the child. By
    pointing HERMES_HOME into a workspace-local directory, Hermes keeps its
    logs/state under the writable root while preserving its provider/model
    behavior via the mirrored config.yaml below. Sandbox mode is unchanged.
    """
    return Path(__file__).resolve().parents[1] / ".hermes-runtime"


def _prepare_hermes_child_env():
    """Environment for the Hermes child process.

    Redirects HERMES_HOME to a workspace-local runtime directory and seeds it
    with the user's provider/model config (llama3.2:3b + custom/Ollama). Only
    config.yaml is mirrored — .env / auth.json (credentials) are never copied
    into the workspace.
    """
    runtime_home = _hermes_runtime_home()
    runtime_home.mkdir(parents=True, exist_ok=True)

    source_config = Path(os.path.expanduser("~/.hermes/config.yaml"))
    if source_config.exists():
        shutil.copyfile(source_config, runtime_home / "config.yaml")

    child_env = os.environ.copy()
    child_env["HERMES_HOME"] = str(runtime_home)

    # Isolate temporary files to the runtime directory so sandbox-exec allows them
    runtime_tmp = runtime_home / "tmp"
    runtime_tmp.mkdir(parents=True, exist_ok=True)
    child_env["TMPDIR"] = str(runtime_tmp)

    return child_env

def _inject_provider_entry(runtime_home, *, provider_id, model, base_url, api_key_env):
    """Register an endpoint-bearing execution provider in the mirrored runtime config.

    Adds a ``providers.<provider_id>`` entry to the workspace-local
    ``.hermes-runtime/config.yaml`` (the app-owned mirror of ``~/.hermes/config.yaml``)
    so the Hermes child can resolve it as a named custom provider via
    ``--provider <provider_id>``, and rewrites the root ``model:`` section to the
    same execution provider so the child config never points at a stale local
    endpoint. Only the provider identity, the endpoint URL, and the ENVIRONMENT
    VARIABLE NAME of its credential are written — the credential VALUE is never
    persisted; Hermes reads it at runtime from ``api_key_env`` in the inherited
    process environment.
    """
    import yaml

    config_path = Path(runtime_home) / "config.yaml"
    data = {}
    if config_path.exists():
        with open(config_path, "r") as f:
            data = yaml.safe_load(f) or {}

    providers = data.get("providers")
    if not isinstance(providers, dict):
        providers = {}
        data["providers"] = providers

    entry = {
        "name": provider_id,
        "api": base_url,
        "key_env": api_key_env,
        "enabled": True,
    }
    if model:
        entry["default_model"] = model
    providers[provider_id] = entry

    # Rewrite the root ``model:`` section to the execution provider as well.
    # The mirrored config otherwise still names the local/custom (Ollama)
    # endpoint from ~/.hermes/config.yaml; ``--provider`` overrides it at
    # runtime, but leaving a stale local base_url in the child config is what
    # previously sent ``opencode-zen/nemotron-3.5-lightning-free`` to Ollama. A provider-handoff run
    # must carry a single, unambiguous provider: the endpoint URL and the env
    # var NAME of the credential, never the credential value.
    root_model = {
        "provider": provider_id,
        "base_url": base_url,
    }
    if model:
        root_model["default"] = model
    data["model"] = root_model

    with open(config_path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def _classify_hermes_failure(stderr_text):
    """Return a structured category for known Hermes/provider failure modes.

    Used as the single source of truth for provider/model failures.
    Returns one of:
    - PROVIDER_RATE_LIMIT
    - PROVIDER_AUTH
    - PROVIDER_ACCESS
    - PROVIDER_TIMEOUT
    - PROVIDER_SERVER_ERROR
    - PROVIDER_UNAVAILABLE
    - IMPLEMENTATION_FAILURE
    - UNKNOWN
    """
    err = (stderr_text or "").lower()
    if not err.strip():
        return "UNKNOWN"

    if any(m in err for m in ("429", "cooldown", "rate limit", "rate_limit", "too many requests")):
        return "PROVIDER_RATE_LIMIT"

    if any(m in err for m in ("401", "402", "unauthorized", "invalid api key", "authentication failed", "billing", "credits exhausted", "payment required")):
        return "PROVIDER_AUTH"

    if any(m in err for m in ("403", "forbidden", "policy", "access restriction", "free tier can only be used from within opencode")):
        return "PROVIDER_ACCESS"

    if any(m in err for m in ("408", "504", "timeout", "read timeout", "gateway timeout", "connection timeout", "timeoutexpired", "timed out after")):
        return "PROVIDER_TIMEOUT"

    if any(m in err for m in ("400", "500", "501", "502", "503", "505", "internal server error", "bad gateway")):
        return "PROVIDER_SERVER_ERROR"

    if any(m in err for m in ("404", "model not found", "does not exist", "unreachable", "could not connect", "failed to connect", "connection refused", "connection reset", "name or service not known")):
        return "PROVIDER_UNAVAILABLE"

    # Distinguish syntax/guardrail/no-diff implementation failures vs just unknown errors
    if any(m in err for m in ("no files were changed", "guardrail", "no diff", "implementation agent returned successfully but no files were modified")):
        return "IMPLEMENTATION_FAILURE"

    return "UNKNOWN"


def run_hermes_oneshot(
    prompt,
    cwd=None,
    safe_mode=False,
    model=None,
    *,
    provider_id=None,
    base_url=None,
    api_key_env=None,
    timeout=900,
):
    """Run a single Hermes prompt in a sandboxed child process.

    Lightweight/local calls keep the historical invocation unchanged:
    ``hermes -z <prompt> [--model <model>]`` against the configured
    local/custom (Ollama) provider.

    When an explicit execution-provider configuration is supplied
    (``provider_id`` + ``base_url`` + ``api_key_env``), the provider is registered
    as a named custom provider inside the mirrored .hermes-runtime config and the
    invocation becomes ``hermes -z <prompt> --model <model> --provider <provider_id>``.
    The credential is never placed on the command line or written to config: the
    child reads it from the ``api_key_env`` environment variable at runtime,
    inherited from the Radar process environment via os.environ.copy().
    """
    import platform

    child_env = _prepare_hermes_child_env()

    cmd = ["hermes"]
    if cwd and platform.system() == "Darwin":
        runtime_home = child_env["HERMES_HOME"]
        cwd_real = os.path.realpath(str(cwd))
        runtime_real = os.path.realpath(str(runtime_home))
        sandbox_profile = (
            "(version 1) "
            "(allow default) "
            '(deny file-write* (subpath "/")) '
            f'(allow file-write* (subpath "{cwd_real}")) '
            f'(allow file-write* (subpath "{runtime_real}")) '
            '(allow file-write* (subpath "/dev"))'
        )
        cmd = ["sandbox-exec", "-p", sandbox_profile] + cmd

    if cwd:
        cmd.extend(["--in", str(cwd), "--no-restore-cwd"])
    cmd.extend(["-z", prompt])
    if model:
        cmd.extend(["--model", model])

    if provider_id:
        if not base_url or not api_key_env:
            raise ValueError(
                "provider_id requires base_url and api_key_env for a provider handoff"
            )
        _inject_provider_entry(
            child_env["HERMES_HOME"],
            provider_id=provider_id,
            model=model,
            base_url=base_url,
            api_key_env=api_key_env,
        )
        cmd.extend(["--provider", provider_id])

    try:
        kwargs = {
            "cwd": cwd,
            "capture_output": True,
            "text": True,
            "timeout": timeout,
            "env": child_env,
        }
        if os.name == "posix":
            kwargs["start_new_session"] = True

        result = subprocess.run(cmd, **kwargs)

        if result.returncode != 0:
            failure = _classify_hermes_failure(result.stderr)
            if failure != "UNKNOWN":
                raise RuntimeError(
                    f"[{failure}] Provider/Hermes execution failed.\nDetails: {result.stderr}"
                )
            raise RuntimeError(
                f"Hermes CLI failed with code {result.returncode}:\n{result.stderr}"
            )

        out = result.stdout.strip()
        if not out:
            raise RuntimeError("Malformed output: Hermes CLI returned empty response.")
        return out

    except subprocess.TimeoutExpired as exc:
        # Surface a real provider/model error when the child left one in the
        # captured output before the outer safety limit killed it; keep
        # the timeout as the outer limit (do not raise it).
        partial_stderr = getattr(exc, "stderr", None)
        if isinstance(partial_stderr, bytes):
            partial_stderr = partial_stderr.decode(errors="replace")
        failure = _classify_hermes_failure(partial_stderr)
        if failure != "UNKNOWN":
            snippet = (partial_stderr or "").strip()[-1500:]
            raise RuntimeError(
                f"Hermes CLI hit the {timeout}-second safety timeout, but the provider "
                f"reported a failure before that: {failure}\n"
                f"Captured stderr: {snippet}\n"
                f"The {timeout}s timeout is the outer safety net; the provider error above "
                "is why execution could not complete."
            )
        raise RuntimeError(
            f"Hermes CLI timed out after {timeout} seconds. Model execution might be stuck or too slow."
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Hermes CLI executable missing. Ensure Hermes is installed and in PATH."
        )

def research(issue_id_or_url):
    from src.run_log import log_event
    print(f"Running Real Hermes Research for Issue {issue_id_or_url}...")
    try:
        from src.autonomous_guard import get_hermes_execution_handoff

        execution_ok, selected_model, execution_reason, provider_config = (
            get_hermes_execution_handoff(task_type="heavy")
        )
        if not execution_ok:
            print(f"Research deferred: {execution_reason}")
            log_event(
                "hermes_research",
                "deferred",
                execution_reason,
                issue_id=issue_id_or_url if isinstance(issue_id_or_url, int) else None,
            )
            return False
    except Exception as e:
        print(f"Research failed: {e}")
        log_event(
            "hermes_research",
            "failed",
            f"Execution preflight failed: {e}",
            issue_id=issue_id_or_url if isinstance(issue_id_or_url, int) else None,
        )
        return False

    issue = get_issue_context(issue_id_or_url)
    if not issue:
        print(f"Issue {issue_id_or_url} not found.")
        log_event("hermes_research", "failed", f"Issue {issue_id_or_url} not found", issue_id=issue_id_or_url if isinstance(issue_id_or_url, int) else None)
        return False

    org = issue['org_slug']
    repo_name_short = issue['repo_name'].split('/')[1]
    issue_number = issue['issue_number']
    reports_dir = get_reports_dir(org, repo_name_short, issue_number)
    research_file = reports_dir / "research.md"
    raw_file = reports_dir / "research_raw.txt"

    repo_analysis = get_repo_analysis(issue['repo_name'])

    prompt = f"""You are a research agent for OSS Discovery Radar.
Analyze the following GitHub issue and repository context.
Output a structured Markdown research report with the following sections exactly:
- Issue summary
- Repository context
- Relevant files
- Related PRs/commits
- Possible root causes
- Potential approaches
- Constraints
- Unknowns
- Questions for maintainers
- Recommended next step

CRITICAL INSTRUCTIONS:
- You must distinguish FACT (verifiable from context), INFERENCE (your deduction), and UNCERTAINTY (missing info). Use these exact prefixes in your bullet points (e.g., "[FACT] The issue mentions...", "[INFERENCE] The bug might be in...", "[UNCERTAINTY] We don't know if...").
- Do not invent repository facts or files outside of the provided context. If evidence is insufficient, state it as [UNCERTAINTY].
- Carefully analyze the Discussion Context below. Distinguish between unresolved maintainer questions vs decisions already made, questions already answered by maintainers/contributors, or work already in progress.

CONTEXT:
Repository: {issue['repo_name']}
Organization: {issue['org_slug']}
Issue Title: {issue['title']}
Labels: {issue['labels']}
Status/Activity: {issue['activity_status']}
Contribution Score: {issue['contribution_value_score']}
GSoC Score: {issue['gsoc_preparation_score']}
Personal Fit Score: {issue['opportunity_score']}

Discussion Context:
{issue.get('discussion_context') or issue.get('body_preview') or 'No description provided.'}

"""
    if repo_analysis:
        prompt += f"""Repository Details:
Has README: {repo_analysis.get('has_readme', False)}
Has CONTRIBUTING: {repo_analysis.get('has_contributing', False)}
Test Frameworks: {repo_analysis.get('test_frameworks', '[]')}
Known AI Policy Constraints: No AI-generated code push without human review.
"""

    prompt += "\nOutput ONLY the Markdown report."

    try:
        try:
            gate_kwargs = {"safe_mode": True, "model": selected_model}
            if provider_config:
                gate_kwargs.update(_oneshot_provider_kwargs(provider_config))
            run_hermes_oneshot("Respond with exactly 'OK'.", timeout=60, **gate_kwargs)
        except Exception as gate_e:
            print(f"Research provider health check failed for {selected_model}: {gate_e}")
            print("Falling back to local safe research model (llama3.2:3b).")
            selected_model = "llama3.2:3b"
            provider_config = None

        response = run_hermes_oneshot(
            prompt,
            safe_mode=True,
            model=selected_model,
            **_oneshot_provider_kwargs(provider_config),
        )

        with open(raw_file, "w") as f:
            f.write(response)

        with open(research_file, "w") as f:
            f.write(response)

        print(f"Research saved to {research_file}")
        log_event("hermes_research", "success", f"Research complete and saved to {research_file}", issue_id=issue_number)
        return True
    except Exception as e:
        print(f"Research failed: {e}")
        log_event("hermes_research", "failed", f"Research failed: {str(e)}", issue_id=issue_number if 'issue_number' in locals() else None)

def plan(issue_id_or_url):
    from src.run_log import log_event
    print(f"Running Real Hermes Plan for Issue {issue_id_or_url}...")
    issue = get_issue_context(issue_id_or_url)
    if not issue:
        print(f"Issue {issue_id_or_url} not found.")
        log_event("hermes_plan", "failed", f"Issue {issue_id_or_url} not found", issue_id=issue_id_or_url if isinstance(issue_id_or_url, int) else None)
        return False

    # Planning is a reasoning-heavy task: use OmniRoute when available,
    # otherwise safe llama3.2:3b fallback. qwen3.5:9b is never auto-selected.
    task_type = "heavy"

    try:
        from src.autonomous_guard import get_hermes_execution_handoff

        execution_ok, selected_model, execution_reason, provider_config = (
            get_hermes_execution_handoff(task_type=task_type)
        )
        if not execution_ok:
            print(f"Plan deferred: {execution_reason}")
            log_event(
                "hermes_plan",
                "deferred",
                execution_reason,
                issue_id=issue_id_or_url if isinstance(issue_id_or_url, int) else None,
            )
            return False

        print(f"Running pre-inference health gate for plan model {selected_model}...")
        try:
            gate_kwargs = {"safe_mode": True, "model": selected_model}
            if provider_config:
                gate_kwargs.update(_oneshot_provider_kwargs(provider_config))
            run_hermes_oneshot("Respond with exactly 'OK'.", timeout=60, **gate_kwargs)
            print(f"Pre-inference health gate passed for {selected_model}.")
        except Exception as gate_e:
            print(f"Plan provider health check failed for {selected_model}: {gate_e}")
            print("Falling back to local safe planning model (llama3.2:3b).")
            selected_model = "llama3.2:3b"
            provider_config = None
    except Exception as e:
        print(f"Plan failed: {e}")
        log_event(
            "hermes_plan",
            "failed",
            f"Execution preflight failed: {e}",
            issue_id=issue_id_or_url if isinstance(issue_id_or_url, int) else None,
        )
        return False

    org = issue['org_slug']
    repo = issue['repo_name'].split('/')[1]
    issue_number = issue['issue_number']
    reports_dir = get_reports_dir(org, repo, issue_number)
    research_file = reports_dir / "research.md"
    plan_file = reports_dir / "plan.md"

    if not research_file.exists():
        print(f"Research report not found at {research_file}. Run research first.")
        log_event("hermes_plan", "failed", f"Research report not found", issue_id=issue_number)
        return False

    # If a valid plan already exists on disk, skip regeneration.
    if plan_file.exists():
        with open(plan_file, "r") as f:
            existing_plan = f.read()
        try:
            _validate_plan_structure(existing_plan)
            print(f"Valid plan already exists at {plan_file}. Skipping regeneration.")
            log_event("hermes_plan", "success", f"Pre-existing plan reused from {plan_file}", issue_id=issue_number)
            return True
        except Exception:
            print(f"Existing plan at {plan_file} failed validation. Regenerating...")

    with open(research_file, "r") as f:
        research_content = f.read()

    # Use a rigid fill-in-the-blank template so even llama3.2:3b can produce
    # output that passes validation without creative restructuring.
    prompt = f"""You are a planning agent. Fill in EACH section below using information
from the research report. Copy the section headers EXACTLY as shown. Do not rename,
reorder, or omit any section. Do not wrap your output in a code block.

## Goal
<one sentence goal>

## Understanding
<brief summary of the issue>

## TARGET FILES
<list one concrete file path per line, e.g. src/test/java/...CheckTest.java>

## TARGET SYMBOL
<concrete class or method name, or N/A>

## ACCEPTANCE CRITERIA
<bullet list of concrete pass/fail criteria>

## TARGETED TEST
<exactly one shell command, no backticks, e.g. ./mvnw test -Dtest=MyTestClass>

## Implementation steps
<numbered list>

## Risks
<bullet list>

## Open questions
<bullet list or None>

RESEARCH REPORT:
{research_content}

Fill in the template above. Output ONLY the filled template, no extra commentary.
"""


    # Attempt planning
    response = None
    try:
        response = run_hermes_oneshot(
            prompt,
            safe_mode=True,
            model=selected_model,
            **_oneshot_provider_kwargs(provider_config),
        )
        _validate_plan_structure(response)
    except Exception as e:
        print(f"Plan with {selected_model} failed validation or generation: {e}")
        if selected_model != "llama3.2:3b":
            print("Falling back to local llama3.2:3b for plan generation...")
            selected_model = "llama3.2:3b"
            provider_config = None
            # llama3.2:3b copies long inputs verbatim; use a minimal prompt with
            # truncated research so the model cannot confuse template with context.
            short_research = research_content[:1500].rstrip()
            if len(research_content) > 1500:
                short_research += "\n... [research truncated] ..."
            fallback_prompt = f"""Fill in EACH field below. Output ONLY these lines, nothing else.

## Goal
<one sentence>

## Understanding
<two sentences>

## TARGET FILES
<one concrete file path per line, e.g. src/test/java/com/puppycrawl/tools/checkstyle/checks/coding/EqualsHashCodeCheckTest.java>

## TARGET SYMBOL
<class or method name, or N/A>

## ACCEPTANCE CRITERIA
- <criterion 1>
- <criterion 2>

## TARGETED TEST
<one shell command with no backticks, e.g. ./mvnw test -Dtest=EqualsHashCodeCheckTest>

## Implementation steps
1. <step>

## Risks
- <risk>

## Open questions
- None

CONTEXT (use only to fill the fields above):
{short_research}
"""
            try:
                response = run_hermes_oneshot(
                    fallback_prompt,
                    safe_mode=True,
                    model=selected_model,
                    **_oneshot_provider_kwargs(provider_config),
                )
                _validate_plan_structure(response)
            except Exception as fb_e:
                print(f"Fallback plan also failed validation: {fb_e}\nRAW FALLBACK RESPONSE:\n{response}")
                log_event("hermes_plan", "failed", f"Fallback plan failed: {str(fb_e)}", issue_id=issue_number)
                return False
        else:
            print(f"RAW FALLBACK RESPONSE:\n{response}")
            log_event("hermes_plan", "failed", f"Plan failed: {str(e)}", issue_id=issue_number)
            return False

    with open(plan_file, "w") as f:
        f.write(response)

    print(f"Plan saved to {plan_file}")
    log_event("hermes_plan", "success", f"Plan complete and saved to {plan_file}", issue_id=issue_number)
    return True

def _oneshot_provider_kwargs(provider_config):
    """Map an execution-provider handoff dict onto run_hermes_oneshot() kwargs.

    Returns {} for the local/lightweight path so existing calls stay byte-identical.
    The config dict comes from get_hermes_execution_handoff() /
    get_omniroute_hermes_provider_config() and carries {provider_id, base_url,
    api_key_env} — never the credential value.
    """
    if not provider_config:
        return {}
    return {
        "provider_id": provider_config.get("provider_id"),
        "base_url": provider_config.get("base_url"),
        "api_key_env": provider_config.get("api_key_env"),
    }


def implement_issue_with_hermes(worktree_path, context, model=None, provider_config=None, telemetry=None):
    print(f"Running Hermes implementation in {worktree_path}...")
    try:
        verify_local_provider()
    except Exception as e:
        raise RuntimeError(f"Local provider verification failed: {e}")

    prompt = f"""You are an implementation agent. You are implementing ONE open-source issue in an isolated worktree.

WORKING DIRECTORY: {worktree_path}

CRITICAL SAFETY INSTRUCTIONS:
- Do not modify the user's main checkout.
- Make the smallest maintainable change that fully addresses the issue.
- Do not modify unrelated files or perform unrelated refactoring.
- Do not fabricate APIs or tests.
- Inspect the existing implementation before changing it.
- Use repository conventions.

CRITICAL IMPLEMENTATION INSTRUCTIONS:
- You are working in this EXACT directory: {worktree_path}
- This is the ONLY valid workspace. All file reads and writes MUST target this exact path. Do not rely on your assumed current working directory.
- 1. Inspect existing files before editing.
- 2. Preserve unrelated content. Make the smallest possible change.
- 3. Use targeted editor/file-edit tools (e.g. `sed`) or built-in file edit tools.
- 4. NEVER replace an entire file unless explicitly required.
- 5. NEVER use placeholder comments to stand in for omitted code (e.g. "// rest of file unchanged").
- 6. Do not touch unrelated files.
- 7. Run `git diff` and `git diff --check` before finishing to verify exactly which files were modified and that there are no whitespace errors.
- You MUST directly create and edit files inside the {worktree_path} directory.
- IMPORTANT CONSTRAINTS: To execute shell commands, you MUST use the `terminal` tool with ONLY the `command` parameter. Do NOT invent parameters like `output`. Emit a valid tool call, do not ask the user for permission.
- You MUST NOT return a patch, code block, explanation, or proposed diff as a substitute. You MUST apply the changes to the filesystem.
- Keep working until the requested implementation is actually present. Stop only after a real filesystem change exists.
- Add/update tests where appropriate.

CONTEXT:
{context}

Implement the change directly in {worktree_path} by writing the modified files, then verify with `git diff` before finishing. If you cannot write files, stop and say so explicitly — outputting a description or patch instead of applied edits is NOT an acceptable implementation.
"""

    prompt_chars = len(prompt)
    prompt_tokens = prompt_chars // 4

    print("TELEMETRY: Implementation Prompt Metrics:")
    print(f"  - character count: {prompt_chars}")
    print(f"  - approximate token count: {prompt_tokens}")
    if telemetry:
        for k, v in telemetry.items():
            print(f"  - {k}: {v}")

    response = run_hermes_oneshot(
        prompt,
        cwd=str(worktree_path),
        safe_mode=True,
        model=model,
        **_oneshot_provider_kwargs(provider_config),
    )

    # Post-execution verification: confirm the worktree was actually modified.
    # This catches the case where the agent described changes instead of applying
    # them, failing fast before the guardrail stage rather than falsely reporting
    # "Hermes applied initial implementation."
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(worktree_path),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        # Only tolerate a directory that is simply not a git repository (e.g.
        # unit tests using a bare tmp dir). Any other git failure means we
        # cannot verify the edit at all, so fail clearly instead of pretending
        # the response was an applied implementation.
        if "not a git repository" not in e.stderr.lower():
            raise RuntimeError(
                "Could not verify worktree edits after implementation: "
                f"{e.stderr.strip() or 'git status failed'}"
            ) from e
    else:
        if not status.stdout.strip():
            raise RuntimeError(
                "Implementation agent returned successfully but no files were "
                "modified in the worktree. The agent likely output a description "
                "instead of directly editing files.\n"
                "--- RAW RESPONSE ---\n"
                f"{response}\n"
                "--- END RAW RESPONSE ---"
            )

    return response

def repair_issue_with_hermes(worktree_path, context, failure_logs, model=None, provider_config=None):
    print(f"Running Hermes repair loop in {worktree_path}...")

    prompt = f"""You are a repair agent. The previous implementation for the issue failed validation.

CONTEXT:
{context}

FAILURE LOGS:
{failure_logs}

Please fix the implementation locally. Make the smallest maintainable change to pass the tests. Explain your assumptions.
"""

    response = run_hermes_oneshot(
        prompt,
        cwd=str(worktree_path),
        safe_mode=True,
        model=model,
        **_oneshot_provider_kwargs(provider_config),
    )
    return response
