import pytest
from unittest.mock import patch, MagicMock
from src.resource_manager import get_available_memory_mb, check_resources_for_hermes

@patch('sys.platform', 'darwin')
@patch('subprocess.check_output')
def test_get_available_memory_mb_mac(mock_check_output):
    # Mock vm_stat output
    mock_check_output.return_value = '''Mach Virtual Memory Statistics: (page size of 4096 bytes)
Pages free:                              100000.
Pages active:                            200000.
Pages inactive:                           50000.
Pages speculative:                        10000.
Pages throttled:                              0.
Pages wired down:                         80000.
'''
    # (100000 + 50000) * 4096 / (1024 * 1024) = 150000 * 4096 / 1048576 = 585.9375 MB
    mem = get_available_memory_mb()
    assert 585 < mem < 586

@patch('sys.platform', 'linux')
def test_get_available_memory_mb_non_mac():
    mem = get_available_memory_mb()
    assert mem == 8192

@patch('src.resource_manager.get_available_memory_mb')
@patch('shutil.disk_usage')
def test_check_resources_for_hermes_success(mock_disk, mock_mem):
    mock_mem.return_value = 8000
    mock_disk.return_value = (100000000000, 50000000000, 50000000000) # ~47GB free
    
    ok, msg = check_resources_for_hermes(min_memory_mb=4096, min_disk_mb=2048)
    assert ok is True
    assert "Resources sufficient" in msg

@patch('src.resource_manager.get_available_memory_mb')
@patch('shutil.disk_usage')
def test_check_resources_for_hermes_low_mem(mock_disk, mock_mem):
    mock_mem.return_value = 2000
    mock_disk.return_value = (100000000000, 50000000000, 50000000000)
    
    ok, msg = check_resources_for_hermes(min_memory_mb=4096, min_disk_mb=2048)
    assert ok is False
    assert "Insufficient memory" in msg

@patch('src.resource_manager.get_available_memory_mb')
@patch('shutil.disk_usage')
def test_check_resources_for_hermes_low_disk(mock_disk, mock_mem):
    mock_mem.return_value = 8000
    mock_disk.return_value = (100000000000, 99000000000, 1000000000) # ~950MB free
    
    ok, msg = check_resources_for_hermes(min_memory_mb=4096, min_disk_mb=2048)
    assert ok is False
    assert "Insufficient disk" in msg
