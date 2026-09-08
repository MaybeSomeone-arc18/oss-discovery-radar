import os
import requests
import json
import subprocess
import yaml
from pathlib import Path
from src.workspace_manager import create_worktree, cleanup_worktree, WORKSPACES_ROOT
from src.hermes_agent import get_issue_context, get_reports_dir, implement_issue_with_hermes, repair_issue_with_hermes, run_hermes_oneshot
from src.sandbox_runner import discover_and_run_tests
from src.opportunity_manager import transition_status

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
        # Add all to index to capture new files
        subprocess.run(["git", "add", "-A"], cwd=str(worktree_path), check=True)
        proc = subprocess.run(["git", "diff", "HEAD"], cwd=str(worktree_path), capture_output=True, text=True, check=True)
        with open(output_path, "w") as f:
            f.write(proc.stdout)
        return True
    except subprocess.CalledProcessError:
        return False

def generate_reports(issue_id, worktree_path, reports_dir, test_results, diff_output, success):
    review_file = reports_dir / "review.md"
    implementation_file = reports_dir / "implementation.md"
    summary_file = reports_dir / "summary.md"
    
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
        review_response = run_hermes_oneshot(review_prompt, cwd=str(worktree_path), safe_mode=True)
        with open(review_file, "w") as f:
            f.write(review_response)
    except Exception as e:
        with open(review_file, "w") as f:
            f.write(f"Failed to generate review: {e}")

    # Generate Implementation Report
    imp_prompt = f"""You are documenting the implementation for Issue {issue_id}.
Describe the approach taken, files changed, tests added, validation results, and any remaining uncertainty.
Do not generate the patch, just describe it.

TEST RESULTS: {json.dumps(test_results, indent=2) if test_results else "None"}
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

def implement(issue_id):
    issue = get_issue_context(issue_id)
    if not issue:
        print(f"Issue {issue_id} not found.")
        return
        
    org = issue['org_slug']
    repo = issue['repo_name'].split('/')[1]
    
    # Safeguard: verify against real GitHub
    try:
        api_url = f"https://api.github.com/repos/{org}/{repo}/issues/{issue_id}"
        resp = requests.get(api_url, timeout=10)
        if resp.status_code != 200:
            print(f"Safeguard failed: Issue {issue_id} not found on GitHub or API error.")
            return
            
        gh_issue = resp.json()
        # If our local title is a generic synthetic one and doesn't match the real one, fail.
        if issue['title'] != gh_issue.get('title') and (issue['title'].startswith('Issue ') or '2024-01-01' in str(issue.get('created_at'))):
            print("Safeguard failed: Local metadata appears synthetic or stale compared to real GitHub issue.")
            return
    except Exception as e:
        print(f"Safeguard error: Could not verify issue against GitHub: {e}")
        return
    
    reports_dir = get_reports_dir(org, repo, issue_id)
    plan_file = reports_dir / "plan.md"
    if not plan_file.exists():
        print("Plan file not found. Run plan first.")
        return
        
    with open(plan_file, "r") as f:
        plan_content = f.read()
        
    with open(plan_file, "r") as f:
        plan_content = f.read()
        
    worktree_path = create_worktree(org, repo, issue_id)
    print(f"Isolated worktree ready at {worktree_path}.")
    
    # Record base commit
    try:
        base_commit_proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(worktree_path), capture_output=True, text=True, check=True)
        base_commit = base_commit_proc.stdout.strip()
        print(f"Base commit recorded: {base_commit}")
        with open(reports_dir / "base_commit.txt", "w") as f:
            f.write(base_commit)
    except subprocess.CalledProcessError as e:
        print(f"Failed to record base commit: {e}")
    
    # Hide GitHub credentials
    original_environ = os.environ.copy()
    if 'GITHUB_TOKEN' in os.environ:
        del os.environ['GITHUB_TOKEN']
    if 'GH_TOKEN' in os.environ:
        del os.environ['GH_TOKEN']
    
    context = f"Issue Title: {issue['title']}\nBody: {issue['body_preview']}\n\nPLAN:\n{plan_content}"
    
    try:
        implement_issue_with_hermes(worktree_path, context)
        print("Hermes applied initial implementation.")
    except Exception as e:
        print(f"Implementation error: {e}")
        transition_status(issue_id, "IMPLEMENTATION_FAILED")
        os.environ.update(original_environ)
        return
        
    # Check guardrails
    passed_guardrails, guardrail_msg = check_diff_guardrails(worktree_path)
    if not passed_guardrails:
        print(f"Validation FAILED: {guardrail_msg}")
        transition_status(issue_id, "IMPLEMENTATION_FAILED")
        os.environ.update(original_environ)
        return
        
    print("Guardrails passed. Running tests...")
    
    # Validation Loop
    success = False
    for iteration in range(2): # Max 2 iterations (initial + 1 repair)
        test_results = discover_and_run_tests(worktree_path)
        all_passed = True
        for t in test_results:
            if not t["result"]["success"]:
                all_passed = False
                break
                
        if all_passed:
            print("All detected tests passed!")
            success = True
            break
            
        if iteration == 0:
            print("Tests failed. Triggering repair loop...")
            failure_logs = json.dumps(test_results, indent=2)
            try:
                repair_issue_with_hermes(worktree_path, context, failure_logs)
            except Exception as e:
                print(f"Repair error: {e}")
                break
            
            passed_guardrails, guardrail_msg = check_diff_guardrails(worktree_path)
            if not passed_guardrails:
                print(f"Validation FAILED after repair: {guardrail_msg}")
                break
        else:
            print("Tests still failing after repair.")
            
    # Generate Artifacts
    print("Generating reports and patch...")
    patch_file = reports_dir / "patch.diff"
    create_patch(worktree_path, patch_file)
    
    try:
        diff_proc = subprocess.run(["git", "diff", "HEAD"], cwd=str(worktree_path), capture_output=True, text=True)
        diff_output = diff_proc.stdout
    except:
        diff_output = ""
        
    generate_reports(issue_id, worktree_path, reports_dir, test_results, diff_output, success)
    
    os.environ.update(original_environ)
    
    if success:
        transition_status(issue_id, "IMPLEMENTED_LOCAL")
        print(f"Success! Marked {issue_id} as IMPLEMENTED_LOCAL.")
    else:
        transition_status(issue_id, "IMPLEMENTATION_FAILED")
        print(f"Validation failed. Marked {issue_id} as IMPLEMENTATION_FAILED.")

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
