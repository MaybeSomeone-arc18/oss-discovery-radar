import requests
from datetime import datetime, timedelta, timezone
from src.config import GITHUB_TOKEN, GRAPHQL_API_URL, TARGET_ORGANIZATIONS, MAX_REPOS_PER_ORG, LOOKBACK_DAYS
from src.database import save_repository, save_repository_metrics, init_db

def fetch_organization_intelligence():
    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN is not set.")
    
    init_db()
    print("Starting GitHub Intelligence Collector...")
    
    headers = {
        "Authorization": f"bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json"
    }

    past_date = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    since_date = past_date.strftime("%Y-%m-%dT%H:%M:%SZ")

    for org_slug in TARGET_ORGANIZATIONS:
        print(f"Fetching intelligence for organization: {org_slug}")
        
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
            "login": org_slug,
            "maxRepos": MAX_REPOS_PER_ORG
        }
        
        response = requests.post(GRAPHQL_API_URL, json={'query': query, 'variables': variables}, headers=headers)
        
        if response.status_code != 200:
            print(f"  [!] HTTP Error for {org_slug}: {response.status_code}")
            continue
            
        data = response.json()
        if 'errors' in data:
            print(f"  [!] GraphQL Error for {org_slug}: {data['errors'][0]['message']}")
            continue
            
        org_data = data.get('data', {}).get('organization')
        if not org_data:
            print(f"  [!] Organization not found or no access: {org_slug}")
            continue
            
        from src.database import save_organization
        save_organization(org_slug, org_data.get('name') or org_slug, url=f"https://github.com/{org_slug}")
            
        repos = org_data.get('repositories', {}).get('nodes', [])
        print(f"  Found {len(repos)} active repositories. Processing...")
        
        for repo in repos:
            repo_name = f"{org_slug}/{repo['name']}"
            
            save_repository(
                name=repo_name,
                url=repo['url'],
                org_slug=org_slug,
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
                    # Rough heuristic for external: assume if they opened it, they might be external, 
                    # but we can't fully know without checking membership. We'll count all merged PRs as good.
                    prs_external += 1 
            
            # Rough responsiveness logic
            maintainer_response_time = 24.0 # default fallback
            review_activity_score = min(100.0, (prs_merged / max(1, prs_opened)) * 100.0)
            
            save_repository_metrics(
                repo_name=repo_name,
                issues_created=issues_created,
                issues_closed=issues_closed,
                prs_opened=prs_opened,
                prs_merged=prs_merged,
                prs_external=prs_external,
                recent_commits=0, # Hard to get purely via simple GraphQL without complex tree queries
                maintainer_response_time=maintainer_response_time,
                review_activity_score=review_activity_score
            )
        
    print("Intelligence collection completed.")
