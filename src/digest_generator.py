import os
from datetime import datetime
from src.database import get_connection

def generate_daily_digest():
    os.makedirs("digests", exist_ok=True)
    today_str = datetime.now().strftime("%Y-%m-%d")
    filepath = f"digests/daily_{today_str}.md"
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        lines = [f"# Daily OSS Radar Digest - {today_str}\n"]
        
        # 1. TOP OPPORTUNITIES
        lines.append("## 1. TOP OPPORTUNITIES")
        cursor.execute('''
        SELECT title, url, org_slug, contribution_value_score, opportunity_score, gsoc_preparation_score
        FROM issues
        WHERE lifecycle_status IN ('NEW', 'WATCHING') AND state = 'OPEN'
        ORDER BY contribution_value_score DESC NULLS LAST, opportunity_score DESC
        LIMIT 5
        ''')
        top_opps = cursor.fetchall()
        if not top_opps:
            lines.append("No top opportunities found today.")
        else:
            for opp in top_opps:
                cval = f"{opp[3]:.1f}" if opp[3] else "N/A"
                fit = f"{opp[4]:.1f}" if opp[4] else "N/A"
                lines.append(f"- **[{opp[2]}]** [{opp[0]}]({opp[1]})\n  - Value: {cval} | Fit: {fit}")
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
        
        # 7. RECOMMENDED NEXT ACTION
        lines.append("## 7. RECOMMENDED NEXT ACTION")
        if top_opps:
            lines.append(f"Consider running `python main.py research-top` to start researching the highest value opportunity: **{top_opps[0][0]}**.")
        else:
            lines.append("Run `python main.py daily-run` to fetch new data.")
            
    with open(filepath, 'w') as f:
        f.write("\n".join(lines))
        
    print(f"Generated daily digest at {filepath}")
