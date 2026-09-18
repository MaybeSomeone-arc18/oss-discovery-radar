import pytest
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path
from src.implementer import (
    check_diff_guardrails,
    implement,
    generate_reports,
    cleanup_issue_workspace
)
from src.database import init_db, get_connection

# Explicit execution-provider handoff produced by the routing layer for a
# successful tool-required implementation (carries the env var NAME, never the
# credential value).
HANDOFF = {
    "provider_id": "omniroute",
    "base_url": "http://127.0.0.1:20128/v1",
    "api_key_env": "OMNIROUTE_API_KEY",
    "model": "free-coding-test",
}

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
        conn.execute(
            """
            UPDATE issues
            SET communication_status = 'APPROVED',
                communication_approved_at = CURRENT_TIMESTAMP
            WHERE url = 'http://test/999'
            """
        )
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

def test_successful_implementation(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.implementer.get_hermes_execution_handoff",
        lambda **kwargs: (True, "free-coding-test", "validated", HANDOFF),
    )

    monkeypatch.setattr(
        "src.implementer.requests.get",
        lambda *args, **kwargs: MagicMock(
            status_code=200,
            json=lambda: {"title": "Issue 999"},
        ),
    )
    fake_worktree = tmp_path / "worktree"
    fake_worktree.mkdir()

    monkeypatch.setattr(
        "src.implementer.create_worktree",
        lambda *args, **kwargs: fake_worktree,
    )
    monkeypatch.setattr(
        "src.implementer.check_diff_guardrails",
        lambda *args, **kwargs: (True, "OK"),
    )
    monkeypatch.setattr(
        "src.implementer.discover_and_run_tests",
        lambda *args, **kwargs: [
            {"framework": "pytest", "result": {"success": True}}
        ],
    )
    captured = {}

    def fake_hermes(*args, **kwargs):
        captured.update(kwargs)
        return "implemented"

    monkeypatch.setattr(
        "src.implementer.implement_issue_with_hermes",
        fake_hermes,
    )
    monkeypatch.setattr(
        "src.implementer.generate_reports",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.implementer.Path.exists",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "src.implementer.run_hermes_oneshot",
        lambda *args, **kwargs: "OK",
    )

    monkeypatch.setattr("builtins.open", mock_open(read_data="plan"))
    with patch("src.implementation_models.load_registry", return_value=[{"model_id": "free-coding-test", "availability_status": "AVAILABLE", "cooldown_until": 0, "free_only": True, "verified_filesystem_edit": True}]):
                implement(999)

    assert captured["model"] == "free-coding-test"
    # The explicit execution-provider config reaches the Hermes implementation call.
    assert captured["provider_config"] == HANDOFF

    from src.opportunity_manager import get_history
    hist = get_history("http://test/999")
    assert hist["lifecycle_status"] == "IMPLEMENTED_LOCAL"


@patch('src.implementer.requests.get')
@patch('src.implementer.subprocess.run')
@patch('src.implementer.create_worktree')
@patch('src.implementer.implement_issue_with_hermes')
@patch('src.implementer.check_diff_guardrails')
@patch('src.implementer.discover_and_run_tests')
@patch('src.implementer.repair_issue_with_hermes')
@patch('src.implementer.generate_reports')
@patch('src.implementer.Path.exists')
@patch('src.implementer.run_hermes_oneshot')
@patch('builtins.open')
def test_failed_implementation_repair_loop(mock_open, mock_run_oneshot, mock_exists, mock_gen_reports, mock_repair, mock_run_tests, mock_guardrails, mock_hermes, mock_worktree, mock_subprocess_run, mock_requests_get):
    mock_open.return_value.__enter__.return_value.read.return_value = 'TARGET FILES:\nsrc/main.py\nTARGET SYMBOL:\nn/a\nACCEPTANCE CRITERIA:\nworks well\nTARGETED TEST:\npytest test.py'
    mock_open.return_value.read.return_value = 'TARGET FILES:\nsrc/main.py\nTARGET SYMBOL:\nn/a\nACCEPTANCE CRITERIA:\nworks well\nTARGETED TEST:\npytest test.py'
    mock_exists.return_value = True
    mock_run_oneshot.return_value = "OK"
    mock_guardrails.return_value = (True, "OK")
    mock_subprocess_run.return_value = MagicMock(stdout="", returncode=0)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"title": "Issue 999"}
    mock_requests_get.return_value = mock_resp
    # Always fail tests
    mock_run_tests.return_value = [{"framework": "pytest", "result": {"success": False}}]

    with patch(
        "src.implementer.get_hermes_execution_handoff",
        return_value=(True, "free-coding-test", "validated", HANDOFF),
    ):
        with patch("src.implementation_models.load_registry", return_value=[{"model_id": "free-coding-test", "availability_status": "AVAILABLE", "cooldown_until": 0, "free_only": True, "verified_filesystem_edit": True}]):
                implement(999)

    # Repair should be called exactly once
    assert mock_repair.call_count == 1
    assert mock_repair.call_args.kwargs["model"] == "free-coding-test"
    assert mock_repair.call_args.kwargs["provider_config"] == HANDOFF

    # Should end in failed state
    from src.opportunity_manager import get_history
    hist = get_history("http://test/999")
    assert hist['lifecycle_status'] == 'IMPLEMENTATION_FAILED'

@patch('src.implementer.requests.get')
@patch('src.implementer.subprocess.run')
@patch('src.implementer.create_worktree')
@patch('src.implementer.implement_issue_with_hermes')
@patch('src.implementer.check_diff_guardrails')
@patch('src.implementer.discover_and_run_tests')
@patch('src.implementer.repair_issue_with_hermes')
@patch('src.implementer.generate_reports')
@patch('src.implementer.Path.exists')
@patch('src.implementer.run_hermes_oneshot')
@patch('builtins.open', new_callable=mock_open, read_data="Dummy plan content")
def test_failed_implementation_timeout_skips_repair(mock_open, mock_run_oneshot, mock_exists, mock_gen_reports, mock_repair, mock_run_tests, mock_guardrails, mock_hermes, mock_worktree, mock_subprocess_run, mock_requests_get):
    from src.implementer import implement
    mock_exists.return_value = True
    mock_run_oneshot.return_value = "OK"
    mock_guardrails.return_value = (True, "OK")
    mock_subprocess_run.return_value = MagicMock(stdout="", returncode=0)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"title": "Issue 999"}
    mock_requests_get.return_value = mock_resp
    mock_run_tests.return_value = [{"framework": "pytest", "result": {"success": True}}]

    mock_hermes.side_effect = Exception("subprocess.TimeoutExpired: Command 'hermes' timed out after 900 seconds")

    with patch(
        "src.implementer.get_hermes_execution_handoff",
        return_value=(True, "free-coding-test", "validated", HANDOFF),
    ):
        with patch("src.implementation_models.load_registry", return_value=[
            {"model_id": "free-coding-test", "availability_status": "AVAILABLE", "cooldown_until": 0, "free_only": True, "verified_filesystem_edit": True},
            {"model_id": "model-2", "availability_status": "AVAILABLE", "cooldown_until": 0, "free_only": True, "verified_filesystem_edit": True}
        ]):
            implement(999)

    # Repair should NOT be called
    assert mock_repair.call_count == 0
    # Hermes should have been called twice (once for each model)
    assert mock_hermes.call_count == 2
    assert mock_hermes.call_args_list[0].kwargs["model"] == "free-coding-test"
    assert mock_hermes.call_args_list[1].kwargs["model"] == "model-2"



@patch('src.implementer.get_hermes_execution_handoff')
@patch('src.implementer.requests.get')
@patch('src.implementer.subprocess.run')
@patch('src.implementer.create_worktree')
@patch('src.implementer.implement_issue_with_hermes')
@patch('src.implementer.check_diff_guardrails')
@patch('src.implementer.discover_and_run_tests')
@patch('src.implementer.generate_reports')
@patch('src.implementer.Path.exists')
@patch('src.implementer.run_hermes_oneshot')
@patch('builtins.open')
def test_implementation_marks_in_progress_before_hermes(
    mock_open,
    mock_run_oneshot,
    mock_exists,
    mock_gen_reports,
    mock_run_tests,
    mock_guardrails,
    mock_hermes,
    mock_worktree,
    mock_subprocess_run,
    mock_requests_get,
    mock_plan,
):
    mock_open.return_value.__enter__.return_value.read.return_value = 'TARGET FILES:\nsrc/main.py\nTARGET SYMBOL:\nn/a\nACCEPTANCE CRITERIA:\nworks well\nTARGETED TEST:\npytest test.py'
    mock_open.return_value.read.return_value = 'TARGET FILES:\nsrc/main.py\nTARGET SYMBOL:\nn/a\nACCEPTANCE CRITERIA:\nworks well\nTARGETED TEST:\npytest test.py'
    mock_exists.return_value = True
    mock_run_oneshot.return_value = "OK"
    mock_worktree.return_value = Path("/tmp/fake/worktree")
    mock_guardrails.return_value = (True, "OK")
    mock_subprocess_run.return_value = MagicMock(stdout="", returncode=0)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"title": "Issue 999"}
    mock_requests_get.return_value = mock_resp

    mock_run_tests.return_value = [{"framework": "pytest", "result": {"success": True}}]

    mock_plan.return_value = (True, "free-coding-test", "validated", HANDOFF)
    from src.opportunity_manager import get_history

    assert get_history("http://test/999")["lifecycle_status"] == "PLANNED"

    observed_states = []

    def observe_lifecycle(*args, **kwargs):
        observed_states.append(get_history("http://test/999")["lifecycle_status"])
        return "mock implementation"

    mock_hermes.side_effect = observe_lifecycle

    with patch("src.implementation_models.load_registry", return_value=[{"model_id": "free-coding-test", "availability_status": "AVAILABLE", "cooldown_until": 0, "free_only": True, "verified_filesystem_edit": True}]):
                implement(999)

    assert observed_states == ["IN_PROGRESS"]


def test_implement_blocks_without_communication_approval(monkeypatch):
    import src.implementer as implementer

    issue_url = "http://test/999"

    monkeypatch.setattr(
        implementer,
        "get_issue_context_by_url",
        lambda url: {
            "url": issue_url,
            "issue_number": 999,
            "org_slug": "test",
            "repo_name": "test/repo",
            "title": "Test issue",
            "body_preview": "Test body",
        },
    )
    monkeypatch.setattr(
        implementer.requests,
        "get",
        lambda *args, **kwargs: type(
            "Response",
            (),
            {"status_code": 200, "json": lambda self: {"title": "Test issue"}},
        )(),
    )
    monkeypatch.setattr(
        implementer,
        "get_hermes_execution_handoff",
        lambda **kwargs: (True, "free-coding-test", "validated", HANDOFF),
    )
    monkeypatch.setattr(
        implementer,
        "get_reports_dir",
        lambda *args: __import__("pathlib").Path("/tmp/nonexistent-radar-test"),
    )
    monkeypatch.setattr(
        "src.opportunity_manager.get_communication_state",
        lambda url: {
            "communication_status": "REVIEW_REQUIRED",
            "communication_recommendation": "Ask maintainer first.",
            "communication_reason": "Intent unclear.",
            "communication_approved_at": None,
        },
    )
    monkeypatch.setattr(
        "src.opportunity_manager.communication_allows_implementation",
        lambda url: False,
    )

    success, test_results, diff_stat = implementer.implement(issue_url)

    assert success is False
    assert test_results is None
    assert diff_stat == ""


def test_implement_allows_approved_communication(monkeypatch, tmp_path):
    import src.implementer as implementer

    issue_url = "http://test/999"

    monkeypatch.setattr(
        implementer,
        "get_issue_context_by_url",
        lambda url: {
            "url": issue_url,
            "issue_number": 999,
            "org_slug": "test",
            "repo_name": "test/repo",
            "title": "Test issue",
            "body_preview": "Test body",
        },
    )
    monkeypatch.setattr(
        implementer.requests,
        "get",
        lambda *args, **kwargs: type(
            "Response",
            (),
            {"status_code": 200, "json": lambda self: {"title": "Test issue"}},
        )(),
    )
    monkeypatch.setattr(
        implementer,
        "get_hermes_execution_handoff",
        lambda **kwargs: (True, "free-coding-test", "validated", HANDOFF),
    )
    plan_dir = tmp_path / "reports"
    plan_dir.mkdir()
    (plan_dir / "plan.md").write_text("PLAN")
    monkeypatch.setattr(
        implementer,
        "get_reports_dir",
        lambda *args: plan_dir,
    )
    monkeypatch.setattr(
        "src.opportunity_manager.communication_allows_implementation",
        lambda url: True,
    )
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    monkeypatch.setattr(
        implementer,
        "create_worktree",
        lambda *args, **kwargs: worktree,
    )
    monkeypatch.setattr(
        implementer,
        "transition_status",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        implementer,
        "implement_issue_with_hermes",
        lambda *args, **kwargs: "implemented",
    )
    monkeypatch.setattr(
        implementer,
        "repair_issue_with_hermes",
        lambda *args, **kwargs: "repaired",
    )
    monkeypatch.setattr(
        implementer,
        "run_hermes_oneshot",
        lambda *args, **kwargs: "OK",
    )
    monkeypatch.setattr(
        implementer,
        "check_diff_guardrails",
        lambda *args: (False, "stop test before execution"),
    )

    success, test_results, diff_stat = implementer.implement(issue_url)

    assert success is False
    assert test_results is None
    assert diff_stat == ""


def test_implement_defers_without_tool_capable_provider(monkeypatch, tmp_path):
    """When no tool-capable execution provider is available, implement() must
    defer before creating any worktree instead of running llama3.2:3b and
    returning a no-diff response."""
    import src.implementer as implementer

    from src.autonomous_guard import TOOL_REQUIRED_UNAVAILABLE_REASON

    issue_url = "http://test/999"

    monkeypatch.setattr(
        implementer,
        "get_issue_context_by_url",
        lambda url: {
            "url": issue_url,
            "issue_number": 999,
            "org_slug": "test",
            "repo_name": "test/repo",
            "title": "Test issue",
            "body_preview": "Test body",
        },
    )
    monkeypatch.setattr(
        implementer.requests,
        "get",
        lambda *args, **kwargs: type(
            "Response",
            (),
            {"status_code": 200, "json": lambda self: {"title": "Test issue"}},
        )(),
    )
    monkeypatch.setattr(
        implementer,
        "get_hermes_execution_handoff",
        lambda task_type="lightweight": (
            False,
            None,
            TOOL_REQUIRED_UNAVAILABLE_REASON,
            None,
        ),
    )
    monkeypatch.setattr(
        "src.opportunity_manager.communication_allows_implementation",
        lambda url: True,
    )
    worktree_calls = []
    monkeypatch.setattr(
        implementer,
        "create_worktree",
        lambda *args, **kwargs: worktree_calls.append(args) or tmp_path / "worktree",
    )

    success, test_results, diff_stat = implementer.implement(issue_url)

    assert success is False
    assert test_results is None
    assert diff_stat == ""
    # Deferred at the execution preflight; no worktree was ever created.
    assert worktree_calls == []

def test_create_patch_does_not_mutate_index(tmp_path):
    import subprocess
    from src.implementer import create_patch

    # Initialize a git repo
    subprocess.run(['git', 'init'], cwd=str(tmp_path), check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=str(tmp_path), check=True)
    subprocess.run(['git', 'config', 'user.name', 'test'], cwd=str(tmp_path), check=True)

    # Create an initial commit
    tracked_file = tmp_path / 'tracked.txt'
    tracked_file.write_text('initial')
    subprocess.run(['git', 'add', 'tracked.txt'], cwd=str(tmp_path), check=True)
    subprocess.run(['git', 'commit', '-m', 'init'], cwd=str(tmp_path), check=True)

    # Modify tracked file
    tracked_file.write_text('modified')

    # Create untracked file
    untracked_file = tmp_path / 'untracked.txt'
    untracked_file.write_text('new')

    output_patch = tmp_path / 'out.diff'
    res = create_patch(tmp_path, output_patch)
    assert res is True

    # Verify index is untouched (untracked file is still untracked)
    proc = subprocess.run(['git', 'status', '--porcelain'], cwd=str(tmp_path), capture_output=True, text=True)
    assert '?? untracked.txt' in proc.stdout
    assert ' M tracked.txt' in proc.stdout

    patch_content = output_patch.read_text()
    assert 'modified' in patch_content
    assert 'new' in patch_content
    assert 'untracked.txt' in patch_content

def test_generate_reports_implementation_diff(monkeypatch, tmp_path):
    from src.implementer import generate_reports
    import json

    captured = {}
    def fake_run(prompt, **kwargs):
        captured['prompt'] = prompt
        return '[FACT] Implementation details'

    monkeypatch.setattr('src.implementer.run_hermes_oneshot', fake_run)
    monkeypatch.setattr('src.implementer.get_hermes_execution_handoff', lambda task_type: (True, 'opencode-zen/nemotron-3.5-lightning-free', 'ok', None))

    generate_reports(123, tmp_path, tmp_path, None, '+++ b/some_file.py', True)

    prompt = captured.get('prompt', '')
    assert 'GIT DIFF:' in prompt
    assert '+++ b/some_file.py' in prompt
    assert 'Describe ONLY what is supported by the provided diff' in prompt


@patch('src.implementer.requests.get')
@patch('src.implementer.subprocess.run')
@patch('src.implementer.create_worktree')
@patch('src.implementer.implement_issue_with_hermes')
@patch('src.implementer.check_diff_guardrails')
@patch('src.implementer.generate_reports')
@patch('src.implementer.Path.exists')
@patch('src.implementer.run_hermes_oneshot')
@patch('builtins.open')
def test_guardrail_failure_patch_preservation(mock_open, mock_run_oneshot, mock_exists, mock_gen_reports, mock_guardrails, mock_hermes, mock_worktree, mock_subprocess_run, mock_requests_get):
    mock_open.return_value.__enter__.return_value.read.return_value = 'TARGET FILES:\nsrc/main.py\nTARGET SYMBOL:\nn/a\nACCEPTANCE CRITERIA:\nworks well\nTARGETED TEST:\npytest test.py'
    mock_open.return_value.read.return_value = 'TARGET FILES:\nsrc/main.py\nTARGET SYMBOL:\nn/a\nACCEPTANCE CRITERIA:\nworks well\nTARGETED TEST:\npytest test.py'
    from pathlib import Path
    mock_exists.return_value = True
    mock_run_oneshot.return_value = "OK"
    mock_worktree.return_value = Path("fake/worktree")

    mock_guardrails.return_value = (False, "Too many files modified")

    mock_subprocess_run.return_value = __import__('unittest').mock.MagicMock(stdout="fake diff", stderr="fake error", returncode=0)

    mock_resp = __import__('unittest').mock.MagicMock(status_code=200)
    mock_resp.json.return_value = {"title": "Issue 999"}
    mock_requests_get.return_value = mock_resp

    from src.implementer import implement
    from unittest.mock import patch

    with patch("src.implementer.get_hermes_execution_handoff", return_value=(True, "free-coding-test", "validated", None)):
        with patch("src.implementation_models.load_registry", return_value=[{"model_id": "free-coding-test", "availability_status": "AVAILABLE", "cooldown_until": 0, "free_only": True, "verified_filesystem_edit": True}]):
            with patch("src.implementer.get_reports_dir", return_value=Path("/tmp/reports")):
                implement(999)

    found_patch = False
    for call in mock_open.call_args_list:
        if call.args and str(call.args[0]).endswith("guardrail-fail.patch"):
            found_patch = True
            break

    assert found_patch

@patch('src.implementer.requests.get')
@patch('src.implementer.subprocess.run')
@patch('src.implementer.create_worktree')
@patch('src.implementer.implement_issue_with_hermes')
@patch('src.implementer.check_diff_guardrails')
@patch('src.implementer.generate_reports')
@patch('src.implementer.Path.exists')
@patch('src.implementer.run_hermes_oneshot')
@patch('builtins.open')
def test_failed_patch_replay_prevents_hermes_repair(mock_open, mock_run_oneshot, mock_exists, mock_gen_reports, mock_guardrails, mock_hermes, mock_worktree, mock_subprocess_run, mock_requests_get):
    mock_open.return_value.__enter__.return_value.read.return_value = 'TARGET FILES:\nsrc/main.py\nTARGET SYMBOL:\nn/a\nACCEPTANCE CRITERIA:\nworks well\nTARGETED TEST:\npytest test.py'
    mock_open.return_value.read.return_value = 'TARGET FILES:\nsrc/main.py\nTARGET SYMBOL:\nn/a\nACCEPTANCE CRITERIA:\nworks well\nTARGETED TEST:\npytest test.py'
    from pathlib import Path
    mock_exists.return_value = True
    mock_run_oneshot.return_value = "OK"
    mock_worktree.return_value = Path("fake/worktree")

    mock_guardrails.return_value = (False, "Too many files modified")

    mock_subprocess_run.return_value = __import__('unittest').mock.MagicMock(stdout="fake diff", stderr="git apply failed", returncode=1)

    mock_resp = __import__('unittest').mock.MagicMock(status_code=200)
    mock_resp.json.return_value = {"title": "Issue 999"}
    mock_requests_get.return_value = mock_resp

    from src.implementer import implement
    from unittest.mock import patch

    with patch("src.implementer.get_hermes_execution_handoff", return_value=(True, "free-coding-test", "validated", None)):
        with patch("src.implementation_models.load_registry", return_value=[{"model_id": "free-coding-test", "availability_status": "AVAILABLE", "cooldown_until": 0, "free_only": True, "verified_filesystem_edit": True}]):
            with patch("src.implementer.get_reports_dir", return_value=Path("/tmp/reports")):
                with patch("src.implementer.repair_issue_with_hermes") as mock_repair:
                    implement(999)

    assert mock_repair.call_count == 0
