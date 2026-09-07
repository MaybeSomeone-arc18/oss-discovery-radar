import sys
import argparse
import json
from src.github_client import fetch_issues
from src.triage_engine import generate_digest
from src.gsoc_collector import fetch_gsoc_organizations
from src.database import get_stats, init_db, get_connection
from src.github_collector import fetch_organization_intelligence
from src.scoring_engine import calculate_organization_scores

def cmd_issues():
    print("Starting OSS Discovery Radar (Issue Pipeline)...")
    try:
        issues = fetch_issues()
        print(f"Found {len(issues)} matching issues.")
        digest_path = generate_digest(issues)
        if digest_path:
            print(f"Pipeline completed successfully. Check {digest_path} for opportunities!")
        else:
            print("Pipeline completed. No digest generated as no issues matched criteria.")
    except Exception as e:
        print(f"Error executing pipeline: {e}", file=sys.stderr)
        sys.exit(1)

def cmd_gsoc():
    fetch_gsoc_organizations()

def cmd_status():
    init_db()
    stats = get_stats()
    print("Database Status:")
    for key, value in stats.items():
        print(f"  {key.capitalize()}: {value}")

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
    print(json.dumps(profile, indent=2))

def cmd_opportunities():
    from src.personal_fit import get_ranked_opportunities
    opps = get_ranked_opportunities()
    if not opps:
        print("No opportunities matched.")
        return
    
    print(f"{'Rank':<5} | {'Type':<12} | {'Organization':<20} | {'Score':<6} | {'Title'}")
    print("-" * 90)
    for i, o in enumerate(opps[:20], 1):
        print(f"{i:<5} | {o['type']:<12} | {o['organization'][:20]:<20} | {o['final_score']:<6.2f} | {o['title'][:40]}")

def cmd_opportunity(opp_id):
    from src.personal_fit import get_ranked_opportunities
    opps = get_ranked_opportunities()
    
    for o in opps:
        if o['id'] == opp_id:
            print(f"=== Opportunity: {o['title']} ===")
            print(f"ID: {o['id']} | Type: {o['type']} | Org: {o['organization']}")
            print(f"Final Score: {o['final_score']} (Personal Fit: {o['personal_fit']}, Org Score: {o['org_score']})")
            print(f"Why it fits: {o['why_it_fits']}")
            print(f"Matched Skills: {', '.join(o['matched_skills']) if o['matched_skills'] else 'None'}")
            print(f"Matched Interests: {', '.join(o['matched_interests']) if o['matched_interests'] else 'None'}")
            print(f"Missing Profile Skills (Sample): {', '.join(o['missing_skills']) if o['missing_skills'] else 'None'}")
            print(f"Learning Value: {', '.join(o['learning_value']) if o['learning_value'] else 'None'}")
            print("\nRecommended next action: Review the project code URL or repository issues to see if you can tackle a good first issue.")
            return
            
    print(f"Opportunity {opp_id} not found.")

def main():
    parser = argparse.ArgumentParser(description="OSS Discovery Radar")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    subparsers.add_parser("issues", help="Runs the existing GitHub issue pipeline.")
    subparsers.add_parser("gsoc", help="Fetches/updates GSoC historical data and stores it in SQLite.")
    subparsers.add_parser("status", help="Prints useful database statistics.")
    subparsers.add_parser("intel", help="Runs the Organization Intelligence Engine (GitHub collection + Scoring).")
    subparsers.add_parser("orgs", help="Prints a ranked table of organizations by opportunity score.")
    subparsers.add_parser("profile", help="Show current personal profile.")
    subparsers.add_parser("opportunities", help="Show top opportunities specifically for me.")
    
    org_parser = subparsers.add_parser("org", help="Prints a detailed report for one organization.")
    org_parser.add_argument("slug", help="Organization slug/name")
    
    opp_parser = subparsers.add_parser("opportunity", help="Prints a detailed explanation of one opportunity.")
    opp_parser.add_argument("id", help="Opportunity ID")
    
    args = parser.parse_args()
    
    if args.command == "issues":
        cmd_issues()
    elif args.command == "gsoc":
        cmd_gsoc()
    elif args.command == "status":
        cmd_status()
    elif args.command == "intel":
        cmd_intel()
    elif args.command == "orgs":
        cmd_orgs()
    elif args.command == "org":
        cmd_org(args.slug)
    elif args.command == "profile":
        cmd_profile()
    elif args.command == "opportunities":
        cmd_opportunities()
    elif args.command == "opportunity":
        cmd_opportunity(args.id)

if __name__ == "__main__":
    main()
