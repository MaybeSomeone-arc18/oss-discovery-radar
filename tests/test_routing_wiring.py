"""Focused tests for the production wiring of the task-aware routing layer.

Proves the routing layer (src.autonomous_guard.select_execution_provider +
src.omniroute) is wired at the explicit reasoning-heavy decision points only:
  a. communication/maintainer analysis invokes the heavy route
  b. difficult implementation planning invokes the heavy route
  c. final code review invokes the heavy route
  d. ordinary research remains lightweight
  e. no other existing callers accidentally become heavy
"""

import pytest
from unittest.mock import patch

from src.autonomous_guard import validate_hermes_execution
from src.communication_gate import generate_communication_recommendation
from src.hermes_agent import plan, research
from src.implementer import generate_reports, implement

ISSUE_BASE = {
    "url": "http://test/5",
    "org_slug": "test",
    "repo_name": "test/repo",
    "issue_number": 5,
    "title": "Test issue",
    "body_preview": "Body",
}

RESEARCH_FIELDS = {
    **ISSUE_BASE,
    "labels": "bug",
    "activity_status": "ACTIVE",
    "contribution_value_score": 10,
    "gsoc_preparation_score": 50,
    "opportunity_score": 80,
}

# --- a. communication/maintainer analysis -> heavy --------------------------


def test_communication_analysis_invokes_heavy_route(monkeypatch, tmp_path):
    calls = []

    def fake_plan(task_type="lightweight"):
        calls.append(task_type)
        return (True, "auto/coding:free", "validated")

    monkeypatch.setattr(
        "src.communication_gate.get_hermes_execution_plan", fake_plan
    )
    monkeypatch.setattr(
        "src.communication_gate.get_issue_context",
        lambda url: dict(RESEARCH_FIELDS, url=url),
    )
    monkeypatch.setattr(
        "src.communication_gate.get_reports_dir",
        lambda org, repo, issue: tmp_path,
    )
    (tmp_path / "research.md").write_text(
        "## Questions for Maintainers\nQ\n"
        "## Recommended Next Step\nS\n"
        "## Constraints\nC\n"
        "## Unknowns\nU\n"
    )

    captured = {}

    def fake_run(prompt, **kwargs):
        captured.update(kwargs)
        return (
            "## Recommendation\nNO_CLARIFICATION_NEEDED\n\n"
            "## Suggested Reply\nNo contact needed.\n\n"
            "## Reason\nThe next step is unambiguous.\n\n"
            "## Questions\n- None\n\n"
            "## Implementation Gate\nMAY_PROCEED"
        )

    monkeypatch.setattr("src.communication_gate.run_hermes_oneshot", fake_run)
    monkeypatch.setattr(
        "src.communication_gate.set_communication_recommendation",
        lambda *args, **kwargs: None,
    )

    result = generate_communication_recommendation(
        "http://test/5"
    )

    assert calls == ["heavy"]
    assert captured["model"] == "auto/coding:free"
    assert result["status"] == "NOT_REQUIRED"


# --- b. difficult implementation planning -> heavy ---------------------------


def test_difficult_planning_invokes_heavy_route(monkeypatch, tmp_path):
    calls = []

    def fake_plan(task_type="lightweight"):
        calls.append(task_type)
        return (True, "auto/coding:free", "validated")

    monkeypatch.setattr(
        "src.autonomous_guard.get_hermes_execution_plan", fake_plan
    )
    monkeypatch.setattr(
        "src.hermes_agent.get_issue_context",
        lambda issue_id: dict(ISSUE_BASE, engineering_depth="SUBSTANTIAL"),
    )
    monkeypatch.setattr(
        "src.hermes_agent.get_reports_dir",
        lambda org, repo, issue: tmp_path,
    )
    (tmp_path / "research.md").write_text("[FACT] Research")
    monkeypatch.setattr(
        "src.hermes_agent.run_hermes_oneshot",
        lambda prompt, **kwargs: "[FACT] Plan",
    )

    assert plan(5) is True
    assert calls == ["heavy"]
    assert (tmp_path / "plan.md").read_text() == "[FACT] Plan"


def test_trivial_planning_stays_lightweight(monkeypatch, tmp_path):
    calls = []

    def fake_plan(task_type="lightweight"):
        calls.append(task_type)
        return (True, "llama3.2:3b", "validated")

    monkeypatch.setattr(
        "src.autonomous_guard.get_hermes_execution_plan", fake_plan
    )
    monkeypatch.setattr(
        "src.hermes_agent.get_issue_context",
        lambda issue_id: dict(ISSUE_BASE, engineering_depth="TRIVIAL"),
    )
    monkeypatch.setattr(
        "src.hermes_agent.get_reports_dir",
        lambda org, repo, issue: tmp_path,
    )
    (tmp_path / "research.md").write_text("[FACT] Research")
    monkeypatch.setattr(
        "src.hermes_agent.run_hermes_oneshot",
        lambda prompt, **kwargs: "[FACT] Plan",
    )

    assert plan(5) is True
    assert calls == ["lightweight"]


# --- c. final code review -> heavy ------------------------------------------


def test_final_review_invokes_heavy_route(monkeypatch, tmp_path):
    calls = []

    def fake_plan(task_type="lightweight"):
        calls.append(task_type)
        return (True, "auto/coding:free", "validated")

    monkeypatch.setattr(
        "src.implementer.get_hermes_execution_plan", fake_plan
    )
    run_calls = []

    def fake_run(prompt, **kwargs):
        run_calls.append(kwargs)
        return "[FACT] Review"

    monkeypatch.setattr("src.implementer.run_hermes_oneshot", fake_run)

    generate_reports(
        1,
        "worktree",
        tmp_path,
        [{"framework": "pytest", "result": {"success": True}}],
        "diff",
        True,
    )

    assert calls == ["heavy"]
    # First Hermes call is the final code review, on the heavy model.
    assert run_calls[0]["model"] == "auto/coding:free"
    assert (tmp_path / "review.md").read_text() == "[FACT] Review"


def test_final_review_falls_back_to_default_when_heavy_unavailable(
    monkeypatch, tmp_path
):
    calls = []

    def fake_plan(task_type="lightweight"):
        calls.append(task_type)
        return (False, None, "deferred")

    monkeypatch.setattr(
        "src.implementer.get_hermes_execution_plan", fake_plan
    )
    run_calls = []

    def fake_run(prompt, **kwargs):
        run_calls.append(kwargs)
        return "[FACT] Review"

    monkeypatch.setattr("src.implementer.run_hermes_oneshot", fake_run)

    generate_reports(
        1,
        "worktree",
        tmp_path,
        [{"framework": "pytest", "result": {"success": True}}],
        "diff",
        True,
    )

    assert calls == ["heavy"]
    # Routing deferred -> review falls back to the default local model.
    assert run_calls[0]["model"] is None
    assert (tmp_path / "review.md").read_text() == "[FACT] Review"


# --- d. ordinary research remains lightweight --------------------------------


def test_ordinary_research_stays_lightweight(monkeypatch, tmp_path):
    calls = []

    def fake_plan(**kwargs):
        calls.append(kwargs)
        return (True, "llama3.2:3b", "validated")

    monkeypatch.setattr(
        "src.autonomous_guard.get_hermes_execution_plan", fake_plan
    )
    monkeypatch.setattr(
        "src.hermes_agent.get_issue_context",
        lambda issue_id: dict(RESEARCH_FIELDS),
    )
    monkeypatch.setattr(
        "src.hermes_agent.get_repo_analysis", lambda repo: None
    )
    monkeypatch.setattr(
        "src.hermes_agent.get_reports_dir",
        lambda org, repo, issue: tmp_path,
    )
    monkeypatch.setattr(
        "src.hermes_agent.run_hermes_oneshot",
        lambda prompt, **kwargs: "[FACT] Research",
    )

    assert research(5) is True
    # research() calls the plan with no task_type -> default lightweight.
    assert calls == [{}]


# --- e. no other existing callers accidentally become heavy ------------------


def test_validate_hermes_execution_stays_lightweight(monkeypatch):
    calls = []

    def fake_plan(**kwargs):
        calls.append(kwargs)
        return (True, "llama3.2:3b", "validated")

    monkeypatch.setattr(
        "src.autonomous_guard.get_hermes_execution_plan", fake_plan
    )

    ok, reason = validate_hermes_execution()

    assert ok is True
    assert "validated" in reason
    assert calls == [{}]


def test_implement_preflight_stays_lightweight(monkeypatch, tmp_path):
    calls = []

    def fake_plan(**kwargs):
        calls.append(kwargs)
        return (True, "llama3.2:3b", "validated")

    monkeypatch.setattr(
        "src.implementer.get_hermes_execution_plan", fake_plan
    )
    monkeypatch.setattr(
        "src.implementer.get_issue_context",
        lambda issue_id: dict(ISSUE_BASE, issue_number=999),
    )
    monkeypatch.setattr(
        "src.implementer.requests.get",
        lambda *args, **kwargs: type(
            "Response",
            (),
            {"status_code": 200, "json": lambda self: {"title": "Test issue"}},
        )(),
    )
    monkeypatch.setattr(
        "src.implementer.get_reports_dir", lambda *args: tmp_path
    )
    # No plan.md -> implement() returns right after the execution preflight.

    success, test_results, diff_stat = implement(999)

    assert success is False
    assert test_results is None
    assert calls == [{}]