import json
from datetime import datetime, timezone
from src.database import get_connection

def transition_status(issue_url, new_status, reason=None, notes=None, difficulty=None, skills=None):
    valid_statuses = ['NEW', 'WATCHING', 'RESEARCHED', 'PLANNED', 'IN_PROGRESS', 'IMPLEMENTED_LOCAL', 'IMPLEMENTATION_FAILED', 'SUBMITTED', 'MERGED', 'DISMISSED', 'STALE']
    if new_status not in valid_statuses:
        raise ValueError(f"Invalid status: {new_status}")
        
    with get_connection() as conn:
        cursor = conn.cursor()
        
        updates = ["lifecycle_status = ?"]
        params = [new_status]
        
        if new_status == 'DISMISSED':
            updates.append("dismissed = 1")
            if reason:
                updates.append("dismissal_reason = ?")
                params.append(reason)
        elif new_status == 'RESEARCHED':
            updates.append("researched = 1")
        elif new_status == 'PLANNED':
            updates.append("planned = 1")
        elif new_status == 'IN_PROGRESS':
            pass
        elif new_status == 'SUBMITTED':
            updates.append("submitted = 1")
        elif new_status == 'MERGED':
            updates.append("merged = 1")
            
        if notes is not None:
            updates.append("user_notes = ?")
            params.append(notes)
        if difficulty is not None:
            updates.append("user_difficulty = ?")
            params.append(difficulty)
        if skills is not None:
            updates.append("skills_learned = ?")
            params.append(skills)
            
        params.append(issue_url)
        query = f"UPDATE issues SET {', '.join(updates)} WHERE url = ?"
        
        cursor.execute(query, params)
        conn.commit()

def generate_daily_shortlist(limit=10):
    with get_connection() as conn:
        cursor = conn.cursor()
        query = '''
        SELECT i.url, i.repo_name, i.issue_number, i.title, i.org_slug, i.contribution_value_score, i.gsoc_preparation_score, i.opportunity_score, o.opportunity_confidence, i.activity_status, i.first_seen_at, i.score_delta
        FROM issues i
        LEFT JOIN organizations o ON i.org_slug = o.slug
        WHERE i.lifecycle_status IN ('NEW', 'WATCHING') 
        AND i.state = 'OPEN'
        AND (i.cooldown_until IS NULL OR i.cooldown_until <= CURRENT_TIMESTAMP)
        ORDER BY i.contribution_value_score DESC NULLS LAST, i.opportunity_score DESC
        LIMIT ?
        '''
        cursor.execute(query, (limit,))
        rows = cursor.fetchall()
        
        results = []
        for r in rows:
            rec = _get_deterministic_recommendation(r)
            results.append({
                'url': r[0], 'repo': r[1], 'issue': r[2], 'title': r[3], 'org': r[4],
                'c_val': r[5], 'gsoc': r[6], 'fit': r[7], 'conf': r[8], 'act': r[9], 'first_seen': r[10],
                'score_delta': r[11],
                'recommendation': rec
            })
            
            # Update last_recommended_at
            cursor.execute("UPDATE issues SET last_recommended_at = CURRENT_TIMESTAMP WHERE url = ?", (r[0],))
            
            # Apply cooldown for 24h
            cursor.execute("UPDATE issues SET cooldown_until = datetime(CURRENT_TIMESTAMP, '+1 day') WHERE url = ?", (r[0],))
            
        conn.commit()
        return results

def _get_deterministic_recommendation(row):
    # row index: 5=c_val, 6=gsoc, 7=fit, 8=conf, 9=act
    if row[9] in ('STALE', 'INACTIVE'):
        return "Likely stale — monitor rather than act."
    if row[5] is not None and row[5] > 7.0:
        return "Good candidate for local Hermes research."
    if row[7] is not None and row[7] > 7.0:
        return "High personal fit. Read CONTRIBUTING.md and inspect 3 recent merged PRs."
    return "Research issue before commenting."

def get_history(issue_id):
    with get_connection() as conn:
        cursor = conn.cursor()

        if isinstance(issue_id, str) and issue_id.startswith("http"):
            query = """
            SELECT url, repo_name, title, first_seen_at, last_seen_at, lifecycle_status,
                   previous_score, current_score, score_delta, researched, planned, implemented, submitted, merged,
                   dismissed, dismissal_reason, user_difficulty, user_notes, skills_learned
            FROM issues WHERE url = ?
            """
            params = (issue_id,)
        else:
            query = """
            SELECT url, repo_name, title, first_seen_at, last_seen_at, lifecycle_status,
                   previous_score, current_score, score_delta, researched, planned, implemented, submitted, merged,
                   dismissed, dismissal_reason, user_difficulty, user_notes, skills_learned
            FROM issues WHERE issue_number = ? OR url LIKE ?
            """
            params = (issue_id, f"%/{issue_id}")

        cursor.execute(query, params)
        row = cursor.fetchone()

        if not row:
            return None

        cols = [c[0] for c in cursor.description]
        return dict(zip(cols, row))


def get_changes_summary():
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # New opportunities
        cursor.execute("SELECT COUNT(*) FROM issues WHERE lifecycle_status = 'NEW' AND (first_seen_at > datetime(CURRENT_TIMESTAMP, '-1 day') OR first_seen_at IS NULL)")
        new_count = cursor.fetchone()[0]
        
        # Score increased
        cursor.execute("SELECT COUNT(*) FROM issues WHERE score_delta > 1.0")
        inc_count = cursor.fetchone()[0]
        
        # Score decreased
        cursor.execute("SELECT COUNT(*) FROM issues WHERE score_delta < -1.0")
        dec_count = cursor.fetchone()[0]
        
        return {
            'new_opportunities': new_count,
            'score_increased': inc_count,
            'score_decreased': dec_count
        }

def deduplicate_opportunities():
    # Minimal deduplication logic to ensure one canonical record per issue
    pass # Already mostly handled by ON CONFLICT(url) in database.py
    
def select_top_for_research():
    with get_connection() as conn:
        cursor = conn.cursor()
        query = '''
        SELECT i.url, i.issue_number
        FROM issues i
        LEFT JOIN organizations o ON i.org_slug = o.slug
        WHERE i.lifecycle_status IN ('NEW', 'WATCHING') 
        AND i.state = 'OPEN'
        AND i.researched = 0
        AND o.opportunity_confidence IN ('high', 'medium')
        AND i.gsoc_preparation_score >= 5.0
        ORDER BY i.contribution_value_score DESC NULLS LAST, i.opportunity_score DESC
        LIMIT 1
        '''
        cursor.execute(query)
        row = cursor.fetchone()
        if not row:
            return None
        return row[1] # issue_number

def run_daily_pipeline():
    from src.gsoc_collector import fetch_gsoc_organizations
    from src.github_collector import fetch_organization_intelligence, enrich_organizations
    from src.contribution_collector import fetch_contributions
    from src.contribution_engine import score_and_classify_issues
    from src.scoring_engine import calculate_organization_scores
    
    print("Running Daily Pipeline...")
    
    # Fault-tolerant pipeline
    try:
        fetch_gsoc_organizations()
    except Exception as e:
        print(f"Error fetching GSoC data: {e}")
        
    try:
        enrich_organizations()
    except Exception as e:
        print(f"Error enriching organizations: {e}")
        
    try:
        fetch_contributions(limit=20)
    except Exception as e:
        print(f"Error syncing issues: {e}")
        
    try:
        score_and_classify_issues()
    except Exception as e:
        print(f"Error scoring issues: {e}")
        
    try:
        calculate_organization_scores()
    except Exception as e:
        print(f"Error scoring organizations: {e}")
        
    print("Pipeline finished.")


def schedule_hermes_retry(issue_url, delay_minutes=30):
    with get_connection() as conn:
        conn.execute(
            "UPDATE issues SET hermes_retry_at = datetime(CURRENT_TIMESTAMP, ?) WHERE url = ?",
            (f"+{int(delay_minutes)} minutes", issue_url),
        )
        conn.commit()


def clear_hermes_retry(issue_url):
    with get_connection() as conn:
        conn.execute(
            "UPDATE issues SET hermes_retry_at = NULL WHERE url = ?",
            (issue_url,),
        )
        conn.commit()


def get_due_hermes_retries(limit=10):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT issue_number, url, repo_name, org_slug, lifecycle_status, hermes_retry_at
            FROM issues
            WHERE hermes_retry_at IS NOT NULL
              AND hermes_retry_at <= CURRENT_TIMESTAMP
            ORDER BY hermes_retry_at ASC
            LIMIT ?
            """,
            (int(limit),),
        )
        rows = cursor.fetchall()

        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
