import os
import json
import yaml
import subprocess
from pathlib import Path
from src.database import get_connection
from src.workspace_manager import WORKSPACES_ROOT, create_worktree
from src.sandbox_runner import discover_and_run_tests

def verify_local_provider():
    config_path = os.path.expanduser("~/.hermes/config.yaml")
    if not os.path.exists(config_path):
        raise RuntimeError("Hermes config not found. Please ensure Hermes is installed and configured.")
        
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
        
    model_conf = config.get("model", {})
    if model_conf.get("default") != "qwen3.5:9b":
        raise RuntimeError(f"Safety Error: Hermes model is not qwen3.5:9b. Currently set to: {model_conf.get('default')}")
        
    provider = model_conf.get("provider", "")
    if provider not in ("custom", "local"):
        raise RuntimeError(f"Safety Error: Hermes provider is not local/custom. Currently set to: {provider}")

def get_issue_context(issue_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM issues WHERE issue_number = ? OR url LIKE ?", (issue_id, f"%/{issue_id}"))
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

def run_hermes_oneshot(prompt, cwd=None, safe_mode=False):
    cmd = ["hermes", "-z", prompt]
    # Removed --safe-mode because it ignores ~/.hermes/config.yaml and disables custom_providers
    
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=900)
        if result.returncode != 0:
            err = result.stderr.lower()
            if "connection refused" in err or "unreachable" in err or "connect" in err:
                raise RuntimeError(f"Ollama/Hermes provider unreachable. Check if ollama serve is running.\nDetails: {result.stderr}")
            if "model not found" in err or "not available" in err:
                raise RuntimeError(f"Model unavailable. Make sure qwen3.5:9b is pulled.\nDetails: {result.stderr}")
            if "context length" in err or "context too small" in err:
                raise RuntimeError(f"Context too small. Adjust config or model parameters.\nDetails: {result.stderr}")
            raise RuntimeError(f"Hermes CLI failed with code {result.returncode}:\n{result.stderr}")
            
        out = result.stdout.strip()
        if not out:
            raise RuntimeError("Malformed output: Hermes CLI returned empty response.")
            
        return out
    except subprocess.TimeoutExpired:
        raise RuntimeError("Hermes CLI timed out after 900 seconds. Model execution might be stuck or too slow.")
    except FileNotFoundError:
        raise RuntimeError("Hermes CLI executable missing. Ensure Hermes is installed and in PATH.")

def research(issue_id):
    print(f"Running Real Hermes Research for Issue {issue_id}...")
    try:
        verify_local_provider()
    except Exception as e:
        print(f"Research failed: {e}")
        return
    
    issue = get_issue_context(issue_id)
    if not issue:
        print(f"Issue {issue_id} not found.")
        return
        
    org = issue['org_slug']
    repo_name_short = issue['repo_name'].split('/')[1]
    reports_dir = get_reports_dir(org, repo_name_short, issue_id)
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

CONTEXT:
Repository: {issue['repo_name']}
Organization: {issue['org_slug']}
Issue Title: {issue['title']}
Issue Body: {issue['body_preview'] or 'No description provided.'}
Labels: {issue['labels']}
Status/Activity: {issue['activity_status']}
Contribution Score: {issue['contribution_value_score']}
GSoC Score: {issue['gsoc_preparation_score']}
Personal Fit Score: {issue['opportunity_score']}

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
        response = run_hermes_oneshot(prompt, safe_mode=True)
        
        with open(raw_file, "w") as f:
            f.write(response)
            
        with open(research_file, "w") as f:
            f.write(response)
            
        print(f"Research saved to {research_file}")
    except Exception as e:
        print(f"Research failed: {e}")

def plan(issue_id):
    print(f"Running Real Hermes Plan for Issue {issue_id}...")
    try:
        verify_local_provider()
    except Exception as e:
        print(f"Plan failed: {e}")
        return
    
    issue = get_issue_context(issue_id)
    if not issue:
        print(f"Issue {issue_id} not found.")
        return
        
    org = issue['org_slug']
    repo = issue['repo_name'].split('/')[1]
    reports_dir = get_reports_dir(org, repo, issue_id)
    research_file = reports_dir / "research.md"
    plan_file = reports_dir / "plan.md"
    
    if not research_file.exists():
        print(f"Research report not found at {research_file}. Run research first.")
        return
        
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
        response = run_hermes_oneshot(prompt, safe_mode=True)
            
        with open(plan_file, "w") as f:
            f.write(response)
            
        print(f"Plan saved to {plan_file}")
    except Exception as e:
        print(f"Plan failed: {e}")

def implement_issue_with_hermes(worktree_path, context):
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

CONTEXT:
{context}

Please implement the change locally in the current directory and explain your assumptions. Add/update tests where appropriate.
If you don't have tools to apply changes, output the full file modifications or patches so they can be reviewed.
"""

    response = run_hermes_oneshot(prompt, cwd=str(worktree_path), safe_mode=True)
    return response

def repair_issue_with_hermes(worktree_path, context, failure_logs):
    print(f"Running Hermes repair loop in {worktree_path}...")
    
    prompt = f"""You are a repair agent. The previous implementation for the issue failed validation.

CONTEXT:
{context}

FAILURE LOGS:
{failure_logs}

Please fix the implementation locally. Make the smallest maintainable change to pass the tests. Explain your assumptions.
"""
    
    response = run_hermes_oneshot(prompt, cwd=str(worktree_path), safe_mode=True)
    return response
