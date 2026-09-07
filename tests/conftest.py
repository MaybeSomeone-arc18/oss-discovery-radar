import os
import pytest
import src.config as config

@pytest.fixture(autouse=True, scope="session")
def use_test_db():
    config.DB_PATH = "data/test_radar.db"
    yield
    if os.path.exists(config.DB_PATH):
        try:
            os.remove(config.DB_PATH)
        except:
            pass
