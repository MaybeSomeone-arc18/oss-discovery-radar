import requests
from unittest.mock import patch

from src.omniroute import (
    get_omniroute_config,
    omniroute_is_available,
    OMNIROUTE_BASE_URL_DEFAULT,
    OMNIROUTE_MODEL_DEFAULT,
)


def test_omniroute_config_resolves_when_configured(monkeypatch):
    """a. OmniRoute config resolves correctly when configured."""
    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")
    monkeypatch.setenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
    monkeypatch.setenv("OMNIROUTE_MODEL", "auto/coding:free")

    config = get_omniroute_config()

    assert config == {
        "base_url": "http://127.0.0.1:20128/v1",
        "model": "auto/coding:free",
        "api_key": "secret-key",
    }


def test_omniroute_config_uses_defaults_for_unset_paths(monkeypatch):
    """Base URL and model fall back to the OmniRoute defaults when unset."""
    monkeypatch.delenv("OMNIROUTE_BASE_URL", raising=False)
    monkeypatch.delenv("OMNIROUTE_MODEL", raising=False)
    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")

    config = get_omniroute_config()

    assert config["base_url"] == OMNIROUTE_BASE_URL_DEFAULT
    assert config["model"] == OMNIROUTE_MODEL_DEFAULT


def test_omniroute_config_missing_credentials_fails_safe(monkeypatch):
    """b. Missing OmniRoute credentials fail safely (None, no raise)."""
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)

    assert get_omniroute_config() is None
    assert omniroute_is_available() is False


def test_omniroute_available_when_reachable_and_authenticated(monkeypatch):
    """Availability probe hits the OpenAI-compatible /models endpoint with the key."""
    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")

    with patch("src.omniroute.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        assert omniroute_is_available() is True

    args, kwargs = mock_get.call_args
    assert args[0] == "http://127.0.0.1:20128/v1/models"
    assert kwargs["headers"]["Authorization"] == "Bearer secret-key"


def test_omniroute_available_false_when_unauthenticated(monkeypatch):
    """An authenticated endpoint (401/403) must resolve to unavailable."""
    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")

    with patch("src.omniroute.requests.get") as mock_get:
        mock_get.return_value.status_code = 401
        assert omniroute_is_available() is False


def test_omniroute_available_false_when_gateway_down(monkeypatch):
    """An unreachable gateway must resolve to unavailable, never raise."""
    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-key")

    with patch(
        "src.omniroute.requests.get",
        side_effect=requests.exceptions.ConnectionError("connection refused"),
    ):
        assert omniroute_is_available() is False


def test_existing_ollama_3b_behavior_unchanged():
    """c. Existing Ollama/3B selection behavior is unchanged."""
    from src.hermes_agent import select_local_model

    models = [
        {"name": "qwen3.5:9b", "size": 6594474711},
        {"name": "llama3.2:3b", "size": 2019393189},
    ]

    assert select_local_model(3072, models) == "llama3.2:3b"
    assert select_local_model(6000, models) == "llama3.2:3b"
    assert select_local_model(16384, models) == "llama3.2:3b"


def test_qwen_never_automatically_selected():
    """d. qwen3.5:9b is still never automatically selected."""
    from src.hermes_agent import select_local_model

    models = [
        {"name": "qwen3.5:9b", "size": 6594474711},
        {"name": "llama3.2:3b", "size": 2019393189},
    ]

    assert select_local_model(16384, models) != "qwen3.5:9b"
    assert select_local_model(9000, models) != "qwen3.5:9b"