import os
import sqlite3
import pytest
from datetime import datetime, timedelta
from src.database import init_db, get_connection
from src.opportunity_manager import (
    transition_status, generate_daily_shortlist, get_history,
    get_changes_summary, select_top_for_research
)
@pytest.fixture(autouse=True)
def setup_test_db():
    init_db()
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO organizations (slug, name, opportunity_confidence) VALUES ('test-org', 'Test Org', 'high')")
        c.execute("INSERT INTO repositories (name, org_slug) VALUES ('test-org/test-repo', 'test-org')")
        c.execute('''
        INSERT INTO issues (url, repo_name, org_slug, issue_number, title, state, opportunity_score, contribution_value_score, gsoc_preparation_score, lifecycle_status, first_seen_at)
        VALUES 
        ('http://test/1', 'test-org/test-repo', 'test-org', 1, 'Issue 1', 'OPEN', 8.0, 8.0, 6.0, 'NEW', CURRENT_TIMESTAMP),
        ('http://test/2', 'test-org/test-repo', 'test-org', 2, 'Issue 2', 'OPEN', 5.0, 5.0, 4.0, 'NEW', CURRENT_TIMESTAMP),
        ('http://test/3', 'test-org/test-repo', 'test-org', 3, 'Issue 3', 'OPEN', 9.0, 9.0, 8.0, 'WATCHING', CURRENT_TIMESTAMP)
        ''')
        conn.commit()

def test_lifecycle_transitions():
    transition_status('http://test/1', 'WATCHING', notes="looks good")
    hist = get_history('http://test/1')
    assert hist['lifecycle_status'] == 'WATCHING'
    assert hist['user_notes'] == 'looks good'
    
    transition_status('http://test/1', 'DISMISSED', reason="too hard")
    hist = get_history('http://test/1')
    assert hist['lifecycle_status'] == 'DISMISSED'
    assert hist['dismissed'] == 1
    assert hist['dismissal_reason'] == 'too hard'

def test_generate_daily_shortlist_and_cooldown():
    shortlist = generate_daily_shortlist(limit=2)
    assert len(shortlist) == 2
    # The top ones should be Issue 3 and Issue 1 based on scores
    urls = [o['url'] for o in shortlist]
    assert 'http://test/3' in urls
    assert 'http://test/1' in urls
    
    # Cooldown should be applied, so a second run should return Issue 2 only
    shortlist2 = generate_daily_shortlist(limit=2)
    assert len(shortlist2) == 1
    assert shortlist2[0]['url'] == 'http://test/2'

def test_score_deltas():
    from src.database import update_issue_opportunity
    
    # We simulate changing the score from 5.0 to 10.0
    update_issue_opportunity('http://test/2', 10.0, 'ACTIVE')
    
    hist = get_history('http://test/2')
    # previous_score should be original (5.0 or None if current_score was null, wait let's check)
    assert hist['current_score'] == 10.0
    
    summary = get_changes_summary()
    assert summary['score_increased'] >= 1

def test_select_top_for_research():
    # Issue 3 is highest score and NEW/WATCHING, hasn't been researched.
    top = select_top_for_research()
    assert top == 3
    
    transition_status('http://test/3', 'RESEARCHED')
    top2 = select_top_for_research()
    assert top2 == 1 # Next best is 1

def test_in_progress_does_not_mark_implemented():
    transition_status("http://test/1", "IN_PROGRESS")

    hist = get_history("http://test/1")

    assert hist["lifecycle_status"] == "IN_PROGRESS"
    assert hist["implemented"] == 0


def test_schedule_and_clear_hermes_retry(monkeypatch):
    from src.opportunity_manager import schedule_hermes_retry, clear_hermes_retry

    class FakeCursor:
        def execute(self, query, params):
            self.query = query
            self.params = params

    class FakeConnection:
        def __init__(self):
            self.cursor_obj = FakeCursor()
            self.executed = []

        def execute(self, query, params=()):
            self.executed.append((query, params))

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    conn = FakeConnection()
    monkeypatch.setattr(
        "src.opportunity_manager.get_connection",
        lambda: conn,
    )

    issue_url = "https://github.com/test/repo/issues/25"

    schedule_hermes_retry(issue_url, delay_minutes=30)

    assert conn.executed[0][1] == ("+30 minutes", issue_url)
    assert "WHERE url = ?" in conn.executed[0][0]

    clear_hermes_retry(issue_url)

    assert conn.executed[1][1] == (issue_url,)
    assert "WHERE url = ?" in conn.executed[1][0]


def test_get_due_hermes_retries_filters_and_orders(monkeypatch):
    from src.opportunity_manager import get_due_hermes_retries

    class FakeCursor:
        description = [
            ("issue_number",),
            ("url",),
            ("repo_name",),
            ("org_slug",),
            ("lifecycle_status",),
            ("hermes_retry_at",),
        ]

        def fetchall(self):
            return [
                (2, "https://github.com/b/issues/2", "b", "org-b", "NEW", "2026-09-10 20:00:00"),
                (1, "https://github.com/a/issues/1", "a", "org-a", "WATCHING", "2026-09-10 19:00:00"),
            ]

    class FakeConnection:
        def execute(self, query, params=()):
            assert "hermes_retry_at <= CURRENT_TIMESTAMP" in query
            assert "ORDER BY hermes_retry_at ASC" in query
            assert params == (10,)
            return FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        "src.opportunity_manager.get_connection",
        lambda: FakeConnection(),
    )

    rows = get_due_hermes_retries()

    assert len(rows) == 2
    assert rows[0]["url"] == "https://github.com/b/issues/2"
    assert rows[1]["url"] == "https://github.com/a/issues/1"
