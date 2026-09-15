"""Optional OmniRoute provider layer for heavier reasoning tasks.

OmniRoute exposes an OpenAI-compatible gateway on the local machine that Radar
can use as an optional heavier-reasoning provider. It is strictly optional:
default/lightweight tasks keep using llama3.2:3b via Ollama, and OmniRoute is
only addressed when it is configured (API key present) and authenticated.

Everything here fails safe: missing config, an unreachable gateway, or an
unauthenticated response resolve to None/False so callers can fall back to the
existing 3B default or deferred execution.

No task routing happens in this module; it only resolves, validates, and caches
the provider availability so the routing step
(src.autonomous_guard.select_execution_provider) can send heavy work to it.
"""

import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

OMNIROUTE_BASE_URL_DEFAULT = "http://127.0.0.1:20128/v1"
OMNIROUTE_MODEL_DEFAULT = "opencode-zen/nemotron-3.5-lightning-free"
OMNIROUTE_MODELS_ENDPOINT = "/models"

# Hermes-side identity of the OmniRoute execution provider. The app registers a
# ``providers:`` entry under this id inside the workspace-local .hermes-runtime
# config so the Hermes child can resolve OmniRoute as a named custom provider.
# ``api_key_env`` names the environment variable the child reads the credential
# from at runtime — the key value itself is never persisted anywhere.
OMNIROUTE_HERMES_PROVIDER_ID = "omniroute"
OMNIROUTE_API_KEY_ENV_NAME = "OMNIROUTE_API_KEY"

# Short TTL for the availability probe so per-task routing never hits the
# gateway once per task; a run that routes many tasks issues at most one
# availability request per window.
OMNIROUTE_AVAILABILITY_TTL_SECONDS = 45

_availability_cache = {"available": False, "checked_at": 0.0}


def get_omniroute_config():
    """Return the OmniRoute provider config, or None when not configured.

    The API key is read from the OMNIROUTE_API_KEY environment variable
    (e.g. set in .env, which is git-ignored) and is never hardcoded.
    """
    api_key = os.getenv("OMNIROUTE_API_KEY")
    if not api_key:
        return None
    return {
        "base_url": os.getenv("OMNIROUTE_BASE_URL", OMNIROUTE_BASE_URL_DEFAULT),
        "model": os.getenv("OMNIROUTE_MODEL", OMNIROUTE_MODEL_DEFAULT),
        "api_key": api_key,
    }


def omniroute_is_available():
    """Return True only when OmniRoute is configured, reachable, and authenticated.

    Never raises: missing config, an unreachable gateway, or an unauthenticated
    response all resolve to False so callers can fall back to llama3.2:3b or
    deferred execution.
    """
    config = get_omniroute_config()
    if not config:
        return False
    try:
        resp = requests.get(
            f"{config['base_url'].rstrip('/')}{OMNIROUTE_MODELS_ENDPOINT}",
            headers={"Authorization": f"Bearer {config['api_key']}"},
            timeout=5,
        )
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False


def omniroute_is_available_cached():
    """Like omniroute_is_available(), but cached for a short TTL.

    The result is reused for OMNIROUTE_AVAILABILITY_TTL_SECONDS so that routing
    many tasks in a row does not probe the gateway repeatedly within the same
    window. Never raises; stale failures behave exactly like the uncached probe.
    """
    now = time.monotonic()
    if now - _availability_cache["checked_at"] < OMNIROUTE_AVAILABILITY_TTL_SECONDS:
        return _availability_cache["available"]

    available = omniroute_is_available()
    _availability_cache["checked_at"] = now
    _availability_cache["available"] = available
    return available


def reset_omniroute_availability_cache():
    """Drop the cached availability result (primarily for tests)."""
    _availability_cache["available"] = False
    _availability_cache["checked_at"] = 0.0


def get_omniroute_hermes_provider_config():
    """Execution-provider handoff config for the Hermes child process.

    Returns a dict describing how to address OmniRoute from the Hermes CLI, or
    None when OmniRoute is not configured:

        {
            "provider_id": "omniroute",          # Hermes providers: entry id
            "base_url": "http://127.0.0.1:20128/v1",
            "api_key_env": "OMNIROUTE_API_KEY",  # env var NAME, never the value
            "model": "opencode-zen/nemotron-3.5-lightning-free",
        }

    The credential VALUE is never returned or persisted: the Hermes child reads
    it at runtime from ``api_key_env`` in the inherited process environment.
    """
    cfg = get_omniroute_config()
    if cfg is None:
        return None
    return {
        "provider_id": OMNIROUTE_HERMES_PROVIDER_ID,
        "base_url": cfg["base_url"],
        "api_key_env": OMNIROUTE_API_KEY_ENV_NAME,
        "model": cfg["model"],
    }