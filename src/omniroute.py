"""Optional OmniRoute provider layer for heavier reasoning tasks.

OmniRoute exposes an OpenAI-compatible gateway on the local machine that Radar
can use as an optional heavier-reasoning provider. It is strictly optional:
default/lightweight tasks keep using llama3.2:3b via Ollama, and OmniRoute is
only addressed when it is configured (API key present) and authenticated.

Everything here fails safe: missing config, an unreachable gateway, or an
unauthenticated response resolve to None/False so callers can fall back to the
existing 3B default or deferred execution.

No task routing happens in this module yet; it only resolves and validates the
provider so a later step can route heavy work to it.
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

OMNIROUTE_BASE_URL_DEFAULT = "http://127.0.0.1:20128/v1"
OMNIROUTE_MODEL_DEFAULT = "auto/coding:free"
OMNIROUTE_MODELS_ENDPOINT = "/models"


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