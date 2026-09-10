import pytest

from src.autonomous_guard import validate_autonomous_run, validate_hermes_execution


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


def test_validate_hermes_execution_allows_3b_fallback(monkeypatch):
    monkeypatch.setattr(
        "src.autonomous_guard.verify_local_provider",
        lambda: None,
    )
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (False, "Insufficient memory headroom"),
    )
    monkeypatch.setattr(
        "src.autonomous_guard.list_local_models",
        lambda: [
            {"name": "qwen3.5:9b", "size": 6594474711},
            {"name": "llama3.2:3b", "size": 2019393189},
        ],
    )
    monkeypatch.setattr(
        "src.autonomous_guard.get_available_memory_mb",
        lambda: 6000,
    )

    ok, reason = validate_hermes_execution()

    assert ok is True
    assert "llama3.2:3b" in reason


def test_get_hermes_execution_plan_selects_qwen(monkeypatch):
    from src.autonomous_guard import get_hermes_execution_plan

    monkeypatch.setattr(
        "src.autonomous_guard.verify_local_provider",
        lambda: None,
    )
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (True, "Resources sufficient"),
    )

    ok, model, reason = get_hermes_execution_plan()

    assert ok is True
    assert model == "qwen3.5:9b"
    assert "qwen3.5:9b" in reason


def test_get_hermes_execution_plan_selects_3b(monkeypatch):
    from src.autonomous_guard import get_hermes_execution_plan

    monkeypatch.setattr(
        "src.autonomous_guard.verify_local_provider",
        lambda: None,
    )
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (False, "Insufficient memory headroom"),
    )
    monkeypatch.setattr(
        "src.autonomous_guard.list_local_models",
        lambda: [
            {"name": "qwen3.5:9b", "size": 6594474711},
            {"name": "llama3.2:3b", "size": 2019393189},
        ],
    )
    monkeypatch.setattr(
        "src.autonomous_guard.get_available_memory_mb",
        lambda: 6000,
    )

    ok, model, reason = get_hermes_execution_plan()

    assert ok is True
    assert model == "llama3.2:3b"
    assert "llama3.2:3b" in reason


def test_get_hermes_execution_plan_defers_when_no_model_fits(monkeypatch):
    from src.autonomous_guard import get_hermes_execution_plan

    monkeypatch.setattr(
        "src.autonomous_guard.verify_local_provider",
        lambda: None,
    )
    monkeypatch.setattr(
        "src.autonomous_guard.check_resources_for_hermes",
        lambda: (False, "Insufficient memory headroom"),
    )
    monkeypatch.setattr(
        "src.autonomous_guard.list_local_models",
        lambda: [
            {"name": "qwen3.5:9b", "size": 6594474711},
            {"name": "llama3.2:3b", "size": 2019393189},
        ],
    )
    monkeypatch.setattr(
        "src.autonomous_guard.get_available_memory_mb",
        lambda: 2000,
    )

    ok, model, reason = get_hermes_execution_plan()

    assert ok is False
    assert model is None
    assert "Insufficient memory headroom" in reason
