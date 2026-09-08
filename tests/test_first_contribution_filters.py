import pytest
from unittest.mock import patch, MagicMock
from src.deep_analysis import check_release_prerequisites
import main

@patch('src.deep_analysis.requests.get')
def test_check_release_prerequisites_unreleased(mock_get):
    # Mock tags response missing the target tag
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"name": "2.24.0"}]
    mock_get.return_value = mock_resp
    
    title = "Cleanup"
    body = "Only work on this after 2.25.0 is released"
    
    status, evidence = check_release_prerequisites("ankidroid/Anki-Android", title, body)
    
    assert status == "WAITING_ON_RELEASE"
    assert "2.25.0" in evidence

@patch('src.deep_analysis.requests.get')
def test_check_release_prerequisites_released(mock_get):
    # Mock tags response with the target tag
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"name": "v2.25.0"}, {"name": "2.24.0"}]
    mock_get.return_value = mock_resp
    
    title = "Cleanup"
    body = "Only work on this after 2.25.0 is released"
    
    status, evidence = check_release_prerequisites("ankidroid/Anki-Android", title, body)
    
    assert status == "READY_NOW"

def test_check_release_prerequisites_no_prereq():
    title = "Fix typo"
    body = "Simple fix"
    status, evidence = check_release_prerequisites("repo/name", title, body)
    assert status == "READY_NOW"

@patch('src.database.get_connection')
@patch('src.contribution_engine.calculate_first_contribution_score')
@patch('src.github_client.check_related_prs')
@patch('src.github_client.fetch_contribution_model')
@patch('src.database.update_readiness_status')
@patch('src.deep_analysis.check_release_prerequisites')
def test_first_contribution_filtering_and_diversity(mock_prereq, mock_update, mock_model, mock_prs, mock_score, mock_conn, capsys):
    # Setup mock db
    mock_cursor = MagicMock()
    
    # Return 5 candidates from the same repo and 1 from another
    mock_cursor.fetchall.return_value = [
        ("url1", "repoA", 1, "t1", "b1", "orgA", 10.0, 10.0, "MEDIUM"),
        ("url2", "repoA", 2, "t2", "b2", "orgA", 10.0, 10.0, "MEDIUM"),
        ("url3", "repoA", 3, "t3", "b3", "orgA", 10.0, 10.0, "MEDIUM"),
        ("url4", "repoA", 4, "t4", "b4", "orgA", 10.0, 10.0, "MEDIUM"),
        ("url5", "repoA", 5, "t5", "b5", "orgA", 10.0, 10.0, "MEDIUM"),
        ("url6", "repoB", 6, "t6", "b6", "orgB", 10.0, 10.0, "MEDIUM")
    ]
    mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor
    
    # All get high score
    mock_score.return_value = (50.0, "good")
    mock_prs.return_value = []
    mock_model.return_value = {"has_contributing": True}
    mock_prereq.return_value = ("READY_NOW", "good")
    
    main.cmd_first_contribution()
    
    captured = capsys.readouterr()
    output = captured.out
    
    # Max 3 from repoA should be in output
    assert output.count("repoA") >= 3
    # Wait, the output lines will contain the name.
    # The printed line looks like: 1 | orgA | repoA ...
    repo_a_lines = [line for line in output.split('\n') if 'repoA' in line and '|' in line]
    # Remove the RECOMMENDED CANDIDATE block which also prints repoA
    table_lines = [l for l in repo_a_lines if "1 " in l or "2 " in l or "3 " in l or "4 " in l]
    
    assert len(table_lines) == 3
    assert "repoB" in output
