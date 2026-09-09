import pytest
from unittest.mock import patch, mock_open, MagicMock
import subprocess

from src.hermes_agent import (
    verify_local_provider,
    run_hermes_oneshot,
    research,
    plan
)

def test_verify_local_provider_success():
    valid_yaml = """
model:
  default: qwen3.5:9b
  provider: custom
"""
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=valid_yaml)):
            verify_local_provider()

def test_verify_local_provider_wrong_model():
    invalid_yaml = """
model:
  default: gpt-4
  provider: custom
"""
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=invalid_yaml)):
            with pytest.raises(RuntimeError, match="not qwen3.5:9b"):
                verify_local_provider()

def test_verify_local_provider_wrong_provider():
    invalid_yaml = """
model:
  default: qwen3.5:9b
  provider: openrouter
"""
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=invalid_yaml)):
            with pytest.raises(RuntimeError, match="not local/custom"):
                verify_local_provider()

def test_run_hermes_oneshot_success():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Expected Output"
    
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        result = run_hermes_oneshot("prompt text")
        assert result == "Expected Output"
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "hermes" in args
        assert "-z" in args

def test_run_hermes_oneshot_timeout():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="hermes", timeout=300)):
        with pytest.raises(RuntimeError, match="timed out"):
            run_hermes_oneshot("prompt text")

@patch("src.hermes_agent.verify_local_provider")
@patch("src.hermes_agent.get_issue_context")
@patch("src.hermes_agent.get_repo_analysis")
@patch("src.hermes_agent.run_hermes_oneshot")
def test_research_command(mock_run, mock_analysis, mock_context, mock_verify, tmp_path):
    mock_context.return_value = {
        'repo_name': 'test/repo',
        'org_slug': 'test',
        'issue_number': 123,
        'title': 'Test Issue',
        'body_preview': 'Body',
        'labels': 'bug',
        'activity_status': 'ACTIVE',
        'contribution_value_score': 10,
        'gsoc_preparation_score': 50,
        'opportunity_score': 80
    }
    mock_analysis.return_value = None
    mock_run.return_value = "[FACT] The issue is simple."
    
    with patch("src.hermes_agent.get_reports_dir", return_value=tmp_path):
        research(123)
        assert mock_run.called
        assert (tmp_path / "research.md").exists()
        assert (tmp_path / "research.md").read_text() == "[FACT] The issue is simple."
