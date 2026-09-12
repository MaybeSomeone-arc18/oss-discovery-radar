import pytest
import os
from unittest.mock import patch, MagicMock
from src.scheduler import install_schedule, remove_schedule, schedule_status

@patch('src.scheduler.get_plist_path')
@patch('subprocess.run')
@patch('builtins.open')
def test_install_schedule_success(mock_open, mock_run, mock_get_plist):
    mock_path = MagicMock()
    mock_get_plist.return_value = mock_path
    
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_run.return_value = mock_result
    
    ok, msg = install_schedule(2, 30)
    assert ok is True
    assert "installed at 02:30" in msg
    mock_open.assert_called_once_with(mock_path, 'w')
    
    # Should call launchctl unload then load
    assert mock_run.call_count == 2
    assert "load" in mock_run.call_args_list[1][0][0]

@patch('src.scheduler.get_plist_path')
@patch('subprocess.run')
@patch('os.remove')
def test_remove_schedule_success(mock_remove, mock_run, mock_get_plist):
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_get_plist.return_value = mock_path
    
    ok, msg = remove_schedule()
    assert ok is True
    assert "removed" in msg
    mock_remove.assert_called_once_with(mock_path)

@patch('src.scheduler.get_plist_path')
def test_remove_schedule_not_installed(mock_get_plist):
    mock_path = MagicMock()
    mock_path.exists.return_value = False
    mock_get_plist.return_value = mock_path
    
    ok, msg = remove_schedule()
    assert ok is False
    assert "not installed" in msg

@patch('src.scheduler.get_plist_path')
@patch('subprocess.run')
def test_schedule_status_loaded(mock_run, mock_get_plist):
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_get_plist.return_value = mock_path
    
    mock_result = MagicMock()
    mock_result.stdout = "123 0 com.oss.discovery.radar\n"
    mock_run.return_value = mock_result
    
    status = schedule_status()
    assert "Installed and loaded" in status


def test_process_due_hermes_retries_clears_success(monkeypatch):
    from src.scheduler import process_due_hermes_retries

    url = "https://github.com/example/repo/issues/25"

    rows = [
        {
            "issue_number": 25,
            "url": url,
            "repo_name": "example/repo",
            "org_slug": "example",
            "lifecycle_status": "PLANNED",
            "hermes_retry_at": "2026-09-10 09:00:00",
        }
    ]

    cleared = []
    calls = []

    monkeypatch.setattr(
        "src.opportunity_manager.get_due_hermes_retries",
        lambda limit=10: rows,
    )
    monkeypatch.setattr(
        "src.autonomous_contributor.run_autonomous_by_url",
        lambda issue_url: calls.append(issue_url) or "/tmp/package",
    )
    monkeypatch.setattr(
        "src.opportunity_manager.clear_hermes_retry",
        lambda issue_url: cleared.append(issue_url),
    )

    result = process_due_hermes_retries()

    assert calls == [url]
    assert cleared == [url]
    assert result == [
        {
            "url": url,
            "result": "success",
            "package": "/tmp/package",
        }
    ]


def test_process_due_hermes_retries_reschedules_when_deferred(monkeypatch):
    from src.scheduler import process_due_hermes_retries

    url = "https://github.com/example/repo/issues/26"

    rows = [
        {
            "issue_number": 26,
            "url": url,
            "repo_name": "example/repo",
            "org_slug": "example",
            "lifecycle_status": "PLANNED",
            "hermes_retry_at": "2026-09-10 09:00:00",
        }
    ]

    scheduled = []
    cleared = []

    monkeypatch.setattr(
        "src.opportunity_manager.get_due_hermes_retries",
        lambda limit=10: rows,
    )
    monkeypatch.setattr(
        "src.autonomous_contributor.run_autonomous_by_url",
        lambda issue_url: None,
    )
    monkeypatch.setattr(
        "src.opportunity_manager.schedule_hermes_retry",
        lambda issue_url: scheduled.append(issue_url),
    )
    monkeypatch.setattr(
        "src.opportunity_manager.clear_hermes_retry",
        lambda issue_url: cleared.append(issue_url),
    )

    result = process_due_hermes_retries()

    assert scheduled == [url]
    assert cleared == []
    assert result == [
        {
            "url": url,
            "result": "deferred",
        }
    ]


def test_hermes_retry_schedule_status_loaded(monkeypatch):
    from src.scheduler import hermes_retry_schedule_status

    path = MagicMock()
    path.exists.return_value = True

    monkeypatch.setattr("src.scheduler.get_hermes_retry_plist_path", lambda: path)
    monkeypatch.setattr(
        "src.scheduler.subprocess.run",
        lambda *args, **kwargs: MagicMock(
            stdout="123 0 com.oss.discovery.radar.hermes-retries\n"
        ),
    )

    assert "installed and loaded" in hermes_retry_schedule_status()


def test_hermes_retry_schedule_not_installed(monkeypatch):
    from src.scheduler import hermes_retry_schedule_status

    path = MagicMock()
    path.exists.return_value = False

    monkeypatch.setattr("src.scheduler.get_hermes_retry_plist_path", lambda: path)

    assert "not installed" in hermes_retry_schedule_status()

def test_process_due_hermes_retries_stops_for_human_communication(monkeypatch):
    from src.scheduler import process_due_hermes_retries

    url = "https://github.com/example/repo/issues/27"

    rows = [
        {
            "issue_number": 27,
            "url": url,
            "repo_name": "example/repo",
            "org_slug": "example",
            "lifecycle_status": "RESEARCHED",
            "hermes_retry_at": "2026-09-10 09:00:00",
        }
    ]

    cleared = []
    scheduled = []

    monkeypatch.setattr(
        "src.opportunity_manager.get_due_hermes_retries",
        lambda limit=10: rows,
    )
    monkeypatch.setattr(
        "src.autonomous_contributor.run_autonomous_by_url",
        lambda issue_url: None,
    )
    monkeypatch.setattr(
        "src.opportunity_manager.get_communication_state",
        lambda issue_url: {"communication_status": "REVIEW_REQUIRED"},
    )
    monkeypatch.setattr(
        "src.opportunity_manager.clear_hermes_retry",
        lambda issue_url: cleared.append(issue_url),
    )
    monkeypatch.setattr(
        "src.opportunity_manager.schedule_hermes_retry",
        lambda issue_url: scheduled.append(issue_url),
    )

    result = process_due_hermes_retries()

    assert cleared == [url]
    assert scheduled == []
    assert result == [
        {
            "url": url,
            "result": "awaiting_human_communication",
        }
    ]

@patch('src.scheduler.get_plist_path')
@patch('subprocess.run')
@patch('builtins.open')
def test_daily_plist_exposes_gh_on_launchd_path(mock_open, mock_run, mock_get_plist):
    """The daily job's generated plist must add Homebrew's bin dir to launchd PATH."""
    mock_get_plist.return_value = MagicMock()
    mock_run.return_value = MagicMock(returncode=0)

    ok, msg = install_schedule(9, 0)
    assert ok is True

    written = mock_open.return_value.__enter__.return_value.write.call_args[0][0]
    assert "<key>EnvironmentVariables</key>" in written
    assert "<key>PATH</key>" in written
    assert "<string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>" in written


def test_hermes_retry_plist_exposes_gh_on_launchd_path(monkeypatch):
    """The Hermes retry job's generated plist must also add Homebrew's bin dir."""
    from src.scheduler import install_hermes_retry_schedule

    written = {}

    def fake_write_text(content):
        written["content"] = content

    mock_path = MagicMock()
    mock_path.write_text.side_effect = fake_write_text

    monkeypatch.setattr("src.scheduler.get_hermes_retry_plist_path", lambda: mock_path)
    monkeypatch.setattr(
        "src.scheduler.subprocess.run",
        lambda *args, **kwargs: MagicMock(returncode=0),
    )

    ok, msg = install_hermes_retry_schedule(interval_minutes=30)
    assert ok is True

    content = written["content"]
    assert "<key>EnvironmentVariables</key>" in content
    assert "<key>PATH</key>" in content
    assert "<string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>" in content
