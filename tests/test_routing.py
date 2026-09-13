"""Focused tests for the provider routing step (lightweight vs heavy).

Covers the routing policy:
  a. lightweight -> llama3.2:3b
  b. heavy + OmniRoute available -> OmniRoute
  c. heavy + OmniRoute unavailable + 3B safe -> llama3.2:3b
  d. heavy + OmniRoute unavailable + 3B unsafe -> defer
  e. qwen3.5:9b is never selected
  f. availability is not probed repeatedly within the same cache window
"""

import requests
import pytest
from unittest.mock import patch

from src.autonomous_guard import TASK_TYPES, select_execution_provider
from src.omniroute import OMNIROUTE_MODEL_DEFAULT, reset_omniroute_availability_cache

LOCAL_MODELS = [
    {"name": "qwen3.5:9b", "size": 6594474711},
    {"name": "llama3.2:3b", "size": 2019393189},
]


@pytest.fixture(autouse=True)
def fresh_omniroute_cache():
    """Every routing test starts and ends with an empty availability cache."""
    reset_omniroute_availability_cache()
    yield
    reset_omniroute_availability_cache()


def test_task_types_stay_minimal():
    assert TASK_TYPES == ("lightweight", "heavy")


def test_unknown_task_type_is_rejected():
    with pytest.raises(ValueError, match="Unknown task type"):
        select_execution_provider("research", 6000, models=LOCAL_MODELS)


# --- a. lightweight -> llama3.2:3b -----------------------------------------


def test_lightweight_routes_to_3b():
    ok, model, reason = select_execution_provider(
        "lightweight", 6000, models=LOCAL_MODELS, resources_ok=False
    )
    assert ok is True
    assert model == "llama3.2:3b"
    assert "llama3.2:3b" in reason


def test_lightweight_never_probes_omniroute(monkeypatch):
    """Even with OmniRoute configured/available, lightweight never probes it."""
    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    with patch("src.omniroute.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        ok, model, _ = select_execution_provider(
            "lightweight", 6000, models=LOCAL_MODELS, resources_ok=False
        )
    assert ok is True
    assert model == "llama3.2:3b"
    mock_get.assert_not_called()


def test_lightweight_routes_to_3b_when_resources_confirmed(monkeypatch):
    ok, model, _ = select_execution_provider(
        "lightweight", 6000, models=LOCAL_MODELS, resources_ok=True
    )
    assert ok is True
    assert model == "llama3.2:3b"


def test_lightweight_defers_when_3b_unsafe():
    ok, model, reason = select_execution_provider(
        "lightweight", 2000, models=LOCAL_MODELS, resources_ok=False
    )
    assert ok is False
    assert model is None
    assert "Insufficient" in reason


# --- b. heavy + OmniRoute available -> OmniRoute ----------------------------


def test_heavy_routes_to_omniroute_when_available(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    with patch("src.omniroute.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        ok, model, reason = select_execution_provider(
            "heavy", 2000, models=LOCAL_MODELS, resources_ok=False
        )
        assert mock_get.call_count == 1
    assert ok is True
    assert model == OMNIROUTE_MODEL_DEFAULT
    assert "OmniRoute" in reason


def test_heavy_routes_to_omniroute_even_when_local_resources_ok(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    with patch("src.omniroute.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        ok, model, _ = select_execution_provider(
            "heavy", 6000, models=LOCAL_MODELS, resources_ok=True
        )
    assert ok is True
    assert model == OMNIROUTE_MODEL_DEFAULT


# --- c. heavy + OmniRoute unavailable + 3B safe -> llama3.2:3b --------------


def test_heavy_falls_back_to_3b_when_omniroute_not_configured(monkeypatch):
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    with patch("src.omniroute.requests.get") as mock_get:
        ok, model, reason = select_execution_provider(
            "heavy", 6000, models=LOCAL_MODELS, resources_ok=False
        )
    # No API key -> no availability request is issued at all.
    mock_get.assert_not_called()
    assert ok is True
    assert model == "llama3.2:3b"


def test_heavy_falls_back_to_3b_when_omniroute_gateway_down(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    with patch(
        "src.omniroute.requests.get",
        side_effect=requests.exceptions.ConnectionError("connection refused"),
    ) as mock_get:
        ok, model, _ = select_execution_provider(
            "heavy", 6000, models=LOCAL_MODELS, resources_ok=False
        )
    assert mock_get.call_count == 1
    assert ok is True
    assert model == "llama3.2:3b"


def test_heavy_falls_back_to_3b_when_omniroute_unauthorized(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    with patch("src.omniroute.requests.get") as mock_get:
        mock_get.return_value.status_code = 401
        ok, model, _ = select_execution_provider(
            "heavy", 6000, models=LOCAL_MODELS, resources_ok=True
        )
    assert ok is True
    assert model == "llama3.2:3b"


# --- d. heavy + OmniRoute unavailable + 3B unsafe -> defer -------------------


def test_heavy_defers_when_omniroute_unavailable_and_local_unsafe(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    with patch(
        "src.omniroute.requests.get",
        side_effect=requests.exceptions.ConnectionError("connection refused"),
    ):
        ok, model, _ = select_execution_provider(
            "heavy", 2000, models=LOCAL_MODELS, resources_ok=False
        )
    assert ok is False
    assert model is None


def test_heavy_defers_with_resource_msg_when_present(monkeypatch):
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    ok, model, reason = select_execution_provider(
        "heavy",
        2000,
        models=LOCAL_MODELS,
        resources_ok=False,
        resource_msg="Insufficient memory headroom",
    )
    assert ok is False
    assert model is None
    assert reason == "Insufficient memory headroom"


# --- e. qwen3.5:9b is never selected ----------------------------------------


@pytest.mark.parametrize("task_type,memory", [("lightweight", 16384), ("heavy", 16384)])
def test_qwen_3_5_9b_never_selected(monkeypatch, task_type, memory):
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    ok, model, _ = select_execution_provider(
        task_type, memory, models=LOCAL_MODELS, resources_ok=False
    )
    assert ok is True
    assert model != "qwen3.5:9b", f"qwen3.5:9b must never be auto-selected (got {model!r})"
    assert model in ("llama3.2:3b", OMNIROUTE_MODEL_DEFAULT, None)


def test_qwen_never_selected_even_as_configured_omniroute_model(monkeypatch):
    """A blocked model configured via OMNIROUTE_MODEL must fall through to 3B."""
    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    monkeypatch.setenv("OMNIROUTE_MODEL", "qwen3.5:9b")
    with patch("src.omniroute.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        ok, model, _ = select_execution_provider(
            "heavy", 6000, models=LOCAL_MODELS, resources_ok=False
        )
    assert ok is True
    assert model == "llama3.2:3b"
    assert model != "qwen3.5:9b"


# --- f. availability is not probed repeatedly within the cache window -------


def test_availability_probed_once_for_repeated_heavy_tasks(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    with patch("src.omniroute.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        for _ in range(5):
            ok, model, _ = select_execution_provider(
                "heavy", 6000, models=LOCAL_MODELS, resources_ok=False
            )
            assert ok is True
            assert model == OMNIROUTE_MODEL_DEFAULT
        assert mock_get.call_count == 1


def test_mixed_light_and_heavy_tasks_share_one_probe(monkeypatch):
    """A lightweight task in between heavy tasks does not cause a re-probe."""
    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    with patch("src.omniroute.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        ok, model, _ = select_execution_provider(
            "lightweight", 6000, models=LOCAL_MODELS, resources_ok=False
        )
        assert ok is True and model == "llama3.2:3b"
        ok, model, _ = select_execution_provider(
            "heavy", 6000, models=LOCAL_MODELS, resources_ok=False
        )
        assert ok is True and model == OMNIROUTE_MODEL_DEFAULT
        ok, model, _ = select_execution_provider(
            "heavy", 6000, models=LOCAL_MODELS, resources_ok=False
        )
        assert ok is True and model == OMNIROUTE_MODEL_DEFAULT
        assert mock_get.call_count == 1


def test_failed_probe_cached_instead_of_repeated(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    with patch(
        "src.omniroute.requests.get",
        side_effect=requests.exceptions.ConnectionError("down"),
    ) as mock_get:
        for _ in range(3):
            ok, model, _ = select_execution_provider(
                "heavy", 6000, models=LOCAL_MODELS, resources_ok=False
            )
            assert ok is True
            assert model == "llama3.2:3b"
        assert mock_get.call_count == 1