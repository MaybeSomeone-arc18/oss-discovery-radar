import pytest
import tempfile
import os
import json
from src import database, scoring_engine

@pytest.fixture(autouse=True)
def override_db_path(monkeypatch):
    fd, path = tempfile.mkstemp()
    os.close(fd)
    monkeypatch.setattr(database, "DB_PATH", path)
    database.init_db()
    yield
    os.remove(path)

def test_database_migrations_and_new_tables():
    stats = database.get_stats()
    assert stats['organizations'] == 0
    # Schema should have been created without errors

def test_organization_scoring_no_activity():
    # Insert org with zero history
    database.save_organization("ghost-org", "Ghost Org", "http://ghost.org")
    
    # Needs to be in repositories table to be scored
    database.save_repository("ghost-org/repo", "http://github.com/ghost", "ghost-org", 0, 0, 0, 0, None, None, False, "main")
    database.save_repository_metrics("ghost-org/repo", 0, 0, 0, 0, 0, 0, 24.0, 0.0)
    
    scoring_engine.calculate_organization_scores()
    
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT opportunity_score, score_breakdown FROM organizations WHERE slug = 'ghost-org'")
        score, breakdown_str = cursor.fetchone()
        
        assert score == 0.4
        breakdown = json.loads(breakdown_str)
        assert breakdown['gsoc_history_score'] == 0.0
        assert breakdown['activity_score'] == 2.0

def test_organization_scoring_strong_activity():
    # Insert org with strong history
    database.save_organization("strong-org", "Strong Org", "http://strong.org")
    database.save_organization("strong-org", "Strong Org", "http://strong.org", 2022)
    database.save_organization("strong-org", "Strong Org", "http://strong.org", 2023)
    
    database.save_repository("strong-org/repo1", "http://github.com/strong1", "strong-org", 1000, 500, 50, 10, None, None, False, "main")
    database.save_repository_metrics("strong-org/repo1", 20, 15, 10, 8, 5, 100, 1.0, 80.0)
    
    scoring_engine.calculate_organization_scores()
    
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT opportunity_score, score_breakdown FROM organizations WHERE slug = 'strong-org'")
        score, breakdown_str = cursor.fetchone()
        
        assert score > 50.0  # Should be highly rated
        breakdown = json.loads(breakdown_str)
        assert breakdown['gsoc_history_score'] == 40.0 # 2 years * 20
        assert breakdown['activity_score'] == 100.0 # Capped at 100

def test_idempotent_metric_storage():
    database.save_repository("idemp-org/repo", "http://github.com/idemp", "idemp-org", 10, 5)
    database.save_repository_metrics("idemp-org/repo", 1, 1, 1, 1, 1, 1, 1.0, 1.0)
    
    # Update metrics
    database.save_repository_metrics("idemp-org/repo", 2, 2, 2, 2, 2, 2, 2.0, 2.0)
    
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT issues_created_recently FROM repository_metrics WHERE repo_name = 'idemp-org/repo'")
        val = cursor.fetchone()[0]
        assert val == 2
