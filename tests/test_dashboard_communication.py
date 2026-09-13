"""Focused tests for Dashboard Phase 2: the communication-review inbox.

Covers:
- communication state appears in /api/data opportunities
- approve / reject / edit actions (POST only) change local DB state
- editing the recommendation persists locally
- no action endpoint performs any GitHub write (guard test)
- GET on the action endpoints is rejected with 405
"""

import io
import json
import os
import sqlite3
import types
from datetime import datetime
from unittest.mock import MagicMock

from src.dashboard import DashboardHandler


def make_conn():
    """Real in-memory SQLite matching the live schema for the issues table
    plus repositories (needed by the /api/data opportunities query)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
    conn.commit()
    return conn


def seed_issue(conn, url="http://test/1", comm_status="REVIEW_REQUIRED",
               recommendation="Please ask about scope before starting.",
               reason="Scope depends on maintainer intent.", approved_at=None):
    conn.execute(
        "INSERT INTO repositories (name, description) VALUES (?, ?)",
        ("test/repo", "desc"),
    )
    conn.execute(
        "INSERT INTO issues (url, repo_name, org_slug, issue_number, title,"
        " created_at, updated_at, state, labels, body_preview,"
        " eligibility_status, activity_status, communication_status,"
        " communication_recommendation, communication_reason,"
        " communication_approved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (url, "test/repo", "test", 1, "Issue", "2025-01-01", "2025-01-02",
         "OPEN", "", "body", "ELIGIBLE", "ACTIVE",
         comm_status, recommendation, reason, approved_at),
    )
    conn.commit()


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
        self.get_dashboard_data = types.MethodType(DashboardHandler.get_dashboard_data, self)

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


def patch_dashboard_read_deps(monkeypatch, conn):
    """Stub the read-only dependencies of get_dashboard_data so the
    /api/data integration test runs purely against the local DB."""
    monkeypatch.setattr("src.dashboard.get_connection", lambda: conn)
    monkeypatch.setattr("src.dashboard.schedule_status", lambda: "Installed and loaded")
    monkeypatch.setattr("src.dashboard.get_recent_logs", lambda n: [])
    monkeypatch.setattr("src.dashboard.calculate_first_contribution_score", lambda url: (10.0, ""))
    monkeypatch.setattr("src.dashboard.check_release_prerequisites", lambda *a: ("READY_NOW", ""))
    monkeypatch.setattr("src.dashboard.verify_local_provider", lambda: None)
    monkeypatch.setattr("glob.glob", lambda p: [])
    monkeypatch.setattr("os.path.getmtime", lambda p: 0)
    monkeypatch.setattr("builtins.open", lambda *a, **k: MagicMock())


def patch_local_db(monkeypatch, conn):
    """Route the action endpoints' get_connection to an in-memory DB."""
    monkeypatch.setattr("src.opportunity_manager.get_connection", lambda: conn)
    monkeypatch.setattr("src.dashboard.get_connection", lambda: conn)


def current_comm_state(conn, url):
    row = conn.execute(
        "SELECT communication_status, communication_recommendation,"
        " communication_reason, communication_approved_at FROM issues WHERE url = ?",
        (url,),
    ).fetchone()
    return dict(zip(
        ["status", "recommendation", "reason", "approved_at"], row)) if row else None


# --- communication state appears in /api/data -------------------------------


def test_communication_state_appears_in_api_data(monkeypatch):
    conn = make_conn()
    seed_issue(conn)
    patch_dashboard_read_deps(monkeypatch, conn)

    data = DashboardHandler.get_dashboard_data(None)

    opp = next(o for o in data["opportunities"] if o["url"] == "http://test/1")
    assert opp["communication"] == {
        "status": "REVIEW_REQUIRED",
        "recommendation": "Please ask about scope before starting.",
        "reason": "Scope depends on maintainer intent.",
        "approved_at": None,
    }


# --- approve action ---------------------------------------------------------


def test_approve_communication_changes_review_required_to_approved(monkeypatch):
    conn = make_conn()
    seed_issue(conn, comm_status="REVIEW_REQUIRED")
    patch_local_db(monkeypatch, conn)

    handler = make_post_handler("/api/communication/approve", {"url": "http://test/1"})
    DashboardHandler.do_POST(handler)

    assert handler.status == 200
    assert handler.payload["ok"] is True
    assert handler.payload["state"]["status"] == "APPROVED"
    assert handler.payload["state"]["approved_at"] is not None
    # Persisted locally in the issue row.
    state = current_comm_state(conn, "http://test/1")
    assert state["status"] == "APPROVED"
    assert state["approved_at"] is not None


# --- reject action ----------------------------------------------------------


def test_reject_communication_changes_to_rejected(monkeypatch):
    conn = make_conn()
    seed_issue(conn, comm_status="REVIEW_REQUIRED")
    patch_local_db(monkeypatch, conn)

    handler = make_post_handler("/api/communication/reject", {"url": "http://test/1"})
    DashboardHandler.do_POST(handler)

    assert handler.status == 200
    assert handler.payload["ok"] is True
    assert handler.payload["state"]["status"] == "REJECTED"
    state = current_comm_state(conn, "http://test/1")
    assert state["status"] == "REJECTED"
    assert state["approved_at"] is None
    # Reject without a reason keeps the existing reason.
    assert state["reason"] == "Scope depends on maintainer intent."


def test_reject_communication_with_reason_persists_reason(monkeypatch):
    conn = make_conn()
    seed_issue(conn, comm_status="REVIEW_REQUIRED")
    patch_local_db(monkeypatch, conn)

    handler = make_post_handler(
        "/api/communication/reject", {"url": "http://test/1", "reason": "Not needed."}
    )
    DashboardHandler.do_POST(handler)

    assert handler.status == 200
    state = current_comm_state(conn, "http://test/1")
    assert state["status"] == "REJECTED"
    assert state["reason"] == "Not needed."


# --- edit recommendation ----------------------------------------------------


def test_edit_recommendation_persists_locally(monkeypatch):
    conn = make_conn()
    seed_issue(conn)
    patch_local_db(monkeypatch, conn)

    handler = make_post_handler(
        "/api/communication/edit",
        {"url": "http://test/1", "recommendation": "Rewritten reply."},
    )
    DashboardHandler.do_POST(handler)

    assert handler.status == 200
    assert handler.payload["ok"] is True
    state = current_comm_state(conn, "http://test/1")
    # Edits persist in the local DB.
    assert state["recommendation"] == "Rewritten reply."
    # The existing reason is preserved, not overwritten.
    assert state["reason"] == "Scope depends on maintainer intent."
    # Mirroring the generation path: a new recommendation resets review state.
    assert state["status"] == "REVIEW_REQUIRED"
    assert state["approved_at"] is None


def test_edit_recommendation_requires_text(monkeypatch):
    conn = make_conn()
    seed_issue(conn)
    patch_local_db(monkeypatch, conn)

    handler = make_post_handler(
        "/api/communication/edit", {"url": "http://test/1", "recommendation": "   "}
    )
    DashboardHandler.do_POST(handler)

    assert handler.status == 400
    assert "recommendation" in handler.payload["error"]


# --- mark-sent action -------------------------------------------------------


def test_mark_sent_from_approved_works(monkeypatch):
    conn = make_conn()
    seed_issue(conn, comm_status="APPROVED", approved_at="2025-01-03 10:00:00")
    patch_local_db(monkeypatch, conn)

    handler = make_post_handler("/api/communication/mark-sent", {"url": "http://test/1"})
    DashboardHandler.do_POST(handler)

    assert handler.status == 200
    assert handler.payload["ok"] is True
    assert handler.payload["state"]["status"] == "COMMENT_SENT"
    state = current_comm_state(conn, "http://test/1")
    assert state["status"] == "COMMENT_SENT"
    # The approval timestamp is preserved for the human acknowledgement.
    assert state["approved_at"] == "2025-01-03 10:00:00"


def test_mark_sent_from_review_required_rejected(monkeypatch):
    conn = make_conn()
    seed_issue(conn, comm_status="REVIEW_REQUIRED")
    patch_local_db(monkeypatch, conn)

    handler = make_post_handler("/api/communication/mark-sent", {"url": "http://test/1"})
    DashboardHandler.do_POST(handler)

    assert handler.status == 409
    assert "approved" in handler.payload["error"].lower()
    assert current_comm_state(conn, "http://test/1")["status"] == "REVIEW_REQUIRED"


def test_mark_sent_from_rejected_rejected(monkeypatch):
    conn = make_conn()
    seed_issue(conn, comm_status="REJECTED")
    patch_local_db(monkeypatch, conn)

    handler = make_post_handler("/api/communication/mark-sent", {"url": "http://test/1"})
    DashboardHandler.do_POST(handler)

    assert handler.status == 409
    assert current_comm_state(conn, "http://test/1")["status"] == "REJECTED"


def test_mark_sent_from_not_required_rejected(monkeypatch):
    conn = make_conn()
    seed_issue(conn, comm_status="NOT_REQUIRED")
    patch_local_db(monkeypatch, conn)

    handler = make_post_handler("/api/communication/mark-sent", {"url": "http://test/1"})
    DashboardHandler.do_POST(handler)

    assert handler.status == 409
    assert current_comm_state(conn, "http://test/1")["status"] == "NOT_REQUIRED"


def test_mark_sent_unknown_issue_404(monkeypatch):
    conn = make_conn()
    patch_local_db(monkeypatch, conn)

    handler = make_post_handler("/api/communication/mark-sent", {"url": "http://nope/1"})
    DashboardHandler.do_POST(handler)

    assert handler.status == 404


# --- edit/reject remain safe -------------------------------------------------


def test_edit_after_sent_returns_to_review_required(monkeypatch):
    conn = make_conn()
    seed_issue(conn, comm_status="COMMENT_SENT", approved_at="2025-01-03 10:00:00")
    patch_local_db(monkeypatch, conn)

    handler = make_post_handler(
        "/api/communication/edit",
        {"url": "http://test/1", "recommendation": "Changed after sending."},
    )
    DashboardHandler.do_POST(handler)

    assert handler.status == 200
    state = current_comm_state(conn, "http://test/1")
    assert state["recommendation"] == "Changed after sending."
    assert state["status"] == "REVIEW_REQUIRED"
    assert state["approved_at"] is None


def test_edit_after_approved_returns_to_review_required(monkeypatch):
    conn = make_conn()
    seed_issue(conn, comm_status="APPROVED", approved_at="2025-01-03 10:00:00")
    patch_local_db(monkeypatch, conn)

    handler = make_post_handler(
        "/api/communication/edit",
        {"url": "http://test/1", "recommendation": "Reworded before sending."},
    )
    DashboardHandler.do_POST(handler)

    assert handler.status == 200
    state = current_comm_state(conn, "http://test/1")
    assert state["status"] == "REVIEW_REQUIRED"
    assert state["approved_at"] is None


def test_reject_after_sent_still_rejects(monkeypatch):
    conn = make_conn()
    seed_issue(conn, comm_status="COMMENT_SENT")
    patch_local_db(monkeypatch, conn)

    handler = make_post_handler("/api/communication/reject", {"url": "http://test/1"})
    DashboardHandler.do_POST(handler)

    assert handler.status == 200
    state = current_comm_state(conn, "http://test/1")
    assert state["status"] == "REJECTED"
    assert state["approved_at"] is None


# --- POST-only actions ------------------------------------------------------


def test_communication_actions_are_post_only(monkeypatch):
    conn = make_conn()
    seed_issue(conn)
    patch_local_db(monkeypatch, conn)

    for path in ("/api/communication/approve", "/api/communication/mark-sent"):
        handler = FakeHandler(path)
        DashboardHandler.do_GET(handler)

        assert handler.status == 405
        assert ("Allow", "POST") in handler.response_headers


# --- input validation -------------------------------------------------------


def test_communication_action_missing_url_rejected(monkeypatch):
    conn = make_conn()
    patch_local_db(monkeypatch, conn)

    handler = make_post_handler("/api/communication/approve", {})
    DashboardHandler.do_POST(handler)

    assert handler.status == 400
    assert "url" in handler.payload["error"]


def test_communication_action_unknown_issue_404(monkeypatch):
    conn = make_conn()
    patch_local_db(monkeypatch, conn)

    handler = make_post_handler("/api/communication/approve", {"url": "http://nope/1"})
    DashboardHandler.do_POST(handler)

    assert handler.status == 404


def test_communication_action_unknown_path_404(monkeypatch):
    conn = make_conn()
    patch_local_db(monkeypatch, conn)

    handler = make_post_handler("/api/communication/explode", {"url": "http://test/1"})
    DashboardHandler.do_POST(handler)

    assert handler.status == 404


# --- no GitHub writes -------------------------------------------------------


def test_no_github_write_on_any_action(monkeypatch):
    """Guard: the action endpoints must never touch GitHub. Every function in
    src.github_client would raise if called, and the only statements executed
    against the local DB are SELECTs and the issues UPDATE."""
    # Any GitHub call would explode loudly.
    for name in ("build_search_query", "fetch_issues", "check_related_prs", "fetch_contribution_model"):
        monkeypatch.setattr(
            f"src.github_client.{name}",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("GitHub write attempted")),
        )

    conn = make_conn()
    # APPROVED so every action below -- including mark-sent -- is valid from
    # its current state.
    seed_issue(conn, comm_status="APPROVED")
    statements = []
    conn.set_trace_callback(lambda sql: statements.append(sql))
    patch_local_db(monkeypatch, conn)

    for path, body in (
        ("/api/communication/mark-sent", {"url": "http://test/1"}),
        ("/api/communication/approve", {"url": "http://test/1"}),
        ("/api/communication/reject", {"url": "http://test/1"}),
        ("/api/communication/edit", {"url": "http://test/1", "recommendation": "New reply"}),
    ):
        handler = make_post_handler(path, body)
        DashboardHandler.do_POST(handler)
        assert handler.status == 200
        assert handler.payload["ok"] is True

    assert statements, "expected the action to touch the local DB"
    for sql in statements:
        verb = sql.lstrip().split(None, 1)[0].upper()
        # Only local reads, transaction control, and the issues UPDATE are
        # allowed: no GitHub writes, no schema changes, nothing else.
        assert verb in ("SELECT", "UPDATE", "BEGIN", "COMMIT"), f"unexpected statement: {sql}"
        if verb == "UPDATE":
            assert "issues" in sql