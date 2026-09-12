from unittest.mock import patch
from datetime import datetime, timezone, timedelta

from src.database import (
    get_daily_run_state,
    record_daily_run_start,
    record_daily_run_complete,
    record_daily_run_failed,
    get_connection,
)


def test_first_run_starts(isolated_test_db):
    """A first run for today should start and record RUNNING."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    state = get_daily_run_state(today)
    assert state is None, "Should be no state before first run"

    record_daily_run_start(today)
    state = get_daily_run_state(today)
    
    assert state is not None
    assert state["status"] == "RUNNING"
    assert state["started_at"] is not None
    assert state["completed_at"] is None
    assert state["error_message"] is None


def test_second_run_same_day_blocked(isolated_test_db, capsys):
    """A completed run must make cmd_run_daily reject a second run the same day."""
    from main import cmd_run_daily

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Simulate a completed run
    record_daily_run_start(today)
    record_daily_run_complete(today)

    state = get_daily_run_state(today)
    assert state["status"] == "COMPLETED"

    # Second attempt to start must be rejected by the actual command
    with patch("main.cmd_daily_run") as mock_pipeline:
        cmd_run_daily()

    mock_pipeline.assert_not_called()
    out = capsys.readouterr().out
    assert "ALREADY_COMPLETED" in out

    # State must be untouched
    state2 = get_daily_run_state(today)
    assert state2["status"] == "COMPLETED"


def test_failed_run_can_be_retried(isolated_test_db):
    """A run marked FAILED must allow a retry the same day."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    record_daily_run_start(today)
    record_daily_run_failed(today, "some transient error")

    state = get_daily_run_state(today)
    assert state["status"] == "FAILED"
    assert state["error_message"] == "some transient error"

    # Should be able to start again (record_daily_run_start resets FAILED)
    record_daily_run_start(today)
    state2 = get_daily_run_state(today)
    assert state2["status"] == "RUNNING"
    assert state2["error_message"] is None  # cleared on retry


def test_successful_run_records_completion(isolated_test_db):
    """A run that completes successfully must record COMPLETED."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    record_daily_run_start(today)
    record_daily_run_complete(today)

    state = get_daily_run_state(today)
    assert state["status"] == "COMPLETED"
    assert state["completed_at"] is not None


def test_stale_running_allows_retry(isolated_test_db):
    """A RUNNING state stuck for >2 hours should be treated as stale and allow retry."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Insert a RUNNING record with an old started_at (>2 hours ago)
    old_start = datetime.now(timezone.utc) - timedelta(hours=3)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO daily_runs (run_date, status, started_at) VALUES (?, 'RUNNING', ?)",
            (today, old_start.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()

    state = get_daily_run_state(today)
    assert state["status"] == "RUNNING"

    # Should be able to record_daily_run_start again (overwrites stale RUNNING)
    record_daily_run_start(today)
    state2 = get_daily_run_state(today)
    assert state2["status"] == "RUNNING"
    # started_at should be refreshed to now
    assert state2["started_at"] != state["started_at"]


def test_recent_running_blocks_retry(isolated_test_db, capsys):
    """A RUNNING state <2 hours old must make cmd_run_daily refuse to rerun."""
    from main import cmd_run_daily

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Insert a RUNNING record with a recent started_at (<2 hours ago)
    recent_start = datetime.now(timezone.utc) - timedelta(minutes=30)
    recent_start_str = recent_start.strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO daily_runs (run_date, status, started_at) VALUES (?, 'RUNNING', ?)",
            (today, recent_start_str),
        )
        conn.commit()

    state = get_daily_run_state(today)
    assert state["status"] == "RUNNING"

    # The actual command must refuse to start while a fresh RUNNING state exists
    with patch("main.cmd_daily_run") as mock_pipeline:
        cmd_run_daily()

    mock_pipeline.assert_not_called()
    out = capsys.readouterr().out
    assert "already in progress" in out.lower()

    # State must be untouched (started_at not refreshed)
    state2 = get_daily_run_state(today)
    assert state2["status"] == "RUNNING"
    assert state2["started_at"] == recent_start_str
