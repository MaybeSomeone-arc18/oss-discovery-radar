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
    impl_models.record_failure("free-model-1", "rate limit")
    
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
    impl_models.record_failure("free-model-2", "timeout")
    eligible = impl_models.get_eligible_models()
    assert len(eligible) == 0  # Both are now on cooldown
    
def test_record_success_resets(mock_registry):
    impl_models.record_failure("free-model-1", "rate limit")
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
        impl_models.record_failure("free-model-1", "timeout")
        impl_models.record_failure("free-model-2", "429")
        
        ok, model, reason = select_execution_provider("implementation", 4000)
        assert not ok
        assert "No eligible FREE implementation models" in reason
        
    # Research/heavy should still use OMNIROUTE_MODEL_DEFAULT or fallback, unchanged
    with patch("src.autonomous_guard.omniroute_is_available_cached", return_value=True), \
         patch("src.autonomous_guard.get_omniroute_config", return_value={"model": "my-research-model"}):
         
        ok, model, reason = select_execution_provider("heavy", 4000)
        assert ok
        assert model == "my-research-model"

