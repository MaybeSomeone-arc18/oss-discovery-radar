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
    """Return (kind, user_message) for known Hermes/provider failure modes.

    Used by run_hermes_oneshot() so a child that exits (or is killed at the
    outer 900s timeout) with a clear provider/model error surfaces the actual
    stderr instead of a generic message. Returns None when the output does not
    match any known failure signature.
    """
    err = (stderr_text or "").lower()
    if not err.strip():
        return None
    if any(
        m in err
        for m in (
            "connection refused",
            "connection reset",
            "unreachable",
            "could not connect",
            "failed to connect",
            "name or service not known",
        )
    ):
        return (
            "unreachable",
            "Inference provider unreachable. Check that the active provider endpoint is running.",
        )
    if (
        "404" in err
        or "model not found" in err
        or "not available" in err
        or ("model" in err and "not found" in err)
        or "does not exist" in err
    ):
        return (
            "model",
            "Model unavailable on the active provider. Make sure the requested model is served.",
        )
    if any(
        m in err
        for m in ("401", "403", "unauthorized", "invalid api key", "authentication failed", "forbidden")
    ):
        return (
            "auth",
            "Inference provider authentication failed. Check the active provider's API key/credential.",
        )
    if "context length" in err or "context too small" in err or "context window" in err:
        return (
            "context",
            "Context too small. Adjust config or model parameters.",
        )
    return None


def run_hermes_oneshot(
    prompt,
    cwd=None,
    safe_mode=False,
    model=None,
    *,
    provider_id=None,
    base_url=None,
    api_key_env=None,
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
            "timeout": 900,
            "env": child_env,
        }
        if os.name == "posix":
            kwargs["start_new_session"] = True

        result = subprocess.run(cmd, **kwargs)

        if result.returncode != 0:
            failure = _classify_hermes_failure(result.stderr)
            if failure is not None:
                _kind, message = failure
                raise RuntimeError(
                    f"{message}\nDetails: {result.stderr}"
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
        # captured output before the outer 900s safety limit killed it; keep
        # 900s as the outer limit (do not raise it).
        partial_stderr = getattr(exc, "stderr", None)
        if isinstance(partial_stderr, bytes):
            partial_stderr = partial_stderr.decode(errors="replace")
        failure = _classify_hermes_failure(partial_stderr)
        if failure is not None:
            _kind, message = failure
            snippet = (partial_stderr or "").strip()[-1500:]
            raise RuntimeError(
                "Hermes CLI hit the 900-second safety timeout, but the provider "
                f"reported a failure before that: {message}\n"
                f"Captured stderr: {snippet}\n"
                "The 900s timeout is the outer safety net; the provider error above "
                "is why execution could not complete."
            )
        raise RuntimeError(
            "Hermes CLI timed out after 900 seconds. Model execution might be stuck or too slow."
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

    with open(research_file, "r") as f:
        research_content = f.read()

    prompt = f"""You are a planning agent for OSS Discovery Radar.
Based on the provided research report, create an implementation plan for the issue.

Output a structured Markdown plan with the following sections exactly:
- Goal
- Understanding
- Files likely to change
- Implementation steps
- Tests
- Risks
- Performance concerns
- Compatibility concerns
- Open questions

CRITICAL INSTRUCTIONS:
- Only plan changes; do not execute or write full code patches.
- Distinguish [FACT], [INFERENCE], and [UNCERTAINTY] where applicable.

RESEARCH REPORT:
{research_content}

Output ONLY the Markdown plan.
"""

    try:
        response = run_hermes_oneshot(
            prompt,
            safe_mode=True,
            model=selected_model,
            **_oneshot_provider_kwargs(provider_config),
        )

        with open(plan_file, "w") as f:
            f.write(response)

        print(f"Plan saved to {plan_file}")
        log_event("hermes_plan", "success", f"Plan complete and saved to {plan_file}", issue_id=issue_number)
        return True
    except Exception as e:
        print(f"Plan failed: {e}")
        log_event("hermes_plan", "failed", f"Plan failed: {str(e)}", issue_id=issue_number if 'issue_number' in locals() else None)
        return False

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


def implement_issue_with_hermes(worktree_path, context, model=None, provider_config=None):
    print(f"Running Hermes implementation in {worktree_path}...")
    try:
        verify_local_provider()
    except Exception as e:
        raise RuntimeError(f"Local provider verification failed: {e}")

    prompt = f"""You are an implementation agent. You are implementing ONE open-source issue in an isolated worktree.

CRITICAL SAFETY INSTRUCTIONS:
- Do not modify the user's main checkout.
- Make the smallest maintainable change that fully addresses the issue.
- Do not modify unrelated files or perform unrelated refactoring.
- Do not fabricate APIs or tests.
- Inspect the existing implementation before changing it.
- Use repository conventions.

CRITICAL IMPLEMENTATION INSTRUCTIONS:
- Work inside the provided isolated worktree (your current working directory). Never modify any other location.
- Inspect the existing code first: find and read the relevant files, then create/modify exactly the files required by the issue.
- You MUST directly create and edit files inside the current working directory (the isolated worktree).
- Use shell commands to write files (for example: cat > path/to/file << 'ENDOFFILE' ... ENDOFFILE), or the file tool if available.
- IMPORTANT CONSTRAINTS: To execute shell commands, you MUST use the `terminal` tool with ONLY the `command` parameter. Do NOT invent parameters like `output`. Emit a valid tool call, do not ask the user for permission.
- After making changes, run `git diff` and `git status` to verify exactly which files were modified.
- Do NOT output patches or descriptions instead of editing files — you MUST apply the changes to the filesystem.
- Add/update tests where appropriate.

CONTEXT:
{context}

Implement the change directly in the current directory by writing the modified files using shell commands, then verify with `git diff` before finishing. If you cannot write files, stop and say so explicitly — outputting a description or patch instead of applied edits is NOT an acceptable implementation.
"""

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
                "instead of directly editing files."
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
