import re
from src.database import update_issue_deep_analysis, get_connection
from src.repository_analyzer import analyze_repository

def classify_issue_quality(title, body):
    length = len(body) if body else 0
    if length > 500 and "```" in (body or ""):
        return "CLEAR"
    elif length > 100:
        return "PARTIALLY_DEFINED"
    elif length < 50:
        return "VAGUE"
    return "INFORMATIONAL"

def classify_contribution_type(labels, title):
    text = (title + " " + " ".join(labels)).lower()
    if "doc" in text or "readme" in text:
        return "DOCUMENTATION"
    if "typo" in text or "format" in text or "lint" in text:
        return "MAINTENANCE"
    if "perf" in text or "slow" in text:
        return "PERFORMANCE"
    if "test" in text:
        return "TESTING"
    if "refactor" in text or "clean" in text:
        return "REFACTOR"
    if "build" in text or "ci" in text or "tool" in text:
        return "TOOLING"
    if "bug" in text or "fix" in text or "defect" in text:
        return "BUG_FIX"
    if "feature" in text or "enhancement" in text or "add" in text:
        return "FEATURE"
    return "OTHER"

def estimate_engineering_depth(title, body, labels):
    text = (title + " " + (body or "") + " " + " ".join(labels)).lower()
    
    # Trivial heuristics
    if "typo" in text or "spelling" in text or "format" in text or "lint" in text:
        return "TRIVIAL"
        
    # Substantial heuristics
    if "architecture" in text or "race condition" in text or "design" in text or "concurrency" in text or "memory leak" in text:
        return "SUBSTANTIAL"
        
    if "refactor" in text or "performance" in text:
        return "MEDIUM"
        
    return "SMALL"

def calculate_gsoc_score(depth, contrib_type):
    score = 50.0
    if depth == "TRIVIAL":
        score -= 40.0
    elif depth == "SUBSTANTIAL":
        score += 40.0
    elif depth == "MEDIUM":
        score += 20.0
        
    if contrib_type == "MAINTENANCE" or contrib_type == "DOCUMENTATION":
        score -= 20.0
    if contrib_type == "BUG_FIX" or contrib_type == "FEATURE":
        score += 20.0
        
    return min(100.0, max(0.0, score))

def find_likely_files(text):
    if not text:
        return []
    # simple heuristic looking for file paths
    pattern = r'([a-zA-Z0-9_\-\./]+\.(?:py|cpp|c|h|rs|java|js|ts|go))'
    matches = re.findall(pattern, text)
    return list(set(matches))

def analyze_and_update_issue(url):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM issues WHERE url = ?", (url,))
        row = cursor.fetchone()
        if not row:
            return None
            
        columns = [col[0] for col in cursor.description]
        issue = dict(zip(columns, row))
        
    quality = classify_issue_quality(issue['title'], issue['body_preview'])
    labels = []
    if issue['labels']:
        import json
        try:
            labels = json.loads(issue['labels'])
        except:
            pass
            
    ctype = classify_contribution_type(labels, issue['title'])
    depth = estimate_engineering_depth(issue['title'], issue['body_preview'], labels)
    gsoc_score = calculate_gsoc_score(depth, ctype)
    
    opp_score = issue['opportunity_score'] or 0.0
    contrib_score = (opp_score * 0.5) + (gsoc_score * 0.5)
    
    update_issue_deep_analysis(
        url=url,
        issue_quality=quality,
        contribution_type=ctype,
        engineering_depth=depth,
        gsoc_score=gsoc_score,
        contribution_score=contrib_score
    )
    
    # We also attempt to analyze the repository
    analyze_repository(issue['repo_name'])

def generate_contribution_brief(issue_dict, repo_analysis, profile):
    import json
    tags = json.loads(issue_dict['classified_tags']) if issue_dict['classified_tags'] else []
    labels = json.loads(issue_dict['labels']) if issue_dict['labels'] else []
    
    files = find_likely_files((issue_dict['title'] or "") + " " + (issue_dict['body_preview'] or ""))
    files_str = "\n".join([f"- {f}" for f in files]) if files else "- (None found in preview text)"
    
    test_dirs = repo_analysis.get('test_frameworks', []) if repo_analysis else []
    if isinstance(test_dirs, str):
        test_dirs = json.loads(test_dirs)
    test_str = "\n".join([f"- {t}" for t in test_dirs]) if test_dirs else "- (Unknown test structure)"
    
    brief = f"""========================================
CONTRIBUTION BRIEF
========================================

Repository: {issue_dict['repo_name']}
Issue: {issue_dict['title']}
URL: {issue_dict['url']}

Why this issue exists:
This issue is identified as a {issue_dict.get('contribution_type', 'UNKNOWN')} task. It appears to be {issue_dict.get('issue_quality', 'UNKNOWN').lower()}.

Current status:
{issue_dict['activity_status']} - Comments: {issue_dict['comments_count']}

Contribution type:
{issue_dict.get('contribution_type', 'UNKNOWN')}

Engineering depth:
{issue_dict.get('engineering_depth', 'UNKNOWN')}

Likely affected files:
{files_str}

Likely tests:
{test_str}

Repository contribution pattern:
"""
    if repo_analysis and repo_analysis.get('pr_patterns'):
        p = repo_analysis['pr_patterns']
        if isinstance(p, str):
            p = json.loads(p)
        brief += f"- Typical PR additions: {p.get('typical_additions', 0):.0f}\n"
        brief += f"- Typical changed files: {p.get('typical_changed_files', 0):.0f}\n"
    else:
        brief += "- (No pattern data available)\n"
        
    brief += f"""
GSoC preparation score:
{issue_dict.get('gsoc_preparation_score', 0):.1f} / 100.0

Why this is useful for you:
Your skills match {tags}. This task provides an opportunity to engage with the maintainers at {issue_dict['org_slug']}.

Potential risks:
If this is TRIVIAL, it may not be useful for a GSoC proposal. If there are no test frameworks identified, getting the PR merged might be difficult.

What you should learn first:
Review the documentation. { 'README found.' if repo_analysis and repo_analysis.get('has_readme') else 'No README found.' }
{ 'CONTRIBUTING found.' if repo_analysis and repo_analysis.get('has_contributing') else 'No CONTRIBUTING guide found.' }

Suggested next action:
{"Check the codebase for the likely affected files." if files else "Read the full issue discussion on GitHub to locate where to make changes."}
"""
    return brief
