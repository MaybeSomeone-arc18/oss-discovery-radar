import os
import re
import requests
from src.config import GITHUB_TOKEN, GRAPHQL_API_URL

def classify_repository(repo_full_name):
    """
    Classifies a repository into NORMAL_PROJECT, GSOC_PROJECT_REPOSITORY, 
    STUDENT_WORK_REPOSITORY, FORK_OR_MIRROR, ARCHIVED, or UNKNOWN.
    Returns (classification, eligibility, evidence, upstream_repo, upstream_confidence).
    """
    if not GITHUB_TOKEN:
        return "UNKNOWN", "UNKNOWN", "No GITHUB_TOKEN", None, None
        
    try:
        owner, name = repo_full_name.split('/')
    except ValueError:
        return "UNKNOWN", "UNKNOWN", f"Invalid repo name format: {repo_full_name}", None, None
    
    headers = {
        "Authorization": f"bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json"
    }

    query = """
    query($owner: String!, $name: String!) {
      repository(owner: $owner, name: $name) {
        name
        description
        isArchived
        isFork
        isMirror
        parent {
          nameWithOwner
        }
        owner {
          __typename
          login
        }
        object(expression: "HEAD:README.md") {
          ... on Blob {
            text
          }
        }
        issues(first: 20, orderBy: {field: CREATED_AT, direction: DESC}) {
          nodes {
            title
            labels(first: 5) {
              nodes { name }
            }
          }
        }
      }
    }
    """
    
    variables = {"owner": owner, "name": name}
    response = requests.post(GRAPHQL_API_URL, json={'query': query, 'variables': variables}, headers=headers)
    
    if response.status_code != 200:
        return "UNKNOWN", "UNKNOWN", f"API Error {response.status_code}", None, None
        
    data = response.json().get('data', {}).get('repository')
    if not data:
        return "UNKNOWN", "UNKNOWN", "Repository not found", None, None
        
    if data.get('isArchived'):
        return "ARCHIVED", "BLOCKED_ARCHIVED", "isArchived=True", None, None
        
    if data.get('isFork') or data.get('isMirror'):
        parent = data.get('parent')
        upstream = parent['nameWithOwner'] if parent else None
        evidence = f"isFork={data.get('isFork')}, isMirror={data.get('isMirror')}"
        return "FORK_OR_MIRROR", "BLOCKED_FORK_OR_MIRROR", evidence, upstream, "HIGH" if upstream else None

    # Signals Collection
    signals = []
    
    lower_name = name.lower()
    lower_desc = (data.get('description') or "").lower()
    
    readme_obj = data.get('object')
    lower_readme = (readme_obj.get('text') or "").lower() if readme_obj else ""
    
    # 1. Name Signals
    if any(s in lower_name for s in ['gsoc', 'student', 'summer-of-code', 'proposal']):
        signals.append("Name contains GSoC/student keywords")
        
    # 2. Description Signals (Exact phrases)
    if 'google summer of code' in lower_desc or 'gsoc' in lower_desc:
        signals.append("Description references GSoC")
        
    # 3. README Signals (Must be strong, e.g., "Google Summer of Code 20", "GSoC 20")
    if re.search(r'google summer of code 20\d\d', lower_readme) or re.search(r'gsoc 20\d\d', lower_readme):
        signals.append("README explicitly mentions GSoC year")
        
    # 4. Issue Signals
    issues = data.get('issues', {}).get('nodes', [])
    gsoc_issue_count = 0
    week_issue_count = 0
    for issue in issues:
        title = issue.get('title', '').lower()
        if 'week' in title or 'community bonding' in title or 'final submission' in title:
            week_issue_count += 1
            
        labels = [l.get('name', '').lower() for l in issue.get('labels', {}).get('nodes', [])]
        if 'gsoc' in labels or 'proposal' in labels:
            gsoc_issue_count += 1
            
    if week_issue_count >= 3:
        signals.append(f"Found {week_issue_count} issues with week/bonding/submission titles")
    if gsoc_issue_count >= 3:
        signals.append(f"Found {gsoc_issue_count} issues with GSoC labels")
        
    # Classification Logic
    # To prevent false positives, we need multiple signals or very strong issue signals.
    is_student_repo = False
    
    if len(signals) >= 2:
        # If we have name/desc + issue patterns, it's very likely a student repo
        if week_issue_count > 0 or gsoc_issue_count > 0:
            is_student_repo = True
        # If it explicitly calls out GSoC in both name and description
        elif "Name contains GSoC/student keywords" in signals and "Description references GSoC" in signals:
            is_student_repo = True
            
    # Very strong single signal: many week-tracking issues
    if week_issue_count >= 5 or gsoc_issue_count >= 5:
        is_student_repo = True

    if is_student_repo:
        classification = "GSOC_PROJECT_REPOSITORY" if 'gsoc' in lower_name or gsoc_issue_count > 0 else "STUDENT_WORK_REPOSITORY"
        evidence = "; ".join(signals)
        eligibility = "BLOCKED_STUDENT_WORK_REPO"
        
        # Try to extract upstream repo
        upstream_repo = None
        upstream_confidence = None
        
        # Look for "upstream: org/repo" or github.com/org/repo in description
        match = re.search(r'github\.com/([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+)', lower_desc)
        if match and match.group(1).lower() != repo_full_name.lower():
            upstream_repo = match.group(1)
            upstream_confidence = "LOW"
            
        return classification, eligibility, evidence, upstream_repo, upstream_confidence

    # If it reached here with some signals but didn't cross threshold
    if len(signals) > 0:
        return "NORMAL_PROJECT", "ELIGIBLE", f"GSoC mentioned but signals too weak: {'; '.join(signals)}", None, None

    return "NORMAL_PROJECT", "ELIGIBLE", "No GSoC/Student signals detected", None, None
