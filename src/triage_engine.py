import os
from datetime import datetime
from collections import defaultdict
from src.database import save_issue, save_repository, init_db

def generate_digest(issues):
    init_db()
    if not issues:
        print("No issues found in the recent window. Skipping digest creation.")
        return None

    # Persist all issues and repos to SQLite
    for issue in issues:
        repo_name = issue['repo_name']
        repo_url = issue['repo_url']
        save_repository(repo_name, repo_url)
        save_issue(
            url=issue['url'],
            repo_name=repo_name,
            title=issue['title'],
            created_at=issue['created_at'],
            labels=issue['labels'],
            body_preview=issue['body_preview']
        )

    today = datetime.now().strftime("%Y-%m-%d")
    digest_filename = f"digests/digest_{today}.md"
    
    # Ensure directory exists
    os.makedirs("digests", exist_ok=True)

    # Group issues: high priority vs others
    high_priority = []
    others = []

    for issue in issues:
        labels_lower = [l.lower() for l in issue['labels']]
        if "good first issue" in labels_lower:
            high_priority.append(issue)
        else:
            others.append(issue)

    # Group by repository
    def group_by_repo(issue_list):
        grouped = defaultdict(list)
        for issue in issue_list:
            grouped[issue['repo_name']].append(issue)
        return grouped

    hp_grouped = group_by_repo(high_priority)
    others_grouped = group_by_repo(others)

    with open(digest_filename, "w", encoding="utf-8") as f:
        f.write(f"# OSS Discovery Radar - Daily Digest ({today})\n\n")
        f.write("This digest contains unassigned issues from target organizations created in the last 48 hours.\n\n")
        
        f.write("## 🌟 High Priority: Good First Issues\n\n")
        if not hp_grouped:
             f.write("*No 'Good First Issues' found today.*\n\n")
        else:
            for repo, repo_issues in hp_grouped.items():
                repo_url = repo_issues[0]['repo_url']
                f.write(f"### [{repo}]({repo_url})\n")
                for issue in repo_issues:
                    labels_str = ", ".join([f"`{l}`" for l in issue['labels']])
                    f.write(f"- **[{issue['title']}]({issue['url']})**\n")
                    f.write(f"  - Labels: {labels_str}\n")
                    f.write(f"  - Created: {issue['created_at']}\n")
                    # Clean up body preview formatting
                    preview = issue['body_preview'].replace('\n', ' ').strip()
                    f.write(f"  - Preview: *{preview}*\n\n")

        f.write("## 🛠️ Other Opportunities (Help Wanted, Bugs, Docs)\n\n")
        if not others_grouped:
             f.write("*No other issues found today.*\n\n")
        else:
            for repo, repo_issues in others_grouped.items():
                repo_url = repo_issues[0]['repo_url']
                f.write(f"### [{repo}]({repo_url})\n")
                for issue in repo_issues:
                    labels_str = ", ".join([f"`{l}`" for l in issue['labels']])
                    f.write(f"- **[{issue['title']}]({issue['url']})**\n")
                    f.write(f"  - Labels: {labels_str}\n")
                    f.write(f"  - Created: {issue['created_at']}\n")
                    preview = issue['body_preview'].replace('\n', ' ').strip()
                    f.write(f"  - Preview: *{preview}*\n\n")
                    
    print(f"Digest successfully generated: {digest_filename}")
    return digest_filename
