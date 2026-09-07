import os
from src import config

def test_default_configurations():
    assert isinstance(config.TARGET_ORGANIZATIONS, list)
    assert len(config.TARGET_ORGANIZATIONS) > 0
    
    assert isinstance(config.GSOC_YEARS, list)
    # Check default years
    assert 2022 in config.GSOC_YEARS
    assert 2026 in config.GSOC_YEARS
    
    assert isinstance(config.LOOKBACK_DAYS, int)
    assert config.LOOKBACK_DAYS == 30
