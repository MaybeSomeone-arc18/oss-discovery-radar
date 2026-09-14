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
    get_omniroute_hermes_provider_config,
    omniroute_is_available_cached,
)

TASK_TYPES = ("lightweight", "heavy", "implementation")

# Models that must never be automatically selected by routing, even when they
# are configured as the OmniRoute model.
BLOCKED_MODELS = ("qwen3.5:9b",)

# Implementation requires a provider that actually executes tool calls (file
# edits, terminal commands) inside the isolated worktree. llama3.2:3b is the
# safe local default for text generation only, so it must never be selected
# for implementation.
TOOL_REQUIRED_TASK_TYPES = ("implementation",)
TOOL_REQUIRED_UNAVAILABLE_REASON = (
    "Implementation requires a tool-capable execution provider; "
    "no suitable provider is currently available."
)


def select_execution_provider(
    task_type,
    available_memory_mb,
    models=None,
    resources_ok=False,
    resource_msg=None,
    omniroute_available=None,
):
    """Route a Hermes task to an execution provider (llama3.2:3b or OmniRoute).

    Task taxonomy (TASK_TYPES):
      * "lightweight" -- llama3.2:3b stays the default; OmniRoute is never
        probed or used.
      * "heavy" -- text-generation reasoning tasks (communication analysis,
        planning, final review). OmniRoute (auto/coding:free) is used when
        available; otherwise fall back to llama3.2:3b when local resources
        permit; otherwise defer.
      * "implementation" -- tool-required tasks that must actually edit files
        inside the isolated worktree. OmniRoute is used when available;
        otherwise the task is DEFERRED with a clear reason. llama3.2:3b is
        never selected here because it is not a proven tool-calling executor
        in this execution mode.

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

    requires_tools = task_type in TOOL_REQUIRED_TASK_TYPES

    # Lightweight tasks never touch OmniRoute (not even a probe); only
    # explicitly heavy/tool-required tasks may route to it.
    if task_type in ("heavy", "implementation") and omniroute_available is None:
        omniroute_available = omniroute_is_available_cached()

    if task_type in ("heavy", "implementation") and omniroute_available:
        config = get_omniroute_config()
        omniroute_model = (
            config["model"] if config else OMNIROUTE_MODEL_DEFAULT
        )
        if omniroute_model not in BLOCKED_MODELS:
            reason = (
                "Implementation routed to OmniRoute provider (tool-capable)."
                if requires_tools
                else "Heavy task routed to OmniRoute provider."
            )
            return True, omniroute_model, reason

    if requires_tools:
        return False, None, TOOL_REQUIRED_UNAVAILABLE_REASON

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


def _compute_hermes_execution_plan(task_type="lightweight"):
    """Full execution decision: (ok, model, reason, provider_config).

    Shared planner behind get_hermes_execution_plan() (public 3-tuple contract)
    and get_hermes_execution_handoff() (4-tuple with the Hermes child handoff).
    Routing policy is identical to the historical decision point.
    """
    try:
        verify_local_provider()
    except Exception as exc:
        return False, None, f"Hermes unavailable: {exc}", None

    resources_ok, resource_msg = check_resources_for_hermes()

    # Probe once here so the routing decision and the handoff config below agree
    # on the SAME availability result (the probe itself is TTL-cached).
    omniroute_available = None
    if task_type in ("heavy", "implementation"):
        omniroute_available = omniroute_is_available_cached()

    ok, model, reason = select_execution_provider(
        task_type,
        get_available_memory_mb(),
        resources_ok=resources_ok,
        resource_msg=resource_msg,
        omniroute_available=omniroute_available,
    )

    # Attach the explicit execution-provider handoff only when the decision
    # actually routed the task to OmniRoute (never derived from the model name).
    provider_config = None
    if ok and omniroute_available:
        provider_config = get_omniroute_hermes_provider_config()
    return ok, model, reason, provider_config


def get_hermes_execution_plan(task_type="lightweight"):
    """Resolve (ok, model, reason) for a Hermes task.

    Contract unchanged: callers receive the routed model plus a human-readable
    reason, or (False, None, reason) when the task must be deferred.
    """
    ok, model, reason, _provider_config = _compute_hermes_execution_plan(
        task_type
    )
    return ok, model, reason


def get_hermes_execution_handoff(task_type="lightweight"):
    """Like get_hermes_execution_plan, plus the Hermes child handoff config.

    Returns (ok, model, reason, provider_config). ``provider_config`` is the
    explicit execution-provider configuration ({provider_id, base_url,
    api_key_env, model}) when the task was routed to OmniRoute, else None —
    so tool-required implementation can hand the full provider to
    run_hermes_oneshot() instead of only the model string.
    """
    return _compute_hermes_execution_plan(task_type)


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
