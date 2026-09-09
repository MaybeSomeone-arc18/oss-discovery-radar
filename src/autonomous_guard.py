from src.hermes_agent import verify_local_provider, get_issue_context
from src.resource_manager import check_resources_for_hermes


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

    try:
        verify_local_provider()
    except Exception as exc:
        return False, f"Hermes unavailable: {exc}"

    resources_ok, resource_msg = check_resources_for_hermes()
    if not resources_ok:
        return False, resource_msg

    return True, "Autonomous run validated."
