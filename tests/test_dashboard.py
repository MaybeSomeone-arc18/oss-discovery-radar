import os
import sqlite3
import types
from datetime import datetime
from unittest.mock import patch, MagicMock

from src.dashboard import DashboardHandler, collect_freshness_metadata


def make_test_conn():
    """Create a real in-memory SQLite connection with the live schema for
    freshness-metadata integration tests. The live schema uses FK, so we
    create the tables here (including the repo_eligibility column the
    dashboard opportunities query selects)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Minimal schema matching init_db (issues, repositories, daily_runs, audit_logs)
    conn.execute("""
        CREATE TABLE repositories (
            name TEXT PRIMARY KEY,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            repo_eligibility TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE issues (
            url TEXT PRIMARY KEY,
            repo_name TEXT,
            org_slug TEXT,
            issue_number INTEGER,
            title TEXT,
            created_at TEXT,
            updated_at TEXT,
            state TEXT,
            labels TEXT,
            body_preview TEXT,
            comments_count INTEGER DEFAULT 0,
            author TEXT,
            assignee_status TEXT,
            milestone TEXT,
            classified_tags TEXT,
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            eligibility_status TEXT,
            activity_status TEXT,
            gsoc_preparation_score REAL,
            contribution_value_score REAL,
            opportunity_score REAL,
            readiness_status TEXT,
            communication_status TEXT DEFAULT 'REVIEW_REQUIRED',
            communication_recommendation TEXT,
            communication_reason TEXT,
            communication_approved_at TIMESTAMP,
            FOREIGN KEY (repo_name) REFERENCES repositories(name)
        )
    """)
    conn.execute("""
        CREATE TABLE daily_runs (
            run_date TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            error_message TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            action TEXT NOT NULL,
            issue_id INTEGER,
            result TEXT,
            message TEXT
        )
    """)
    conn.commit()
    return conn


def seed_repository(conn, name):
    """Insert a repository row so issue inserts satisfy the FK."""
    conn.execute(
        "INSERT OR IGNORE INTO repositories (name, description) VALUES (?, ?)",
        (name, "desc"),
    )


def patch_dashboard_deps(monkeypatch, conn, **kw):
    """Stub every heavy/external dependency of get_dashboard_data so the
    function runs purely against the provided local DB connection.

    Supported kwargs: scheduler_status, logs, score, readiness,
    digest_glob, digest.
    """
    monkeypatch.setattr("src.dashboard.get_connection", lambda: conn)
    monkeypatch.setattr(
        "src.dashboard.schedule_status",
        lambda: kw.get("scheduler_status", "Installed and loaded"),
    )
    monkeypatch.setattr("src.dashboard.get_recent_logs", lambda n: kw.get("logs", []))
    monkeypatch.setattr(
        "src.dashboard.calculate_first_contribution_score",
        lambda url: (kw.get("score", 10.0), ""),
    )
    monkeypatch.setattr(
        "src.dashboard.check_release_prerequisites",
        lambda *a: (kw.get("readiness", "READY_NOW"), ""),
    )
    monkeypatch.setattr("src.dashboard.verify_local_provider", lambda: None)
    monkeypatch.setattr("glob.glob", lambda p: kw.get("digest_glob", []))
    monkeypatch.setattr("os.path.getmtime", lambda p: kw.get("mtime", 1000))

    mock_file = MagicMock()
    mock_file.__enter__.return_value.read.return_value = kw.get("digest", "digest")
    monkeypatch.setattr("builtins.open", lambda *a, **k: mock_file)


def seed_open_issue(conn, url, repo_name, updated_at, updated_at_raw=None):
    """Insert an OPEN/ELIGIBLE/ACTIVE issue that passes the dashboard query."""
    conn.execute(
        "INSERT INTO issues (url, repo_name, org_slug, issue_number, title,"
        " created_at, updated_at, state, labels, body_preview,"
        " eligibility_status, activity_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (url, repo_name, "test", 1, "Issue", updated_at,
         updated_at if updated_at_raw is None else updated_at_raw,
         "OPEN", "", "body", "ELIGIBLE", "ACTIVE"),
    )


class CapturingHandler:
    """Minimal stand-in for BaseHTTPRequestHandler that captures responses
    instead of writing to a socket."""

    def __init__(self, path="/api/data"):
        self.path = path
        self.status = None
        self.payload = None
        # Borrow the real implementation, bound to this fake instance.
        self.get_dashboard_data = types.MethodType(DashboardHandler.get_dashboard_data, self)

    def send_response(self, code):
        self.status = code

    def send_header(self, *args, **kwargs):
        pass

    def end_headers(self):
        pass

    def send_json(self, data, status=200):
        self.payload = data
        self.status = status


# --- a. /api/data remains read-only -----------------------------------------


def test_dashboard_data_remains_read_only(monkeypatch):
    """The dashboard payload is a pure read of the local DB: only SELECTs are
    executed, and the freshness metadata is included."""
    conn = make_test_conn()
    now = datetime.now().isoformat(timespec="seconds")
    seed_repository(conn, "test/repo")
    seed_open_issue(conn, "http://test/1", "test/repo", now)
    conn.execute(
        "INSERT INTO daily_runs (run_date, status, started_at, completed_at, error_message)"
        " VALUES (?, ?, ?, ?, ?)",
        ("2025-01-15", "COMPLETED", now, now, None),
    )
    conn.execute(
        "INSERT INTO audit_logs (timestamp, action, issue_id, result, message)"
        " VALUES (?, ?, ?, ?, ?)",
        (now, "sync", None, "success", "synced 5 repos"),
    )
    conn.commit()

    statements = []
    conn.set_trace_callback(lambda sql: statements.append(sql))
    patch_dashboard_deps(monkeypatch, conn)

    data = DashboardHandler.get_dashboard_data(None)

    assert "freshness" in data
    f = data["freshness"]
    assert "latest_issue_timestamp" in f
    assert "daily_run" in f
    assert "sync" in f
    assert "generated_at" in f
    assert "error" not in f

    # Every statement executed against the local DB was a read. A refresh
    # must never write rows, never sync, and never run the daily pipeline.
    assert statements, "expected the dashboard to read the local DB"
    for sql in statements:
        verb = sql.lstrip().split(None, 1)[0].upper()
        assert verb not in (
            "INSERT", "UPDATE", "DELETE", "REPLACE",
            "ALTER", "CREATE", "DROP",
        ), f"dashboard refresh issued a write statement: {sql}"


def test_api_data_endpoint_renders_snapshot_only(monkeypatch):
    """GET /api/data serves a 200 JSON snapshot with freshness metadata and
    never triggers sync/inference/pipeline (all deps are stubbed out)."""
    conn = make_test_conn()
    now = datetime.now().isoformat(timespec="seconds")
    seed_repository(conn, "test/repo")
    seed_open_issue(conn, "http://test/1", "test/repo", now)
    conn.commit()
    patch_dashboard_deps(monkeypatch, conn)

    handler = CapturingHandler("/api/data")
    DashboardHandler.do_GET(handler)

    assert handler.status == 200
    assert "error" not in handler.payload
    assert handler.payload["freshness"]["latest_issue_timestamp"] == now


# --- b. freshness metadata is returned --------------------------------------


def test_freshness_metadata_contains_expected_fields(monkeypatch):
    """Freshness payload includes latest_issue_timestamp, daily_run, sync,
    generated_at even when the DB is empty."""
    conn = make_test_conn()
    patch_dashboard_deps(monkeypatch, conn)

    data = DashboardHandler.get_dashboard_data(None)

    f = data["freshness"]
    assert "latest_issue_timestamp" in f
    assert "daily_run" in f
    assert "sync" in f
    assert "generated_at" in f
    assert isinstance(f["generated_at"], str)
    # All values may be None when nothing is stored, but the keys exist.
    assert f["latest_issue_timestamp"] is None
    assert f["daily_run"] is None
    assert f["sync"] is None


def test_freshness_reflects_actual_local_state(monkeypatch):
    """Freshness shows the actual issue timestamp, daily run, and sync from
    the local DB."""
    conn = make_test_conn()
    now = datetime.now().isoformat(timespec="seconds")
    seed_repository(conn, "test/repo")
    seed_open_issue(conn, "http://test/1", "test/repo", now)
    conn.execute(
        "INSERT INTO daily_runs (run_date, status, started_at, completed_at, error_message)"
        " VALUES (?, ?, ?, ?, ?)",
        ("2025-01-15", "COMPLETED", now, now, None),
    )
    conn.execute(
        "INSERT INTO audit_logs (timestamp, action, issue_id, result, message)"
        " VALUES (?, ?, ?, ?, ?)",
        (now, "sync", None, "success", "synced 5 repos"),
    )
    conn.commit()
    patch_dashboard_deps(monkeypatch, conn)

    f = DashboardHandler.get_dashboard_data(None)["freshness"]

    assert f["latest_issue_timestamp"] == now
    assert f["daily_run"] == {
        "run_date": "2025-01-15",
        "status": "COMPLETED",
        "started_at": now,
        "completed_at": now,
        "error_message": None,
    }
    assert f["sync"] == {
        "timestamp": now,
        "status": "success",
        "message": "synced 5 repos",
    }


def test_freshness_latest_issue_falls_back_to_discovered_at(monkeypatch):
    """When no issue has a usable updated_at, the newest discovered_at is used."""
    conn = make_test_conn()
    now = datetime.now().isoformat(timespec="seconds")
    seed_repository(conn, "test/repo")
    # Seeds updated_at='' and lets discovered_at default to now.
    conn.execute(
        "INSERT INTO issues (url, repo_name, org_slug, issue_number, title,"
        " created_at, updated_at, state, labels, body_preview,"
        " eligibility_status, activity_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("http://test/1", "test/repo", "test", 1, "Issue", now, "", "OPEN", "",
         "body", "ELIGIBLE", "ACTIVE"),
    )
    conn.commit()
    patch_dashboard_deps(monkeypatch, conn)

    f = DashboardHandler.get_dashboard_data(None)["freshness"]
    assert f["latest_issue_timestamp"] is not None


def test_freshness_sync_failed_shows_error(monkeypatch):
    """A failed sync audit log surfaces status + message in freshness."""
    conn = make_test_conn()
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO audit_logs (timestamp, action, issue_id, result, message)"
        " VALUES (?, ?, ?, ?, ?)",
        (now, "sync", None, "failed", "GitHub rate limit"),
    )
    conn.commit()
    patch_dashboard_deps(monkeypatch, conn)

    f = DashboardHandler.get_dashboard_data(None)["freshness"]

    assert f["sync"]["status"] == "failed"
    assert "GitHub rate limit" in f["sync"]["message"]


def test_collect_freshness_metadata_standalone(monkeypatch):
    """collect_freshness_metadata is a pure read-only function."""
    conn = make_test_conn()
    now = datetime.now().isoformat(timespec="seconds")
    seed_repository(conn, "test/repo2")
    conn.execute(
        "INSERT INTO issues (url, repo_name, org_slug, issue_number, title,"
        " created_at, updated_at, state, labels, body_preview,"
        " eligibility_status, activity_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("http://test/2", "test/repo2", "test", 2, "Issue 2", now, now, "OPEN",
         "", "body", "ELIGIBLE", "ACTIVE"),
    )
    conn.commit()
    monkeypatch.setattr("src.dashboard.get_connection", lambda: conn)

    f = collect_freshness_metadata()

    assert f["latest_issue_timestamp"] == now
    assert f["daily_run"] is None
    assert f["sync"] is None


# --- c. refresh errors are visible to the user ------------------------------


def test_freshness_error_captured_when_db_unavailable(monkeypatch):
    """A DB failure during freshness collection lands in the payload's
    freshness.error so the UI can display it."""
    def exploding_get_conn():
        raise RuntimeError("DB locked")

    monkeypatch.setattr("src.dashboard.get_connection", exploding_get_conn)
    monkeypatch.setattr("src.dashboard.schedule_status", lambda: "Installed and loaded")
    monkeypatch.setattr("src.dashboard.get_recent_logs", lambda n: [])
    monkeypatch.setattr("src.dashboard.calculate_first_contribution_score", lambda url: (10.0, ""))
    monkeypatch.setattr("src.dashboard.check_release_prerequisites", lambda *a: ("READY_NOW", ""))
    monkeypatch.setattr("src.dashboard.verify_local_provider", lambda: None)
    monkeypatch.setattr("glob.glob", lambda p: [])
    monkeypatch.setattr("os.path.getmtime", lambda p: 0)
    monkeypatch.setattr("builtins.open", lambda *a, **k: MagicMock())

    data = DashboardHandler.get_dashboard_data(None)

    assert data["freshness"]["error"] == "DB locked"


def test_api_data_endpoint_surfaces_errors_as_500(monkeypatch):
    """A payload build failure reaches the UI as a 500 JSON error (the UI
    shows 'Refresh failed' with the message)."""
    def boom():
        raise RuntimeError("boom: db corrupt")

    monkeypatch.setattr("src.dashboard.schedule_status", boom)
    monkeypatch.setattr("src.dashboard.get_recent_logs", lambda n: [])
    monkeypatch.setattr("src.dashboard.calculate_first_contribution_score", lambda url: (10.0, ""))
    monkeypatch.setattr("src.dashboard.check_release_prerequisites", lambda *a: ("READY_NOW", ""))
    monkeypatch.setattr("src.dashboard.verify_local_provider", lambda: None)
    monkeypatch.setattr("glob.glob", lambda p: [])
    monkeypatch.setattr("os.path.getmtime", lambda p: 0)
    monkeypatch.setattr("builtins.open", lambda *a, **k: MagicMock())

    handler = CapturingHandler("/api/data")
    DashboardHandler.do_GET(handler)

    assert handler.status == 500
    assert "boom: db corrupt" in handler.payload["error"]


# --- d. existing dashboard behavior remains intact where not related ---------


@patch('src.dashboard.get_connection')
@patch('src.dashboard.verify_local_provider')
@patch('src.dashboard.schedule_status')
@patch('src.dashboard.get_recent_logs')
@patch('glob.glob')
@patch('os.path.getmtime')
@patch('builtins.open')
@patch('src.dashboard.calculate_first_contribution_score')
@patch('src.dashboard.check_release_prerequisites')
def test_dashboard_data(mock_check_prereq, mock_calc_score, mock_open, mock_mtime, mock_glob, mock_logs, mock_sched, mock_verify, mock_get_conn):
    """Pre-existing dashboard payload behavior is preserved."""
    mock_verify.return_value = None  # success
    mock_sched.return_value = "Installed and loaded"
    mock_logs.return_value = [
        (1, "2023-10-10", "sync", None, "success", "msg")
    ]
    mock_glob.return_value = ["digests/daily_2023-10-10.md"]
    mock_mtime.return_value = 1000

    mock_file = MagicMock()
    mock_file.__enter__.return_value.read.return_value = "digest content"
    mock_open.return_value = mock_file

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_get_conn.return_value = mock_conn

    # Opportunities fetchall
    mock_cursor.fetchall.return_value = [
        ("url1", "repo1", 123, "title1", "preview", "org1",
         "REVIEW_REQUIRED", "suggested reply", "reason", None)
    ]
    # gsoc fetchone
    mock_cursor.fetchone.return_value = (5.5,)

    mock_calc_score.return_value = (80.0, "notes")
    mock_check_prereq.return_value = ("READY_NOW", "ev")

    data = DashboardHandler.get_dashboard_data(None)

    assert data['hermes_available'] is True
    assert data['scheduler_status'] == "Installed and loaded"
    assert len(data['events']) == 1
    assert data['digest'] == "digest content"
    assert len(data['opportunities']) == 1
    assert data['opportunities'][0]['repo'] == "repo1"
    assert data['opportunities'][0]['score'] == 80.0
    assert data['opportunities'][0]['gsoc'] == 5.5
    # The freshness metadata is added to the existing payload.
    assert 'freshness' in data


@patch('src.dashboard.verify_local_provider')
@patch('glob.glob')
def test_dashboard_hermes_fail(mock_glob, mock_verify):
    """Pre-existing hermes-failure handling is preserved."""
    mock_verify.side_effect = RuntimeError("Hermes failed")
    mock_glob.return_value = []

    with patch('src.dashboard.get_connection'), patch('src.dashboard.schedule_status'), patch('src.dashboard.get_recent_logs'):
        data = DashboardHandler.get_dashboard_data(None)

    assert data['hermes_available'] is False
    assert data['hermes_error'] == "Hermes failed"


def test_existing_events_digest_opportunities_unchanged(monkeypatch):
    """Existing payload fields (events, digest, opportunities) are unchanged
    when the local DB is healthy."""
    conn = make_test_conn()
    now = datetime.now().isoformat(timespec="seconds")
    seed_repository(conn, "test/repo")
    seed_open_issue(conn, "http://test/3", "test/repo", now)
    conn.execute(
        "INSERT INTO audit_logs (timestamp, action, issue_id, result, message)"
        " VALUES (?, ?, ?, ?, ?)",
        (now, "sync", None, "success", "msg"),
    )
    conn.commit()
    patch_dashboard_deps(
        monkeypatch, conn,
        logs=[(1, now, "digest", None, "success", "built digest")],
        digest_glob=["digests/daily_2025-01-01.md"],
        digest="digest content",
        score=90.0,
    )

    data = DashboardHandler.get_dashboard_data(None)

    assert data["digest"] == "digest content"
    assert len(data["events"]) == 1
    assert data["events"][0]["action"] == "digest"
    assert data["events"][0]["result"] == "success"
    assert data["opportunities"][0]["score"] == 90.0
    assert data["opportunities"][0]["repo"] == "test/repo"
def test_api_radar_start_endpoint_triggers_run_daily(monkeypatch):
    """POST /api/radar/start triggers cmd_run_daily in a background process."""
    import subprocess
    mock_popen = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", mock_popen)

    handler = CapturingHandler("/api/radar/start")
    handler.headers = {"Content-Length": "2"}
    handler.rfile = MagicMock()
    handler.rfile.read.return_value = b"{}"

    DashboardHandler.do_POST(handler)

    assert handler.status == 200
    mock_popen.assert_called_once()
    args, kwargs = mock_popen.call_args
    assert "main.py" in args[0]
    assert "run-daily" in args[0]

def test_api_radar_start_endpoint_post_only(monkeypatch):
    """GET /api/radar/start is not allowed (method safety)."""
    handler = CapturingHandler("/api/radar/start")
    DashboardHandler.do_GET(handler)

    # 404 or 405 depending on implementation. In our case we didn't add it to do_GET so it falls through to 404.
    assert handler.status == 404

def test_dashboard_data_includes_active_work(monkeypatch):
    from src.dashboard import DashboardHandler
    from src.dashboard import get_connection
    import sqlite3
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE issues (url TEXT, repo_name TEXT, issue_number INTEGER, title TEXT, lifecycle_status TEXT)')
    conn.execute("INSERT INTO issues VALUES ('http://test/99', 'test/repo', 99, 'Test', 'IMPLEMENTATION')")
    conn.commit()
    monkeypatch.setattr('src.dashboard.get_connection', lambda: conn)
    monkeypatch.setattr('src.dashboard.schedule_status', lambda: 'Active')
    monkeypatch.setattr('src.dashboard.get_recent_logs', lambda x: [])
    monkeypatch.setattr('src.dashboard.verify_local_provider', lambda: None)
    monkeypatch.setattr('glob.glob', lambda x: [])
    monkeypatch.setattr('src.dashboard.collect_freshness_metadata', lambda: {})
    data = DashboardHandler.get_dashboard_data(None)
    assert 'active_work' in data
    assert len(data['active_work']) == 1
    assert data['active_work'][0]['lifecycle_status'] == 'IMPLEMENTATION'
