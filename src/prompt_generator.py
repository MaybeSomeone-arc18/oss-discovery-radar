import json
from pathlib import Path
from src.hermes_agent import get_issue_context, get_repo_analysis, get_reports_dir

def generate_implementation_prompt(issue_id):
    """
    Generates a precise Markdown prompt for Antigravity to implement the fix for a given issue.
    Returns the markdown string.
    """
    issue = get_issue_context(issue_id)
    if not issue:
        return f"Error: Issue {issue_id} not found in database."
        
    repo_name = issue.get('repo_name')
    org_slug = issue.get('org_slug')
    repo_name_short = repo_name.split('/')[1] if '/' in repo_name else repo_name
    
    repo_analysis = get_repo_analysis(repo_name) or {}
    
    reports_dir = get_reports_dir(org_slug, repo_name_short, issue_id)
    research_file = reports_dir / "research.md"
    plan_file = reports_dir / "plan.md"
    
    research_content = None
    if research_file.exists():
        with open(research_file, "r") as f:
            research_content = f.read().strip()
            
    plan_content = None
    if plan_file.exists():
        with open(plan_file, "r") as f:
            plan_content = f.read().strip()

    title = issue.get('title', 'Unknown Title')
    body = issue.get('body_preview', 'No body available')
    labels = issue.get('labels', '')
    url = issue.get('url', f"https://github.com/{repo_name}/issues/{issue_id}")

    prompt = []
    prompt.append(f"# Implementation Task: {repo_name}#{issue_id}")
    prompt.append(f"**URL:** {url}\n")
    
    prompt.append("## 1. Issue Requirements")
    prompt.append(f"**Title:** {title}")
    prompt.append(f"**Labels:** {labels}")
    prompt.append(f"**Description:**\n{body}\n")
    
    prompt.append("## 2. Context & Maintainer Conventions")
    if repo_analysis:
        pr_patterns = repo_analysis.get('pr_patterns') or "No specific PR patterns known."
        build_sys = repo_analysis.get('build_systems') or "Unknown"
        tests_sys = repo_analysis.get('test_frameworks') or "Unknown"
        
        prompt.append(f"**Build Systems:** {build_sys}")
        prompt.append(f"**Test Frameworks:** {tests_sys}")
        prompt.append(f"**Conventions/PR Patterns:** {pr_patterns}\n")
    else:
        prompt.append("*(No repository analysis available)*\n")
        
    prompt.append("## 3. Research Findings")
    if research_content:
        prompt.append(research_content)
        prompt.append("")
    else:
        prompt.append("*(No automated research available)*\n")
        
    prompt.append("## 4. Implementation Plan")
    if plan_content:
        prompt.append(plan_content)
        prompt.append("")
    else:
        prompt.append("*(No automated plan available)*\n")
        
    prompt.append("## 5. Explicit Constraints (CRITICAL)")
    prompt.append("- **ISOLATION:** You MUST work ONLY in the isolated worktree for this issue.")
    prompt.append("- **NO EXTERNAL WRITES:** DO NOT push to GitHub. DO NOT merge. DO NOT open a Pull Request. DO NOT attempt to write or commit outside the current local worktree.")
    prompt.append("- **FOCUS:** Stick strictly to implementing the fix as described in the requirements and plan. Do not refactor unrelated code.")
    
    return "\n".join(prompt)
