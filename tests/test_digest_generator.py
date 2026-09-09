import pytest
from unittest.mock import patch, MagicMock
from src.digest_generator import generate_daily_digest

@patch('src.digest_generator.get_connection')
@patch('src.contribution_engine.calculate_first_contribution_score')
@patch('src.deep_analysis.check_release_prerequisites')
@patch('src.implementer.get_agent_config')
@patch('src.resource_manager.check_resources_for_hermes')
@patch('src.hermes_agent.research')
@patch('src.hermes_agent.plan')
@patch('builtins.open')
def test_generate_daily_digest_hermes_trigger(mock_open, mock_plan, mock_research, mock_res, mock_config, mock_prereq, mock_score, mock_conn):
    # Setup mock db
    mock_cursor = MagicMock()
    # Mock for first fetchall (issues)
    mock_cursor.fetchall.side_effect = [
        [
            ("url1", "repoA", 123, "Issue 1", "body", "orgA")
        ],
        [], # New opps count
        [], # Score inc count
        [], # Projects to watch
        [], # Active contributions
        []  # GSoC signals
    ]
    # Mock for score delta, new opps
    mock_cursor.fetchone.side_effect = [
        (10,), # gsoc fetch
        (5,), # new opps
        (2,)  # score inc
    ]
    mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor
    
    # Mock score high enough to trigger
    mock_score.return_value = (85.0, "notes")
    mock_prereq.return_value = ("READY_NOW", "ev")
    
    mock_config.return_value = {'hermes_auto_trigger_threshold': 80.0}
    mock_res.return_value = (True, "OK")
    
    generate_daily_digest()
    
    # Check that Hermes was triggered
    mock_research.assert_called_once_with('url1')
    mock_plan.assert_called_once_with('url1')
    
    # Check that it opened the file to write
    mock_open.assert_called_once()

@patch('src.digest_generator.get_connection')
@patch('src.contribution_engine.calculate_first_contribution_score')
@patch('src.deep_analysis.check_release_prerequisites')
@patch('src.implementer.get_agent_config')
@patch('src.hermes_agent.research')
@patch('builtins.open')
def test_generate_daily_digest_no_trigger_low_score(mock_open, mock_research, mock_config, mock_prereq, mock_score, mock_conn):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.side_effect = [
        [
            ("url1", "repoA", 124, "Issue 2", "body", "orgA")
        ],
        [], [], [], [], []
    ]
    mock_cursor.fetchone.side_effect = [(10,), (0,), (0,)]
    mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor
    
    # Mock score lower than threshold
    mock_score.return_value = (75.0, "notes")
    mock_prereq.return_value = ("READY_NOW", "ev")
    
    mock_config.return_value = {'hermes_auto_trigger_threshold': 80.0}
    
    generate_daily_digest()
    
    # Hermes should NOT be triggered
    mock_research.assert_not_called()
