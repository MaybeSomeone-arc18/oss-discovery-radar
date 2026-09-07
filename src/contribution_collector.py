import requests
import json
from src.database import get_connection, save_issue, save_pull_request, init_db
from src.config import GITHUB_TOKEN, GRAPHQL_API_URL
from src.classifier import extract_tags

def get_target_repositories(limit=20):
    with get_connection() as conn:
        cursor = conn.cursor()
        # Prioritize repositories from verified organizations that have high scores and high activity
        cursor.execute('''
        SELECT r.name, r.org_slug
        FROM repositories r
        JOIN organizations o ON r.org_slug = o.slug
        JOIN repository_metrics m ON r.name = m.repo_name
        WHERE o.is_verified_github = 1 AND r.archived = 'False'
        ORDER BY 
            (o.opportunity_score * 0.5 + m.review_merge_activity_score * 0.5) DESC, 
            m.prs_merged_recently DESC
        LIMIT ?
        ''', (limit,))
        return cursor.fetchall()

def fetch_contributions(limit=20):
    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN is not set.")
    
    init_db()
    repos = get_target_repositories(limit)
    print(f"Starting Live Contribution Discovery for top {len(repos)} active repositories...")
    
    headers = {
        "Authorization": f"bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json"
    }

    # We fetch last 50 issues and last 50 PRs per repo
    for repo_name, org_slug in repos:
        owner, name = repo_name.split('/')
        print(f"Fetching contributions for {repo_name}...")
        
        query = """
        query($owner: String!, $name: String!) {
          repository(owner: $owner, name: $name) {
            issues(states: OPEN, first: 50, orderBy: {field: UPDATED_AT, direction: DESC}) {
              nodes {
                number
                title
                bodyText
                state
                createdAt
                updatedAt
                url
                author { login }
                assignees(first: 1) { totalCount }
                comments { totalCount }
                labels(first: 10) { nodes { name } }
                milestone { title }
              }
            }
            pullRequests(first: 50, orderBy: {field: UPDATED_AT, direction: DESC}) {
              nodes {
                number
                title
                state
                createdAt
                updatedAt
                mergedAt
                url
                author { login }
                reviews(first: 1) { totalCount }
                comments { totalCount }
              }
            }
          }
        }
        """
        
        variables = {"owner": owner, "name": name}
        response = requests.post(GRAPHQL_API_URL, json={'query': query, 'variables': variables}, headers=headers)
        
        if response.status_code != 200:
            print(f"  [!] HTTP Error for {repo_name}: {response.status_code}")
            continue
            
        data = response.json()
        if 'errors' in data:
            print(f"  [!] GraphQL Error for {repo_name}")
            continue
            
        repo_data = data.get('data', {}).get('repository')
        if not repo_data:
            continue
            
        # Process Issues
        issues = repo_data.get('issues', {}).get('nodes', [])
        for issue in issues:
            labels = [lbl['name'] for lbl in issue.get('labels', {}).get('nodes', [])]
            assignee_status = "ASSIGNED" if issue.get('assignees', {}).get('totalCount', 0) > 0 else "UNASSIGNED"
            author = issue.get('author', {}).get('login') if issue.get('author') else "Unknown"
            milestone = issue.get('milestone', {}).get('title') if issue.get('milestone') else None
            
            # Extract tags using our classifier
            tags = extract_tags([issue['title'], issue['bodyText'], ", ".join(labels)])
            
            save_issue(
                url=issue['url'],
                repo_name=repo_name,
                org_slug=org_slug,
                issue_number=issue['number'],
                title=issue['title'],
                created_at=issue['createdAt'],
                updated_at=issue['updatedAt'],
                state=issue['state'],
                labels=json.dumps(labels),
                body_preview=issue['bodyText'][:500] if issue['bodyText'] else "",
                comments_count=issue.get('comments', {}).get('totalCount', 0),
                author=author,
                assignee_status=assignee_status,
                milestone=milestone,
                classified_tags=tags
            )
            
        # Process PRs
        prs = repo_data.get('pullRequests', {}).get('nodes', [])
        for pr in prs:
            author = pr.get('author', {}).get('login') if pr.get('author') else "Unknown"
            reviews_count = pr.get('reviews', {}).get('totalCount', 0)
            comments_count = pr.get('comments', {}).get('totalCount', 0)
            total_comments = reviews_count + comments_count
            
            save_pull_request(
                url=pr['url'],
                pr_number=pr['number'],
                repo_name=repo_name,
                title=pr['title'],
                state=pr['state'],
                created_at=pr['createdAt'],
                updated_at=pr['updatedAt'],
                merged_at=pr['mergedAt'],
                author=author,
                review_comments_count=total_comments
            )

    print("Contribution collection completed.")
