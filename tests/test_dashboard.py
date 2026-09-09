import pytest
from unittest.mock import patch, MagicMock
from src.dashboard import DashboardHandler

@patch('src.dashboard.get_connection')
@patch('src.dashboard.verify_local_provider')
@patch('src.dashboard.schedule_status')
@patch('src.dashboard.get_recent_logs')
@patch('glob.glob')
@patch('os.path.getmtime')
@patch('builtins.open')
@patch('src.dashboard.calculate_first_contribution_score')
@patch('src.dashboard.check_release_prerequisites')
def test_dashboard_data(mock_check_prereq, mock_calc_score, mock_open, mock_mtime, mock_glob, mock_logs, mock_sched, mock_verify, mock_get_conn):
    mock_verify.return_value = None # success
    mock_sched.return_value = "Installed and loaded"
    mock_logs.return_value = [
        (1, "2023-10-10", "sync", None, "success", "msg")
    ]
    mock_glob.return_value = ["digests/daily_2023-10-10.md"]
    mock_mtime.return_value = 1000
    
    mock_file = MagicMock()
    mock_file.__enter__.return_value.read.return_value = "digest content"
    mock_open.return_value = mock_file
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_get_conn.return_value = mock_conn
    
    # Opportunities fetchall
    mock_cursor.fetchall.return_value = [
        ("url1", "repo1", 123, "title1", "preview", "org1")
    ]
    # gsoc fetchone
    mock_cursor.fetchone.return_value = (5.5,)
    
    mock_calc_score.return_value = (80.0, "notes")
    mock_check_prereq.return_value = ("READY_NOW", "ev")
    
    data = DashboardHandler.get_dashboard_data(None)
    
    assert data['hermes_available'] is True
    assert data['scheduler_status'] == "Installed and loaded"
    assert len(data['events']) == 1
    assert data['digest'] == "digest content"
    assert len(data['opportunities']) == 1
    assert data['opportunities'][0]['repo'] == "repo1"
    assert data['opportunities'][0]['score'] == 80.0
    assert data['opportunities'][0]['gsoc'] == 5.5

@patch('src.dashboard.verify_local_provider')
@patch('glob.glob')
def test_dashboard_hermes_fail(mock_glob, mock_verify):
    mock_verify.side_effect = RuntimeError("Hermes failed")
    mock_glob.return_value = []
    
    with patch('src.dashboard.get_connection'), patch('src.dashboard.schedule_status'), patch('src.dashboard.get_recent_logs'):
        data = DashboardHandler.get_dashboard_data(None)
        
    assert data['hermes_available'] is False
    assert data['hermes_error'] == "Hermes failed"
