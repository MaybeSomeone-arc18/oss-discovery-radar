"""Dashboard Phase 5A: read-only implementation lifecycle visibility.

Derives a normalized lifecycle snapshot for a specific issue URL entirely from
EXISTING local state:

* the ``issues`` table (lifecycle_status, communication_status, flags ...)
* the per-issue report/package artifacts under ``workspaces/.../reports/``
* the audit log (per-issue timestamps and failure messages)

This module stores nothing, writes nothing, performs no GitHub access, and
does not create a parallel state system: it only normalizes what the rest of
the project already records.

Normalized stages (requirement 4):
    RESEARCH, COMMUNICATION, PLAN, IMPLEMENTATION, TESTS, REVIEW, SUBMISSION,
    COMPLETED, BLOCKED, FAILED

PROGRESSIVE_STAGES are the timeline steps; the last three are terminal
conditions derived with highest priority from existing state.
"""

from datetime import datetime
from pathlib import Path

from src.database import get_connection
from src.hermes_agent import get_issue_context_by_url
from src.workspace_manager import WORKSPACES_ROOT

PROGRESSIVE_STAGES = (
    "RESEARCH",
    "COMMUNICATION",
    "PLAN",
    "IMPLEMENTATION",
    "TESTS",
    "REVIEW",
    "SUBMISSION",
)

COMPLETED = "COMPLETED"
BLOCKED = "BLOCKED"
FAILED = "FAILED"

STAGE_LABELS = {
    "RESEARCH": "Research",
    "COMMUNICATION": "Communication",
    "PLAN": "Plan",
    "IMPLEMENTATION": "Implementation",
    "TESTS": "Tests",
    "REVIEW": "Review",
    "SUBMISSION": "Submission",
    COMPLETED: "Completed",
    BLOCKED: "Blocked",
    FAILED: "Failed",
}

# Existing eligibility_status values that mean "do not pursue".
BLOCKING_ELIGIBILITY = {
    "BLOCKED",
    "SOLVED",
    "DUPLICATE",
    "BLOCKED_STUDENT_WORK_REPO",
    "BLOCKED_RELATED_PR",
    "LIKELY_SOLVED",
}

# audit_logs actions that represent an autonomous run of the local pipeline.
_RUN_ACTIONS = ("autonomous_run", "autonomous_retry")

# Top-level selection-preflight reports written by main.py (CWD-relative).
PREFLIGHT_ROOT = Path("reports")


def _issue_dirs(issue):
    org = issue.get("org_slug") or "unknown"
    repo = issue.get("repo_name") or ""
    repo_short = repo.split("/")[1] if "/" in repo else (repo or "unknown")
    issue_number = issue.get("issue_number") or 0

    base = WORKSPACES_ROOT / org / repo_short
    reports_dir = base / "reports" / str(issue_number)
    worktree_path = base / "worktrees" / str(issue_number)
    # Top-level selection preflight written by main.py.
    preflight_path = PREFLIGHT_ROOT / str(issue_number) / "first_contribution_preflight.md"
    return reports_dir, worktree_path, preflight_path


def _recent_audit(issue_number, limit=10):
    if not issue_number:
        return []
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT timestamp, action, result, message
            FROM audit_logs
            WHERE issue_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (issue_number, int(limit)),
        ).fetchall()
    return [
        {"timestamp": r[0], "action": r[1], "result": r[2], "message": r[3]}
        for r in rows
    ]


def _read_head(path, limit=2048):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def _parse_ts(value):
    if value is None:
        return None
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _last_updated(issue, reports_dir, audit):
    """Best available local timestamp: newest audit log entry, report file
    modification time, or communication approval timestamp."""
    candidates = []
    approved_at = issue.get("communication_approved_at")
    if approved_at:
        candidates.append(approved_at)
    for entry in audit:
        if entry.get("timestamp"):
            candidates.append(entry["timestamp"])
    if reports_dir.exists():
        for name in (
            "research.md",
            "plan.md",
            "summary.md",
            "review.md",
            "implementation.md",
            "patch.diff",
            "final-report.md",
            "base_commit.txt",
        ):
            path = reports_dir / name
            try:
                if path.exists():
                    candidates.append(datetime.fromtimestamp(path.stat().st_mtime))
            except OSError:
                pass

    best = None
    for candidate in candidates:
        parsed = candidate if isinstance(candidate, datetime) else _parse_ts(candidate)
        if parsed is None:
            continue
        if best is None or parsed > best:
            best = parsed
    if best is None:
        return None
    return best.strftime("%Y-%m-%d %H:%M:%S")


def _collect_evidence(issue, reports_dir, worktree_path):
    has = lambda name: (reports_dir / name).exists()
    comm_status = issue.get("communication_status") or ""
    comm_recommendation = issue.get("communication_recommendation")
    research_done = bool(issue.get("researched")) or has("research.md")
    communication_done = (
        comm_status in ("APPROVED", "COMMENT_SENT", "NOT_REQUIRED") and research_done
    )
    return {
        "lifecycle_status": issue.get("lifecycle_status"),
        "eligibility_status": issue.get("eligibility_status"),
        "dismissal_reason": issue.get("dismissal_reason"),
        "research_done": research_done,
        "communication_started": research_done
        and (bool(comm_recommendation) or comm_status not in ("", "REVIEW_REQUIRED")),
        "communication_done": communication_done,
        "comm_status": comm_status,
        "comm_recommendation": comm_recommendation,
        "plan_done": bool(issue.get("planned")) or has("plan.md"),
        "implementation_started": worktree_path.exists()
        or issue.get("lifecycle_status") == "IN_PROGRESS",
        "implementation_done": bool(issue.get("implemented")) or has("patch.diff"),
        "tests_done": has("summary.md"),
        "review_done": has("review.md"),
        "package_done": has("final-report.md"),
        "submitted": bool(issue.get("submitted"))
        or issue.get("lifecycle_status") == "SUBMITTED",
        "merged": bool(issue.get("merged")) or issue.get("lifecycle_status") == "MERGED",
        "dismissed": bool(issue.get("dismissed"))
        or issue.get("lifecycle_status") == "DISMISSED",
    }


def _latest_run_audit(audit):
    for entry in audit:
        if entry.get("action") in _RUN_ACTIONS:
            return entry
    return None


def _terminal(issue, evidence, audit, reports_dir):
    """Return (stage, reason, completed_flavor) when a terminal condition is
    reached from existing state; otherwise (None, None, None)."""
    # 1. Human-declared completion / submission has the highest authority.
    if evidence["submitted"] or evidence["merged"]:
        flavor = "merged" if evidence["merged"] else "submitted"
        return COMPLETED, None, flavor

    # 2. Dismissed -> terminal blocked state (existing human decision).
    if evidence["dismissed"]:
        return (
            BLOCKED,
            evidence["dismissal_reason"] or "Opportunity dismissed by the user.",
            None,
        )

    # 3. Blocked conditions: work cannot proceed until a human decision.
    if evidence["comm_status"] == "REJECTED":
        return BLOCKED, "Communication recommendation was rejected (human decision).", None
    eligibility = evidence["eligibility_status"]
    if eligibility in BLOCKING_ELIGIBILITY:
        return BLOCKED, f"Issue is ineligible: {eligibility}.", None
    latest_run = _latest_run_audit(audit)
    if (
        latest_run
        and latest_run["result"] == "failed"
        and "Communication gate blocked" in (latest_run["message"] or "")
    ):
        return BLOCKED, latest_run["message"], None

    # 4. Failed conditions (local implementation pipeline reported failure).
    if evidence["lifecycle_status"] == "IMPLEMENTATION_FAILED":
        return FAILED, "Implementation failed locally (see summary.md / review.md).", None
    package_text = _read_head(reports_dir / "final-report.md")
    if "IMPLEMENTATION FAILED" in package_text:
        return (
            FAILED,
            "Implementation validation failed; package marked "
            "'IMPLEMENTATION FAILED - DO NOT SUBMIT'.",
            None,
        )
    summary_text = _read_head(reports_dir / "summary.md")
    if "**Status:** FAILED" in summary_text:
        return FAILED, "Implementation validation failed (see summary.md).", None
    if latest_run and latest_run["result"] == "failed":
        return FAILED, latest_run["message"] or "Autonomous run failed.", None

    return None, None, None


def _timeline(stage, evidence):
    done = {
        "RESEARCH": evidence["research_done"],
        "COMMUNICATION": evidence["communication_done"],
        "PLAN": evidence["plan_done"],
        "IMPLEMENTATION": evidence["implementation_done"],
        "TESTS": evidence["tests_done"],
        "REVIEW": evidence["review_done"],
        "SUBMISSION": evidence["package_done"],
    }
    items = []
    for index, name in enumerate(PROGRESSIVE_STAGES):
        if stage in (COMPLETED, BLOCKED, FAILED):
            state = "done" if done[name] else ("active" if name == stage else "pending")
        elif done[name] and name != stage:
            state = "done"
        elif name == stage:
            state = "active"
        else:
            state = "pending"
        items.append({"stage": name, "label": STAGE_LABELS[name], "state": state})
    return items


def _human_action(stage, evidence):
    """(human_action_required, hint) derived from existing gate state."""
    if stage == "COMMUNICATION":
        comm = evidence["comm_status"]
        if comm == "REVIEW_REQUIRED" and evidence["comm_recommendation"]:
            return (
                True,
                "Waiting for human approval of the suggested maintainer comment.",
            )
        if comm == "APPROVED":
            return (
                True,
                "Communication approved \u2014 mark the comment as sent to start local work.",
            )
    if stage == "SUBMISSION":
        return (
            True,
            "Contribution package ready \u2014 review the patch and submit manually "
            "(local-only; nothing is sent to GitHub automatically).",
        )
    if (
        stage == "PLAN"
        and evidence["research_done"]
        and evidence["communication_done"]
    ):
        return (
            True,
            "Ready to start local work \u2014 research and communication are done.",
        )
    return False, None


def _ui_state(stage, evidence, human_action_required):
    if stage == COMPLETED:
        return "completed"
    if stage == BLOCKED:
        return "blocked"
    if stage == FAILED:
        return "failed"
    if human_action_required:
        return "waiting_human"
    if not evidence["research_done"] and not evidence["communication_started"]:
        return "idle"
    return "running"


def _status_text(stage, terminal_reason, completed_flavor, evidence, human_hint):
    if stage == COMPLETED:
        return (
            "Completed \u2014 merged upstream."
            if completed_flavor == "merged"
            else "Completed \u2014 submitted locally; awaiting upstream merge."
        )
    if stage == BLOCKED:
        return f"Blocked \u2014 {terminal_reason}"
    if stage == FAILED:
        return f"Failed \u2014 {terminal_reason}"
    if human_hint:
        return human_hint
    return {
        "RESEARCH": "No local work started yet.",
        "COMMUNICATION": "Communication stage in progress.",
        "PLAN": "Planning in progress.",
        "IMPLEMENTATION": "Implementation in progress \u2014 local changes and "
        "tests run automatically.",
        "TESTS": "Tests in progress.",
        "REVIEW": "Review in progress.",
        "SUBMISSION": "Contribution package ready for human review and submission.",
    }.get(stage, stage)


def _existing_paths(reports_dir, worktree_path, preflight_path):
    paths = {}
    for key, path in (
        ("research", reports_dir / "research.md"),
        ("plan", reports_dir / "plan.md"),
        ("implementation", reports_dir / "implementation.md"),
        ("summary", reports_dir / "summary.md"),
        ("review", reports_dir / "review.md"),
        ("patch", reports_dir / "patch.diff"),
        ("package", reports_dir / "final-report.md"),
        ("preflight", preflight_path),
    ):
        if path.exists():
            paths[key] = str(path)
    if worktree_path.exists():
        paths["worktree"] = str(worktree_path)
    return paths


def _snapshot(
    issue_url,
    issue,
    stage,
    terminal_reason,
    completed_flavor,
    evidence,
    audit,
    reports_dir,
    worktree_path,
    preflight_path,
):
    human_required, human_hint = _human_action(stage, evidence)
    return {
        "url": issue_url,
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
        "state": _ui_state(stage, evidence, human_required),
        "status": _status_text(
            stage, terminal_reason, completed_flavor, evidence, human_hint
        ),
        "human_action_required": human_required,
        "human_action_hint": human_hint,
        "last_updated": _last_updated(issue, reports_dir, audit),
        "blocked_reason": terminal_reason if stage == BLOCKED else None,
        "failed_reason": terminal_reason if stage == FAILED else None,
        "timeline": _timeline(stage, evidence),
        "paths": _existing_paths(reports_dir, worktree_path, preflight_path),
    }


def get_implementation_status(issue_url):
    """Return the normalized lifecycle snapshot for an issue URL, or None when
    the issue is unknown. Pure read of local DB + workspaces artifacts."""
    issue = get_issue_context_by_url(issue_url)
    if not issue:
        return None

    reports_dir, worktree_path, preflight_path = _issue_dirs(issue)
    audit = _recent_audit(issue.get("issue_number"))
    evidence = _collect_evidence(issue, reports_dir, worktree_path)

    stage, terminal_reason, completed_flavor = _terminal(
        issue, evidence, audit, reports_dir
    )
    if stage in (COMPLETED, BLOCKED, FAILED):
        return _snapshot(
            issue_url, issue, stage, terminal_reason, completed_flavor,
            evidence, audit, reports_dir, worktree_path, preflight_path,
        )

    # Progressive stage: the first pipeline stage that is not yet done.
    done = {
        "RESEARCH": evidence["research_done"],
        "COMMUNICATION": evidence["communication_done"],
        "PLAN": evidence["plan_done"],
        "IMPLEMENTATION": evidence["implementation_done"],
        "TESTS": evidence["tests_done"],
        "REVIEW": evidence["review_done"],
        "SUBMISSION": evidence["package_done"],
    }
    for index, name in enumerate(PROGRESSIVE_STAGES):
        if not done[name]:
            stage = name
            break
    else:
        stage = PROGRESSIVE_STAGES[-1]

    return _snapshot(
        issue_url, issue, stage, None, None,
        evidence, audit, reports_dir, worktree_path, preflight_path,
    )