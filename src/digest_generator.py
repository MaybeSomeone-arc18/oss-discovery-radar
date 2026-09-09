import os
from datetime import datetime
from src.database import get_connection
from src.run_log import log_event

def generate_daily_digest():
    os.makedirs("digests", exist_ok=True)
    today_str = datetime.now().strftime("%Y-%m-%d")
    filepath = f"digests/daily_{today_str}.md"
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        lines = [f"# Daily OSS Radar Digest - {today_str}\n"]
        
        # 1. TOP OPPORTUNITIES
        lines.append("## 1. TOP OPPORTUNITIES")
        
        # Use the robust filtering from first-contribution
        cursor.execute('''
            SELECT i.url, i.repo_name, i.issue_number, i.title, i.body_preview, i.org_slug
            FROM issues i
            LEFT JOIN repositories r ON i.repo_name = r.name
            WHERE i.state = 'OPEN' 
            AND (i.eligibility_status IS NULL OR i.eligibility_status NOT IN ('BLOCKED', 'SOLVED', 'DUPLICATE', 'BLOCKED_STUDENT_WORK_REPO', 'BLOCKED_RELATED_PR', 'LIKELY_SOLVED'))
            AND (i.activity_status IS NULL OR i.activity_status IN ('ACTIVE', 'LIKELY_ACTIVE'))
            AND (i.assignee_status IS NULL OR i.assignee_status != 'ASSIGNED')
            AND (r.repo_eligibility IS NULL OR r.repo_eligibility NOT IN ('BLOCKED_STUDENT_WORK_REPO', 'BLOCKED_ARCHIVED', 'BLOCKED_FORK_OR_MIRROR'))
        ''')
        rows = cursor.fetchall()
        
        from src.contribution_engine import calculate_first_contribution_score
        from src.deep_analysis import check_release_prerequisites
        
        scored_candidates = []
        for row in rows:
            url, repo_name, issue_number, title, body_preview, org_slug = row
            score, notes = calculate_first_contribution_score(url)
            if score > 0:
                # Re-fetch dynamic fields
                cur2 = conn.cursor()
                cur2.execute("SELECT gsoc_preparation_score FROM issues WHERE url = ?", (url,))
                row2 = cur2.fetchone()
                gsoc = row2[0] if row2 else None
                
                # Check readiness
                readiness, read_ev = check_release_prerequisites(repo_name, title, body_preview)
                if readiness == "READY_NOW":
                    scored_candidates.append({
                        "url": url, "repo": repo_name, "num": issue_number, "title": title,
                        "score": score, "gsoc": gsoc, "readiness": readiness
                    })
                    
        scored_candidates.sort(key=lambda x: x["score"], reverse=True)
        top_opps = scored_candidates[:5]
        
        if not top_opps:
            lines.append("No top eligible opportunities found today.")
        else:
            for opp in top_opps:
                gsoc_str = f"{opp['gsoc']:.1f}" if opp['gsoc'] else "N/A"
                lines.append(f"- **[{opp['repo']}#{opp['num']}]** [{opp['title']}]({opp['url']})\n  - Score: {opp['score']:.1f} | Readiness: {opp['readiness']} | GSoC: {gsoc_str}")
                lines.append(f"  - Action: Run `python main.py prompt {opp['num']}` or `python main.py research {opp['num']}`")
        lines.append("")
        
        # 2. WHAT CHANGED
        lines.append("## 2. WHAT CHANGED")
        cursor.execute("SELECT COUNT(*) FROM issues WHERE lifecycle_status = 'NEW' AND (first_seen_at > datetime(CURRENT_TIMESTAMP, '-1 day') OR first_seen_at IS NULL)")
        new_opps = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM issues WHERE score_delta > 1.0")
        score_inc = cursor.fetchone()[0]
        lines.append(f"- **New Opportunities:** {new_opps}")
        lines.append(f"- **Opportunities with increased score:** {score_inc}")
        lines.append("")
        
        # 3. PROJECTS TO WATCH
        lines.append("## 3. PROJECTS TO WATCH")
        cursor.execute("SELECT name, opportunity_score FROM organizations ORDER BY opportunity_score DESC LIMIT 3")
        for org in cursor.fetchall():
            score = f"{org[1]:.1f}" if org[1] else "N/A"
            lines.append(f"- {org[0]} (Score: {score})")
        lines.append("")
            
        # 4. MY ACTIVE CONTRIBUTIONS
        lines.append("## 4. MY ACTIVE CONTRIBUTIONS")
        cursor.execute("SELECT title, url, lifecycle_status FROM issues WHERE lifecycle_status IN ('RESEARCHED', 'PLANNED', 'IN_PROGRESS', 'SUBMITTED')")
        active = cursor.fetchall()
        if not active:
            lines.append("No active contributions currently.")
        else:
            for a in active:
                lines.append(f"- [{a[0]}]({a[1]}) - **{a[2]}**")
        lines.append("")
        
        # 5. GSoC-RELEVANT SIGNALS
        lines.append("## 5. GSoC-RELEVANT SIGNALS")
        cursor.execute('''
        SELECT title, url, gsoc_preparation_score 
        FROM issues WHERE gsoc_preparation_score > 7.0 AND state = 'OPEN' 
        ORDER BY gsoc_preparation_score DESC LIMIT 3
        ''')
        gsoc_opps = cursor.fetchall()
        for g in gsoc_opps:
            lines.append(f"- [{g[0]}]({g[1]}) - GSoC Score: {g[2]:.1f}")
        lines.append("")
        
        # 6. PROGRAM DEADLINES
        lines.append("## 6. PROGRAM DEADLINES/UPDATES")
        lines.append("No recorded program deadlines right now.")
        lines.append("")
        
        # 7. RECOMMENDED NEXT ACTION & HERMES TRIGGER
        lines.append("## 7. RECOMMENDED NEXT ACTION")
        if top_opps:
            best = top_opps[0]
            lines.append(f"The highest value opportunity is **{best['repo']}#{best['num']}** with score {best['score']:.1f}.")
            
            # Check configurable threshold (e.g. from agent.yaml)
            from src.implementer import get_agent_config
            from src.resource_manager import check_resources_for_hermes
            
            config = get_agent_config()
            threshold = config.get('hermes_auto_trigger_threshold', 50.0)
            
            if best['score'] >= threshold:
                lines.append(f"\nScore {best['score']:.1f} >= {threshold} threshold. Attempting to trigger Hermes...")
                from src.autonomous_guard import validate_hermes_execution

                ok, msg = validate_hermes_execution()
                if ok:
                    lines.append(f"Hermes preflight passed: {msg}. Triggering Hermes research/plan...")
                    try:
                        from src.hermes_agent import research, plan
                        print(f"Auto-triggering Hermes for top opportunity: {best['num']}")

                        research_ok = research(best['url'])
                        if not research_ok:
                            raise RuntimeError("Research phase failed.")

                        plan_ok = plan(best['url'])
                        if not plan_ok:
                            raise RuntimeError("Plan phase failed.")

                        log_event(
                            "hermes_auto_trigger",
                            "success",
                            f"Triggered Hermes research/plan for {best['repo']}#{best['num']}",
                            issue_id=best['num'],
                        )
                        lines.append(f"Successfully ran Hermes research/plan for {best['num']}.")
                    except Exception as e:
                        log_event(
                            "hermes_auto_trigger",
                            "failed",
                            f"Failed to run Hermes: {e}",
                            issue_id=best['num'],
                        )
                        lines.append(f"Failed to run Hermes: {e}")
                else:
                    log_event(
                        "hermes_auto_trigger",
                        "skipped",
                        f"Hermes preflight failed: {msg}",
                        issue_id=best['num'],
                    )
                    lines.append(f"Skipping Hermes auto-trigger: {msg}")
            else:
                lines.append(f"\nScore {best['score']:.1f} < {threshold} threshold. Skipping Hermes auto-trigger.")
        else:
            lines.append("Run `python main.py daily-run` to fetch new data.")
            
    with open(filepath, 'w') as f:
        f.write("\n".join(lines))
        
    print(f"Generated daily digest at {filepath}")
    log_event("digest", "success", f"Generated digest at {filepath}")
