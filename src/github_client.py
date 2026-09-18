import requests
from datetime import datetime, timedelta, timezone
from src.config import GITHUB_TOKEN, GRAPHQL_API_URL, TARGET_ORGANIZATIONS

def build_search_query(org, timestamp_str):
    # Search for this specific org with comma-separated labels (which means OR)
    return f'is:issue is:open no:assignee org:{org} created:>{timestamp_str} label:"good first issue",bug,documentation,"help wanted"'


def format_discussion_context(body_text, author_login="Unknown", author_association=None, comments_nodes=None):
    """Format issue body and recent comments into bounded, attributed discussion context.

    Bounding strategy:
    - Issue body is truncated to max 4000 characters if exceptionally long.
    - Up to 15 recent comments are retrieved.
    - Each comment body is truncated to max 1000 characters.
    - Author identity and role (Maintainer vs Contributor) are explicitly attributed.
    """
    MAINTAINER_ASSOCIATIONS = {"MEMBER", "OWNER", "COLLABORATOR"}
    CONTRIBUTOR_ASSOCIATIONS = {"CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER"}

    def _get_role(login, assoc):
        if not assoc:
            return f"User ({login})"
        assoc_upper = assoc.upper()
        if assoc_upper in MAINTAINER_ASSOCIATIONS:
            return f"Maintainer ({login}, {assoc_upper})"
        elif assoc_upper in CONTRIBUTOR_ASSOCIATIONS:
            return f"Contributor ({login}, {assoc_upper})"
        else:
            return f"Community Member ({login}, {assoc_upper})"

    body = (body_text or "").strip()
    if len(body) > 4000:
        body = body[:4000] + "\n[...issue body truncated...]"

    body_role = _get_role(author_login or "Unknown", author_association)
    parts = [f"=== ISSUE BODY (by {body_role}) ===\n{body if body else 'No description provided.'}"]

    comments = comments_nodes or []
    if comments:
        parts.append(f"\n=== DISCUSSION HISTORY (showing last {len(comments)} comments) ===")
        for idx, comment in enumerate(comments, 1):
            c_author = comment.get("author", {}) if isinstance(comment.get("author"), dict) else {}
            c_login = c_author.get("login", "Unknown")
            c_assoc = c_author.get("association") or comment.get("authorAssociation")
            c_role = _get_role(c_login, c_assoc)
            c_created = comment.get("createdAt", "")
            c_body = (comment.get("bodyText") or comment.get("body") or "").strip()
            if len(c_body) > 1000:
                c_body = c_body[:1000] + "\n[...comment truncated...]"

            header = f"[Comment #{idx} by {c_role} at {c_created}]:"
            parts.append(f"\n{header}\n{c_body if c_body else '(empty comment)'}")

    return "\n".join(parts)


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
              author {
                login
                association: authorAssociation
              }
              comments(last: 15) {
                totalCount
                nodes {
                  author {
                    login
                    association: authorAssociation
                  }
                  bodyText
                  createdAt
                }
              }
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
            author_data = node.get("author") or {}
            author_login = author_data.get("login", "Unknown")
            author_assoc = author_data.get("association")

            comments_data = node.get("comments", {}).get("nodes", [])
            discussion_ctx = format_discussion_context(
                node.get("bodyText", ""),
                author_login,
                author_assoc,
                comments_data
            )

            issue = {
                "title": node.get("title"),
                "url": node.get("url"),
                "repo_name": node.get("repository", {}).get("nameWithOwner"),
                "repo_url": node.get("repository", {}).get("url"),
                "created_at": node.get("createdAt"),
                "labels": labels,
                "author": author_login,
                "body_preview": node.get("bodyText", "")[:200] + "..." if node.get("bodyText") else "",
                "discussion_context": discussion_ctx
            }
            issues.append(issue)

    return issues

def check_related_prs(repo_name, issue_number):
    if not GITHUB_TOKEN:
        return []

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # Check for PRs mentioning the issue number
    q = f"repo:{repo_name} type:pr {issue_number}"
    url = "https://api.github.com/search/issues"

    prs = []
    try:
        response = requests.get(url, params={"q": q}, headers=headers, timeout=10)
        if response.status_code == 200:
            prs.extend(response.json().get('items', []))
        elif response.status_code in (401, 403, 429):
            raise RuntimeError(
                f"GitHub PR validation unavailable for {repo_name}#{issue_number} "
                f"(HTTP {response.status_code})"
            )
        else:
            raise RuntimeError(
                f"GitHub PR search failed for {repo_name}#{issue_number} "
                f"(HTTP {response.status_code})"
            )
    except RuntimeError:
        raise
    except Exception as e:
        print(f"Error checking related PRs for {repo_name}#{issue_number}: {e}")

    # Check for recent commits mentioning the issue number (Milestone 11 enhancement)
    q_commit = f"repo:{repo_name} {issue_number}"
    url_commit = f"https://api.github.com/search/commits?q={q_commit}"
    # Commits search requires a specific accept header
    commit_headers = headers.copy()
    commit_headers["Accept"] = "application/vnd.github.cloak-preview+json"

    try:
        response_commit = requests.get(url_commit, headers=commit_headers, timeout=10)
        if response_commit.status_code == 200:
            # Add a mock PR structure for commits so it triggers the same penalty logic
            for commit in response_commit.json().get('items', []):
                prs.append({
                    'title': f"Commit: {commit.get('commit', {}).get('message', '').splitlines()[0]}",
                    'state': 'closed',  # treat merged commits as closed PRs
                    'html_url': commit.get('html_url')
                })
    except Exception as e:
        print(f"Error checking related commits for {repo_name}#{issue_number}: {e}")

    return prs

def fetch_contribution_model(repo_name):
    if not GITHUB_TOKEN:
        return {}

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    model = {
        "has_contributing": False,
        "has_pr_template": False,
        "has_issue_template": False
    }

    # Try fetching CONTRIBUTING.md
    try:
        url = f"https://api.github.com/repos/{repo_name}/contents/CONTRIBUTING.md"
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            model["has_contributing"] = True
    except:
        pass

    return model

