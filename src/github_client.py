import requests
from datetime import datetime, timedelta, timezone
from src.config import GITHUB_TOKEN, GRAPHQL_API_URL, TARGET_ORGANIZATIONS

def build_search_query(org, timestamp_str):
    # Search for this specific org with comma-separated labels (which means OR)
    return f'is:issue is:open no:assignee org:{org} created:>{timestamp_str} label:"good first issue",bug,documentation,"help wanted"'


def fetch_issues():
    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN is not set in the environment.")

    # Calculate timestamp for LOOKBACK_DAYS ago
    from src.config import LOOKBACK_DAYS
    past_date = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    timestamp_str = past_date.strftime("%Y-%m-%dT%H:%M:%SZ")

    graphql_query = """
    query SearchIssues($queryString: String!) {
      search(query: $queryString, type: ISSUE, first: 20) {
        issueCount
        edges {
          node {
            ... on Issue {
              title
              url
              createdAt
              bodyText
              repository {
                nameWithOwner
                url
              }
              labels(first: 10) {
                nodes {
                  name
                }
              }
            }
          }
        }
      }
    }
    """

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json"
    }

    issues = []

    for org in TARGET_ORGANIZATIONS:
        search_query = build_search_query(org, timestamp_str)
        response = requests.post(
            GRAPHQL_API_URL,
            json={"query": graphql_query, "variables": {"queryString": search_query}},
            headers=headers
        )

        if response.status_code != 200:
            print(f"Warning: GraphQL API request failed for org {org} with status code {response.status_code}: {response.text}")
            continue

        data = response.json()
        if "errors" in data:
            print(f"Warning: GraphQL API returned errors for org {org}: {data['errors']}")
            continue

        edges = data.get("data", {}).get("search", {}).get("edges", [])
        
        for edge in edges:
            node = edge.get("node", {})
            if not node:
                continue
                
            labels = [label["name"] for label in node.get("labels", {}).get("nodes", [])]
            
            issue = {
                "title": node.get("title"),
                "url": node.get("url"),
                "repo_name": node.get("repository", {}).get("nameWithOwner"),
                "repo_url": node.get("repository", {}).get("url"),
                "created_at": node.get("createdAt"),
                "labels": labels,
                "body_preview": node.get("bodyText", "")[:200] + "..." if node.get("bodyText") else ""
            }
            issues.append(issue)

    return issues
