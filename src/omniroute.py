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
OMNIROUTE_MODEL_DEFAULT = "auto/coding:free"
OMNIROUTE_MODELS_ENDPOINT = "/models"

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