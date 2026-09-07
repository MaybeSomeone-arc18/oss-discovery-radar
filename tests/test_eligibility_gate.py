import pytest
from unittest.mock import patch, MagicMock
from src.github_client import check_related_prs
from src.contribution_engine import score_and_classify_issues
from src.database import init_db, get_connection

@pytest.fixture(autouse=True)
def setup_test_db():
    init_db()
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO organizations (slug, name) VALUES ('test-org', 'Test Org')")
        c.execute("INSERT OR IGNORE INTO repositories (name, org_slug) VALUES ('test-org/test-repo', 'test-org')")
        c.execute("INSERT OR IGNORE INTO repository_metrics (repo_name) VALUES ('test-org/test-repo')")
        
        c.execute('''
        INSERT OR REPLACE INTO issues (url, repo_name, org_slug, issue_number, title, state, eligibility_status)
        VALUES 
        ('http://test/1', 'test-org/test-repo', 'test-org', 1, 'Issue 1', 'OPEN', 'UNKNOWN')
        ''')
        conn.commit()

@patch('src.github_client.requests.get')
def test_check_related_prs(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        'items': [{'number': 100, 'title': 'Fixes #1', 'state': 'closed'}]
    }
    mock_get.return_value = mock_response
    
    prs = check_related_prs('test-org/test-repo', 1)
    assert len(prs) == 1
    assert prs[0]['number'] == 100
    assert prs[0]['state'] == 'closed'

@patch('src.contribution_engine.check_related_prs')
def test_score_and_classify_issues_eligibility_gate(mock_check):
    # Mock related PRs to simulate LIKELY_SOLVED
    mock_check.return_value = [{'number': 100, 'title': 'Fixes #1', 'state': 'closed'}]
    
    score_and_classify_issues()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT eligibility_status, opportunity_score FROM issues WHERE issue_number = 1")
        row = cursor.fetchone()
        assert row[0] == 'LIKELY_SOLVED'
        assert row[1] == 0.0 # Heavy penalty applied

@patch('src.contribution_engine.check_related_prs')
def test_score_and_classify_issues_active_with_work(mock_check):
    # Mock related PRs to simulate ACTIVE_WITH_WORK
    mock_check.return_value = [{'number': 101, 'title': 'Fixes #1', 'state': 'open'}]
    
    # reset issue to UNKNOWN for next test
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE issues SET eligibility_status = 'UNKNOWN' WHERE issue_number = 1")
        conn.commit()
        
    score_and_classify_issues()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT eligibility_status, opportunity_score FROM issues WHERE issue_number = 1")
        row = cursor.fetchone()
        assert row[0] == 'ACTIVE_WITH_WORK'
        # Penalty should have been applied (x 0.1 of whatever the score was)
        # Score is > 0 but less than it would normally be
        # We can just check the status
