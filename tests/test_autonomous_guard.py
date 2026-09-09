import pytest

from src.autonomous_guard import validate_autonomous_run


def test_validate_autonomous_run_accepts_ready_issue(monkeypatch):
    monkeypatch.setattr(
        "src.autonomous_guard.get_issue_context",
        lambda issue_id: {
            "readiness_status": "READY_NOW",
            "eligibility_status": "ELIGIBLE",
        },
    )
    monkeypatch.setattr(
        "src.autonomous_guard.verify_local_provider",
        lambda: None,
    )
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (True, "Resources sufficient"),
    )

    ok, reason = validate_autonomous_run(123)

    assert ok is True
    assert reason == "Autonomous run validated."


def test_validate_autonomous_run_rejects_non_ready_issue(monkeypatch):
    monkeypatch.setattr(
        "src.autonomous_guard.get_issue_context",
        lambda issue_id: {
            "readiness_status": "WAITING_ON_RELEASE",
            "eligibility_status": "ELIGIBLE",
        },
    )

    ok, reason = validate_autonomous_run(123)

    assert ok is False
    assert "not READY_NOW" in reason


def test_validate_autonomous_run_rejects_blocked_issue(monkeypatch):
    monkeypatch.setattr(
        "src.autonomous_guard.get_issue_context",
        lambda issue_id: {
            "readiness_status": "READY_NOW",
            "eligibility_status": "BLOCKED",
        },
    )

    ok, reason = validate_autonomous_run(123)

    assert ok is False
    assert "ineligible" in reason


def test_validate_autonomous_run_rejects_missing_issue(monkeypatch):
    monkeypatch.setattr(
        "src.autonomous_guard.get_issue_context",
        lambda issue_id: None,
    )

    ok, reason = validate_autonomous_run(123)

    assert ok is False
    assert reason == "Issue not found."


def test_validate_autonomous_run_rejects_unavailable_hermes(monkeypatch):
    monkeypatch.setattr(
        "src.autonomous_guard.get_issue_context",
        lambda issue_id: {
            "readiness_status": "READY_NOW",
            "eligibility_status": "ELIGIBLE",
        },
    )

    def fail_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "src.autonomous_guard.verify_local_provider",
        fail_provider,
    )

    ok, reason = validate_autonomous_run(123)

    assert ok is False
    assert "Hermes unavailable" in reason
