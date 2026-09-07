import sys
import argparse
from src.github_client import fetch_issues
from src.triage_engine import generate_digest
from src.gsoc_collector import fetch_gsoc_organizations
from src.database import get_stats, init_db

def cmd_issues():
    print("Starting OSS Discovery Radar (Issue Pipeline)...")
    print("Fetching issues from GitHub API...")
    
    try:
        issues = fetch_issues()
        print(f"Found {len(issues)} matching issues.")
        
        print("Running triage engine, persisting to DB, and generating digest...")
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

def main():
    parser = argparse.ArgumentParser(description="OSS Discovery Radar")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Subcommand: issues
    subparsers.add_parser("issues", help="Runs the existing GitHub issue pipeline.")
    
    # Subcommand: gsoc
    subparsers.add_parser("gsoc", help="Fetches/updates GSoC historical data and stores it in SQLite.")
    
    # Subcommand: status
    subparsers.add_parser("status", help="Prints useful database statistics.")
    
    args = parser.parse_args()
    
    if args.command == "issues":
        cmd_issues()
    elif args.command == "gsoc":
        cmd_gsoc()
    elif args.command == "status":
        cmd_status()

if __name__ == "__main__":
    main()
