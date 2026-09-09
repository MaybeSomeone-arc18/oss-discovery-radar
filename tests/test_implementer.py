import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from src.implementer import (
    check_diff_guardrails,
    implement,
    generate_reports,
    cleanup_issue_workspace
)
from src.database import init_db, get_connection

@pytest.fixture(autouse=True)
def setup_test_db():
    init_db()
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO organizations (slug, name) VALUES ('test-org', 'Test Org')")
        c.execute("INSERT OR IGNORE INTO repositories (name, org_slug) VALUES ('test-org/test-repo', 'test-org')")
        c.execute('''
        INSERT OR REPLACE INTO issues (url, repo_name, org_slug, issue_number, title, state, lifecycle_status)
        VALUES 
        ('http://test/999', 'test-org/test-repo', 'test-org', 999, 'Issue 999', 'OPEN', 'PLANNED')
        ''')
        conn.commit()
    yield

def test_guardrails_secret_detection():
    with patch('subprocess.run') as mock_run:
        # Simulate git diff returning a secret file
        mock_run.side_effect = [
            MagicMock(stdout=" M .env\n", returncode=0), # git status
            MagicMock(stdout=" 1 file changed", returncode=0), # git diff --stat
            MagicMock(stdout=".env\n", returncode=0) # git diff --name-only
        ]
        
        passed, msg = check_diff_guardrails("/tmp/fake")
        assert not passed
        assert "Potential secret file modified" in msg

def test_guardrails_too_many_files():
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout=" M file1\n", returncode=0),
            MagicMock(stdout=" 10 files changed", returncode=0),
            MagicMock(stdout="\n".join([f"file{i}" for i in range(10)]), returncode=0)
        ]
        
        passed, msg = check_diff_guardrails("/tmp/fake")
        assert not passed
        assert "Too many files changed" in msg

def test_guardrails_main_branch_modification():
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout=" M file1\n", returncode=0),
            MagicMock(stdout=" 1 file changed", returncode=0),
            MagicMock(stdout="file1\n", returncode=0),
            MagicMock(stdout="10\n11", returncode=0), # lines
            MagicMock(stdout="main\n", returncode=0) # branch
        ]
        
        passed, msg = check_diff_guardrails("/tmp/fake")
        assert not passed
        assert "Modified default branch directly: main" in msg

@patch('src.implementer.requests.get')
@patch('src.implementer.subprocess.run')
@patch('src.implementer.create_worktree')
@patch('src.implementer.implement_issue_with_hermes')
@patch('src.implementer.check_diff_guardrails')
@patch('src.implementer.discover_and_run_tests')
@patch('src.implementer.generate_reports')
@patch('src.implementer.Path.exists')
@patch('builtins.open')
def test_successful_implementation(mock_open, mock_exists, mock_gen_reports, mock_run_tests, mock_guardrails, mock_hermes, mock_worktree, mock_subprocess_run, mock_requests_get):
    mock_exists.return_value = True # plan file exists
    mock_worktree.return_value = Path("/tmp/fake/worktree")
    mock_guardrails.return_value = (True, "OK")
    mock_subprocess_run.return_value = MagicMock(stdout="", returncode=0)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"title": "Issue 999"}
    mock_requests_get.return_value = mock_resp
    mock_run_tests.return_value = [{"framework": "pytest", "result": {"success": True}}]
    
    implement(999)
    
    # It should transition to IMPLEMENTED_LOCAL
    from src.opportunity_manager import get_history
    hist = get_history(999)
    assert hist['lifecycle_status'] == 'IMPLEMENTED_LOCAL'

@patch('src.implementer.requests.get')
@patch('src.implementer.subprocess.run')
@patch('src.implementer.create_worktree')
@patch('src.implementer.implement_issue_with_hermes')
@patch('src.implementer.check_diff_guardrails')
@patch('src.implementer.discover_and_run_tests')
@patch('src.implementer.repair_issue_with_hermes')
@patch('src.implementer.generate_reports')
@patch('src.implementer.Path.exists')
@patch('builtins.open')
def test_failed_implementation_repair_loop(mock_open, mock_exists, mock_gen_reports, mock_repair, mock_run_tests, mock_guardrails, mock_hermes, mock_worktree, mock_subprocess_run, mock_requests_get):
    mock_exists.return_value = True
    mock_guardrails.return_value = (True, "OK")
    mock_subprocess_run.return_value = MagicMock(stdout="", returncode=0)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"title": "Issue 999"}
    mock_requests_get.return_value = mock_resp
    # Always fail tests
    mock_run_tests.return_value = [{"framework": "pytest", "result": {"success": False}}]
    
    implement(999)
    
    # Repair should be called exactly once
    assert mock_repair.call_count == 1
    
    # Should end in failed state
    from src.opportunity_manager import get_history
    hist = get_history(999)
    assert hist['lifecycle_status'] == 'IMPLEMENTATION_FAILED'


@patch('src.implementer.requests.get')
@patch('src.implementer.subprocess.run')
@patch('src.implementer.create_worktree')
@patch('src.implementer.implement_issue_with_hermes')
@patch('src.implementer.check_diff_guardrails')
@patch('src.implementer.discover_and_run_tests')
@patch('src.implementer.generate_reports')
@patch('src.implementer.Path.exists')
@patch('builtins.open')
def test_implementation_marks_in_progress_before_hermes(
    mock_open,
    mock_exists,
    mock_gen_reports,
    mock_run_tests,
    mock_guardrails,
    mock_hermes,
    mock_worktree,
    mock_subprocess_run,
    mock_requests_get,
):
    mock_exists.return_value = True
    mock_worktree.return_value = Path("/tmp/fake/worktree")
    mock_guardrails.return_value = (True, "OK")
    mock_subprocess_run.return_value = MagicMock(stdout="", returncode=0)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"title": "Issue 999"}
    mock_requests_get.return_value = mock_resp

    mock_run_tests.return_value = [{"framework": "pytest", "result": {"success": True}}]

    from src.opportunity_manager import get_history

    assert get_history(999)["lifecycle_status"] == "PLANNED"

    observed_states = []

    def observe_lifecycle(*args, **kwargs):
        observed_states.append(get_history(999)["lifecycle_status"])
        return "mock implementation"

    mock_hermes.side_effect = observe_lifecycle

    implement(999)

    assert observed_states == ["IN_PROGRESS"]
