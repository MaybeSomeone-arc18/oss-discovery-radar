import requests
from src.config import GITHUB_TOKEN, GRAPHQL_API_URL
from src.database import save_repository_analysis

def analyze_repository(repo_full_name):
    """
    Fetches deeper metadata for a repository and caches it in SQLite.
    """
    if not GITHUB_TOKEN:
        print("GITHUB_TOKEN not set.")
        return None
        
    owner, name = repo_full_name.split('/')
    
    headers = {
        "Authorization": f"bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json"
    }

    query = """
    query($owner: String!, $name: String!) {
      repository(owner: $owner, name: $name) {
        description
        object(expression: "HEAD:") {
          ... on Tree {
            entries {
              name
              type
            }
          }
        }
        pullRequests(states: MERGED, first: 10, orderBy: {field: UPDATED_AT, direction: DESC}) {
          nodes {
            additions
            deletions
            changedFiles
            author { login }
            reviews(first: 1) { totalCount }
          }
        }
      }
    }
    """
    
    variables = {"owner": owner, "name": name}
    response = requests.post(GRAPHQL_API_URL, json={'query': query, 'variables': variables}, headers=headers)
    
    if response.status_code != 200:
        return None
        
    data = response.json().get('data', {}).get('repository')
    if not data:
        return None
        
    # Analyze root files
    has_readme = False
    has_contributing = False
    has_coc = False
    test_frameworks = []
    build_systems = []
    
    entries = data.get('object', {}).get('entries', []) if data.get('object') else []
    for entry in entries:
        lower_name = entry['name'].lower()
        if 'readme' in lower_name: has_readme = True
        if 'contributing' in lower_name: has_contributing = True
        if 'code_of_conduct' in lower_name: has_coc = True
        if lower_name in ['tests', 'test', 'spec', 'specs']: test_frameworks.append(entry['name'])
        if lower_name in ['package.json', 'pom.xml', 'build.gradle', 'cargo.toml', 'requirements.txt', 'makefile', 'cmakelists.txt']: 
            build_systems.append(entry['name'])
            
    # Analyze PR patterns
    prs = data.get('pullRequests', {}).get('nodes', [])
    avg_additions = sum(pr.get('additions', 0) for pr in prs) / max(len(prs), 1)
    avg_files = sum(pr.get('changedFiles', 0) for pr in prs) / max(len(prs), 1)
    
    pr_patterns = {
        "typical_additions": avg_additions,
        "typical_changed_files": avg_files,
        "recent_merged_count": len(prs)
    }
    
    save_repository_analysis(
        repo_name=repo_full_name,
        has_readme=has_readme,
        has_contributing=has_contributing,
        has_code_of_conduct=has_coc,
        description=data.get('description') or "",
        test_frameworks=test_frameworks,
        build_systems=build_systems,
        pr_patterns=pr_patterns
    )
    
    return {
        "has_readme": has_readme,
        "has_contributing": has_contributing,
        "has_code_of_conduct": has_coc,
        "description": data.get('description'),
        "test_frameworks": test_frameworks,
        "build_systems": build_systems,
        "pr_patterns": pr_patterns
    }
