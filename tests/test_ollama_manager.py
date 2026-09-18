import pytest
from unittest.mock import patch, MagicMock
from src.ollama_manager import install_ollama, remove_ollama, ollama_status, get_ollama_plist_path

@patch('shutil.which')
@patch('pathlib.Path.mkdir')
@patch('builtins.open', new_callable=MagicMock)
@patch('subprocess.run')
def test_install_ollama_success(mock_run, mock_open, mock_mkdir, mock_which):
    mock_which.return_value = '/usr/local/bin/ollama'

    mock_run_result = MagicMock()
    mock_run_result.returncode = 0
    mock_run.return_value = mock_run_result

    success, msg = install_ollama()
    assert success is True
    assert "installed and started" in msg
    mock_open.assert_called_once()
    assert mock_run.call_count == 2

@patch('shutil.which')
def test_install_ollama_not_found(mock_which):
    mock_which.return_value = None
    success, msg = install_ollama()
    assert success is False
    assert "not found" in msg

@patch('pathlib.Path.exists')
@patch('subprocess.run')
@patch('os.remove')
def test_remove_ollama_success(mock_remove, mock_run, mock_exists):
    mock_exists.return_value = True
    success, msg = remove_ollama()
    assert success is True
    assert "removed" in msg
    mock_run.assert_called_once()
    mock_remove.assert_called_once()

@patch('pathlib.Path.exists')
def test_remove_ollama_not_installed(mock_exists):
    mock_exists.return_value = False
    success, msg = remove_ollama()
    assert success is False
    assert "not installed" in msg

@patch('pathlib.Path.exists')
@patch('subprocess.run')
def test_ollama_status_running(mock_run, mock_exists):
    mock_exists.return_value = True
    mock_result = MagicMock()
    mock_result.stdout = "12345 0 com.oss.discovery.ollama\n"
    mock_run.return_value = mock_result

    status = ollama_status()
    assert status == "Installed and running in launchd."

@patch('pathlib.Path.exists')
@patch('subprocess.run')
def test_ollama_status_not_running(mock_run, mock_exists):
    mock_exists.return_value = True
    mock_result = MagicMock()
    mock_result.stdout = ""
    mock_run.return_value = mock_result

    status = ollama_status()
    assert status == "Installed (plist exists) but not running in launchd."
