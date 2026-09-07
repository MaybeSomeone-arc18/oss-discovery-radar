from src.database import get_connection, update_organization_score

def calculate_organization_scores():
    print("Calculating organization opportunity scores...")
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Get all orgs that have some repositories
        cursor.execute('''
        SELECT DISTINCT org_slug FROM repositories
        ''')
        orgs = [row[0] for row in cursor.fetchall()]
        
        for org_slug in orgs:
            # 1. GSoC History
            cursor.execute("SELECT COUNT(DISTINCT year) FROM gsoc_years WHERE org_slug = ?", (org_slug,))
            gsoc_years = cursor.fetchone()[0]
            gsoc_score = min(100, gsoc_years * 20)
            
            # 2. Repo Activity
            cursor.execute('''
            SELECT SUM(stars), SUM(forks), COUNT(*) 
            FROM repositories WHERE org_slug = ? AND archived = 'False'
            ''', (org_slug,))
            row = cursor.fetchone()
            stars, forks, active_repos = row[0] or 0, row[1] or 0, row[2] or 0
            activity_score = min(100, (stars * 0.1) + (forks * 0.2) + (active_repos * 2))
            
            # 3. Issue / PR Activity (from repository_metrics)
            cursor.execute('''
            SELECT SUM(rm.issues_closed_recently), SUM(rm.prs_merged_recently), AVG(rm.review_merge_activity_score)
            FROM repository_metrics rm
            JOIN repositories r ON rm.repo_name = r.name
            WHERE r.org_slug = ?
            ''', (org_slug,))
            metrics_row = cursor.fetchone()
            issues_closed = metrics_row[0] or 0
            prs_merged = metrics_row[1] or 0
            avg_review_score = metrics_row[2] or 0
            
            responsiveness_score = min(100, avg_review_score)
            issue_pr_score = min(100, (issues_closed * 2) + (prs_merged * 5))
            
            # Overall Score Calculation
            total_score = (gsoc_score * 0.3) + (activity_score * 0.2) + (issue_pr_score * 0.3) + (responsiveness_score * 0.2)
            
            # Confidence & Completeness
            cursor.execute("SELECT is_verified_github FROM organizations WHERE slug = ?", (org_slug,))
            row_verified = cursor.fetchone()
            is_verified = bool(row_verified[0]) if row_verified else False
            
            if is_verified and active_repos > 0:
                confidence = "HIGH"
            elif is_verified and active_repos == 0:
                confidence = "MEDIUM"
            else:
                confidence = "LOW"
                total_score = total_score * 0.5 # Penalty for unverified orgs so they don't overtake verified ones based purely on history
            
            breakdown = {
                "gsoc_history_score": round(gsoc_score, 2),
                "activity_score": round(activity_score, 2),
                "issue_pr_score": round(issue_pr_score, 2),
                "responsiveness_score": round(responsiveness_score, 2)
            }
            
            update_organization_score(org_slug, round(total_score, 2), breakdown, github_account=org_slug, is_verified=is_verified, confidence=confidence)
            
    print("Scoring complete.")
