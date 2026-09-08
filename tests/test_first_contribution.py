import pytest
from src.contribution_engine import calculate_first_contribution_score
from src.database import init_db, get_connection, save_issue, save_repository_metrics, save_repository, save_organization, update_organization_score

def setup_test_data():
    init_db()
    save_organization("test-org", "Test Org")
    update_organization_score("test-org", 80.0, {})
    save_repository("test-org/repo", "http://github.com", "test-org")
    save_repository_metrics("test-org/repo", 10, 10, 5, 5, 5, 20, 24.0, 75.0)
    
    # Issue 1: Good candidate
    save_issue(
        "http://issue1", "test-org/repo", "test-org", 1, "Good Issue python backend", 
        "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", "OPEN", '["good first issue"]', 
        "Great bug to fix", 2, "author", "UNASSIGNED", "", classified_tags=["python"]
    )
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE issues SET contribution_value_score=80.0, gsoc_preparation_score=80.0, opportunity_score=80.0, eligibility_status='ACTIVE_UNADDRESSED' WHERE url='http://issue1'")
        conn.commit()
        
    # Issue 2: Assigned
    save_issue(
        "http://issue2", "test-org/repo", "test-org", 2, "Assigned Issue", 
        "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", "OPEN", '["bug"]', 
        "Already assigned", 2, "author", "ASSIGNED", ""
    )
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE issues SET contribution_value_score=80.0, gsoc_preparation_score=80.0, eligibility_status='ACTIVE_UNADDRESSED' WHERE url='http://issue2'")
        conn.commit()

def test_calculate_first_contribution_score(monkeypatch):
    setup_test_data()
    
    # Mock profile
    monkeypatch.setattr('src.contribution_engine.load_profile', lambda: {'skills': ['python'], 'interests': ['backend']})
    
    # Test Issue 1
    score, notes = calculate_first_contribution_score("http://issue1")
    assert score > 0
    assert "Engineering Value" in notes
    assert "GSoC Prep" in notes
    
    # Test Issue 2
    score2, notes2 = calculate_first_contribution_score("http://issue2")
    assert score2 == 0.0
    assert "Already assigned" in notes2
