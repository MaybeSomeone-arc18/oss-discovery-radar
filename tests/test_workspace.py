import os
import pytest
from pathlib import Path
from src.workspace_manager import setup_workspace_dir, WORKSPACES_ROOT
from src.sandbox_runner import get_safe_env

def test_setup_workspace_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("src.workspace_manager.WORKSPACES_ROOT", tmp_path)
    
    org = "test-org"
    repo = "test-repo"
    
    setup_workspace_dir(org, repo)
    
    assert (tmp_path / org / repo / "base").exists()
    assert (tmp_path / org / repo / "worktrees").exists()
    assert (tmp_path / org / repo / "reports").exists()
    assert (tmp_path / org / repo / "patches").exists()

def test_safe_env():
    env = get_safe_env()
    assert "GITHUB_TOKEN" not in env
    assert "SECRET_KEY" not in env
    assert "PATH" in env
