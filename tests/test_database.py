import os
import pytest
from src import database

import tempfile

# Fixture to override DB_PATH to a temporary file for testing
@pytest.fixture(autouse=True)
def override_db_path(monkeypatch):
    fd, path = tempfile.mkstemp()
    os.close(fd)
    monkeypatch.setattr(database, "DB_PATH", path)
    database.init_db()
    yield
    os.remove(path)

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
        title="Test Issue",
        created_at="2026-01-01T00:00:00Z",
        labels=["bug", "good first issue"],
        body_preview="This is a test issue."
    )
    
    stats = database.get_stats()
    assert stats['repositories'] == 1
    assert stats['issues'] == 1
    
    # Duplicate insert should not increase count
    database.save_issue(
        url="https://github.com/test/repo/issues/1",
        repo_name="test-repo",
        title="Test Issue Updated",
        created_at="2026-01-01T00:00:00Z",
        labels=["bug"],
        body_preview="Updated preview"
    )
    
    stats = database.get_stats()
    assert stats['issues'] == 1
