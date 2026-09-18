import pytest
import os
import json
import time
from unittest.mock import patch, MagicMock

import src.implementation_models as impl_models
from src.autonomous_guard import select_execution_provider

@pytest.fixture
def mock_registry(tmp_path):
    registry_file = tmp_path / "implementation_registry.json"

    test_models = [
        {
            "model_id": "free-model-1",
            "provider": "omniroute",
            "free_only": True,
            "verified_filesystem_edit": True,
            "availability_status": "AVAILABLE",
            "cooldown_until": 0,
        },
        {
            "model_id": "free-model-2",
            "provider": "omniroute",
            "free_only": True,
            "verified_filesystem_edit": True,
            "availability_status": "AVAILABLE",
            "cooldown_until": 0,
        },
        {
            "model_id": "paid-model-1",
            "provider": "omniroute",
            "free_only": False,
            "verified_filesystem_edit": True,
            "availability_status": "AVAILABLE",
            "cooldown_until": 0,
        },
        {
            "model_id": "unverified-model",
            "provider": "omniroute",
            "free_only": True,
            "verified_filesystem_edit": False,
            "availability_status": "AVAILABLE",
            "cooldown_until": 0,
        },
    ]

    with patch("src.implementation_models.REGISTRY_PATH", registry_file):
        with patch("src.implementation_models.INITIAL_MODELS", test_models):
            with open(registry_file, "w") as f:
                json.dump(test_models, f)
            yield registry_file

def test_get_eligible_models(mock_registry):
    eligible = impl_models.get_eligible_models()
    assert len(eligible) == 2
    assert eligible[0]["model_id"] == "free-model-1"
    assert eligible[1]["model_id"] == "free-model-2"
    # Paid and unverified should not be included

def test_record_failure_cooldown(mock_registry):
    # Record a 429 rate limit
    impl_models.record_failure("free-model-1", "PROVIDER_RATE_LIMIT")

    eligible = impl_models.get_eligible_models()
    assert len(eligible) == 1
    assert eligible[0]["model_id"] == "free-model-2"

    # Reload and check cooldown logic
    data = impl_models.load_registry()
    m1 = next(m for m in data if m["model_id"] == "free-model-1")
    assert m1["availability_status"] == "COOLDOWN"
    assert m1["cooldown_until"] > time.time() + 290  # roughly +300s
    assert m1["failure_count"] == 1

    # Record a timeout
    impl_models.record_failure("free-model-2", "PROVIDER_TIMEOUT")
    eligible = impl_models.get_eligible_models()
    assert len(eligible) == 0  # Both are now on cooldown

def test_record_success_resets(mock_registry):
    impl_models.record_failure("free-model-1", "PROVIDER_RATE_LIMIT")
    assert len(impl_models.get_eligible_models()) == 1

    impl_models.record_success("free-model-1")
    eligible = impl_models.get_eligible_models()
    assert len(eligible) == 2

    data = impl_models.load_registry()
    m1 = next(m for m in data if m["model_id"] == "free-model-1")
    assert m1["availability_status"] == "AVAILABLE"
    assert m1["cooldown_until"] == 0
    assert m1["failure_count"] == 0

def test_autonomous_guard_routing(mock_registry):
    # Implementation should use the registry
    with patch("src.autonomous_guard.omniroute_is_available_cached", return_value=True), \
         patch("src.autonomous_guard.get_omniroute_config", return_value={"model": "default"}):
        ok, model, reason = select_execution_provider("implementation", 4000)
        assert ok
        assert model == "free-model-1"
        assert "OmniRoute provider" in reason

        # Test exhaustion
        impl_models.record_failure("free-model-1", "PROVIDER_TIMEOUT")
        impl_models.record_failure("free-model-2", "PROVIDER_RATE_LIMIT")

        ok, model, reason = select_execution_provider("implementation", 4000)
        assert not ok
        assert "No eligible FREE implementation models" in reason

    # Research/heavy should still use OMNIROUTE_MODEL_DEFAULT or fallback, unchanged
    with patch("src.autonomous_guard.omniroute_is_available_cached", return_value=True), \
         patch("src.autonomous_guard.get_omniroute_config", return_value={"model": "my-research-model"}):

        ok, model, reason = select_execution_provider("heavy", 4000)
        assert ok
        assert model == "my-research-model"



def test_fallback_state_machine(monkeypatch, mock_registry, tmp_path):
    from src.implementer import implement
    from src.implementation_models import load_registry
    from unittest.mock import MagicMock
    import json

    mock_get_issue = MagicMock()
    mock_get_issue.return_value = {"url": "http://test", "issue_number": 999, "title": "Test", "body_preview": "Test", "org_slug": "test", "repo_name": "test/repo"}
    monkeypatch.setattr("src.implementer.get_issue_context_by_url", mock_get_issue)

    mock_req = MagicMock()
    mock_req.return_value.status_code = 200
    mock_req.return_value.json.return_value = {"title": "Test"}
    monkeypatch.setattr("src.implementer.requests.get", mock_req)

    mock_guardrails = MagicMock()
    mock_guardrails.return_value = (True, "OK")
    monkeypatch.setattr("src.implementer.check_diff_guardrails", mock_guardrails)

    mock_run_tests = MagicMock()
    mock_run_tests.return_value = [{"framework": "pytest", "result": {"success": True}}]
    monkeypatch.setattr("src.implementer.discover_and_run_tests", mock_run_tests)

    mock_run = MagicMock()
    mock_run.return_value.stdout = "diff"
    mock_run.return_value.returncode = 0
    monkeypatch.setattr("src.implementer.subprocess.run", mock_run)

    monkeypatch.setattr("src.implementer.generate_reports", MagicMock())
    monkeypatch.setattr("src.implementer.transition_status", MagicMock())

    mock_implement = MagicMock()
    monkeypatch.setattr("src.implementer.implement_issue_with_hermes", mock_implement)

    mock_repair = MagicMock()
    monkeypatch.setattr("src.implementer.repair_issue_with_hermes", mock_repair)

    monkeypatch.setattr("src.implementer.create_worktree", lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr("src.implementer.get_hermes_execution_handoff", lambda **kwargs: (True, "model", "ok", {}))
    monkeypatch.setattr("src.implementer.get_reports_dir", lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr("src.opportunity_manager.communication_allows_implementation", lambda *args, **kwargs: True)
    monkeypatch.setattr("src.implementer.run_hermes_oneshot", lambda *a, **k: "OK")
    (tmp_path / "plan.md").write_text("plan")

    # Provider exception -> next model
    mock_implement.side_effect = [
        Exception("rate_limit exceeded"),
        None
    ]

    success, _, _ = implement("http://test")
    assert success is True

    # 2 calls to implement (one failed provider, one succeeded)
    assert mock_implement.call_count == 2
    # 0 calls to repair
    assert mock_repair.call_count == 0

    # Check registry state
    data = load_registry()
    m1 = next(m for m in data if m["model_id"] == "free-model-1")
    assert m1["availability_status"] == "COOLDOWN"

    # Reset registry
    for m in data:
        m["availability_status"] = "AVAILABLE"
        m["cooldown_until"] = 0
    with open(mock_registry, "w") as f:
        json.dump(data, f)

    mock_implement.reset_mock()
    mock_repair.reset_mock()

    # Implementation failure -> one repair -> next model
    mock_implement.side_effect = [
        Exception("Validation FAILED: No files were changed"), # caught as implementation failure
        None
    ]
    mock_repair.side_effect = [
        Exception("repair also failed Validation FAILED"), # repair fails
        None
    ]

    success, _, _ = implement("http://test")
    assert success is True

    assert mock_implement.call_count == 2
    assert mock_repair.call_count == 1

    data = load_registry()
    m1 = next(m for m in data if m["model_id"] == "free-model-1")
    assert m1["availability_status"] == "IMPLEMENTATION_ERROR"

def test_alias_models_sorted_after_concrete(mock_registry):
    import time
    from src.implementation_models import load_registry, save_registry, get_eligible_models, INITIAL_MODELS

    # We must patch INITIAL_MODELS to include our alias model, since the registry drops unknown models
    alias_model = {
        "model_id": "auto/alias-model",
        "provider": "omniroute",
        "free_only": True,
        "verified_filesystem_edit": True,
        "availability_status": "AVAILABLE",
        "cooldown_until": 0,
        "measured_latency": 1.0 # Very fast, but it's an alias
    }

    with patch("src.implementation_models.INITIAL_MODELS", INITIAL_MODELS + [alias_model]):
        eligible = get_eligible_models()
        assert len(eligible) == 3
        # Even though auto/alias-model has 1.0 latency, concrete models should come first
        assert eligible[0]["model_id"] == "free-model-1"
        assert eligible[1]["model_id"] == "free-model-2"
        assert eligible[2]["model_id"] == "auto/alias-model"
