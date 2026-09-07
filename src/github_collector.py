import requests
import time
import yaml
import os
from datetime import datetime, timedelta, timezone
from src.config import GITHUB_TOKEN, GRAPHQL_API_URL, TARGET_ORGANIZATIONS, MAX_REPOS_PER_ORG, LOOKBACK_DAYS, ENRICH_ORG_BATCH_SIZE, ORG_ALIASES_PATH
from src.database import save_repository, save_repository_metrics, init_db, get_connection, save_organization

def load_aliases():
    if not os.path.exists(ORG_ALIASES_PATH):
        return {}
    with open(ORG_ALIASES_PATH, 'r') as f:
        data = yaml.safe_load(f)
        return data.get('mappings', {}) if data else {}

def fetch_organization_intelligence(org_list=None):
    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN is not set.")
    
    init_db()
    
    orgs_to_process = org_list if org_list is not None else TARGET_ORGANIZATIONS
    print(f"Starting GitHub Intelligence Collector for {len(orgs_to_process)} organizations...")
    
    headers = {
        "Authorization": f"bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json"
    }

    past_date = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    since_date = past_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    aliases = load_aliases()

    for original_slug in orgs_to_process:
        github_slug = aliases.get(original_slug, original_slug)
        print(f"Fetching intelligence for organization: {original_slug} (GitHub: {github_slug})")
        
        query = """
        query($login: String!, $maxRepos: Int!) {
          organization(login: $login) {
            login
            name
            repositories(first: $maxRepos, orderBy: {field: PUSHED_AT, direction: DESC}, privacy: PUBLIC, isFork: false) {
              nodes {
                name
                url
                stargazerCount
                forkCount
                isArchived
                pushedAt
                primaryLanguage {
                  name
                }
                defaultBranchRef {
                  name
                }
                issues(states: OPEN) {
                  totalCount
                }
                pullRequests(states: OPEN) {
                  totalCount
                }
                # Activity metrics
                recentIssues: issues(last: 50, orderBy: {field: CREATED_AT, direction: DESC}) {
                  nodes {
                    createdAt
                    closedAt
                    state
                  }
                }
                recentPRs: pullRequests(last: 50, orderBy: {field: CREATED_AT, direction: DESC}) {
                  nodes {
                    createdAt
                    mergedAt
                    state
                    author {
                      login
                    }
                  }
                }
              }
            }
          }
        }
        """
        
        variables = {
            "login": github_slug,
            "maxRepos": MAX_REPOS_PER_ORG
        }
        
        # Retry logic
        max_retries = 3
        for attempt in range(max_retries):
            response = requests.post(GRAPHQL_API_URL, json={'query': query, 'variables': variables}, headers=headers)
            
            if response.status_code == 200:
                break
            elif response.status_code == 403: # Rate limit
                print(f"  [!] Rate limited. Sleeping for 10 seconds...")
                time.sleep(10)
            else:
                print(f"  [!] HTTP Error for {github_slug}: {response.status_code}")
                break
                
        if response.status_code != 200:
            continue
            
        data = response.json()
        if 'errors' in data:
            print(f"  [!] GraphQL Error for {github_slug}: {data['errors'][0]['message']}")
            # Mark as not verified if not found
            from src.scoring_engine import update_organization_score
            update_organization_score(original_slug, 0.0, {}, github_account=None, is_verified=False, confidence="LOW")
            continue
            
        org_data = data.get('data', {}).get('organization')
        if not org_data:
            print(f"  [!] Organization not found or no access: {github_slug}")
            # Mark as not verified
            from src.scoring_engine import update_organization_score
            update_organization_score(original_slug, 0.0, {}, github_account=None, is_verified=False, confidence="LOW")
            continue
            
        # Update organization to mark as verified
        save_organization(original_slug, org_data.get('name') or original_slug, url=f"https://github.com/{github_slug}")
        from src.scoring_engine import update_organization_score
        # Temporarily pass empty breakdown to mark verified; full score calc happens later
        update_organization_score(original_slug, 0.0, {}, github_account=github_slug, is_verified=True, confidence="MEDIUM")
            
        repos = org_data.get('repositories', {}).get('nodes', [])
        print(f"  Found {len(repos)} active repositories. Processing...")
        
        for repo in repos:
            repo_name = f"{github_slug}/{repo['name']}"
            
            save_repository(
                name=repo_name,
                url=repo['url'],
                org_slug=original_slug,
                stars=repo['stargazerCount'],
                forks=repo['forkCount'],
                open_issues=repo['issues']['totalCount'],
                open_prs=repo['pullRequests']['totalCount'],
                last_pushed_at=repo['pushedAt'],
                primary_language=repo['primaryLanguage']['name'] if repo.get('primaryLanguage') else None,
                archived=repo['isArchived'],
                default_branch=repo['defaultBranchRef']['name'] if repo.get('defaultBranchRef') else None
            )
            
            # Calculate metrics
            issues_created = 0
            issues_closed = 0
            for issue in repo.get('recentIssues', {}).get('nodes', []):
                if issue['createdAt'] >= since_date:
                    issues_created += 1
                if issue['state'] == 'CLOSED' and issue['closedAt'] and issue['closedAt'] >= since_date:
                    issues_closed += 1
                    
            prs_opened = 0
            prs_merged = 0
            prs_external = 0
            
            for pr in repo.get('recentPRs', {}).get('nodes', []):
                if pr['createdAt'] >= since_date:
                    prs_opened += 1
                if pr['state'] == 'MERGED' and pr['mergedAt'] and pr['mergedAt'] >= since_date:
                    prs_merged += 1
                    prs_external += 1 
            
            maintainer_response_time = 24.0 
            review_activity_score = min(100.0, (prs_merged / max(1, prs_opened)) * 100.0)
            
            save_repository_metrics(
                repo_name=repo_name,
                issues_created=issues_created,
                issues_closed=issues_closed,
                prs_opened=prs_opened,
                prs_merged=prs_merged,
                prs_external=prs_external,
                recent_commits=0, 
                maintainer_response_time=maintainer_response_time,
                review_activity_score=review_activity_score
            )
        
    print("Intelligence collection completed.")

def enrich_organizations():
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        # Prioritize orgs that are recent and have not been verified yet
        # For simplicity, we just look at max(year) and whether they are unverified
        cursor.execute('''
        SELECT o.slug 
        FROM organizations o
        JOIN gsoc_years y ON o.slug = y.org_slug
        WHERE o.is_verified_github = 0 OR o.opportunity_confidence = 'LOW' OR o.opportunity_confidence IS NULL
        GROUP BY o.slug
        ORDER BY MAX(y.year) DESC
        LIMIT ?
        ''', (ENRICH_ORG_BATCH_SIZE,))
        
        orgs = [row[0] for row in cursor.fetchall()]
        
    if orgs:
        print(f"Batch enriching {len(orgs)} organizations...")
        fetch_organization_intelligence(orgs)
    else:
        print("No new organizations to enrich.")
