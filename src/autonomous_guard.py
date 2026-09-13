from src.hermes_agent import (
    verify_local_provider,
    get_issue_context,
    list_local_models,
    select_local_model,
)
from src.resource_manager import check_resources_for_hermes, get_available_memory_mb
from src.omniroute import (
    OMNIROUTE_MODEL_DEFAULT,
    get_omniroute_config,
    omniroute_is_available_cached,
)

TASK_TYPES = ("lightweight", "heavy")

# Models that must never be automatically selected by routing, even when they
# are configured as the OmniRoute model.
BLOCKED_MODELS = ("qwen3.5:9b",)


def select_execution_provider(
    task_type,
    available_memory_mb,
    models=None,
    resources_ok=False,
    resource_msg=None,
    omniroute_available=None,
):
    """Route a Hermes task to an execution provider (llama3.2:3b or OmniRoute).

    Minimal task taxonomy (TASK_TYPES):
      * "lightweight" -- llama3.2:3b stays the default; OmniRoute is never
        probed or used.
      * "heavy" -- OmniRoute (auto/coding:free) is used when available;
        otherwise fall back to llama3.2:3b when local resources permit;
        otherwise defer.

    qwen3.5:9b is never selected. Returns (ok, model, reason) like
    get_hermes_execution_plan(). `resources_ok`/`resource_msg` carry the result
    of check_resources_for_hermes(); when resources are confirmed OK the local
    model inventory is skipped (verify_local_provider already confirmed
    llama3.2:3b is installed, and the default headroom gate is far above the
    3B memory threshold).
    """
    if task_type not in TASK_TYPES:
        raise ValueError(
            f"Unknown task type {task_type!r}; expected one of {TASK_TYPES}"
        )

    # Lightweight tasks never touch OmniRoute (not even a probe); only
    # explicitly heavy tasks may route to it.
    if task_type == "heavy" and omniroute_available is None:
        omniroute_available = omniroute_is_available_cached()

    if task_type == "heavy" and omniroute_available:
        config = get_omniroute_config()
        omniroute_model = (
            config["model"] if config else OMNIROUTE_MODEL_DEFAULT
        )
        if omniroute_model not in BLOCKED_MODELS:
            return (
                True,
                omniroute_model,
                "Heavy task routed to OmniRoute provider.",
            )

    if resources_ok:
        return True, "llama3.2:3b", "Hermes execution validated with llama3.2:3b."

    try:
        local_model = select_local_model(available_memory_mb, models)
    except Exception as exc:
        return False, None, f"Hermes model selection failed: {exc}"

    if local_model == "llama3.2:3b":
        return True, "llama3.2:3b", "Hermes execution validated with llama3.2:3b."

    if resource_msg:
        return False, None, resource_msg
    return (
        False,
        None,
        f"Insufficient local resources for llama3.2:3b "
        f"(available {available_memory_mb:.0f}MB). Deferring.",
    )


def get_hermes_execution_plan(task_type="lightweight"):
    try:
        verify_local_provider()
    except Exception as exc:
        return False, None, f"Hermes unavailable: {exc}"

    resources_ok, resource_msg = check_resources_for_hermes()

    if not resources_ok:
        try:
            models = list_local_models()
        except Exception as exc:
            return False, None, f"Hermes model selection failed: {exc}"
    else:
        models = None

    return select_execution_provider(
        task_type,
        get_available_memory_mb(),
        models=models,
        resources_ok=resources_ok,
        resource_msg=resource_msg,
    )


def validate_autonomous_run_by_url(issue_url: str):
    from src.hermes_agent import get_issue_context_by_url

    issue = get_issue_context_by_url(issue_url)
    if not issue:
        return False, "Issue not found."

    if issue.get("readiness_status") != "READY_NOW":
        return False, f"Issue is not READY_NOW: {issue.get('readiness_status')}"

    blocked = {
        "BLOCKED",
        "SOLVED",
        "DUPLICATE",
        "BLOCKED_STUDENT_WORK_REPO",
        "BLOCKED_RELATED_PR",
        "LIKELY_SOLVED",
    }
    if issue.get("eligibility_status") in blocked:
        return False, f"Issue is ineligible: {issue.get('eligibility_status')}"

    execution_ok, execution_reason = validate_hermes_execution()
    if not execution_ok:
        return False, execution_reason

    return True, "Autonomous run validated."

def validate_hermes_execution():
    ok, _model, reason = get_hermes_execution_plan()
    return ok, reason


def validate_autonomous_run(issue_id: int):
    issue = get_issue_context(issue_id)
    if not issue:
        return False, "Issue not found."

    if issue.get("readiness_status") != "READY_NOW":
        return False, f"Issue is not READY_NOW: {issue.get('readiness_status')}"

    blocked = {
        "BLOCKED",
        "SOLVED",
        "DUPLICATE",
        "BLOCKED_STUDENT_WORK_REPO",
        "BLOCKED_RELATED_PR",
        "LIKELY_SOLVED",
    }
    if issue.get("eligibility_status") in blocked:
        return False, f"Issue is ineligible: {issue.get('eligibility_status')}"

    execution_ok, execution_reason = validate_hermes_execution()
    if not execution_ok:
        return False, execution_reason

    return True, "Autonomous run validated."
