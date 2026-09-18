import os
import pytest
from src import database

import tempfile

# Fixture to override DB_PATH to a temporary file for testing

def test_database_initialization():
    stats = database.get_stats()
    assert stats['organizations'] == 0
    assert stats['years'] == 0
    assert stats['repositories'] == 0
    assert stats['issues'] == 0

def test_save_organization_idempotent():
    # Insert once
    database.save_organization("test-org", "Test Organization", "https://test.org", 2023)
    stats = database.get_stats()
    assert stats['organizations'] == 1
    assert stats['years'] == 1

    # Insert again (idempotent)
    database.save_organization("test-org", "Test Organization Updated", "https://test.org", 2024)
    stats = database.get_stats()
    assert stats['organizations'] == 1  # Should still be 1
    assert stats['years'] == 2          # New year added

def test_save_issue():
    database.save_repository("test-repo", "https://github.com/test/repo", "test-org")
    database.save_issue(
        url="https://github.com/test/repo/issues/1",
        repo_name="test-repo",
        org_slug="test-org",
        issue_number=1,
        title="Test Issue",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        state="OPEN",
        labels="[]",
        body_preview="This is a test issue.",
        comments_count=0,
        author="test",
        assignee_status="UNASSIGNED",
        milestone=None
    )

    stats = database.get_stats()
    assert stats['repositories'] == 1
    assert stats['issues'] == 1

    # Duplicate insert should not increase count
    database.save_issue(
        url="https://github.com/test/repo/issues/1",
        repo_name="test-repo",
        org_slug="test-org",
        issue_number=1,
        title="Test Issue Updated",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        state="OPEN",
        labels="[]",
        body_preview="This is a test issue updated.",
        comments_count=0,
        author="test",
        assignee_status="UNASSIGNED",
        milestone=None
    )

    stats = database.get_stats()
    assert stats['issues'] == 1


def test_save_issue_with_discussion_context():
    disc_text = "=== ISSUE BODY ===\nFull issue text\n=== DISCUSSION HISTORY ===\n[Comment #1 by Maintainer]: Use Option A"
    database.save_issue(
        url="https://github.com/test/repo/issues/2",
        repo_name="test-repo",
        org_slug="test-org",
        issue_number=2,
        title="Test Issue 2",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        state="OPEN",
        labels="[]",
        body_preview="Full issue text",
        comments_count=1,
        author="testauthor",
        assignee_status="UNASSIGNED",
        milestone=None,
        discussion_context=disc_text
    )
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT discussion_context FROM issues WHERE url = 'https://github.com/test/repo/issues/2'")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == disc_text

