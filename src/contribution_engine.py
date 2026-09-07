import json
from datetime import datetime, timezone
from src.database import get_connection, update_issue_opportunity
from src.personal_fit import load_profile

def calculate_personal_fit(tags, title, body, profile):
    skills = [s.lower() for s in profile.get('skills', [])]
    interests = [i.lower() for i in profile.get('interests', [])]
    
    score = 0
    text = (title + " " + body).lower()
    
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
            i.url, i.title, i.body_preview, i.labels, i.created_at, i.updated_at, i.comments_count, i.assignee_status, i.classified_tags,
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
            url, title, body, labels_str, created_at, updated_at, comments, assignee, tags_str, rev_score, prs_merged, prs_ext, org_score = row
            
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
            maint_score = (min(100.0, rev_score) + min(100.0, comments * 10)) / 2
            
            # 10% External contributors
            ext_score = min(100.0, prs_ext * 20)
            
            # 10% Contribution accessibility
            labels_lower = [l.lower() for l in labels]
            access_score = 0.0
            if "good first issue" in labels_lower or "beginner" in labels_lower:
                access_score = 100.0
            elif "help wanted" in labels_lower or "enhancement" in labels_lower or "bug" in labels_lower:
                access_score = 70.0
                
            if assignee == "ASSIGNED":
                access_score = access_score * 0.1 # Heavily penalize if already assigned
                
            # 5% Clarity
            clarity_score = min(100.0, len(body) / 5) # Assume longer body = more context up to 500 chars
            
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
