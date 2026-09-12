from src.hermes_agent import (
    verify_local_provider,
    get_issue_context,
    list_local_models,
    select_local_model,
)
from src.resource_manager import check_resources_for_hermes, get_available_memory_mb


def get_hermes_execution_plan():
    try:
        verify_local_provider()
    except Exception as exc:
        return False, None, f"Hermes unavailable: {exc}"

    resources_ok, resource_msg = check_resources_for_hermes()

    if resources_ok:
        return True, "llama3.2:3b", "Hermes execution validated with llama3.2:3b."

    try:
        selected_model = select_local_model(
            get_available_memory_mb(),
            list_local_models(),
        )
    except Exception as exc:
        return False, None, f"Hermes model selection failed: {exc}"

    if selected_model == "llama3.2:3b":
        return True, "llama3.2:3b", "Hermes execution validated with llama3.2:3b."

    return False, None, resource_msg


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
