import json
from src import database
from src import contribution_engine

def test_calculate_personal_fit():
    profile = {
        "skills": ["Python", "Rust"],
        "interests": ["networking", "systems"]
    }
    
    tags = ["Rust", "networking"]
    title = "Fix socket bug in rust core"
    body = "The python wrapper is also broken"
    
    score = contribution_engine.calculate_personal_fit(tags, title, body, profile)
    
    # Rust (10) + networking (5) + Python in text (5) + rust in text (5) = 25
    assert score > 0

def test_parse_date():
    dt = contribution_engine.parse_date("2026-09-07T12:00:00Z")
    assert dt.year == 2026
    assert dt.month == 9

def test_save_and_fetch_issue():
    database.init_db()
    database.save_repository("test-org/test-repo", "http://github.com", "test-org", 0, 0, 0, 0, None, None, False, "main")
    
    database.save_issue(
        url="http://github.com/issue/1",
        repo_name="test-org/test-repo",
        org_slug="test-org",
        issue_number=1,
        title="Test Issue",
        created_at="2026-09-07T12:00:00Z",
        updated_at="2026-09-07T12:00:00Z",
        state="OPEN",
        labels=json.dumps(["bug", "good first issue"]),
        body_preview="Body",
        comments_count=2,
        author="testuser",
        assignee_status="UNASSIGNED",
        milestone=None,
        classified_tags=["Rust"]
    )
    
    database.save_pull_request(
        url="http://github.com/pr/1",
        pr_number=1,
        repo_name="test-org/test-repo",
        title="Test PR",
        state="OPEN",
        created_at="2026-09-07T12:00:00Z",
        updated_at="2026-09-07T12:00:00Z",
        merged_at=None,
        author="testuser",
        review_comments_count=1
    )
    
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM issues WHERE issue_number = 1")
        assert cursor.fetchone()[0] == "Test Issue"
        
        cursor.execute("SELECT title FROM pull_requests WHERE pr_number = 1")
        assert cursor.fetchone()[0] == "Test PR"
