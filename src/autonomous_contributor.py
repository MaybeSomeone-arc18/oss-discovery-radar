from pathlib import Path

from src.hermes_agent import research, plan, get_issue_context, get_reports_dir
from src.implementer import implement


def _run_pipeline(issue_id: int) -> tuple:
    issue = get_issue_context(issue_id)
    if not issue:
        raise RuntimeError(f"Issue {issue_id} not found.")

    org = issue["org_slug"]
    repo = issue["repo_name"].split("/")[1]
    reports_dir = get_reports_dir(org, repo, issue_id)

    research(issue_id)
    research_file = reports_dir / "research.md"
    if not research_file.exists():
        raise RuntimeError("Research phase did not produce research.md.")

    plan(issue_id)
    plan_file = reports_dir / "plan.md"
    if not plan_file.exists():
        raise RuntimeError("Plan phase did not produce plan.md.")

    success, test_results, diff_stat = implement(issue_id)

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
