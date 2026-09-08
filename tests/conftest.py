import os
import pytest
import src.config as config
from src.database import init_db

# Ensure we always indicate we're running tests to trigger safety checks
os.environ["IS_PYTEST"] = "1"

@pytest.fixture(autouse=True, scope="function")
def isolated_test_db(tmp_path):
    """Provides a strict isolated database per test."""
    db_file = tmp_path / "test_radar.db"
    original_db = config.DB_PATH
    config.DB_PATH = str(db_file)
    
    init_db()
    
    yield
    
    config.DB_PATH = original_db
