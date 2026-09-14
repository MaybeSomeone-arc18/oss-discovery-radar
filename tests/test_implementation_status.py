"""Focused tests for Dashboard Phase 5A: read-only implementation lifecycle
visibility.

Covers (requirement 9):
- known issue with an active (currently running) stage
- unknown issue -> 404
- blocked state
- failed state
- completed / submission state
- malformed request
- GET/read-only behavior (SELECT-only, POST rejected with 405)
"""

import io
import json
from contextlib import contextmanager

from src.dashboard import DashboardHandler
from src.database import get_connection

ISSUE_URL = "http://github.com/owner/repo/issues/1"


class FakeHandler:
    """Minimal stand-in for BaseHTTPRequestHandler that captures responses
    instead of writing to a socket."""

    def __init__(self, path):
        self.path = path
        self.headers = {}
        self._rfile = io.BytesIO(b"")
        self.status = None
        self.payload = None
        self.response_headers = []

    @property
    def rfile(self):
        return self._rfile

    def send_response(self, code):
        self.status = code

    def send_header(self, name, value):
        self.response_headers.append((name, value))

    def end_headers(self):
        pass

    def send_json(self, data, status=200):
        self.payload = data
        self.status = status


def make_post_handler(path, body):
    payload = json.dumps(body).encode() if body is not None else b""
    handler = FakeHandler(path)
    handler.headers = {"Content-Length": str(len(payload))}
    handler._rfile = io.BytesIO(payload)
    return handler


def insert_issue(conn, url=ISSUE_URL, *, lifecycle_status="NEW",
                 comm_status="REVIEW_REQUIRED", recommendation=None,
                 eligibility_status="ELIGIBLE", researched=0, planned=0,
                 implemented=0, submitted=0, merged=0, dismissed=0,
                 dismissal_reason=None, approved_at=None):
    conn.execute(
        """
        INSERT INTO issues (url, repo_name, org_slug, issue_number, title,
                            created_at, updated_at, state, labels, body_preview,
                            eligibility_status, activity_status, lifecycle_status,
                            communication_status, communication_recommendation,
                            researched, planned, implemented, submitted, merged,
                            dismissed, dismissal_reason, communication_approved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (url, "owner/repo", "owner", 1, "Issue", "2025-01-01", "2025-01-02",
         "OPEN", "", "body", eligibility_status, "ACTIVE", lifecycle_status,
         comm_status, recommendation, researched, planned, implemented,
         submitted, merged, dismissed, dismissal_reason, approved_at),
    )
    conn.commit()


def seed_reports(tmp_path, *names):
    """Write artifact files under the monkeypatched workspaces root and return
    the reports dir."""
    reports = tmp_path / "owner" / "repo" / "reports" / "1"
    reports.mkdir(parents=True, exist_ok=True)
    for name in names:
        if name == "final-report.md":
            (reports / name).write_text("# Contribution Package: #1\n\n## Status\nREADY FOR HUMAN REVIEW\n")
        elif name == "summary.md":
            (reports / name).write_text("# Implementation Summary for Issue 1\n\n**Status:** SUCCESS\n")
        else:
            (reports / name).write_text("# " + name + "\n")
    return reports


def patch_workspaces(monkeypatch, tmp_path):
    monkeypatch.setattr("src.implementation_status.WORKSPACES_ROOT", tmp_path)
    monkeypatch.setattr("src.implementation_status.PREFLIGHT_ROOT", tmp_path)


# --- known issue with an active status --------------------------------------


def test_active_status_returns_implementation_snapshot(monkeypatch, tmp_path):
    """A known issue mid-implementation maps to stage IMPLEMENTATION with a
    running state; existing artifacts surface as report paths; the timeline
    marks earlier stages done and later stages pending."""
    with get_connection() as conn:
        insert_issue(conn, lifecycle_status="IN_PROGRESS", comm_status="COMMENT_SENT",
                     recommendation="Please proceed.", researched=1)
    reports = seed_reports(tmp_path, "research.md", "plan.md")
    worktree = tmp_path / "owner" / "repo" / "worktrees" / "1"
    worktree.mkdir(parents=True)
    patch_workspaces(monkeypatch, tmp_path)

    from src.implementation_status import get_implementation_status
    snapshot = get_implementation_status(ISSUE_URL)

    assert snapshot is not None
    assert snapshot["stage"] == "IMPLEMENTATION"
    assert snapshot["stage_label"] == "Implementation"
    assert snapshot["state"] == "running"
    assert snapshot["human_action_required"] is False
    assert snapshot["blocked_reason"] is None
    assert snapshot["failed_reason"] is None
    assert snapshot["last_updated"] is not None
    assert snapshot["paths"]["research"] == str(reports / "research.md")
    assert snapshot["paths"]["plan"] == str(reports / "plan.md")
    assert snapshot["paths"]["worktree"] == str(worktree)

    timeline = {t["stage"]: t["state"] for t in snapshot["timeline"]}
    assert timeline["RESEARCH"] == "done"
    assert timeline["COMMUNICATION"] == "done"
    assert timeline["PLAN"] == "done"
    assert timeline["IMPLEMENTATION"] == "active"
    assert timeline["TESTS"] == "pending"
    assert timeline["SUBMISSION"] == "pending"


def test_known_issue_before_work_starts_is_idle(monkeypatch, tmp_path):
    """A known issue with no local artifacts is idle at stage RESEARCH."""
    with get_connection() as conn:
        insert_issue(conn)
    patch_workspaces(monkeypatch, tmp_path)

    from src.implementation_status import get_implementation_status
    snapshot = get_implementation_status(ISSUE_URL)

    assert snapshot["stage"] == "RESEARCH"
    assert snapshot["state"] == "idle"
    assert snapshot["paths"] == {}


# --- unknown issue -> 404 ---------------------------------------------------


def test_unknown_issue_404(monkeypatch, tmp_path):
    handler = FakeHandler("/api/implementation/status?url=" + ISSUE_URL)
    DashboardHandler.do_GET(handler)

    assert handler.status == 404
    assert "error" in handler.payload


# --- blocked state ----------------------------------------------------------


def test_blocked_communication_rejected(monkeypatch, tmp_path):
    """Rejected communication maps to the terminal BLOCKED stage with a
    human-readable reason derived from existing state."""
    with get_connection() as conn:
        insert_issue(conn, lifecycle_status="RESEARCHED", comm_status="REJECTED",
                     recommendation="Proposed reply.", researched=1)
    patch_workspaces(monkeypatch, tmp_path)

    from src.implementation_status import get_implementation_status
    snapshot = get_implementation_status(ISSUE_URL)

    assert snapshot["stage"] == "BLOCKED"
    assert snapshot["state"] == "blocked"
    assert snapshot["blocked_reason"]
    assert snapshot["status"].startswith("Blocked")


# --- failed state -----------------------------------------------------------


def test_failed_state(monkeypatch, tmp_path):
    """IMPLEMENTATION_FAILED with a FAILED summary maps to FAILED with a
    reason; the timeline still shows what completed before the failure."""
    with get_connection() as conn:
        insert_issue(conn, lifecycle_status="IMPLEMENTATION_FAILED",
                     comm_status="COMMENT_SENT", recommendation="ok", researched=1)
    reports = seed_reports(tmp_path, "research.md", "plan.md")
    (reports / "summary.md").write_text("# Implementation Summary for Issue 1\n\n**Status:** FAILED\n")
    patch_workspaces(monkeypatch, tmp_path)

    from src.implementation_status import get_implementation_status
    snapshot = get_implementation_status(ISSUE_URL)

    assert snapshot["stage"] == "FAILED"
    assert snapshot["state"] == "failed"
    assert snapshot["failed_reason"]
    assert snapshot["status"].startswith("Failed")
    timeline = {t["stage"]: t["state"] for t in snapshot["timeline"]}
    assert timeline["RESEARCH"] == "done"
    assert timeline["PLAN"] == "done"


def test_failed_from_audit_log(monkeypatch, tmp_path):
    """An autonomous_run 'failed' audit entry is enough to derive FAILED with
    the recorded message."""
    with get_connection() as conn:
        insert_issue(conn, lifecycle_status="IN_PROGRESS", comm_status="COMMENT_SENT",
                     recommendation="ok", researched=1)
        conn.execute(
            "INSERT INTO audit_logs (timestamp, action, issue_id, result, message)"
            " VALUES (datetime('now'), 'autonomous_run', 1, 'failed', 'Tests still failing after repair.')"
        )
        conn.commit()
    seed_reports(tmp_path, "research.md", "plan.md")
    patch_workspaces(monkeypatch, tmp_path)

    from src.implementation_status import get_implementation_status
    snapshot = get_implementation_status(ISSUE_URL)

    assert snapshot["stage"] == "FAILED"
    assert "Tests still failing" in snapshot["failed_reason"]


# --- completed / submission state -------------------------------------------


def test_submission_state_package_ready(monkeypatch, tmp_path):
    """A generated contribution package with no failure maps to SUBMISSION and
    is flagged as waiting for human action."""
    with get_connection() as conn:
        insert_issue(conn, lifecycle_status="IMPLEMENTED_LOCAL",
                     comm_status="COMMENT_SENT", recommendation="ok", researched=1)
    seed_reports(tmp_path, "research.md", "plan.md", "patch.diff", "summary.md",
                 "review.md", "implementation.md", "final-report.md")
    patch_workspaces(monkeypatch, tmp_path)

    from src.implementation_status import get_implementation_status
    snapshot = get_implementation_status(ISSUE_URL)

    assert snapshot["stage"] == "SUBMISSION"
    assert snapshot["state"] == "waiting_human"
    assert snapshot["human_action_required"] is True
    assert snapshot["paths"]["package"]
    timeline = {t["stage"]: t["state"] for t in snapshot["timeline"]}
    assert timeline["SUBMISSION"] == "active"
    assert timeline["REVIEW"] == "done"


def test_completed_state_submitted(monkeypatch, tmp_path):
    """A human-declared SUBMITTED lifecycle is terminal COMPLETED."""
    with get_connection() as conn:
        insert_issue(conn, lifecycle_status="SUBMITTED", comm_status="COMMENT_SENT",
                     recommendation="ok", researched=1, submitted=1)
    patch_workspaces(monkeypatch, tmp_path)

    from src.implementation_status import get_implementation_status
    snapshot = get_implementation_status(ISSUE_URL)

    assert snapshot["stage"] == "COMPLETED"
    assert snapshot["state"] == "completed"
    assert snapshot["human_action_required"] is False
    assert snapshot["status"].startswith("Completed")


# --- malformed request ------------------------------------------------------


def test_malformed_request_missing_url():
    handler = FakeHandler("/api/implementation/status")
    DashboardHandler.do_GET(handler)

    assert handler.status == 400
    assert "url" in handler.payload["error"]


def test_malformed_request_invalid_url():
    handler = FakeHandler("/api/implementation/status?url=not-a-url")
    DashboardHandler.do_GET(handler)

    assert handler.status == 400
    assert "Invalid url" in handler.payload["error"]


# --- GET/read-only behavior -------------------------------------------------


def test_status_endpoint_is_read_only(monkeypatch, tmp_path):
    """GET /api/implementation/status executes only SELECTs against the local
    DB and returns a 200 JSON snapshot."""
    with get_connection() as conn:
        insert_issue(conn, lifecycle_status="IN_PROGRESS", comm_status="COMMENT_SENT",
                     recommendation="ok", researched=1)
    seed_reports(tmp_path, "research.md", "plan.md")
    patch_workspaces(monkeypatch, tmp_path)

    statements = []
    from src import database as database_module
    real_get_connection = database_module.get_connection

    @contextmanager
    def traced_conn():
        with real_get_connection() as conn:
            conn.set_trace_callback(lambda sql: statements.append(sql))
            yield conn

    monkeypatch.setattr("src.implementation_status.get_connection", traced_conn)
    monkeypatch.setattr("src.hermes_agent.get_connection", traced_conn)

    handler = FakeHandler("/api/implementation/status?url=" + ISSUE_URL)
    DashboardHandler.do_GET(handler)

    assert handler.status == 200
    assert handler.payload["stage"] == "IMPLEMENTATION"
    assert "error" not in handler.payload

    assert statements, "expected the endpoint to read the local DB"
    for sql in statements:
        verb = sql.lstrip().split(None, 1)[0].upper()
        assert verb in ("SELECT", "BEGIN", "COMMIT"), f"read-only endpoint issued a write: {sql}"


def test_status_endpoint_rejects_post():
    """POST on the lifecycle endpoint is rejected with 405 + Allow: GET."""
    handler = make_post_handler("/api/implementation/status", {"url": ISSUE_URL})
    DashboardHandler.do_POST(handler)

    assert handler.status == 405
    assert ("Allow", "GET") in handler.response_headers