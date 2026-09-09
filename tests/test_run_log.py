import pytest
from unittest.mock import patch, MagicMock
from src.run_log import log_event, get_recent_logs

@patch('src.run_log.get_connection')
def test_log_event(mock_get_conn):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_get_conn.return_value = mock_conn
    
    log_event("test_action", "success", "Test message", 123)
    
    mock_cursor.execute.assert_called_once()
    args = mock_cursor.execute.call_args[0][1]
    assert args == ("test_action", 123, "success", "Test message")
    mock_conn.commit.assert_called_once()

@patch('src.run_log.get_connection')
def test_get_recent_logs(mock_get_conn):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_get_conn.return_value = mock_conn
    
    mock_cursor.fetchall.return_value = [
        (1, '2023-10-10', 'sync', None, 'success', 'done')
    ]
    
    logs = get_recent_logs(10)
    
    assert len(logs) == 1
    mock_cursor.execute.assert_called_once()
    assert "LIMIT ?" in mock_cursor.execute.call_args[0][0]
    assert mock_cursor.execute.call_args[0][1] == (10,)
