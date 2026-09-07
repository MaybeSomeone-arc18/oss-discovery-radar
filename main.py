import sys
import argparse
import json
from src.github_client import fetch_issues
from src.triage_engine import generate_digest
from src.gsoc_collector import fetch_gsoc_organizations
from src.database import get_stats, init_db, get_connection
from src.github_collector import fetch_organization_intelligence
from src.scoring_engine import calculate_organization_scores

def cmd_issues(active_only=False, org_filter=None, limit=20, gsoc=False, meaningful=False):
    from src.database import get_connection
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Backwards compatible query just in case deep analysis hasn't run yet
        query = '''
        SELECT url, repo_name, issue_number, title, opportunity_score, activity_status,
               gsoc_preparation_score, contribution_value_score, engineering_depth, org_slug
        FROM issues
        WHERE state = 'OPEN' AND opportunity_score IS NOT NULL
        AND eligibility_status NOT IN ('LIKELY_SOLVED', 'SOLVED', 'BLOCKED_RELATED_PR', 'ACTIVE_WITH_WORK')
        '''
        params = []
        if active_only:
            query += " AND activity_status IN ('ACTIVE', 'LIKELY_ACTIVE')"
        if org_filter:
            query += " AND org_slug = ?"
            params.append(org_filter)
        if meaningful:
            query += " AND engineering_depth != 'TRIVIAL' AND contribution_type != 'MAINTENANCE'"
            
        if gsoc:
            query += " ORDER BY gsoc_preparation_score DESC NULLS LAST LIMIT ?"
        else:
            query += " ORDER BY contribution_value_score DESC NULLS LAST, opportunity_score DESC LIMIT ?"
            
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
    if not rows:
        print("No open contribution opportunities found. Try running `python main.py sync_issues` first.")
        return
        
    print(f"{'Rank':<4} | {'Org':<15} | {'Repo':<20} | {'Issue':<6} | {'C-Val':<5} | {'GSoC':<5} | {'Fit':<4} | {'Act':<6} | {'Title'}")
    print("-" * 110)
    for i, r in enumerate(rows, 1):
        url, repo, num, title, opp_score, status, gsoc_score, c_val, depth, org = r
        c_val_str = f"{c_val:.1f}" if c_val is not None else "N/A"
        gsoc_str = f"{gsoc_score:.1f}" if gsoc_score is not None else "N/A"
        fit_str = f"{opp_score:.1f}" if opp_score is not None else "N/A"
        act_str = status[:6] if status else "UNK"
        print(f"{i:<4} | {org[:15]:<15} | {repo[:20]:<20} | {num:<6} | {c_val_str:<5} | {gsoc_str:<5} | {fit_str:<4} | {act_str:<6} | {title[:30]}")

def cmd_analyze(issue_id_or_url):
    from src.database import get_connection
    from src.deep_analysis import analyze_and_update_issue, generate_contribution_brief
    from src.personal_fit import load_profile
    import json
    
    with get_connection() as conn:
        cursor = conn.cursor()
        if issue_id_or_url.isdigit():
            cursor.execute("SELECT * FROM issues WHERE issue_number = ?", (int(issue_id_or_url),))
        else:
            cursor.execute("SELECT * FROM issues WHERE url = ?", (issue_id_or_url,))
            
        row = cursor.fetchone()
        if not row:
            print("Issue not found.")
            return
            
        url = row[0] # assuming url is first column, let's just get from dict
        columns = [col[0] for col in cursor.description]
        issue_dict = dict(zip(columns, row))
        
    # Trigger deep analysis
    print(f"Running deep analysis on {issue_dict['url']}...")
    analyze_and_update_issue(issue_dict['url'])
    
    # Re-fetch after deep analysis
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM issues WHERE url = ?", (issue_dict['url'],))
        issue_dict = dict(zip(columns, cursor.fetchone()))
        
        cursor.execute("SELECT * FROM repository_analysis WHERE repo_name = ?", (issue_dict['repo_name'],))
        repo_row = cursor.fetchone()
        if repo_row:
            repo_columns = [col[0] for col in cursor.description]
            repo_dict = dict(zip(repo_columns, repo_row))
        else:
            repo_dict = None
            
    profile = load_profile()
    brief = generate_contribution_brief(issue_dict, repo_dict, profile)
    print(brief)

def cmd_issue(issue_id):
    from src.database import get_connection
    from src.github_client import check_related_prs
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT url, repo_name, issue_number, title, eligibility_status 
        FROM issues WHERE issue_number = ? OR url = ?
        ''', (issue_id, issue_id))
        row = cursor.fetchone()
        
    if not row:
        print(f"Issue {issue_id} not found in database.")
        return
        
    url, repo_name, issue_number, title, eligibility = row
    print(f"=== Issue #{issue_number} ===")
    print(f"Repository: {repo_name}")
    print(f"Title: {title}")
    print(f"URL: {url}")
    print(f"Current Eligibility Status: {eligibility}")
    
    print("\nFetching related PRs from GitHub...")
    prs = check_related_prs(repo_name, issue_number)
    if not prs:
        print("No related PRs found.")
    else:
        print("Related PRs:")
        for pr in prs:
            print(f" - PR #{pr.get('number')}: {pr.get('title')} (State: {pr.get('state')})")

def cmd_research(issue_id):
    from src.database import init_db
    init_db()
    from src.hermes_agent import research
    research(issue_id)

def cmd_plan(issue_id):
    from src.database import init_db
    init_db()
    from src.hermes_agent import plan
    plan(issue_id)

def cmd_implement(issue_id, auto_yes=False):
    from src.database import init_db
    init_db()
    if not auto_yes:
        print("WARNING:")
        print("This will allow Hermes to modify code in a LOCAL isolated worktree.")
        print("No GitHub writes will occur.")
        print("\nProceed? [y/N]")
        choice = input().strip().lower()
        if choice not in ['y', 'yes']:
            print("Implementation aborted.")
            return

    from src.implementer import implement
    implement(issue_id)

def cmd_review(issue_id):
    from src.implementer import review
    review(issue_id)

def cmd_workspace(issue_id):
    from src.implementer import show_workspace
    show_workspace(issue_id)

def cmd_cleanup(issue_id):
    print(f"WARNING: This will safely remove the isolated worktree for issue {issue_id}.")
    print("Reports and patches will be preserved.")
    print("\nProceed? [y/N]")
    choice = input().strip().lower()
    if choice not in ['y', 'yes']:
        print("Cleanup aborted.")
        return
        
    from src.implementer import cleanup_issue_workspace
    cleanup_issue_workspace(issue_id)

def cmd_gsoc():
    fetch_gsoc_organizations()

def cmd_status():
    init_db()
    stats = get_stats()
    print("Database Status:")
    for key, value in stats.items():
        print(f"  {key.capitalize()}: {value}")
        
    print("\nOpportunity Lifecycle Status:")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT lifecycle_status, COUNT(*) FROM issues GROUP BY lifecycle_status")
        for status, count in cursor.fetchall():
            print(f"  {status or 'UNKNOWN'}: {count}")

def cmd_intel():
    fetch_organization_intelligence()
    calculate_organization_scores()

def cmd_orgs():
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT slug, name, opportunity_score 
        FROM organizations 
        WHERE opportunity_score IS NOT NULL
        ORDER BY opportunity_score DESC
        ''')
        rows = cursor.fetchall()
        
        if not rows:
            print("No organization intelligence data found. Run 'python main.py intel' first.")
            return
            
        print(f"{'Rank':<5} | {'Organization':<30} | {'Score':<10}")
        print("-" * 55)
        for i, row in enumerate(rows, 1):
            score = f"{row[2]:.2f}" if row[2] is not None else "N/A"
            print(f"{i:<5} | {row[1][:30]:<30} | {score:<10}")

def cmd_org(slug):
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, opportunity_score, score_breakdown FROM organizations WHERE slug = ?", (slug,))
        org = cursor.fetchone()
        
        if not org:
            print(f"Organization '{slug}' not found.")
            return
            
        print(f"=== Report for {org[0]} ({slug}) ===")
        score = f"{org[1]:.2f}" if org[1] is not None else "N/A"
        print(f"Opportunity Score: {score}")
        
        if org[2]:
            print("\nScore Breakdown:")
            breakdown = json.loads(org[2])
            for k, v in breakdown.items():
                print(f"  {k}: {v}")
                
        # Repositories
        cursor.execute('''
        SELECT name, stars, forks, open_issues, open_prs
        FROM repositories WHERE org_slug = ?
        ORDER BY CAST(stars AS INTEGER) DESC LIMIT 5
        ''', (slug,))
        repos = cursor.fetchall()
        
        if repos:
            print("\nTop Repositories:")
            for r in repos:
                print(f"  - {r[0]} (Stars: {r[1]}, Forks: {r[2]}, Issues: {r[3]}, PRs: {r[4]})")

def cmd_profile():
    from src.personal_fit import load_profile
    profile = load_profile()
    if not profile:
        print("No profile found. Create config/profile.yaml")
        return
    import json
    print(json.dumps(profile, indent=2))

def cmd_opportunities(verified_only=False, confidence_filter=None):
    from src.personal_fit import get_ranked_opportunities
    opps = get_ranked_opportunities(verified_only=verified_only, confidence_filter=confidence_filter)
    if not opps:
        print("No opportunities matched.")
        return
    
    print(f"{'Rank':<4} | {'Org':<15} | {'Score':<5} | {'Conf':<6} | {'Data':<15} | {'Title'}")
    print("-" * 100)
    for i, o in enumerate(opps[:20], 1):
        print(f"{i:<4} | {o['organization'][:15]:<15} | {o['final_score']:<5.1f} | {o['confidence']:<6} | {o['data_completeness']:<15} | {o['title'][:40]}")

def cmd_opportunity(opp_id):
    from src.personal_fit import get_ranked_opportunities
    opps = get_ranked_opportunities()
    
    for o in opps:
        if o['id'] == opp_id:
            print(f"=== Opportunity: {o['title']} ===")
            print(f"ID: {o['id']} | Type: {o['type']} | Org: {o['organization']}")
            print(f"Final Score: {o['final_score']} (Personal Fit: {o['personal_fit']}, Org Score: {o['org_score']})")
            print(f"Data Completeness: {o['data_completeness']} | Confidence: {o['confidence']}")
            print(f"Classified Tags: {o['tags']}")
            print(f"Why it fits: {o['why_it_fits']}")
            print(f"Matched Skills: {', '.join(o['matched_skills']) if o['matched_skills'] else 'None'}")
            print(f"Matched Interests: {', '.join(o['matched_interests']) if o['matched_interests'] else 'None'}")
            print(f"Missing Profile Skills (Sample): {', '.join(o['missing_skills']) if o['missing_skills'] else 'None'}")
            print(f"Learning Value: {', '.join(o['learning_value']) if o['learning_value'] else 'None'}")
            print("\nRecommended next action: Review the project code URL or repository issues to see if you can tackle a good first issue.")
            return
            
    print(f"Opportunity {opp_id} not found.")

def cmd_enrich():
    from src.github_collector import enrich_organizations
    from src.scoring_engine import calculate_organization_scores
    from src.classifier import backfill_classifications
    from src.database import init_db
    init_db()
    print("Extracting classification tags...")
    backfill_classifications()
    enrich_organizations()
    calculate_organization_scores()

def cmd_sync_issues(limit=20):
    from src.contribution_collector import fetch_contributions
    from src.contribution_engine import score_and_classify_issues
    fetch_contributions(limit=limit)
    score_and_classify_issues()

def cmd_daily():
    from src.opportunity_manager import generate_daily_shortlist
    from src.database import init_db
    init_db()
    opps = generate_daily_shortlist(limit=10)
    if not opps:
        print("No new/watched opportunities available.")
        return
    print(f"{'Rank':<4} | {'Org':<15} | {'Repo':<20} | {'Issue':<6} | {'Val':<4} | {'GSoC':<4} | {'Fit':<4} | {'Action'}")
    print("-" * 110)
    for i, o in enumerate(opps, 1):
        cval = f"{o['c_val']:.1f}" if o['c_val'] else "N/A"
        gsoc = f"{o['gsoc']:.1f}" if o['gsoc'] else "N/A"
        fit = f"{o['fit']:.1f}" if o['fit'] else "N/A"
        print(f"{i:<4} | {o['org'][:15]:<15} | {o['repo'][:20]:<20} | {str(o['issue'])[:6]:<6} | {cval:<4} | {gsoc:<4} | {fit:<4} | {o['recommendation'][:30]}")

def cmd_changes():
    from src.opportunity_manager import get_changes_summary
    from src.database import init_db
    init_db()
    summary = get_changes_summary()
    print("Daily Delta:")
    print(f"  New Opportunities: {summary['new_opportunities']}")
    print(f"  Score Increased (>1.0): {summary['score_increased']}")
    print(f"  Score Decreased (<-1.0): {summary['score_decreased']}")

def cmd_history(issue_id):
    from src.opportunity_manager import get_history
    import json
    hist = get_history(issue_id)
    if not hist:
        print("Issue not found in history.")
        return
    for k, v in hist.items():
        print(f"{k}: {v}")

def cmd_dismiss(issue_id, reason):
    from src.opportunity_manager import transition_status
    transition_status(issue_id, "DISMISSED", reason=reason)
    print(f"Opportunity {issue_id} dismissed.")

def cmd_watch(issue_id):
    from src.opportunity_manager import transition_status
    transition_status(issue_id, "WATCHING")
    print(f"Now watching opportunity {issue_id}.")

def cmd_digest():
    from src.digest_generator import generate_daily_digest
    generate_daily_digest()

def cmd_daily_run():
    from src.opportunity_manager import run_daily_pipeline
    from src.digest_generator import generate_daily_digest
    run_daily_pipeline()
    generate_daily_digest()

def cmd_research_top():
    from src.opportunity_manager import select_top_for_research, transition_status
    from src.hermes_agent import research
    issue_id = select_top_for_research()
    if not issue_id:
        print("No valid opportunity found for top research.")
        return
    print(f"Selected top opportunity issue #{issue_id} for research.")
    research(issue_id)
    transition_status(issue_id, "RESEARCHED")
    print(f"Marked {issue_id} as RESEARCHED.")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="OSS Discovery Radar")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    subparsers.add_parser("gsoc", help="Fetches/updates GSoC historical data and stores it in SQLite.")
    subparsers.add_parser("status", help="Prints useful database statistics.")
    subparsers.add_parser("intel", help="Runs the Organization Intelligence Engine (GitHub collection + Scoring).")
    subparsers.add_parser("enrich", help="Intelligently enriches organization intelligence for top targets.")
    subparsers.add_parser("orgs", help="Prints a ranked table of organizations by opportunity score.")
    subparsers.add_parser("profile", help="Show current personal profile.")
    
    sync_parser = subparsers.add_parser("sync_issues", help="Fetch and score live contribution opportunities.")
    sync_parser.add_argument("--limit", type=int, default=20, help="Number of repos to query")
    
    issues_parser = subparsers.add_parser("issues", help="Show top contribution opportunities.")
    issues_parser.add_argument("--active", action="store_true", help="Show only ACTIVE or LIKELY_ACTIVE issues")
    issues_parser.add_argument("--org", help="Filter by organization slug")
    issues_parser.add_argument("--limit", type=int, default=20, help="Number of issues to return")
    issues_parser.add_argument("--gsoc", action="store_true", help="Prioritize GSoC preparation value")
    issues_parser.add_argument("--meaningful", action="store_true", help="Filter out trivial/maintenance issues")
    
    analyze_parser = subparsers.add_parser("analyze", help="Prints a detailed contribution brief for an issue.")
    analyze_parser.add_argument("id", help="Issue number or URL")
    
    research_parser = subparsers.add_parser("research", help="Run local Hermes research on an issue.")
    research_parser.add_argument("id", help="Issue number or URL")

    plan_parser = subparsers.add_parser("plan", help="Generate local Hermes implementation plan for an issue.")
    plan_parser.add_argument("id", help="Issue number or URL")

    implement_parser = subparsers.add_parser("implement", help="Run local Hermes implementation in an isolated worktree.")
    implement_parser.add_argument("id", help="Issue number or URL")
    implement_parser.add_argument("--yes", action="store_true", help="Bypass approval prompt")

    review_parser = subparsers.add_parser("review", help="Review local Hermes implementation results.")
    review_parser.add_argument("id", help="Issue number or URL")
    
    workspace_parser = subparsers.add_parser("workspace", help="Show current local worktree and implementation status.")
    workspace_parser.add_argument("id", help="Issue number or URL")
    
    cleanup_parser = subparsers.add_parser("cleanup", help="Safely remove the local worktree for an issue.")
    cleanup_parser.add_argument("id", help="Issue number or URL")
    
    opps_parser = subparsers.add_parser("opportunities", help="Show top opportunities specifically for me.")
    opps_parser.add_argument("--verified", action="store_true", help="Only show opportunities with verified GitHub org data")
    opps_parser.add_argument("--confidence", choices=["high", "medium", "low"], help="Filter by confidence level")
    
    org_parser = subparsers.add_parser("org", help="Prints a detailed report for one organization.")
    org_parser.add_argument("slug", help="Organization slug/name")
    
    opp_parser = subparsers.add_parser("opportunity", help="Prints a detailed explanation of one opportunity.")
    opp_parser.add_argument("id", help="Opportunity ID")
    
    issue_parser = subparsers.add_parser("issue", help="View issue details and related PRs")
    issue_parser.add_argument("id", help="Issue number or URL")
    
    subparsers.add_parser("daily", help="Print daily shortlist of opportunities")
    subparsers.add_parser("changes", help="Print summary of changes since last run")
    
    history_parser = subparsers.add_parser("history", help="Show history of an opportunity")
    history_parser.add_argument("id", help="Issue number or URL")
    
    dismiss_parser = subparsers.add_parser("dismiss", help="Dismiss an opportunity")
    dismiss_parser.add_argument("id", help="Issue number or URL")
    dismiss_parser.add_argument("reason", help="Reason for dismissal")
    
    watch_parser = subparsers.add_parser("watch", help="Watch an opportunity")
    watch_parser.add_argument("id", help="Issue number or URL")
    
    subparsers.add_parser("digest", help="Generate daily digest markdown")
    subparsers.add_parser("daily-run", help="Run the full daily data pipeline")
    subparsers.add_parser("research-top", help="Research the single highest value NEW opportunity locally")
    
    args = parser.parse_args()
    
    if args.command == "issues":
        cmd_issues(active_only=args.active, org_filter=args.org, limit=args.limit, gsoc=args.gsoc, meaningful=args.meaningful)
    elif args.command == "analyze":
        cmd_analyze(args.id)
    elif args.command == "research":
        cmd_research(args.id)
    elif args.command == "plan":
        cmd_plan(args.id)
    elif args.command == "implement":
        cmd_implement(args.id, auto_yes=args.yes)
    elif args.command == "review":
        cmd_review(args.id)
    elif args.command == "workspace":
        cmd_workspace(args.id)
    elif args.command == "cleanup":
        cmd_cleanup(args.id)
    elif args.command == "sync_issues":
        cmd_sync_issues(limit=args.limit)
    elif args.command == "gsoc":
        cmd_gsoc()
    elif args.command == "status":
        cmd_status()
    elif args.command == "intel":
        cmd_intel()
    elif args.command == "enrich":
        cmd_enrich()
    elif args.command == "orgs":
        cmd_orgs()
    elif args.command == "org":
        cmd_org(args.slug)
    elif args.command == "profile":
        cmd_profile()
    elif args.command == "opportunities":
        cmd_opportunities(verified_only=args.verified, confidence_filter=args.confidence)
    elif args.command == "opportunity":
        cmd_opportunity(args.id)
    elif args.command == "issue":
        cmd_issue(args.id)
    elif args.command == "daily":
        cmd_daily()
    elif args.command == "changes":
        cmd_changes()
    elif args.command == "history":
        cmd_history(args.id)
    elif args.command == "dismiss":
        cmd_dismiss(args.id, args.reason)
    elif args.command == "watch":
        cmd_watch(args.id)
    elif args.command == "digest":
        cmd_digest()
    elif args.command == "daily-run":
        cmd_daily_run()
    elif args.command == "research-top":
        cmd_research_top()

if __name__ == "__main__":
    main()
