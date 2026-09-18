valid_plan = 'TARGET FILES:\nsrc/main.py\nTARGET SYMBOL:\nn/a\nACCEPTANCE CRITERIA:\nworks well\nTARGETED TEST:\npytest test.py'
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

def test_verify_local_provider_rejects_drifted_glm_default():
    """E2E regression: the drifted config default (glm-5.3:cloud) is rejected."""
    drifted_yaml = """
model:
  default: glm-5.3:cloud
  provider: custom
"""
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=drifted_yaml)):
            with pytest.raises(RuntimeError, match="not llama3.2:3b"):
                verify_local_provider()

def test_verify_local_provider_rejects_drifted_ollama_launch_provider():
    """E2E regression: provider 'ollama-launch' is not a local/custom provider."""
    drifted_yaml = """
model:
  default: llama3.2:3b
  provider: ollama-launch
"""
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=drifted_yaml)):
            with pytest.raises(RuntimeError, match="not local/custom"):
                verify_local_provider()

def test_verify_local_provider_accepts_fixed_3b_custom_config():
    """Corrected config (llama3.2:3b + custom) passes and proves the local Ollama path."""
    fixed_yaml = """
model:
  default: llama3.2:3b
  provider: custom
  base_url: http://127.0.0.1:11434/v1
"""
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=fixed_yaml)):
            with patch("requests.get") as mock_get:
                mock_get.return_value.status_code = 200
                mock_get.return_value.json.return_value = {"models": [{"name": "llama3.2:3b"}]}
                verify_local_provider()
                # Ollama API base is the base_url with /v1 stripped.
                assert mock_get.call_args[0][0] == "http://127.0.0.1:11434/api/tags"

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


def test_run_hermes_oneshot_lightweight_has_no_provider_flag(monkeypatch, tmp_path):
    """Lightweight/local runs stay backward-compatible: no --provider flag and
    no provider entry injected into the mirrored runtime config."""
    from src.hermes_agent import run_hermes_oneshot

    runtime = tmp_path / ".hermes-runtime"
    fake_home = tmp_path / "fake-home"
    (fake_home / ".hermes").mkdir(parents=True)
    (fake_home / ".hermes" / "config.yaml").write_text(
        "model:\n  default: llama3.2:3b\n  provider: custom\n"
        "  base_url: http://127.0.0.1:11434/v1\n"
    )

    captured = {}

    class Result:
        returncode = 0
        stdout = "OK"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        return Result()

    def fake_expanduser(path):
        if path == "~/.hermes/config.yaml":
            return str(fake_home / ".hermes" / "config.yaml")
        return path

    monkeypatch.setattr("src.hermes_agent._hermes_runtime_home", lambda: runtime)
    monkeypatch.setattr("os.path.expanduser", fake_expanduser)
    monkeypatch.setattr("src.hermes_agent.subprocess.run", fake_run)

    assert run_hermes_oneshot("prompt text", model="llama3.2:3b") == "OK"
    assert captured["cmd"] == [
        "hermes",
        "-z",
        "prompt text",
        "--model",
        "llama3.2:3b",
    ]
    assert "--provider" not in captured["cmd"]
    # The mirrored config must NOT have been given a provider entry.
    seeded = (runtime / "config.yaml").read_text()
    assert "omniroute" not in seeded


def test_run_hermes_oneshot_with_provider_config_targets_omniroute(monkeypatch, tmp_path):
    """A tool-required implementation run with the OmniRoute handoff must build
    `hermes -z ... --model opencode-zen/nemotron-3.5-lightning-free --provider omniroute`, inject ONLY
    the endpoint + env var NAME into the mirrored config (never the key value),
    and keep HERMES_HOME inside the workspace."""
    from src.hermes_agent import run_hermes_oneshot

    runtime = tmp_path / ".hermes-runtime"
    fake_home = tmp_path / "fake-home"
    (fake_home / ".hermes").mkdir(parents=True)
    (fake_home / ".hermes" / "config.yaml").write_text(
        "model:\n  default: llama3.2:3b\n  provider: custom\n"
        "  base_url: http://127.0.0.1:11434/v1\n"
    )

    captured = {}

    class Result:
        returncode = 0
        stdout = "OK"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        return Result()

    def fake_expanduser(path):
        if path == "~/.hermes/config.yaml":
            return str(fake_home / ".hermes" / "config.yaml")
        return path

    monkeypatch.setattr("src.hermes_agent._hermes_runtime_home", lambda: runtime)
    monkeypatch.setattr("os.path.expanduser", fake_expanduser)
    monkeypatch.setattr("src.hermes_agent.subprocess.run", fake_run)
    monkeypatch.setenv("OMNIROUTE_API_KEY", "super-secret-omniroute-key-123")

    result = run_hermes_oneshot(
        "prompt text",
        model="opencode-zen/nemotron-3.5-lightning-free",
        provider_id="omniroute",
        base_url="http://127.0.0.1:20128/v1",
        api_key_env="OMNIROUTE_API_KEY",
    )

    assert result == "OK"
    assert captured["cmd"] == [
        "hermes",
        "-z",
        "prompt text",
        "--model",
        "opencode-zen/nemotron-3.5-lightning-free",
        "--provider",
        "omniroute",
    ]
    # HERMES_HOME sandbox redirection is preserved for provider runs too.
    assert captured["env"]["HERMES_HOME"] == str(runtime)

    seeded = (runtime / "config.yaml").read_text()
    assert "omniroute" in seeded
    assert "http://127.0.0.1:20128/v1" in seeded
    assert "key_env: OMNIROUTE_API_KEY" in seeded
    # The implementation must target OmniRoute, NOT local Ollama.
    assert "11434" not in seeded
    # The credential VALUE is never written to the config file.
    assert "super-secret-omniroute-key-123" not in seeded


def test_run_hermes_oneshot_provider_config_requires_endpoint(monkeypatch, tmp_path):
    """A provider handoff without base_url/api_key_env fails fast (misuse)."""
    import pytest
    from src.hermes_agent import run_hermes_oneshot

    runtime = tmp_path / ".hermes-runtime"
    fake_home = tmp_path / "fake-home"
    (fake_home / ".hermes").mkdir(parents=True)
    (fake_home / ".hermes" / "config.yaml").write_text(
        "model:\n  default: llama3.2:3b\n  provider: custom\n"
    )

    def fake_expanduser(path):
        if path == "~/.hermes/config.yaml":
            return str(fake_home / ".hermes" / "config.yaml")
        return path

    monkeypatch.setattr("src.hermes_agent._hermes_runtime_home", lambda: runtime)
    monkeypatch.setattr("os.path.expanduser", fake_expanduser)

    with pytest.raises(ValueError, match="provider_id requires base_url"):
        run_hermes_oneshot(
            "prompt text",
            model="opencode-zen/nemotron-3.5-lightning-free",
            provider_id="omniroute",
        )


def test_run_hermes_oneshot_redirects_hermes_home_into_workspace(monkeypatch, tmp_path):
    """The Hermes child must run with HERMES_HOME inside the writable workspace
    (so its logs/state are not EPERM), seeding config.yaml from the user home
    so provider/model behavior is preserved."""
    from src.hermes_agent import run_hermes_oneshot

    runtime = tmp_path / ".hermes-runtime"
    fake_home = tmp_path / "fake-home"
    (fake_home / ".hermes").mkdir(parents=True)
    (fake_home / ".hermes" / "config.yaml").write_text(
        "model:\n  default: llama3.2:3b\n  provider: custom\n"
        "  base_url: http://127.0.0.1:11434/v1\n"
    )

    captured = {}

    class Result:
        returncode = 0
        stdout = "OK"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return Result()

    def fake_expanduser(path):
        if path == "~/.hermes/config.yaml":
            return str(fake_home / ".hermes" / "config.yaml")
        return path

    monkeypatch.setattr("src.hermes_agent._hermes_runtime_home", lambda: runtime)
    monkeypatch.setattr("os.path.expanduser", fake_expanduser)
    monkeypatch.setattr("src.hermes_agent.subprocess.run", fake_run)

    assert run_hermes_oneshot("prompt text") == "OK"
    assert captured["env"]["HERMES_HOME"] == str(runtime)
    seeded = (runtime / "config.yaml").read_text()
    assert "llama3.2:3b" in seeded
    assert "provider: custom" in seeded


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
        "src.autonomous_guard.get_hermes_execution_handoff",
        return_value=(True, "opencode-zen/nemotron-3.5-lightning-free", "validated", None),
    ):
        with patch("src.hermes_agent.get_reports_dir", return_value=tmp_path):
            result = research(123)
            assert result is True
            assert mock_run.call_count == 2 # 1 gate + 1 real

            gate_call = mock_run.call_args_list[0]
            assert "Respond with exactly 'OK'." in gate_call.args[0]
            assert gate_call.kwargs["model"] == "opencode-zen/nemotron-3.5-lightning-free"

            real_call = mock_run.call_args_list[1]
            assert real_call.kwargs["model"] == "opencode-zen/nemotron-3.5-lightning-free"
            assert (tmp_path / "research.md").exists()
            assert (tmp_path / "research.md").read_text() == "[FACT] The issue is simple."

@patch("src.hermes_agent.get_repo_analysis")
@patch("src.hermes_agent.get_issue_context")
@patch("src.hermes_agent.verify_local_provider")
def test_research_fallback_when_remote_unavailable(mock_verify, mock_context, mock_analysis, tmp_path):
    from src.hermes_agent import research
    mock_context.return_value = {
        "org_slug": "checkstyle",
        "repo_name": "checkstyle/checkstyle",
        "issue_number": 123,
        "title": "Discussion aware test issue",
        "body_preview": "Truncated body preview",
        "labels": "[]",
        "activity_status": "HIGH",
        "contribution_value_score": 80.0,
        "gsoc_preparation_score": 90.0,
        "opportunity_score": 85.0
    }
    mock_analysis.return_value = {}

    with patch("src.hermes_agent.get_reports_dir", return_value=tmp_path):
        with patch("src.hermes_agent.run_hermes_oneshot") as mock_run:
            def fake_run(prompt, **kwargs):
                if prompt == "Respond with exactly 'OK'.":
                    raise RuntimeError("403 Free tier limit")
                return "[FACT] The issue is simple."
            mock_run.side_effect = fake_run

            result = research(123)
            assert result is True
            assert mock_run.call_count == 2

            gate_call = mock_run.call_args_list[0]
            assert gate_call.kwargs["model"] == "opencode-zen/nemotron-3.5-lightning-free"

            real_call = mock_run.call_args_list[1]
            assert real_call.kwargs["model"] == "llama3.2:3b"
            assert real_call.kwargs.get("endpoint") is None # Local fallback does not pass endpoint


@patch("src.hermes_agent.verify_local_provider")
@patch("src.hermes_agent.get_issue_context", return_value=None)
def test_research_returns_false_when_issue_missing(mock_context, mock_verify):
    assert research(123) is False


def test_plan_passes_selected_model_to_hermes(monkeypatch, tmp_path):
    from src.hermes_agent import plan

    plan_calls = []

    def fake_execution_plan(task_type="lightweight"):
        plan_calls.append(task_type)
        return (True, "opencode-zen/nemotron-3.5-lightning-free", "validated", None)

    monkeypatch.setattr(
        "src.autonomous_guard.get_hermes_execution_handoff",
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
        return "TARGET FILES:\nsrc/main.py\nTARGET SYMBOL:\nn/a\nACCEPTANCE CRITERIA:\nworks well\nTARGETED TEST:\npytest test.py"

    monkeypatch.setattr("src.hermes_agent.run_hermes_oneshot", fake_run)

    assert plan(123) is True
    assert captured["model"] == "opencode-zen/nemotron-3.5-lightning-free"
    assert (tmp_path / "plan.md").read_text() == "TARGET FILES:\nsrc/main.py\nTARGET SYMBOL:\nn/a\nACCEPTANCE CRITERIA:\nworks well\nTARGETED TEST:\npytest test.py"
    # Planning is reasoning-heavy: it always requests the heavy (OmniRoute) route.
    assert plan_calls == ["heavy"]


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
    # Lightweight/no handoff: no provider kwargs reach the oneshot call.
    assert "provider_id" not in captured
    assert "base_url" not in captured
    assert "api_key_env" not in captured


def test_implement_issue_with_hermes_passes_provider_config(monkeypatch, tmp_path):
    """A tool-required implementation with the OmniRoute handoff forwards the
    full provider config to run_hermes_oneshot (never the key value)."""
    from src.hermes_agent import implement_issue_with_hermes

    captured = {}

    def fake_run(prompt, **kwargs):
        captured.update(kwargs)
        return "implemented"

    monkeypatch.setattr("src.hermes_agent.run_hermes_oneshot", fake_run)
    monkeypatch.setattr("src.hermes_agent.verify_local_provider", lambda: None)

    provider_config = {
        "provider_id": "omniroute",
        "base_url": "http://127.0.0.1:20128/v1",
        "api_key_env": "OMNIROUTE_API_KEY",
        "model": "opencode-zen/nemotron-3.5-lightning-free",
    }
    result = implement_issue_with_hermes(
        tmp_path,
        "Issue Title: Test\nPLAN:\nDo the thing",
        model="opencode-zen/nemotron-3.5-lightning-free",
        provider_config=provider_config,
    )

    assert result == "implemented"
    assert captured["model"] == "opencode-zen/nemotron-3.5-lightning-free"
    assert captured["provider_id"] == "omniroute"
    assert captured["base_url"] == "http://127.0.0.1:20128/v1"
    assert captured["api_key_env"] == "OMNIROUTE_API_KEY"
    assert "super-secret" not in str(captured)


def test_get_issue_context_by_url(monkeypatch):
    from src.hermes_agent import get_issue_context_by_url

    class FakeCursor:
        description = [("url",), ("issue_number",), ("repo_name",)]

        def execute(self, query, params):
            assert query == "SELECT * FROM issues WHERE url = ?"
            assert params == ("https://github.com/example/repo/issues/25",)

        def fetchone(self):
            return (
                "https://github.com/example/repo/issues/25",
                25,
                "example/repo",
            )

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        "src.hermes_agent.get_connection",
        lambda: FakeConnection(),
    )

    issue = get_issue_context_by_url(
        "https://github.com/example/repo/issues/25"
    )

    assert issue["url"] == "https://github.com/example/repo/issues/25"
    assert issue["issue_number"] == 25
    assert issue["repo_name"] == "example/repo"


def test_research_passes_discussion_context_to_prompt(monkeypatch, tmp_path):
    import src.hermes_agent as hermes
    from pathlib import Path

    mock_issue = {
        "org_slug": "checkstyle",
        "repo_name": "checkstyle/checkstyle",
        "issue_number": 21480,
        "title": "Discussion aware test issue",
        "body_preview": "Truncated body preview",
        "discussion_context": "=== ISSUE BODY ===\nFull issue text\n=== DISCUSSION HISTORY ===\n[Comment #1 by Maintainer (MEMBER)]: Decision reached, proceed with fix.",
        "labels": "[]",
        "activity_status": "HIGH",
        "contribution_value_score": 80.0,
        "gsoc_preparation_score": 90.0,
        "opportunity_score": 85.0
    }

    monkeypatch.setattr(hermes, "get_issue_context", lambda issue_id: mock_issue)
    monkeypatch.setattr(hermes, "get_repo_analysis", lambda repo: {})
    monkeypatch.setattr(hermes, "WORKSPACES_ROOT", tmp_path)

    fake_handoff = (True, "mock_model", "ok", {})
    monkeypatch.setattr("src.autonomous_guard.get_hermes_execution_handoff", lambda task_type: fake_handoff)

    captured_prompt = []
    def mock_run_oneshot(prompt, safe_mode=True, model=None, **kwargs):
        captured_prompt.append(prompt)
        return "# Issue summary\n[FACT] Summary\n## Questions for maintainers\n- None\n## Recommended next step\nProceed."

    monkeypatch.setattr(hermes, "run_hermes_oneshot", mock_run_oneshot)

    res = hermes.research(21480)
    assert res is True
    assert len(captured_prompt) == 2
    assert captured_prompt[0] == "Respond with exactly 'OK'."
    assert "Discussion aware test issue" in captured_prompt[1]
    assert "Decision reached, proceed with fix." in captured_prompt[1]
    assert "=== DISCUSSION HISTORY ===" in captured_prompt[1]


def test_implement_issue_with_hermes_preserves_raw_response_on_empty_diff(monkeypatch, tmp_path):
    import subprocess
    import pytest
    from src.hermes_agent import implement_issue_with_hermes

    monkeypatch.setattr("src.hermes_agent.verify_local_provider", lambda: None)
    monkeypatch.setattr("src.hermes_agent.run_hermes_oneshot", lambda *a, **k: "MARKDOWN_CODE_BLOCK_WITHOUT_TOOL_CALL")

    class FakeCompletedProcess:
        stdout = ""

    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "status"]:
            return FakeCompletedProcess()
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="")

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        implement_issue_with_hermes(tmp_path, "context")

    err_msg = str(exc_info.value)
    assert "Implementation agent returned successfully but no files were modified" in err_msg
    assert "--- RAW RESPONSE ---" in err_msg
    assert "MARKDOWN_CODE_BLOCK_WITHOUT_TOOL_CALL" in err_msg
    assert "--- END RAW RESPONSE ---" in err_msg


def test_implement_issue_with_hermes_prompt_contains_strict_tool_constraints(monkeypatch, tmp_path):
    from src.hermes_agent import implement_issue_with_hermes

    captured_prompt = []
    monkeypatch.setattr("src.hermes_agent.verify_local_provider", lambda: None)
    def mock_run(*args, **kwargs):
        captured_prompt.append(args[0])
        return "ok"
    monkeypatch.setattr("src.hermes_agent.run_hermes_oneshot", mock_run)

    class FakeCompletedProcess:
        stdout = "M something.txt\n"
    monkeypatch.setattr("subprocess.run", lambda *a, **k: FakeCompletedProcess())

    implement_issue_with_hermes(tmp_path, "context")

    prompt = captured_prompt[0]
    assert "directly create and edit files" in prompt
    assert "MUST NOT return a patch, code block, explanation" in prompt
    assert "Keep working until the requested implementation is actually present" in prompt
    assert "terminal" in prompt
    assert f"WORKING DIRECTORY: {tmp_path}" in prompt
    assert f"All file reads and writes MUST target this exact path." in prompt

def test_classify_hermes_failure_structured_categories():
    from src.hermes_agent import _classify_hermes_failure

    assert _classify_hermes_failure("timeout of 15000ms exceeded (504)") == "PROVIDER_TIMEOUT"
    assert _classify_hermes_failure("503 Service Unavailable") == "PROVIDER_SERVER_ERROR"
    assert _classify_hermes_failure("rate limit exceeded (429)") == "PROVIDER_RATE_LIMIT"
    assert _classify_hermes_failure("Error from provider (Console): OpenCode's free tier can only be used from within OpenCode (HTTP 403)") == "PROVIDER_ACCESS"
    assert _classify_hermes_failure("auth — Billing or credits exhausted") == "PROVIDER_AUTH"
    assert _classify_hermes_failure("read timeout") == "PROVIDER_TIMEOUT"
    assert _classify_hermes_failure("Implementation agent returned successfully but no files were modified") == "IMPLEMENTATION_FAILURE"
    assert _classify_hermes_failure("Validation FAILED: No files were changed") == "IMPLEMENTATION_FAILURE"
    assert _classify_hermes_failure("guardrail failed") == "IMPLEMENTATION_FAILURE"
    assert _classify_hermes_failure("subprocess.TimeoutExpired: Command 'hermes' timed out after 900 seconds") == "PROVIDER_TIMEOUT"
    assert _classify_hermes_failure("Hermes CLI timed out after 900 seconds. Model execution might be stuck or too slow.") == "PROVIDER_TIMEOUT"
    assert _classify_hermes_failure("some weird obscure error") == "UNKNOWN"


def test_plan_semantic_validation_rejects_empty_or_generic():
    from src.hermes_agent import _validate_plan_structure
    import pytest

    bad_plans = [
        "TARGET FILES:\nTARGET SYMBOL:\nACCEPTANCE CRITERIA:\nTARGETED TEST:\nSome plan",
        "TARGET FILES:\nnone\nTARGET SYMBOL:\nvalid\nACCEPTANCE CRITERIA:\nvalid\nTARGETED TEST:\nvalid",
        "TARGET FILES:\nvalid\nTARGET SYMBOL:\nvalid\nACCEPTANCE CRITERIA:\nvalid\nTARGETED TEST:\nrun tests",
    ]

    for bp in bad_plans:
        with pytest.raises(ValueError):
            _validate_plan_structure(bp)

    good_plan = "TARGET FILES:\nsrc/main.py\nTARGET SYMBOL:\nn/a\nACCEPTANCE CRITERIA:\nworks well\nTARGETED TEST:\npytest test.py"
    _validate_plan_structure(good_plan) # Should not raise

def test_plan_semantic_validation_targeted_test_extraction():
    from src.hermes_agent import _validate_plan_structure
    import pytest

    valid_plan = """TARGET FILES:
src/main.py
TARGET SYMBOL:
n/a
ACCEPTANCE CRITERIA:
works well
TARGETED TEST:
pytest test.py
### Implementation steps
1. do this
2. do that
"""
    # This should not raise, meaning TARGETED TEST correctly extracted `pytest test.py` without the ### Implementation steps
    _validate_plan_structure(valid_plan)

    invalid_plan_prose_1 = """TARGET FILES:
src/main.py
TARGET SYMBOL:
n/a
ACCEPTANCE CRITERIA:
works well
TARGETED TEST:
Perform `./mvnw test -Dtest=YourTestClass` where `YourTestClass` is a newly converted test class.
### Implementation steps
"""
    with pytest.raises(ValueError, match="raw shell command, but starts with conversational prose"):
        _validate_plan_structure(invalid_plan_prose_1)

    invalid_plan_prose_2 = """TARGET FILES:
src/main.py
TARGET SYMBOL:
n/a
ACCEPTANCE CRITERIA:
works well
TARGETED TEST:
run `mvn test` to check
"""
    with pytest.raises(ValueError, match="starts with conversational prose"):
        _validate_plan_structure(invalid_plan_prose_2)

    invalid_plan_multiline = """TARGET FILES:
src/main.py
TARGET SYMBOL:
n/a
ACCEPTANCE CRITERIA:
works well
TARGETED TEST:
./mvnw test
echo "done"
"""
    with pytest.raises(ValueError, match="multiple lines"):
        _validate_plan_structure(invalid_plan_multiline)

    invalid_plan_backticks = """TARGET FILES:
src/main.py
TARGET SYMBOL:
n/a
ACCEPTANCE CRITERIA:
works well
TARGETED TEST:
`./mvnw test`
"""
    with pytest.raises(ValueError, match="markdown backticks"):
        _validate_plan_structure(invalid_plan_backticks)

    good_commands = [
        "./mvnw test",
        "mvn test",
        "./gradlew test",
        "gradle test",
        "pytest test.py",
        "python -m pytest",
        "npm test",
        "pnpm test",
        "yarn test",
        "cargo test",
        "go test ./...",
        "make test",
    ]

    for cmd in good_commands:
        good_plan = f"TARGET FILES:\nvalid\nTARGET SYMBOL:\nvalid\nACCEPTANCE CRITERIA:\nvalid\nTARGETED TEST:\n{cmd}\n### Risks\nnone"
        _validate_plan_structure(good_plan)
