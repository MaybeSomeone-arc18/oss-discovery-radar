import pytest
import os
from unittest.mock import patch, MagicMock
from src.scheduler import install_schedule, remove_schedule, schedule_status

@patch('src.scheduler.get_plist_path')
@patch('subprocess.run')
@patch('builtins.open')
def test_install_schedule_success(mock_open, mock_run, mock_get_plist):
    mock_path = MagicMock()
    mock_get_plist.return_value = mock_path
    
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_run.return_value = mock_result
    
    ok, msg = install_schedule(2, 30)
    assert ok is True
    assert "installed at 02:30" in msg
    mock_open.assert_called_once_with(mock_path, 'w')
    
    # Should call launchctl unload then load
    assert mock_run.call_count == 2
    assert "load" in mock_run.call_args_list[1][0][0]

@patch('src.scheduler.get_plist_path')
@patch('subprocess.run')
@patch('os.remove')
def test_remove_schedule_success(mock_remove, mock_run, mock_get_plist):
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_get_plist.return_value = mock_path
    
    ok, msg = remove_schedule()
    assert ok is True
    assert "removed" in msg
    mock_remove.assert_called_once_with(mock_path)

@patch('src.scheduler.get_plist_path')
def test_remove_schedule_not_installed(mock_get_plist):
    mock_path = MagicMock()
    mock_path.exists.return_value = False
    mock_get_plist.return_value = mock_path
    
    ok, msg = remove_schedule()
    assert ok is False
    assert "not installed" in msg

@patch('src.scheduler.get_plist_path')
@patch('subprocess.run')
def test_schedule_status_loaded(mock_run, mock_get_plist):
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_get_plist.return_value = mock_path
    
    mock_result = MagicMock()
    mock_result.stdout = "123 0 com.oss.discovery.radar\n"
    mock_run.return_value = mock_result
    
    status = schedule_status()
    assert "Installed and loaded" in status
