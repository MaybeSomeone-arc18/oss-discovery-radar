import pytest
import os
import subprocess
import requests
from unittest.mock import patch, mock_open, MagicMock

from src.hermes_agent import (
    verify_local_provider,
    run_hermes_oneshot,
    research,
    plan
)

def test_verify_local_provider_success():
    valid_yaml = """
model:
  default: llama3.2:3b
  provider: custom
"""
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=valid_yaml)):
            with patch("requests.get") as mock_get:
                mock_get.return_value.status_code = 200
                mock_get.return_value.json.return_value = {"models": [{"name": "llama3.2:3b"}]}
                verify_local_provider()
                mock_get.assert_called_once()

def test_verify_local_provider_wrong_model():
    invalid_yaml = """
model:
  default: gpt-4
  provider: custom
"""
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=invalid_yaml)):
            with pytest.raises(RuntimeError, match="not llama3.2:3b"):
                verify_local_provider()

def test_verify_local_provider_wrong_provider():
    invalid_yaml = """
model:
  default: llama3.2:3b
  provider: openrouter
"""
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=invalid_yaml)):
            with pytest.raises(RuntimeError, match="not local/custom"):
                verify_local_provider()

def test_verify_local_provider_unreachable():
    valid_yaml = """
model:
  default: llama3.2:3b
  provider: custom
"""
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=valid_yaml)):
            with patch("requests.get", side_effect=requests.exceptions.ConnectionError("Connection refused")):
                with pytest.raises(RuntimeError, match="unreachable"):
                    verify_local_provider()

def test_verify_local_provider_bad_status():
    valid_yaml = """
model:
  default: llama3.2:3b
  provider: custom
"""
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=valid_yaml)):
            with patch("requests.get") as mock_post:
                mock_post.return_value.status_code = 500
                mock_post.return_value.text = "Internal Server Error"
                with pytest.raises(RuntimeError, match="failed with 500"):
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

def test_run_hermes_oneshot_passes_model_override(monkeypatch):
    captured = {}

    class Result:
        returncode = 0
        stdout = "OK"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return Result()

    monkeypatch.setattr("src.hermes_agent.subprocess.run", fake_run)

    assert run_hermes_oneshot("prompt text", model="llama3.2:3b") == "OK"
    assert captured["cmd"] == [
        "hermes",
        "-z",
        "prompt text",
        "--model",
        "llama3.2:3b",
    ]


def test_run_hermes_oneshot_timeout():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="hermes", timeout=300)):
        with pytest.raises(RuntimeError, match="timed out"):
            run_hermes_oneshot("prompt text")

@patch("src.hermes_agent.get_issue_context")
@patch("src.hermes_agent.get_repo_analysis")
@patch("src.hermes_agent.run_hermes_oneshot")
def test_research_command(mock_run, mock_analysis, mock_context, tmp_path):
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

    with patch(
        "src.autonomous_guard.get_hermes_execution_plan",
        return_value=(True, "llama3.2:3b", "validated"),
    ):
        with patch("src.hermes_agent.get_reports_dir", return_value=tmp_path):
            result = research(123)
            assert result is True
            mock_run.assert_called_once()
            assert mock_run.call_args.kwargs["model"] == "llama3.2:3b"
            assert (tmp_path / "research.md").exists()
            assert (tmp_path / "research.md").read_text() == "[FACT] The issue is simple."


@patch("src.hermes_agent.verify_local_provider")
@patch("src.hermes_agent.get_issue_context", return_value=None)
def test_research_returns_false_when_issue_missing(mock_context, mock_verify):
    assert research(123) is False


def test_plan_passes_selected_model_to_hermes(monkeypatch, tmp_path):
    from src.hermes_agent import plan

    plan_calls = []

    def fake_execution_plan(task_type="lightweight"):
        plan_calls.append(task_type)
        return (True, "llama3.2:3b", "validated")

    monkeypatch.setattr(
        "src.autonomous_guard.get_hermes_execution_plan",
        fake_execution_plan,
    )
    monkeypatch.setattr(
        "src.hermes_agent.get_issue_context",
        lambda issue_id: {
            "org_slug": "test",
            "repo_name": "test/repo",
            "issue_number": 123,
        },
    )
    monkeypatch.setattr(
        "src.hermes_agent.get_reports_dir",
        lambda org, repo, issue: tmp_path,
    )

    (tmp_path / "research.md").write_text("[FACT] Research")

    captured = {}

    def fake_run(prompt, **kwargs):
        captured.update(kwargs)
        return "[FACT] Plan"

    monkeypatch.setattr("src.hermes_agent.run_hermes_oneshot", fake_run)

    assert plan(123) is True
    assert captured["model"] == "llama3.2:3b"
    assert (tmp_path / "plan.md").read_text() == "[FACT] Plan"
    # Issue has no engineering_depth -> ordinary planning stays lightweight.
    assert plan_calls == ["lightweight"]


@patch("src.hermes_agent.verify_local_provider")
@patch("src.hermes_agent.get_issue_context")
def test_plan_returns_false_when_research_missing(mock_context, mock_verify, tmp_path):
    mock_context.return_value = {
        "repo_name": "test/repo",
        "org_slug": "test",
        "issue_number": 123,
    }
    with patch("src.hermes_agent.get_reports_dir", return_value=tmp_path):
        assert plan(123) is False


@patch("requests.get")
def test_list_local_models(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "models": [
            {"name": "qwen3.5:9b", "size": 6594474711},
            {"name": "llama3.2:3b", "size": 2019393189},
        ]
    }
    mock_get.return_value = mock_response

    from src.hermes_agent import list_local_models

    models = list_local_models()

    assert models == [
        {"name": "qwen3.5:9b", "size": 6594474711},
        {"name": "llama3.2:3b", "size": 2019393189},
    ]


@patch("requests.get", side_effect=requests.exceptions.ConnectionError("Connection refused"))
def test_list_local_models_unreachable(mock_get):
    from src.hermes_agent import OllamaUnavailableError, list_local_models

    with pytest.raises(OllamaUnavailableError, match="unreachable"):
        list_local_models()


def test_select_local_model_never_selects_qwen_even_with_plenty_of_memory():
    """qwen3.5:9b must never be auto-selected, even with plenty of memory."""
    from src.hermes_agent import select_local_model

    models = [
        {"name": "qwen3.5:9b", "size": 6594474711},
        {"name": "llama3.2:3b", "size": 2019393189},
    ]

    result = select_local_model(16384, models)

    assert result == "llama3.2:3b"
    assert result != "qwen3.5:9b"


def test_select_local_model_selects_3b_when_memory_threshold_met():
    """llama3.2:3b is selected whenever the configured memory threshold is met."""
    from src.hermes_agent import select_local_model

    models = [
        {"name": "qwen3.5:9b", "size": 6594474711},
        {"name": "llama3.2:3b", "size": 2019393189},
    ]

    assert select_local_model(6000, models) == "llama3.2:3b"
    assert select_local_model(3072, models) == "llama3.2:3b"


def test_select_local_model_defers_when_neither_fits():
    from src.hermes_agent import select_local_model

    models = [
        {"name": "qwen3.5:9b", "size": 6594474711},
        {"name": "llama3.2:3b", "size": 2019393189},
    ]

    assert select_local_model(2000, models) is None


def test_select_local_model_uses_3b_when_qwen_is_not_installed():
    from src.hermes_agent import select_local_model

    models = [
        {"name": "llama3.2:3b", "size": 2019393189},
    ]

    assert select_local_model(9000, models) == "llama3.2:3b"


def test_select_local_model_defers_when_no_supported_model_is_installed():
    from src.hermes_agent import select_local_model

    models = [
        {"name": "some-other-model", "size": 1000000000},
    ]

    assert select_local_model(9000, models) is None


def test_implement_issue_with_hermes_passes_selected_model(monkeypatch, tmp_path):
    from src.hermes_agent import implement_issue_with_hermes

    captured = {}

    def fake_run(prompt, **kwargs):
        captured.update(kwargs)
        return "implemented"

    monkeypatch.setattr("src.hermes_agent.run_hermes_oneshot", fake_run)
    monkeypatch.setattr("src.hermes_agent.verify_local_provider", lambda: None)

    result = implement_issue_with_hermes(
        tmp_path,
        "Issue Title: Test\nPLAN:\nDo the thing",
        model="llama3.2:3b",
    )

    assert result == "implemented"
    assert captured["model"] == "llama3.2:3b"


