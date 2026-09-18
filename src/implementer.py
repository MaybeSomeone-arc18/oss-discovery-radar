import os
import requests
import json
import subprocess
import yaml
from pathlib import Path
from src.workspace_manager import create_worktree, cleanup_worktree, WORKSPACES_ROOT
from src.hermes_agent import get_issue_context, get_issue_context_by_url, get_reports_dir, implement_issue_with_hermes, repair_issue_with_hermes, run_hermes_oneshot, _oneshot_provider_kwargs
from src.sandbox_runner import discover_and_run_tests
from src.opportunity_manager import transition_status
from src.autonomous_guard import get_hermes_execution_handoff

def get_agent_config():
    config_path = Path("config/agent.yaml")
    if config_path.exists():
        with open(config_path, "r") as f:
            return yaml.safe_load(f)
    return {}

def check_diff_guardrails(worktree_path):
    config = get_agent_config()
    max_files = config.get("max_changed_files", 5)
    max_lines = config.get("max_diff_lines", 500)

    try:
        # Check if any files changed
        status_proc = subprocess.run(["git", "status", "--porcelain"], cwd=str(worktree_path), capture_output=True, text=True, check=True)
        if not status_proc.stdout.strip():
            return False, "No files were changed."

        # Get diff stats
        stat_proc = subprocess.run(["git", "diff", "HEAD", "--stat"], cwd=str(worktree_path), capture_output=True, text=True, check=True)
        stat_output = stat_proc.stdout.strip()

        # Check files count
        changed_files_proc = subprocess.run(["git", "diff", "HEAD", "--name-only"], cwd=str(worktree_path), capture_output=True, text=True, check=True)
        changed_files = [f for f in changed_files_proc.stdout.strip().split('\n') if f]

        if len(changed_files) > max_files:
            return False, f"Too many files changed: {len(changed_files)} (max allowed: {max_files})"

        # Basic check for vendor/secrets
        for f in changed_files:
            f_lower = f.lower()
            if "vendor/" in f_lower or "node_modules/" in f_lower:
                return False, f"Vendor file modified: {f}"
            if "secret" in f_lower or ".env" in f_lower or "key" in f_lower:
                if not ("test" in f_lower or "mock" in f_lower):
                    return False, f"Potential secret file modified: {f}"

        # Count lines
        lines_proc = subprocess.run(["git", "diff", "HEAD"], cwd=str(worktree_path), capture_output=True, text=True, check=True)
        diff_lines = len(lines_proc.stdout.split('\n'))
        if diff_lines > max_lines:
            return False, f"Diff too large: {diff_lines} lines (max allowed: {max_lines})"

        # Check main branch modified
        branch_proc = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(worktree_path), capture_output=True, text=True, check=True)
        branch = branch_proc.stdout.strip()
        if branch in ["main", "master", "develop"]:
            return False, f"Modified default branch directly: {branch}"

        return True, "Guardrails passed."

    except subprocess.CalledProcessError as e:
        return False, f"Git command failed: {e.stderr}"

def create_patch(worktree_path, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Capture tracked files (staged and unstaged) without mutating index
        proc = subprocess.run(["git", "diff", "HEAD"], cwd=str(worktree_path), capture_output=True, text=True, check=True)
        diff_text = proc.stdout

        # Manually append untracked files
        proc_untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=str(worktree_path), capture_output=True, text=True, check=True)
        for f in proc_untracked.stdout.strip().split('\n'):
            if not f: continue
            file_path = worktree_path / f
            if file_path.is_file():
                diff_text += f"\n--- /dev/null\n+++ b/{f}\n@@ -0,0 +1 @@\n"
                try:
                    with open(file_path, 'r', errors='replace') as uf:
                        diff_text += "".join(f"+{line}" for line in uf)
                except Exception:
                    pass

        with open(output_path, "w") as f:
            f.write(diff_text)
        return True
    except subprocess.CalledProcessError:
        return False

def generate_reports(issue_id, worktree_path, reports_dir, test_results, diff_output, success, diff_stat=""):
    review_file = reports_dir / "review.md"
    implementation_file = reports_dir / "implementation.md"
    summary_file = reports_dir / "summary.md"

    # Final code review is reasoning-heavy: use the heavy route (OmniRoute
    # when available, else the existing 3B fallback). When routing defers,
    # fall back to the default local model exactly as before.
    review_model = None
    review_provider = None
    try:
        execution_ok, selected_model, _execution_reason, provider_config = (
            get_hermes_execution_handoff(task_type="heavy")
        )
        if execution_ok:
            review_model = selected_model
            review_provider = provider_config
    except Exception:
        review_model = None

    # Generate Review
    review_prompt = f"""You are a code reviewer.
Review the following local implementation diff and test results for Issue {issue_id}.

CRITICAL INSTRUCTIONS:
- Distinguish [FACT], [INFERENCE], and [UNCERTAINTY].
- Evaluate if the patch addresses the issue.
- Is the diff unnecessarily large?
- Are there unhandled edge cases?
- What should a human verify before submitting?
- Identify potential regressions, performance implications, and compatibility concerns.

TEST RESULTS:
{json.dumps(test_results, indent=2) if test_results else "No tests run."}

GIT DIFF:
{diff_output[:10000]}
"""
    try:
        review_response = run_hermes_oneshot(
            review_prompt,
            cwd=str(worktree_path),
            safe_mode=True,
            model=review_model,
            **_oneshot_provider_kwargs(review_provider),
        )
        with open(review_file, "w") as f:
            f.write(review_response)
    except Exception as e:
        with open(review_file, "w") as f:
            f.write(f"Failed to generate review: {e}")

    # Generate Implementation Report
    imp_prompt = f"""You are documenting the implementation for Issue {issue_id}.
Describe the approach taken, files changed, tests added, validation results, and any remaining uncertainty.
Do not generate the patch, just describe it.

CRITICAL INSTRUCTIONS:
- Describe ONLY what is supported by the provided diff and test results. Do not invent files, behavior, or changes.
- Distinguish [FACT], [INFERENCE], and [UNCERTAINTY].
- If the diff is empty, state explicitly that no changes were made.

TEST RESULTS: {json.dumps(test_results, indent=2) if test_results else "None"}

GIT DIFF:
{diff_output[:10000] if diff_output.strip() else "Empty diff. No files changed."}
"""
    try:
        imp_response = run_hermes_oneshot(imp_prompt, cwd=str(worktree_path), safe_mode=True)
        with open(implementation_file, "w") as f:
            f.write(imp_response)
    except Exception as e:
        with open(implementation_file, "w") as f:
            f.write(f"Failed to generate implementation report: {e}")

    # Generate Summary
    with open(summary_file, "w") as f:
        f.write(f"# Implementation Summary for Issue {issue_id}\n\n")
        f.write(f"**Status:** {'SUCCESS' if success else 'FAILED'}\n\n")
        f.write("## Check Artifacts\n")
        f.write(f"- Patch: `patch.diff`\n")
        f.write(f"- Review: `review.md`\n")
        f.write(f"- Details: `implementation.md`\n\n")
        if test_results:
            f.write("## Test Results\n")
            for t in test_results:
                f.write(f"- {t['framework']}: {'PASS' if t['result']['success'] else 'FAIL'}\n")
        f.write("\n## Next Steps\nReview the patch and tests before deciding to submit.\n")

def is_environment_failure(test_results):
    markers=("sdk location not found","android_home","command not found","permission denied","could not find java","java_home")
    for t in test_results or []:
        r=t.get("result",{})
        text=f"{r.get("stdout","")} {r.get("stderr","")}".lower()
        if any(m in text for m in markers): return True
    return False


def implement(issue_id_or_url):
    if isinstance(issue_id_or_url, str) and issue_id_or_url.startswith("http"):
        issue = get_issue_context_by_url(issue_id_or_url)
    else:
        issue = get_issue_context(issue_id_or_url)

    if not issue:
        print(f"Issue {issue_id_or_url} not found.")
        return False, None, ""

    issue_id = issue["issue_number"]

    org = issue['org_slug']
    repo = issue['repo_name'].split('/')[1]

    # Safeguard: verify against real GitHub
    try:
        api_url = f"https://api.github.com/repos/{org}/{repo}/issues/{issue_id}"
        resp = requests.get(api_url, timeout=10)
        if resp.status_code != 200:
            print(f"Safeguard failed: Issue {issue_id} not found on GitHub or API error.")
            return False, None, ""

        gh_issue = resp.json()
        # If our local title is a generic synthetic one and doesn't match the real one, fail.
        if issue['title'] != gh_issue.get('title') and (issue['title'].startswith('Issue ') or '2024-01-01' in str(issue.get('created_at'))):
            print("Safeguard failed: Local metadata appears synthetic or stale compared to real GitHub issue.")
            return False, None, ""
    except Exception as e:
        print(f"Safeguard error: Could not verify issue against GitHub: {e}")
        return False, None, ""

    execution_ok, selected_model, execution_reason, execution_provider = (
        get_hermes_execution_handoff(task_type="implementation")
    )
    if not execution_ok:
        print(f"Implementation deferred: {execution_reason}")
        return False, None, ""

    reports_dir = get_reports_dir(org, repo, issue_id)
    plan_file = reports_dir / "plan.md"
    if not plan_file.exists():
        print("Plan file not found. Run plan first.")
        return False, None, ""

    with open(plan_file, "r") as f:
        plan_content = f.read()

    with open(plan_file, "r") as f:
        plan_content = f.read()

    from src.opportunity_manager import (
        communication_allows_implementation,
        get_communication_state,
    )

    if not communication_allows_implementation(issue["url"]):
        communication_state = get_communication_state(issue["url"])
        status = (
            communication_state["communication_status"]
            if communication_state
            else "UNKNOWN"
        )
        print(
            f"Implementation blocked by communication gate: "
            f"status={status}. Human approval is required."
        )
        return False, None, ""

    transition_status(issue["url"], "IN_PROGRESS")

    # Create a temporary worktree just to get the base commit
    temp_worktree = create_worktree(org, repo, issue_id, branch_name=f"issue-{issue_id}-base")
    try:
        base_commit_proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(temp_worktree), capture_output=True, text=True, check=True)
        base_commit = base_commit_proc.stdout.strip()
        print(f"Base commit recorded: {base_commit}")
        with open(reports_dir / "base_commit.txt", "w") as f:
            f.write(base_commit)
    except subprocess.CalledProcessError as e:
        print(f"Failed to record base commit: {e}")
    finally:
        from src.workspace_manager import cleanup_worktree, get_base_repo_path
        cleanup_worktree(org, repo, issue_id)
        # Delete the temp branch
        subprocess.run(["git", "branch", "-D", f"issue-{issue_id}-base"], cwd=str(get_base_repo_path(org, repo)), capture_output=True)

    # Hide GitHub credentials
    original_environ = os.environ.copy()
    if 'GITHUB_TOKEN' in os.environ:
        del os.environ['GITHUB_TOKEN']
    if 'GH_TOKEN' in os.environ:
        del os.environ['GH_TOKEN']

    def extract_section(text, header):
        import re
        match = re.search(rf"{header}:?\s*(.*?)(?=(?:^[A-Z\s]+:|\Z))", text, re.DOTALL | re.MULTILINE)
        return match.group(1).strip() if match else "None specified"

    target_files = extract_section(plan_content, "TARGET FILES")
    target_symbol = extract_section(plan_content, "TARGET SYMBOL")
    acceptance_criteria = extract_section(plan_content, "ACCEPTANCE CRITERIA")
    targeted_test = extract_section(plan_content, "TARGETED TEST")

    context = f"""Issue Title: {issue['title']}
Body: {issue['body_preview']}

TARGET FILES:
{target_files}

TARGET SYMBOL:
{target_symbol}

ACCEPTANCE CRITERIA:
{acceptance_criteria}

TARGETED TEST:
{targeted_test}

PLAN:
{plan_content}"""

    from src.implementation_models import get_eligible_models, record_failure, record_success
    from src.omniroute import get_omniroute_hermes_provider_config

    eligible_models = get_eligible_models()
    if not eligible_models:
        print("Abort: No viable FREE implementation models available in registry.")
        transition_status(issue["url"], "IMPLEMENTATION_FAILED")
        os.environ.update(original_environ)
        return False, None, ""

    max_model_attempts = 3
    success = False
    test_results = None
    diff_stat = ""

    from src.workspace_manager import cleanup_worktree, get_base_repo_path

    def prepare_clean_worktree(attempt_suffix):
        cleanup_worktree(org, repo, issue_id)
        base_repo = get_base_repo_path(org, repo)
        branch = f"issue-{issue_id}-{attempt_suffix}"
        subprocess.run(["git", "branch", "-D", branch], cwd=str(base_repo), capture_output=True)
        wt = create_worktree(org, repo, issue_id, branch_name=branch)
        print(f"Isolated worktree ready at {wt} on branch {branch}.")
        return wt

    def preserve_patch(wt_path, r_dir, attempt_suffix, raw_response, fail_class):
        try:
            diff_proc = subprocess.run(["git", "diff", "HEAD"], cwd=str(wt_path), capture_output=True, text=True)
            diff_stat_proc = subprocess.run(["git", "diff", "HEAD", "--stat"], cwd=str(wt_path), capture_output=True, text=True)
            diff_name_proc = subprocess.run(["git", "diff", "HEAD", "--name-only"], cwd=str(wt_path), capture_output=True, text=True)

            patch_file = r_dir / f"{attempt_suffix}.patch"
            with open(patch_file, "w") as pf:
                pf.write(diff_proc.stdout)

            info_file = r_dir / f"{attempt_suffix}_info.txt"
            with open(info_file, "w") as inf:
                inf.write(f"Failure Classification: {fail_class}\n")
                inf.write(f"Raw Response:\n{raw_response}\n\n")
                inf.write(f"Changed Files:\n{diff_name_proc.stdout}\n")
                inf.write(f"Diff Stat:\n{diff_stat_proc.stdout}\n")

            print(f"Preserved patch and attempt info to {patch_file}")
            return patch_file
        except Exception as e:
            print(f"Failed to preserve patch: {e}")
            return None

    for attempt, m_entry in enumerate(eligible_models[:max_model_attempts]):
        selected_model = m_entry["model_id"]
        print(f"\n--- [Attempt {attempt+1}/{max_model_attempts}] Implementing with model: {selected_model} ---")

        execution_provider = get_omniroute_hermes_provider_config()
        if execution_provider:
            execution_provider["model"] = selected_model

        # Pre-Inference Provider Health Gate
        print(f"Running pre-inference health gate for {selected_model}...")
        try:
            gate_kwargs = {"safe_mode": True, "model": selected_model}
            if execution_provider:
                gate_kwargs.update(_oneshot_provider_kwargs(execution_provider))
            run_hermes_oneshot("Respond with exactly 'OK'.", timeout=15, **gate_kwargs)
            print(f"Pre-inference health gate passed for {selected_model}.")
        except Exception as gate_e:
            from src.hermes_agent import _classify_hermes_failure
            gate_error_str = str(gate_e)
            failure_category = _classify_hermes_failure(gate_error_str)
            if failure_category.startswith("PROVIDER_"):
                print(f"Provider health issue detected at gate for {selected_model}: {failure_category}. Selecting next model...")
                record_failure(selected_model, failure_category)
                continue
            else:
                print(f"Unknown error at pre-inference gate for {selected_model}: {gate_e}")
                record_failure(selected_model, "UNKNOWN_GATE_ERROR")
                continue

        telemetry_data = {
            "plan_size": len(plan_content),
            "issue_body_size": len(issue.get('body_preview') or ''),
            "discussion_context_size": len(issue.get('discussion_context') or ''),
            "repo_context_size": 0,
        }

        repaired = False
        worktree_path = prepare_clean_worktree(f"attempt-{attempt}")

        try:
            implement_issue_with_hermes(
                worktree_path,
                context,
                model=selected_model,
                provider_config=execution_provider,
                telemetry=telemetry_data,
            )
            print(f"Hermes applied initial implementation using {selected_model}.")
        except Exception as e:
            from src.hermes_agent import _classify_hermes_failure
            error_str = str(e)
            print(f"Implementation error with {selected_model}: {e}")
            failure_category = _classify_hermes_failure(error_str)

            patch_file = preserve_patch(worktree_path, reports_dir, f"attempt-{attempt}-impl-error", error_str, failure_category)

            if failure_category.startswith("PROVIDER_"):
                print(f"Provider health issue detected for {selected_model} during execution: {failure_category}. Selecting next model...")
                record_failure(selected_model, failure_category)
                cleanup_worktree(org, repo, issue_id)
                continue

            if failure_category == "IMPLEMENTATION_FAILURE":
                print(f"Implementation quality failure (e.g. no diff). Triggering bounded repair for {selected_model} on a CLEAN worktree...")
                repaired = True
                worktree_path = prepare_clean_worktree(f"attempt-{attempt}-repair")

                apply_ok = False
                if patch_file and patch_file.exists():
                    apply_proc = subprocess.run(["git", "apply", str(patch_file)], cwd=str(worktree_path), capture_output=True, text=True)
                    if apply_proc.returncode == 0:
                        apply_ok = True
                    else:
                        print(f"Failed to apply patch: {apply_proc.stderr}")

                if not apply_ok:
                    print("Repair infrastructure failed (patch apply). Skipping repair.")
                    preserve_patch(worktree_path, reports_dir, f"attempt-{attempt}-repair-infra-fail", apply_proc.stderr if patch_file else "No patch file", "repair_infrastructure_failed")
                    record_failure(selected_model, "repair_infrastructure_failed")
                    cleanup_worktree(org, repo, issue_id)
                    continue

                try:
                    repair_issue_with_hermes(
                        worktree_path,
                        context,
                        error_str,
                        model=selected_model,
                        provider_config=execution_provider,
                    )
                    print("Repair attempt finished.")
                except Exception as repair_e:
                    print(f"Repair attempt failed for {selected_model}: {repair_e}")
                    preserve_patch(worktree_path, reports_dir, f"attempt-{attempt}-repair-fail", str(repair_e), "implementation_repair_failed")
                    record_failure(selected_model, "implementation_repair_failed")
                    cleanup_worktree(org, repo, issue_id)
                    continue
            else:
                print(f"Unknown error encountered with {selected_model}: {failure_category}. Preserving evidence and safely stopping current model.")
                record_failure(selected_model, failure_category)
                cleanup_worktree(org, repo, issue_id)
                continue

        passed_guardrails, guardrail_msg = check_diff_guardrails(worktree_path)
        if not passed_guardrails:
            print(f"Validation FAILED: {guardrail_msg}")
            patch_file = preserve_patch(worktree_path, reports_dir, f"attempt-{attempt}-guardrail-fail", guardrail_msg, "guardrail_failed")

            if repaired:
                print("Already repaired once, giving up on this model.")
                record_failure(selected_model, "guardrail_failed")
                cleanup_worktree(org, repo, issue_id)
                continue

            print(f"Triggering repair for guardrail failure on a CLEAN worktree...")
            repaired = True
            worktree_path = prepare_clean_worktree(f"attempt-{attempt}-repair")

            apply_ok = False
            if patch_file and patch_file.exists():
                apply_proc = subprocess.run(["git", "apply", str(patch_file)], cwd=str(worktree_path), capture_output=True, text=True)
                if apply_proc.returncode == 0:
                    apply_ok = True
                else:
                    print(f"Failed to apply patch: {apply_proc.stderr}")

            if not apply_ok:
                print("Repair infrastructure failed (patch apply). Skipping repair.")
                preserve_patch(worktree_path, reports_dir, f"attempt-{attempt}-repair-infra-fail", apply_proc.stderr if patch_file else "No patch file", "repair_infrastructure_failed")
                record_failure(selected_model, "repair_infrastructure_failed")
                cleanup_worktree(org, repo, issue_id)
                continue

            try:
                repair_issue_with_hermes(
                    worktree_path,
                    context,
                    f"Guardrail failure on previous attempt: {guardrail_msg}",
                    model=selected_model,
                    provider_config=execution_provider,
                )
            except Exception as repair_e:
                print(f"Repair attempt failed for {selected_model}: {repair_e}")
                preserve_patch(worktree_path, reports_dir, f"attempt-{attempt}-repair-fail2", str(repair_e), "guardrail_repair_failed")
                record_failure(selected_model, "guardrail_repair_failed")
                cleanup_worktree(org, repo, issue_id)
                continue

            passed_guardrails, guardrail_msg = check_diff_guardrails(worktree_path)
            if not passed_guardrails:
                print(f"Validation FAILED after repair: {guardrail_msg}")
                preserve_patch(worktree_path, reports_dir, f"attempt-{attempt}-guardrail-fail3", guardrail_msg, "guardrail_failed")
                record_failure(selected_model, "guardrail_failed")
                cleanup_worktree(org, repo, issue_id)
                continue

        print("Guardrails passed. Running tests...")

        test_results = discover_and_run_tests(worktree_path, targeted_test=targeted_test if targeted_test and targeted_test != "None specified" else None)
        all_passed = True
        for t in test_results:
            if not t["result"]["success"]:
                all_passed = False
                break

        if all_passed and targeted_test and targeted_test != "None specified":
            print("Targeted tests passed. Running full suite...")
            full_results = discover_and_run_tests(worktree_path)
            test_results.extend(full_results)
            for t in full_results:
                if not t["result"]["success"]:
                    all_passed = False
                    break

        if all_passed:
            print("All detected tests passed!")
            record_success(selected_model)
            success = True
            break

        is_timeout = any("command timed out" in (t.get("result", {}).get("stderr") or "").lower() for t in test_results)
        if is_timeout:
            print("Validation blocked by test timeout. Skipping Hermes repair.")
            preserve_patch(worktree_path, reports_dir, f"attempt-{attempt}-timeout", "Test timeout", "TEST_TIMEOUT")
            record_failure(selected_model, "TEST_TIMEOUT")
            cleanup_worktree(org, repo, issue_id)
            continue

        if is_environment_failure(test_results):
            print("Validation blocked by environment/toolchain failure. Skipping Hermes repair.")
            preserve_patch(worktree_path, reports_dir, f"attempt-{attempt}-env-fail", "Environment failure", "env_failure")
            record_failure(selected_model, "env_failure")
            cleanup_worktree(org, repo, issue_id)
            continue

        if repaired:
            print("Tests failed, but we already used our one repair attempt.")
            preserve_patch(worktree_path, reports_dir, f"attempt-{attempt}-test-fail", "Test failure", "tests_failed")
            record_failure(selected_model, "tests_failed")
            cleanup_worktree(org, repo, issue_id)
            continue

        print("Tests failed. Triggering repair on a CLEAN worktree with patch replay...")
        repaired = True
        patch_file = preserve_patch(worktree_path, reports_dir, f"attempt-{attempt}-tests-failed", "Test failure", "tests_failed")

        fail_output = ""
        for t in test_results:
            if not t["result"]["success"]:
                fail_output += f"--- {t['framework']} ---\nSTDOUT:\n{t['result'].get('stdout','')}STDERR:\n{t['result'].get('stderr','')}\n"

        worktree_path = prepare_clean_worktree(f"attempt-{attempt}-repair")

        apply_ok = False
        if patch_file and patch_file.exists():
            apply_proc = subprocess.run(["git", "apply", str(patch_file)], cwd=str(worktree_path), capture_output=True, text=True)
            if apply_proc.returncode == 0:
                apply_ok = True
                print("Candidate patch applied successfully to repair worktree.")
            else:
                print(f"Failed to apply patch to repair worktree: {apply_proc.stderr}")

        if not apply_ok:
            print("Repair infrastructure failed (patch apply). Skipping repair.")
            preserve_patch(worktree_path, reports_dir, f"attempt-{attempt}-repair-infra-fail", apply_proc.stderr if patch_file else "No patch file", "repair_infrastructure_failed")
            record_failure(selected_model, "repair_infrastructure_failed")
            cleanup_worktree(org, repo, issue_id)
            continue

        repair_msg = f"Tests failed on candidate patch.\n\nFAILING TEST OUTPUT:\n{fail_output}\n\nEXACT REPAIR GOAL:\nFix the implementation to pass the targeted tests."

        try:
            repair_issue_with_hermes(
                worktree_path,
                context,
                repair_msg,
                model=selected_model,
                provider_config=execution_provider,
            )
        except Exception as repair_e:
            print(f"Repair attempt failed for {selected_model}: {repair_e}")
            preserve_patch(worktree_path, reports_dir, f"attempt-{attempt}-test-repair-fail", str(repair_e), "test_repair_failed")
            record_failure(selected_model, "test_repair_failed")
            cleanup_worktree(org, repo, issue_id)
            continue

        test_results = discover_and_run_tests(worktree_path, targeted_test=targeted_test if targeted_test and targeted_test != "None specified" else None)
        all_passed = True
        for t in test_results:
            if not t["result"]["success"]:
                all_passed = False
                break

        if all_passed and targeted_test and targeted_test != "None specified":
            print("Targeted tests passed. Running full suite...")
            full_results = discover_and_run_tests(worktree_path)
            test_results.extend(full_results)
            for t in full_results:
                if not t["result"]["success"]:
                    all_passed = False
                    break

        if all_passed:
            print("All detected tests passed after repair!")
            record_success(selected_model)
            success = True
            break
        else:
            print("Tests still failing after repair.")
            preserve_patch(worktree_path, reports_dir, f"attempt-{attempt}-test-fail-final", "Test failure after repair", "tests_failed")
            record_failure(selected_model, "tests_failed")
            cleanup_worktree(org, repo, issue_id)
            continue
    if not success:
        print("All viable implementation models exhausted or failed.")
        transition_status(issue["url"], "IMPLEMENTATION_FAILED")
        os.environ.update(original_environ)
        return False, None, ""

    print("Generating reports and patch...")
    patch_file = reports_dir / "patch.diff"
    create_patch(worktree_path, patch_file)

    try:
        diff_proc = subprocess.run(["git", "diff", "HEAD"], cwd=str(worktree_path), capture_output=True, text=True)
        diff_output = diff_proc.stdout
    except:
        diff_output = ""

    try:
        diff_stat_proc = subprocess.run(["git", "diff", "HEAD", "--stat"], cwd=str(worktree_path), capture_output=True, text=True)
        diff_stat = diff_stat_proc.stdout
    except:
        diff_stat = ""

    generate_reports(issue_id, worktree_path, reports_dir, test_results, diff_output, success, diff_stat)

    os.environ.update(original_environ)

    transition_status(issue["url"], "IMPLEMENTED_LOCAL")
    print(f"Success! Marked {issue_id} as IMPLEMENTED_LOCAL.")
    return success, test_results, diff_stat

def review(issue_id):
    issue = get_issue_context(issue_id)
    if not issue:
        print("Issue not found.")
        return
    org = issue['org_slug']
    repo = issue['repo_name'].split('/')[1]
    reports_dir = get_reports_dir(org, repo, issue_id)

    review_file = reports_dir / "review.md"
    if review_file.exists():
        with open(review_file, "r") as f:
            print(f"=== REVIEW REPORT ===\n{f.read()}\n=====================")
    else:
        print("No review report found.")

    summary_file = reports_dir / "summary.md"
    if summary_file.exists():
        with open(summary_file, "r") as f:
            print(f"=== SUMMARY ===\n{f.read()}\n===============")
    else:
        print("No summary report found.")

def show_workspace(issue_id):
    issue = get_issue_context(issue_id)
    if not issue:
        print("Issue not found.")
        return
    org = issue['org_slug']
    repo = issue['repo_name'].split('/')[1]
    worktree_path = WORKSPACES_ROOT / org / repo / "worktrees" / str(issue_id)

    if worktree_path.exists():
        print(f"Local worktree exists for {issue_id}: {worktree_path}")
        print(f"Lifecycle Status: {issue['lifecycle_status']}")
        try:
            status = subprocess.run(["git", "status", "--short"], cwd=str(worktree_path), capture_output=True, text=True).stdout
            print("Changed files:")
            print(status if status else "None")
        except:
            pass
    else:
        print(f"No local worktree found for issue {issue_id}.")

def cleanup_issue_workspace(issue_id):
    issue = get_issue_context(issue_id)
    if not issue:
        print("Issue not found.")
        return
    org = issue['org_slug']
    repo = issue['repo_name'].split('/')[1]

    try:
        cleanup_worktree(org, repo, issue_id)
        print(f"Worktree for {issue_id} safely removed. Reports are preserved.")
    except Exception as e:
        print(f"Failed to cleanup worktree: {e}")
