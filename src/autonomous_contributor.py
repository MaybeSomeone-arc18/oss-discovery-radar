from pathlib import Path

from src.hermes_agent import research, plan, get_issue_context, get_issue_context_by_url, get_reports_dir
from src.implementer import implement
from src.communication_gate import generate_communication_recommendation
from src.opportunity_manager import communication_allows_implementation, get_communication_state
from src.autonomous_guard import get_hermes_execution_plan, validate_autonomous_run_by_url


def _run_pipeline(issue_id_or_url) -> tuple:
    if isinstance(issue_id_or_url, str) and issue_id_or_url.startswith("http"):
        issue = get_issue_context_by_url(issue_id_or_url)
    else:
        issue = get_issue_context(issue_id_or_url)

    if not issue:
        raise RuntimeError(f"Issue {issue_id_or_url} not found.")

    issue_id = issue["issue_number"]
    org = issue["org_slug"]
    repo = issue["repo_name"].split("/")[1]
    reports_dir = get_reports_dir(org, repo, issue_id)

    if not research(issue_id_or_url):
        raise RuntimeError("Research phase failed.")

    research_file = reports_dir / "research.md"
    if not research_file.exists():
        raise RuntimeError("Research phase reported success but did not produce research.md.")

    communication = generate_communication_recommendation(issue["url"])
    communication_state = get_communication_state(issue["url"])

    if not communication_allows_implementation(issue["url"]):
        status = communication_state["communication_status"] if communication_state else "UNKNOWN"
        raise RuntimeError(
            f"Communication gate blocked implementation: status={status}. "
            "Human review/approval is required before planning or implementation."
        )

    if not plan(issue_id_or_url):
        raise RuntimeError("Plan phase failed.")

    plan_file = reports_dir / "plan.md"
    if not plan_file.exists():
        raise RuntimeError("Plan phase reported success but did not produce plan.md.")

    success, test_results, diff_stat = implement(issue_id_or_url)

    summary_file = reports_dir / "summary.md"
    if not summary_file.exists():
        raise RuntimeError("Implementation phase did not produce summary.md.")

    return summary_file, success, test_results, diff_stat

from src.autonomous_guard import validate_autonomous_run
from src.contribution_package import generate_contribution_package
from src.run_log import log_event


def run_autonomous(issue_id: int) -> Path:
    ok, reason = validate_autonomous_run(issue_id)
    if not ok:
        log_event("autonomous_run", "skipped", reason, issue_id=issue_id)
        print(f"Autonomous run skipped: {reason}")
        return None

    log_event(
        "autonomous_run",
        "started",
        "Autonomous contribution started",
        issue_id=issue_id,
    )

    try:
        summary_file, success, test_results, diff_stat = _run_pipeline(issue_id)
        issue = get_issue_context(issue_id)
        org = issue["org_slug"]
        repo = issue["repo_name"].split("/")[1]
        reports_dir = get_reports_dir(org, repo, issue_id)

        package = generate_contribution_package(
            reports_dir,
            issue_id,
            success=success,
            test_results=test_results,
            diff_stat=diff_stat,
        )

        log_event(
            "autonomous_run",
            "success",
            f"Autonomous contribution completed: {package}",
            issue_id=issue_id,
        )
        return package
    except Exception as exc:
        log_event(
            "autonomous_run",
            "failed",
            str(exc),
            issue_id=issue_id,
        )
        raise




def run_best_autonomous():
    from src.contribution_engine import get_ready_first_contribution_candidates

    candidates = get_ready_first_contribution_candidates()

    if not candidates:
        print("No READY_NOW autonomous candidate available.")
        return None

    candidate = candidates[0]
    issue_id = candidate["num"]

    print(
        f"Selected autonomous candidate: #{issue_id} "
        f"({candidate['repo']}, score {candidate['score']})"
    )

    return run_autonomous(issue_id)


def run_autonomous_by_url(issue_url: str) -> Path:
    issue = get_issue_context_by_url(issue_url)
    if not issue:
        log_event(
            "autonomous_retry",
            "skipped",
            "Issue URL not found.",
        )
        print(f"Autonomous retry skipped: issue URL not found: {issue_url}")
        return None

    issue_id = issue["issue_number"]

    valid, validation_reason = validate_autonomous_run_by_url(issue_url)
    if not valid:
        log_event(
            "autonomous_retry",
            "skipped" if "READY_NOW" not in validation_reason else "deferred",
            validation_reason,
            issue_id=issue_id,
        )
        print(f"Autonomous retry skipped/deferred: {validation_reason}")
        return None

    execution_ok, selected_model, execution_reason = get_hermes_execution_plan()
    if not execution_ok:
        log_event(
            "autonomous_retry",
            "deferred",
            execution_reason,
            issue_id=issue_id,
        )
        print(f"Autonomous retry deferred: {execution_reason}")
        return None

    log_event(
        "autonomous_retry",
        "started",
        f"Retrying autonomous contribution with {selected_model}",
        issue_id=issue_id,
    )

    try:
        summary_file, success, test_results, diff_stat = _run_pipeline(issue_url)

        org = issue["org_slug"]
        repo = issue["repo_name"].split("/")[1]
        reports_dir = get_reports_dir(org, repo, issue_id)

        package = generate_contribution_package(
            reports_dir,
            issue_id,
            success=success,
            test_results=test_results,
            diff_stat=diff_stat,
        )

        log_event(
            "autonomous_retry",
            "success",
            f"Autonomous retry completed: {package}",
            issue_id=issue_id,
        )
        return package

    except Exception as exc:
        log_event(
            "autonomous_retry",
            "failed",
            str(exc),
            issue_id=issue_id,
        )
        raise
