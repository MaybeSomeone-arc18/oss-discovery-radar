import pytest
import os
from pathlib import Path
from src.hermes_agent import run_hermes_oneshot

def test_run_hermes_oneshot_cwd_flags(monkeypatch, tmp_path):
    captured_cmd = []
    def mock_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        class MockResult:
            returncode = 0
            stdout = "mocked"
        return MockResult()
        
    import src.hermes_agent
    monkeypatch.setattr(src.hermes_agent.subprocess, "run", mock_run)
    
    run_hermes_oneshot("test prompt", cwd=str(tmp_path))
    import platform
    if platform.system() == "Darwin":
        assert "sandbox-exec" in captured_cmd
        assert "-p" in captured_cmd
    assert "--in" in captured_cmd
    assert str(tmp_path) in captured_cmd
    assert "--no-restore-cwd" in captured_cmd
