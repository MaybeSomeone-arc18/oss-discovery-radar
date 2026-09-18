import re
import requests
from src.config import GITHUB_TOKEN
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

    # Medium heuristics
    if "refactor" in text or "performance" in text or "cleanup" in text or "one pr per line" in text or "verification" in text:
        return "MEDIUM"

    return "SMALL"

def check_release_prerequisites(repo_full_name, title, body):
    """
    Looks for phrases like 'after 2.25.0 is released'.
    If found, checks GitHub for that release/tag.
    Returns (status, evidence) where status is READY_NOW or WAITING_ON_RELEASE.
    """
    text = (title + " " + (body or "")).lower()

    # Simple regex for "after X.Y.Z is released" or "wait for X.Y.Z"
    match = re.search(r'(?:after|wait for|until)[^\d]{0,20}(\d+\.\d+\.\d+(?:-\w+)?)', text)
    if not match:
        return "READY_NOW", "No release prerequisites detected"

    required_version = match.group(1)

    # Check github tags/releases
    headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
    url = f"https://api.github.com/repos/{repo_full_name}/releases"
    resp = requests.get(url, headers=headers, timeout=10)

    if resp.status_code == 200:
        releases = resp.json()
        for r in releases:
            if r.get('prerelease', False):
                continue
            if required_version in r.get('tag_name', '') or required_version in r.get('name', ''):
                return "READY_NOW", f"Required version {required_version} is already released."

    # Also check tags just in case
    url_tags = f"https://api.github.com/repos/{repo_full_name}/tags"
    resp_tags = requests.get(url_tags, headers=headers, timeout=10)
    if resp_tags.status_code == 200:
        tags = resp_tags.json()
        for t in tags:
            t_name = t.get('name', '').lower()
            if any(x in t_name for x in ['alpha', 'beta', 'rc']):
                continue
            if required_version in t_name:
                return "READY_NOW", f"Required version {required_version} found in tags."

    return "WAITING_ON_RELEASE", f"Waiting on unreleased version: {required_version}"
def calculate_gsoc_score(depth, contrib_type, org_gsoc_history_score, gsoc_projects, issue_dict):
    score = 0.0
    evidence = []

    # 1. Verified org history (max 30)
    org_score = min(30.0, org_gsoc_history_score * 0.30)
    score += org_score
    if org_score > 0:
        evidence.append(f"Org History: +{org_score:.1f} (Organization has verified GSoC participation)")

    # 2. Repo/Project historical relevance (max 30)
    repo_relevance = 0.0
    repo_name_parts = issue_dict.get('repo_name', '').lower().split('/')
    repo_short_name = repo_name_parts[-1] if repo_name_parts else ""

    if gsoc_projects and repo_short_name:
        import re
        for p in gsoc_projects:
            title = (p.get('title') or "").lower()
            tech = (p.get('technologies') or "").lower()
            desc = (p.get('short_description') or "").lower()

            if re.search(r'\b' + re.escape(repo_short_name) + r'\b', title + " " + tech + " " + desc):
                repo_relevance = 30.0
                evidence.append(f"Project History: +30.0 (Repository '{repo_short_name}' explicitly mentioned in past GSoC projects)")
                break

    score += repo_relevance

    # 3. Technical/Skill Alignment (max 20)
    skill_match = 0.0
    import json
    tags = []
    try:
        tags_str = issue_dict.get('classified_tags')
        if tags_str:
            tags = json.loads(tags_str)
    except:
        pass

    if tags and gsoc_projects:
        matched_tags = []
        import re
        for tag in tags:
            tag_l = tag.lower()
            for p in gsoc_projects:
                tech = (p.get('technologies') or "").lower()
                if re.search(r'\b' + re.escape(tag_l) + r'\b', tech):
                    if tag_l not in matched_tags:
                        matched_tags.append(tag_l)

        if matched_tags:
            skill_match = min(20.0, len(matched_tags) * 10.0)
            evidence.append(f"Technical Alignment: +{skill_match:.1f} (Tags {matched_tags} match past GSoC technologies)")

    score += skill_match

    # 4. Engineering Depth (max 10)
    depth_score = 0.0
    if depth == "SUBSTANTIAL":
        depth_score = 10.0
    elif depth == "MEDIUM":
        depth_score = 5.0
    elif depth == "TRIVIAL":
        depth_score = -20.0

    score += depth_score
    if depth_score > 0:
        evidence.append(f"Engineering Depth: +{depth_score:.1f} ({depth} tasks indicate GSoC-level complexity)")
    elif depth_score < 0:
        evidence.append(f"Engineering Depth: {depth_score:.1f} ({depth} tasks are generally too small for GSoC impact)")

    # 5. Contribution Type (max 10)
    type_score = 0.0
    if contrib_type in ("FEATURE", "BUG_FIX"):
        type_score = 10.0
    elif contrib_type in ("MAINTENANCE", "DOCUMENTATION"):
        type_score = -10.0

    score += type_score
    if type_score > 0:
        evidence.append(f"Contribution Type: +{type_score:.1f} ({contrib_type} aligns well with GSoC codebase work)")
    elif type_score < 0:
        evidence.append(f"Contribution Type: {type_score:.1f} ({contrib_type} typically lacks necessary technical depth)")

    final_score = min(100.0, max(0.0, score))
    evidence_str = "\\n".join(evidence) if evidence else "No explicit GSoC evidence found."
    return final_score, evidence_str

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

        # Fetch org info
        cursor.execute("SELECT score_breakdown FROM organizations WHERE slug = ?", (issue.get('org_slug'),))
        org_row = cursor.fetchone()
        org_gsoc_history_score = 0.0
        if org_row and org_row[0]:
            import json
            try:
                bd = json.loads(org_row[0])
                org_gsoc_history_score = bd.get('gsoc_history_score', 0.0)
            except:
                pass

        # Fetch gsoc projects
        cursor.execute("SELECT title, short_description, technologies FROM gsoc_projects WHERE org_slug = ?", (issue.get('org_slug'),))
        gsoc_projects = []
        for p_row in cursor.fetchall():
            gsoc_projects.append({'title': p_row[0], 'short_description': p_row[1], 'technologies': p_row[2]})

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
    gsoc_score, gsoc_evidence = calculate_gsoc_score(depth, ctype, org_gsoc_history_score, gsoc_projects, issue)

    opp_score = issue['opportunity_score'] or 0.0
    contrib_score = (opp_score * 0.5) + (gsoc_score * 0.5)

    update_issue_deep_analysis(
        url=url,
        issue_quality=quality,
        contribution_type=ctype,
        engineering_depth=depth,
        gsoc_score=gsoc_score,
        contribution_score=contrib_score,
        gsoc_evidence=gsoc_evidence
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
