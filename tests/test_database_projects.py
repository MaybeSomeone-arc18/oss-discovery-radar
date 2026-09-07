import pytest
from src import database
import tempfile
import os

@pytest.fixture(autouse=True)
def override_db_path(monkeypatch):
    fd, path = tempfile.mkstemp()
    os.close(fd)
    monkeypatch.setattr(database, "DB_PATH", path)
    database.init_db()
    yield
    os.remove(path)

def test_save_gsoc_project():
    database.save_organization("test-org", "Test Organization", "https://test.org", 2023)
    
    database.save_gsoc_project(
        org_slug="test-org",
        year=2023,
        title="Test Project",
        description="A cool project.",
        short_description="Short desc",
        contributor="Alice",
        url="https://example.com/project",
        code_url="https://github.com/example/code",
        technologies="python,c++"
    )
    
    stats = database.get_stats()
    assert stats['projects'] == 1
    
    # Idempotency test
    database.save_gsoc_project(
        org_slug="test-org",
        year=2023,
        title="Test Project",
        description="A cooler project now.",
        short_description="Short desc",
        contributor="Alice Updated",
        url="https://example.com/project",
        code_url="https://github.com/example/code",
        technologies="python,c++,rust"
    )
    
    stats = database.get_stats()
    assert stats['projects'] == 1
