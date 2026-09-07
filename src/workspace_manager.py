import os
import subprocess
import shutil
from pathlib import Path

WORKSPACES_ROOT = Path(__file__).parent.parent / "workspaces"
WORKSPACES_ROOT = WORKSPACES_ROOT.resolve()

def setup_workspace_dir(org, repo):
    base_dir = WORKSPACES_ROOT / org / repo
    (base_dir / "base").mkdir(parents=True, exist_ok=True)
    (base_dir / "worktrees").mkdir(parents=True, exist_ok=True)
    (base_dir / "reports").mkdir(parents=True, exist_ok=True)
    (base_dir / "patches").mkdir(parents=True, exist_ok=True)
    return base_dir

def get_base_repo_path(org, repo):
    return setup_workspace_dir(org, repo) / "base"

def clone_base_repository(org, repo, url):
    base_path = get_base_repo_path(org, repo)
    
    # Use a bare clone to save space, or a standard clone
    if not (base_path / ".git").exists() and not (base_path / "config").exists():
        print(f"Cloning {url} into {base_path}...")
        subprocess.run(["git", "clone", url, str(base_path)], check=True)
    else:
        print(f"Base repository for {org}/{repo} already exists. Fetching updates...")
        subprocess.run(["git", "fetch", "origin"], cwd=str(base_path), check=True)

def create_worktree(org, repo, issue_id, branch_name=None):
    base_path = get_base_repo_path(org, repo)
    worktrees_path = WORKSPACES_ROOT / org / repo / "worktrees"
    target_path = worktrees_path / str(issue_id)
    
    if not (base_path / ".git").exists() and not (base_path / "config").exists():
        clone_base_repository(org, repo, f"https://github.com/{org}/{repo}.git")
        
    if not branch_name:
        branch_name = f"issue-{issue_id}"
        
    if target_path.exists():
        print(f"Worktree for issue {issue_id} already exists at {target_path}")
        return target_path
        
    print(f"Creating worktree for {branch_name} at {target_path}...")
    
    # We must ensure we're creating the worktree correctly
    try:
        subprocess.run(["git", "worktree", "add", "-b", branch_name, str(target_path)], cwd=str(base_path), check=True)
    except subprocess.CalledProcessError:
        # If the branch already exists, just check it out
        subprocess.run(["git", "worktree", "add", str(target_path), branch_name], cwd=str(base_path), check=True)
        
    return target_path

def cleanup_worktree(org, repo, issue_id):
    base_path = get_base_repo_path(org, repo)
    worktrees_path = WORKSPACES_ROOT / org / repo / "worktrees"
    target_path = worktrees_path / str(issue_id)
    
    if target_path.exists():
        print(f"Removing worktree at {target_path}...")
        subprocess.run(["git", "worktree", "remove", "--force", str(target_path)], cwd=str(base_path), check=True)
