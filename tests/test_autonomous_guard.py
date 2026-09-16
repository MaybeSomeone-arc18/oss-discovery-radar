import pytest
import requests
from unittest.mock import patch

from src.autonomous_guard import validate_autonomous_run, validate_hermes_execution
from src.omniroute import OMNIROUTE_MODEL_DEFAULT, reset_omniroute_availability_cache


@pytest.fixture(autouse=True)
def fresh_omniroute_cache():
    """Keep the OmniRoute availability cache empty between tests."""
    reset_omniroute_availability_cache()
    yield
    reset_omniroute_availability_cache()


def test_validate_autonomous_run_accepts_ready_issue(monkeypatch):
    monkeypatch.setattr(
        "src.autonomous_guard.get_issue_context",
        lambda issue_id: {
            "readiness_status": "READY_NOW",
            "eligibility_status": "ELIGIBLE",
        },
    )
    monkeypatch.setattr(
        "src.autonomous_guard.verify_local_provider",
        lambda: None,
    )
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (True, "Resources sufficient"),
    )

    ok, reason = validate_autonomous_run(123)

    assert ok is True
    assert reason == "Autonomous run validated."


def test_validate_autonomous_run_rejects_non_ready_issue(monkeypatch):
    monkeypatch.setattr(
        "src.autonomous_guard.get_issue_context",
        lambda issue_id: {
            "readiness_status": "WAITING_ON_RELEASE",
            "eligibility_status": "ELIGIBLE",
        },
    )

    ok, reason = validate_autonomous_run(123)

    assert ok is False
    assert "not READY_NOW" in reason


def test_validate_autonomous_run_rejects_blocked_issue(monkeypatch):
    monkeypatch.setattr(
        "src.autonomous_guard.get_issue_context",
        lambda issue_id: {
            "readiness_status": "READY_NOW",
            "eligibility_status": "BLOCKED",
        },
    )

    ok, reason = validate_autonomous_run(123)

    assert ok is False
    assert "ineligible" in reason


def test_validate_autonomous_run_rejects_missing_issue(monkeypatch):
    monkeypatch.setattr(
        "src.autonomous_guard.get_issue_context",
        lambda issue_id: None,
    )

    ok, reason = validate_autonomous_run(123)

    assert ok is False
    assert reason == "Issue not found."


def test_validate_autonomous_run_rejects_unavailable_hermes(monkeypatch):
    monkeypatch.setattr(
        "src.autonomous_guard.get_issue_context",
        lambda issue_id: {
            "readiness_status": "READY_NOW",
            "eligibility_status": "ELIGIBLE",
        },
    )

    def fail_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "src.autonomous_guard.verify_local_provider",
        fail_provider,
    )

    ok, reason = validate_autonomous_run(123)

    assert ok is False
    assert "Hermes unavailable" in reason


def test_validate_hermes_execution_allows_3b_fallback(monkeypatch):
    monkeypatch.setattr(
        "src.autonomous_guard.verify_local_provider",
        lambda: None,
    )
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (False, "Insufficient memory headroom"),
    )
    monkeypatch.setattr(
        "src.hermes_agent.list_local_models",
        lambda: [
            {"name": "qwen3.5:9b", "size": 6594474711},
            {"name": "llama3.2:3b", "size": 2019393189},
        ],
    )
    monkeypatch.setattr(
        "src.autonomous_guard.get_available_memory_mb",
        lambda: 6000,
    )

    ok, reason = validate_hermes_execution()

    assert ok is True
    assert "llama3.2:3b" in reason


def test_get_hermes_execution_plan_never_selects_qwen_even_with_resources(monkeypatch):
    """Even when resource check passes and qwen is installed, 3B is returned, never 9B."""
    from src.autonomous_guard import get_hermes_execution_plan

    monkeypatch.setattr(
        "src.autonomous_guard.verify_local_provider",
        lambda: None,
    )
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (True, "Resources sufficient"),
    )

    ok, model, reason = get_hermes_execution_plan()

    assert ok is True
    assert model == "llama3.2:3b"
    assert "llama3.2:3b" in reason
    assert "qwen3.5:9b" not in model


def test_get_hermes_execution_plan_selects_3b(monkeypatch):
    from src.autonomous_guard import get_hermes_execution_plan

    monkeypatch.setattr(
        "src.autonomous_guard.verify_local_provider",
        lambda: None,
    )
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (False, "Insufficient memory headroom"),
    )
    monkeypatch.setattr(
        "src.hermes_agent.list_local_models",
        lambda: [
            {"name": "qwen3.5:9b", "size": 6594474711},
            {"name": "llama3.2:3b", "size": 2019393189},
        ],
    )
    monkeypatch.setattr(
        "src.autonomous_guard.get_available_memory_mb",
        lambda: 6000,
    )

    ok, model, reason = get_hermes_execution_plan()

    assert ok is True
    assert model == "llama3.2:3b"
    assert "llama3.2:3b" in reason


def test_get_hermes_execution_plan_defers_when_no_model_fits(monkeypatch):
    from src.autonomous_guard import get_hermes_execution_plan

    monkeypatch.setattr(
        "src.autonomous_guard.verify_local_provider",
        lambda: None,
    )
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (False, "Insufficient memory headroom"),
    )
    monkeypatch.setattr(
        "src.hermes_agent.list_local_models",
        lambda: [
            {"name": "qwen3.5:9b", "size": 6594474711},
            {"name": "llama3.2:3b", "size": 2019393189},
        ],
    )
    monkeypatch.setattr(
        "src.autonomous_guard.get_available_memory_mb",
        lambda: 2000,
    )

    ok, model, reason = get_hermes_execution_plan()

    assert ok is False
    assert model is None
    assert "Insufficient memory headroom" in reason


@pytest.mark.parametrize("available_mb", [16384, 9000, 6000, 3072])
def test_get_hermes_execution_plan_never_returns_qwen_at_any_memory(monkeypatch, available_mb):
    """qwen3.5:9b must never be the returned model, regardless of available memory."""
    from src.autonomous_guard import get_hermes_execution_plan

    monkeypatch.setattr(
        "src.autonomous_guard.verify_local_provider",
        lambda: None,
    )
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (False, "Insufficient memory headroom"),
    )
    monkeypatch.setattr(
        "src.hermes_agent.list_local_models",
        lambda: [
            {"name": "qwen3.5:9b", "size": 6594474711},
            {"name": "llama3.2:3b", "size": 2019393189},
        ],
    )
    monkeypatch.setattr(
        "src.autonomous_guard.get_available_memory_mb",
        lambda mb=available_mb: mb,
    )

    ok, model, _ = get_hermes_execution_plan()

    assert model != "qwen3.5:9b", (
        f"qwen3.5:9b must never be selected automatically (got model={model!r} at {available_mb}MB)"
    )


def test_insufficient_memory_returns_no_safe_model(monkeypatch):
    """When memory is too low even for 3B, the plan must defer with no model."""
    from src.autonomous_guard import get_hermes_execution_plan

    monkeypatch.setattr(
        "src.autonomous_guard.verify_local_provider",
        lambda: None,
    )
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (False, "Insufficient memory headroom"),
    )
    monkeypatch.setattr(
        "src.hermes_agent.list_local_models",
        lambda: [{"name": "llama3.2:3b", "size": 2019393189}],
    )
    monkeypatch.setattr(
        "src.autonomous_guard.get_available_memory_mb",
        lambda: 2000,
    )

    ok, model, reason = get_hermes_execution_plan()

    assert ok is False
    assert model is None
    assert "Insufficient memory" in reason


# --- task routing through the execution-plan decision point -----------------


def test_heavy_task_routes_to_omniroute_when_available(monkeypatch):
    """b. heavy + OmniRoute available -> OmniRoute, even when 3B is unsafe."""
    from src.autonomous_guard import get_hermes_execution_plan

    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    monkeypatch.setattr("src.autonomous_guard.verify_local_provider", lambda: None)
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (False, "Insufficient memory headroom"),
    )
    monkeypatch.setattr(
        "src.hermes_agent.list_local_models",
        lambda: [
            {"name": "qwen3.5:9b", "size": 6594474711},
            {"name": "llama3.2:3b", "size": 2019393189},
        ],
    )
    monkeypatch.setattr("src.autonomous_guard.get_available_memory_mb", lambda: 2000)

    with patch("src.omniroute.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        ok, model, reason = get_hermes_execution_plan("heavy")

    assert ok is True
    assert model == OMNIROUTE_MODEL_DEFAULT
    assert "OmniRoute" in reason
    assert "qwen3.5:9b" not in model


def test_heavy_task_falls_back_to_3b_when_omniroute_down(monkeypatch):
    """c. heavy + OmniRoute unavailable + 3B safe -> llama3.2:3b."""
    from src.autonomous_guard import get_hermes_execution_plan

    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    monkeypatch.setattr("src.autonomous_guard.verify_local_provider", lambda: None)
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (False, "Insufficient memory headroom"),
    )
    monkeypatch.setattr(
        "src.hermes_agent.list_local_models",
        lambda: [
            {"name": "qwen3.5:9b", "size": 6594474711},
            {"name": "llama3.2:3b", "size": 2019393189},
        ],
    )
    monkeypatch.setattr("src.autonomous_guard.get_available_memory_mb", lambda: 6000)

    with patch(
        "src.omniroute.requests.get",
        side_effect=requests.exceptions.ConnectionError("connection refused"),
    ):
        ok, model, reason = get_hermes_execution_plan("heavy")

    assert ok is True
    assert model == "llama3.2:3b"
    assert "qwen3.5:9b" not in model


def test_heavy_task_falls_back_to_3b_when_omniroute_key_missing(monkeypatch):
    """heavy + no OMNIROUTE_API_KEY (the real runtime state) -> safer 3B fallback,
    with no availability probe issued at all."""
    from src.autonomous_guard import get_hermes_execution_plan

    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    monkeypatch.setattr("src.autonomous_guard.verify_local_provider", lambda: None)
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (False, "Insufficient memory headroom"),
    )
    monkeypatch.setattr(
        "src.hermes_agent.list_local_models",
        lambda: [
            {"name": "qwen3.5:9b", "size": 6594474711},
            {"name": "llama3.2:3b", "size": 2019393189},
        ],
    )
    monkeypatch.setattr("src.autonomous_guard.get_available_memory_mb", lambda: 6000)

    with patch("src.omniroute.requests.get") as mock_get:
        ok, model, reason = get_hermes_execution_plan("heavy")

    assert ok is True
    assert model == "llama3.2:3b"
    assert "qwen3.5:9b" not in model
    mock_get.assert_not_called()


def test_heavy_task_defers_when_omniroute_down_and_3b_unsafe(monkeypatch):
    """d. heavy + OmniRoute unavailable + 3B unsafe -> defer."""
    from src.autonomous_guard import get_hermes_execution_plan

    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    monkeypatch.setattr("src.autonomous_guard.verify_local_provider", lambda: None)
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (False, "Insufficient memory headroom"),
    )
    monkeypatch.setattr(
        "src.hermes_agent.list_local_models",
        lambda: [{"name": "llama3.2:3b", "size": 2019393189}],
    )
    monkeypatch.setattr("src.autonomous_guard.get_available_memory_mb", lambda: 2000)

    with patch(
        "src.omniroute.requests.get",
        side_effect=requests.exceptions.ConnectionError("connection refused"),
    ):
        ok, model, reason = get_hermes_execution_plan("heavy")

    assert ok is False
    assert model is None
    assert "Insufficient memory headroom" in reason


def test_lightweight_task_never_uses_omniroute_even_when_available(monkeypatch):
    """a. lightweight stays on llama3.2:3b; no OmniRoute probe is made."""
    from src.autonomous_guard import get_hermes_execution_plan

    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    monkeypatch.setattr("src.autonomous_guard.verify_local_provider", lambda: None)
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (True, "Resources sufficient"),
    )

    with patch("src.omniroute.requests.get") as mock_get:
        ok, model, reason = get_hermes_execution_plan("lightweight")

    assert ok is True
    assert model == "llama3.2:3b"
    assert "llama3.2:3b" in reason
    mock_get.assert_not_called()


# --- implementation (tool-required) routing at the plan level ----------------


def test_implementation_task_routes_to_omniroute_when_available(monkeypatch):
    """implementation + OmniRoute available -> OmniRoute (tool-capable),
    even when local 3B is fully safe."""
    from src.autonomous_guard import get_hermes_execution_plan

    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    monkeypatch.setattr("src.autonomous_guard.verify_local_provider", lambda: None)
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (True, "Resources sufficient"),
    )

    with patch("src.omniroute.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        ok, model, reason = get_hermes_execution_plan("implementation")

    assert ok is True
    assert model == "openrouter/poolside/laguna-s-2.1:free"
    assert "tool-capable" in reason
    assert "qwen3.5:9b" not in model


def test_implementation_task_defers_when_omniroute_unavailable(monkeypatch):
    """implementation + OmniRoute unavailable -> DEFER with the tool-capable
    provider reason; llama3.2:3b is never selected even when installed and
    local resources are fully sufficient."""
    from src.autonomous_guard import (
        TOOL_REQUIRED_UNAVAILABLE_REASON,
        get_hermes_execution_plan,
    )

    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    monkeypatch.setattr("src.autonomous_guard.verify_local_provider", lambda: None)
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (True, "Resources sufficient"),
    )

    ok, model, reason = get_hermes_execution_plan("implementation")

    assert ok is False
    assert model is None
    assert reason == TOOL_REQUIRED_UNAVAILABLE_REASON


def test_implementation_task_defers_when_omniroute_down(monkeypatch):
    """implementation + OmniRoute reachable but gateway down -> DEFER,
    NOT fall back to llama3.2:3b even with memory ample."""
    from src.autonomous_guard import get_hermes_execution_plan

    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    monkeypatch.setattr("src.autonomous_guard.verify_local_provider", lambda: None)
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (True, "Resources sufficient"),
    )

    with patch(
        "src.omniroute.requests.get",
        side_effect=requests.exceptions.ConnectionError("connection refused"),
    ):
        ok, model, reason = get_hermes_execution_plan("implementation")

    assert ok is False
    assert model is None
    assert "tool-capable" in reason


# --- provider handoff: get_hermes_execution_handoff -------------------------


def test_handoff_implementation_routes_to_omniroute_config(monkeypatch):
    """The implementation handoff carries the explicit OmniRoute provider
    config (provider_id + base_url + env var NAME), never the key value."""
    from src.autonomous_guard import get_hermes_execution_handoff

    monkeypatch.setenv("OMNIROUTE_API_KEY", "super-secret-omniroute-key-123")
    monkeypatch.setattr("src.autonomous_guard.verify_local_provider", lambda: None)
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (True, "Resources sufficient"),
    )

    with patch("src.omniroute.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        ok, model, reason, provider_config = get_hermes_execution_handoff(
            "implementation"
        )

    assert ok is True
    assert model == "openrouter/poolside/laguna-s-2.1:free"
    assert "tool-capable" in reason
    assert provider_config == {
        "provider_id": "omniroute",
        "base_url": "http://127.0.0.1:20128/v1",
        "api_key_env": "OMNIROUTE_API_KEY",
        "model": "openrouter/poolside/laguna-s-2.1:free",
    }
    assert "super-secret-omniroute-key-123" not in str(provider_config)


def test_handoff_implementation_defers_without_omniroute(monkeypatch):
    """Implementation handoff defers (provider_config None) when OmniRoute is
    unavailable; llama3.2:3b is never selected for implementation."""
    from src.autonomous_guard import (
        TOOL_REQUIRED_UNAVAILABLE_REASON,
        get_hermes_execution_handoff,
    )

    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    monkeypatch.setattr("src.autonomous_guard.verify_local_provider", lambda: None)
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (True, "Resources sufficient"),
    )

    ok, model, reason, provider_config = get_hermes_execution_handoff(
        "implementation"
    )

    assert ok is False
    assert model is None
    assert reason == TOOL_REQUIRED_UNAVAILABLE_REASON
    assert provider_config is None


def test_handoff_implementation_never_omniroutes_ollama(monkeypatch):
    """A routed implementation handoff must point at the OmniRoute endpoint,
    never the local Ollama base URL."""
    from src.autonomous_guard import get_hermes_execution_handoff

    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    monkeypatch.setattr("src.autonomous_guard.verify_local_provider", lambda: None)
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (True, "Resources sufficient"),
    )

    with patch("src.omniroute.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        _ok, _model, _reason, provider_config = get_hermes_execution_handoff(
            "implementation"
        )

    assert provider_config["base_url"] == "http://127.0.0.1:20128/v1"
    assert "11434" not in provider_config["base_url"]


def test_handoff_implementation_blocks_qwen_model(monkeypatch):
    """qwen3.5:9b configured as the OmniRoute model stays blocked: no handoff,
    no selection, exact tool-required defer reason."""
    from src.autonomous_guard import (
        TOOL_REQUIRED_UNAVAILABLE_REASON,
        get_hermes_execution_handoff,
    )

    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    monkeypatch.setenv("OMNIROUTE_MODEL", "qwen3.5:9b")
    monkeypatch.setattr("src.autonomous_guard.verify_local_provider", lambda: None)
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (True, "Resources sufficient"),
    )

    with patch("src.omniroute.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        ok, model, reason, provider_config = get_hermes_execution_handoff(
            "implementation"
        )

    assert ok is False
    assert model is None
    assert reason == TOOL_REQUIRED_UNAVAILABLE_REASON
    assert provider_config is None


def test_handoff_lightweight_never_carries_provider_config(monkeypatch):
    """Lightweight stays on llama3.2:3b with no provider handoff and no probe."""
    from src.autonomous_guard import get_hermes_execution_handoff

    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    monkeypatch.setattr("src.autonomous_guard.verify_local_provider", lambda: None)
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (True, "Resources sufficient"),
    )

    with patch("src.omniroute.requests.get") as mock_get:
        ok, model, reason, provider_config = get_hermes_execution_handoff(
            "lightweight"
        )

    assert ok is True
    assert model == "llama3.2:3b"
    assert "llama3.2:3b" in reason
    assert provider_config is None
    mock_get.assert_not_called()

def test_heavy_task_routes_to_omniroute_when_local_ollama_offline(monkeypatch):
    """Regression test: heavy + OmniRoute available works even when list_local_models fails."""
    from src.autonomous_guard import get_hermes_execution_plan

    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    monkeypatch.setattr("src.autonomous_guard.verify_local_provider", lambda: None)
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (False, "Insufficient memory headroom"),
    )
    
    # Model discovery raises exception (Ollama is down)
    def failing_list_models():
        raise Exception("Connection refused")
        
    monkeypatch.setattr("src.hermes_agent.list_local_models", failing_list_models)

    with patch("src.omniroute.requests.get") as mock_get:
        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        ok, model, reason = get_hermes_execution_plan("heavy")

    assert ok is True
    assert model == "opencode-zen/nemotron-3.5-lightning-free"
    assert "OmniRoute" in reason
