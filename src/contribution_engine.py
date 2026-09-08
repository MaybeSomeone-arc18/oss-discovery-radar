import json
from datetime import datetime, timezone
from src.database import get_connection, update_issue_opportunity, update_eligibility_status, update_first_contribution_score
from src.personal_fit import load_profile
from src.github_client import check_related_prs, fetch_contribution_model

def calculate_personal_fit(tags, title, body, profile):
    skills = [s.lower() for s in profile.get('skills', [])]
    interests = [i.lower() for i in profile.get('interests', [])]
    
    score = 0
    safe_title = title or ""
    safe_body = body or ""
    text = (safe_title + " " + safe_body).lower()
    
    # Simple overlap with tags
    if tags:
        for t in tags:
            if t.lower() in skills: score += 10
            if t.lower() in interests: score += 5
            
    # Quick text scan for skills
    for s in skills:
        if s in text: score += 5
        
    return min(100.0, score)

def parse_date(date_str):
    if not date_str: return datetime.now(timezone.utc)
    # GitHub ISO format: 2026-09-07T12:00:00Z
    try:
        return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except:
        return datetime.now(timezone.utc)

def score_and_classify_issues():
    profile = load_profile()
    now = datetime.now(timezone.utc)
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Fetch issues with repository and organization metrics
        cursor.execute('''
        SELECT 
            i.url, i.title, i.body_preview, i.labels, i.created_at, i.updated_at, i.comments_count, i.assignee_status, i.classified_tags, i.issue_number, i.repo_name, i.eligibility_status,
            m.review_merge_activity_score, m.prs_merged_recently, m.prs_external,
            o.opportunity_score
        FROM issues i
        JOIN repository_metrics m ON i.repo_name = m.repo_name
        JOIN organizations o ON i.org_slug = o.slug
        WHERE i.state = 'OPEN'
        ''')
        
        issues = cursor.fetchall()
        
    print(f"Scoring {len(issues)} open issues...")
    
    for row in issues:
        url, title, body, labels_str, created_at, updated_at, comments, assignee, tags_str, issue_number, repo_name, current_eligibility, rev_score, prs_merged, prs_ext, org_score = row
            
        labels = json.loads(labels_str) if labels_str else []
        tags = json.loads(tags_str) if tags_str else []
        
        created_dt = parse_date(created_at)
        updated_dt = parse_date(updated_at)
        
        days_since_update = (now - updated_dt).days
        
        # --- Status Determination ---
        if days_since_update <= 14:
            status = "ACTIVE"
        elif days_since_update <= 30:
            status = "LIKELY_ACTIVE"
        elif days_since_update > 60:
            status = "STALE"
        else:
            status = "UNKNOWN"
            
        # --- Eligibility Gate (Related PRs) ---
        eligibility_status = current_eligibility or "UNKNOWN"
        if eligibility_status == "UNKNOWN":
            related_prs = check_related_prs(repo_name, issue_number)
            if related_prs:
                has_merged = any(pr.get('state') == 'closed' for pr in related_prs)
                if has_merged:
                    eligibility_status = "LIKELY_SOLVED"
                else:
                    eligibility_status = "ACTIVE_WITH_WORK"
            else:
                eligibility_status = "ACTIVE_UNADDRESSED"
            
            update_eligibility_status(url, eligibility_status)
            
        # --- Score Calculation ---
        # 20% Personal technical fit
        fit_score = calculate_personal_fit(tags, title, body, profile)
        
        # 15% Topic alignment (does the issue align with our skills/tags? Simplified to use fit_score base)
        topic_score = fit_score * 0.8 if tags else fit_score * 0.5
        
        # 15% Org Opportunity
        org_opp_score = org_score or 0.0
        
        # 10% Recency
        recency_score = max(0, 100 - (days_since_update * 2))
        
        # 10% Maintainer activity (from review score and comments)
        safe_rev_score = rev_score or 0.0
        safe_comments = comments or 0
        maint_score = (min(100.0, safe_rev_score) + min(100.0, safe_comments * 10)) / 2
        
        # 10% External contributors
        safe_prs_ext = prs_ext or 0
        ext_score = min(100.0, safe_prs_ext * 20)
        
        # 10% Contribution accessibility
        labels_lower = [l.lower() for l in labels]
        access_score = 0.0
        if "good first issue" in labels_lower or "beginner" in labels_lower:
            access_score = 100.0
        elif "help wanted" in labels_lower or "enhancement" in labels_lower or "bug" in labels_lower:
            access_score = 70.0
            
        if assignee == "ASSIGNED":
            access_score = access_score * 0.1 # Heavily penalize if already assigned
            
        if eligibility_status in ("LIKELY_SOLVED", "SOLVED", "BLOCKED_RELATED_PR"):
            access_score = 0.0
        elif eligibility_status == "ACTIVE_WITH_WORK":
            access_score = access_score * 0.1
            
        # 5% Clarity
        safe_body = body or ""
        clarity_score = min(100.0, len(safe_body) / 5) # Assume longer body = more context up to 500 chars
        
        # 5% Difficulty
        # We want medium difficulty. Too easy/short = 50, well documented = 100.
        difficulty_score = 80.0
        if "documentation" in labels_lower or "typo" in labels_lower:
            difficulty_score = 40.0 # Too easy
            
        final_score = (
            (fit_score * 0.20) +
            (topic_score * 0.15) +
            (org_opp_score * 0.15) +
            (recency_score * 0.10) +
            (maint_score * 0.10) +
            (ext_score * 0.10) +
            (access_score * 0.10) +
                (clarity_score * 0.05) +
                (difficulty_score * 0.05)
            )
            
        if eligibility_status in ("LIKELY_SOLVED", "SOLVED", "BLOCKED_RELATED_PR"):
            final_score = 0.0
        elif eligibility_status == "ACTIVE_WITH_WORK":
            final_score = final_score * 0.1
        
        update_issue_opportunity(url, round(final_score, 2), status)
        
    print("Issue scoring completed.")

def generate_opportunity_explanation(issue_dict, profile):
    # Generates a deterministic explanation string
    score = issue_dict['opportunity_score']
    status = issue_dict['activity_status']
    org = issue_dict['org_slug']
    repo = issue_dict['repo_name']
    
    tags = json.loads(issue_dict['classified_tags']) if issue_dict['classified_tags'] else []
    
    matched_skills = [s for s in profile.get('skills', []) if s.lower() in [t.lower() for t in tags] or s.lower() in issue_dict['title'].lower()]
    
    difficulty = "MEDIUM"
    if 'documentation' in issue_dict['labels'].lower() or 'good first issue' in issue_dict['labels'].lower():
        difficulty = "EASY"
    elif 'refactor' in issue_dict['labels'].lower() or 'performance' in issue_dict['labels'].lower():
        difficulty = "HARD"
        
    explanation = f"""Contribution Opportunity
----------------
{org} / {repo}
Issue #{issue_dict['issue_number']}

Score: {score}
Confidence: HIGH
Status: {status}

Why this is attractive:
- strong match with your {', '.join(matched_skills) if matched_skills else 'core'} skills
- repository is actively maintained
- maintainers have recently responded to similar issues
- issue is {'unassigned' if issue_dict['assignee_status'] == 'UNASSIGNED' else 'already assigned, but worth tracking'}
- related PRs from outside contributors were recently merged

Difficulty: {difficulty}

Potential learning:
{chr(10).join(['- ' + t for t in tags]) if tags else '- codebase architecture'}

Recommended next action:
Inspect CONTRIBUTING.md and two recent merged PRs in the same subsystem.
"""
    return explanation

def calculate_first_contribution_score(issue_url):
    """
    Calculates the strategic ranking for FIRST REAL CONTRIBUTION.
    Weights:
    25% meaningful engineering value (contribution_value_score)
    20% GSoC preparation value (gsoc_preparation_score)
    15% personal technical fit
    15% maintainer accessibility
    10% contributor accessibility
    5% repository health
    5% implementation feasibility
    5% confidence
    """
    profile = load_profile()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT 
            i.url, i.title, i.body_preview, i.labels, i.classified_tags, 
            i.contribution_value_score, i.gsoc_preparation_score, i.repo_name, i.eligibility_status, i.assignee_status, i.issue_number,
            m.review_merge_activity_score, m.maintainer_response_time_hours,
            o.opportunity_score,
            ra.has_contributing, ra.test_frameworks,
            r.repo_eligibility
        FROM issues i
        LEFT JOIN repository_metrics m ON i.repo_name = m.repo_name
        LEFT JOIN organizations o ON i.org_slug = o.slug
        LEFT JOIN repository_analysis ra ON i.repo_name = ra.repo_name
        LEFT JOIN repositories r ON i.repo_name = r.name
        WHERE i.url = ?
        ''', (issue_url,))
        
        row = cursor.fetchone()
        if not row:
            return 0.0, "Issue not found"
            
        url, title, body, labels_str, tags_str, eng_value, gsoc_prep, repo_name, eligibility, assignee, issue_number, rev_score, resp_time, org_score, has_contrib, tests_str, repo_eligibility = row

    # --- Initial Filters (Phase 2) ---
    if repo_eligibility in ("BLOCKED_STUDENT_WORK_REPO", "BLOCKED_ARCHIVED", "BLOCKED_FORK_OR_MIRROR"):
        return 0.0, f"Failed Phase 1 Filter: Repository is {repo_eligibility}"

    if eligibility in ("LIKELY_SOLVED", "SOLVED", "BLOCKED_RELATED_PR", "ACTIVE_WITH_WORK"):
        return 0.0, f"Failed Phase 2 Filter: Eligibility is {eligibility}"
    
    if assignee == "ASSIGNED":
        return 0.0, "Failed Phase 2 Filter: Already assigned"
        
    labels_lower = [l.lower() for l in (json.loads(labels_str) if labels_str else [])]
    if "wontfix" in labels_lower or "duplicate" in labels_lower or "invalid" in labels_lower:
        return 0.0, "Failed Phase 2 Filter: Invalid/wontfix labels"

    # --- Calculate Sub-scores ---
    notes = []
    
    # 25% Meaningful engineering value
    safe_eng_value = eng_value or 0.0
    if safe_eng_value < 10.0:
        safe_eng_value = 50.0  # fallback if not calculated deeply yet
    notes.append(f"Engineering Value: {safe_eng_value:.1f} (Weight: 25%)")
    
    # 20% GSoC preparation value
    safe_gsoc_prep = gsoc_prep or 0.0
    if safe_gsoc_prep < 10.0:
        safe_gsoc_prep = 40.0 # fallback
    notes.append(f"GSoC Prep: {safe_gsoc_prep:.1f} (Weight: 20%)")
    
    # 15% Personal technical fit
    tags = json.loads(tags_str) if tags_str else []
    fit_score = calculate_personal_fit(tags, title, body, profile)
    if fit_score < 10.0:
        return 0.0, "Failed Phase 2 Filter: Poor personal fit"
    notes.append(f"Personal Fit: {fit_score:.1f} (Weight: 15%)")
    
    # 15% Maintainer accessibility
    safe_rev_score = rev_score or 50.0
    notes.append(f"Maintainer Accessibility (Review Score): {safe_rev_score:.1f} (Weight: 15%)")
    
    # 10% Contributor accessibility
    contrib_access = 50.0
    if "good first issue" in labels_lower:
        contrib_access = 100.0
    elif "help wanted" in labels_lower:
        contrib_access = 80.0
        
    if has_contrib:
        contrib_access = min(100.0, contrib_access + 20)
    notes.append(f"Contributor Accessibility: {contrib_access:.1f} (Weight: 10%)")
    
    # 5% Repository health
    safe_org_score = org_score or 50.0
    notes.append(f"Repository Health: {safe_org_score:.1f} (Weight: 5%)")
    
    # 5% Implementation feasibility
    # M4 Mac is great, but we prefer languages like Python, JS, Go. 
    # Harder if requires Windows or heavy JVM setup not documented.
    feasibility = 80.0 
    if body and "windows" in body.lower():
        feasibility = 20.0
    notes.append(f"Feasibility (M4 Mac context): {feasibility:.1f} (Weight: 5%)")
    
    # 5% Confidence
    confidence = 80.0
    if not eng_value or not gsoc_prep:
        confidence = 40.0 # lowered confidence if deep analysis missing
    notes.append(f"Confidence: {confidence:.1f} (Weight: 5%)")
    
    # --- Final Score ---
    final_score = (
        (safe_eng_value * 0.25) +
        (safe_gsoc_prep * 0.20) +
        (fit_score * 0.15) +
        (safe_rev_score * 0.15) +
        (contrib_access * 0.10) +
        (safe_org_score * 0.05) +
        (feasibility * 0.05) +
        (confidence * 0.05)
    )
    
    final_notes = "\\n".join(notes)
    
    update_first_contribution_score(issue_url, round(final_score, 2), final_notes)
    return round(final_score, 2), final_notes
