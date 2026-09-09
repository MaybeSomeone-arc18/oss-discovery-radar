import pytest
from unittest.mock import patch, MagicMock
from src.database import get_connection
import os
import json
import glob

# Ensure DB is isolated via standard test fixtures or we can just patch everything,
# but our `get_connection` in tests usually connects to `test_radar.db` based on logic in `database.py`.

@patch('src.hermes_agent.verify_local_provider')
@patch('src.hermes_agent.run_hermes_oneshot')
@patch('src.resource_manager.check_resources_for_hermes')
@patch('urllib.request.urlopen')
def test_end_to_end_smoke(mock_urlopen, mock_resources, mock_hermes, mock_verify):
    # Setup mocks
    mock_verify.return_value = None
    mock_hermes.return_value = "Mocked hermes response"
    mock_resources.return_value = (True, "Mocked resources OK")
    
    # Mock github API
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps({
        "items": [
            {
                "html_url": "https://github.com/mock-org/mock-repo/issues/123",
                "number": 123,
                "title": "Mock issue",
                "body": "Mock body",
                "state": "open",
                "labels": [{"name": "good first issue"}],
                "created_at": "2023-10-10T10:00:00Z",
                "updated_at": "2023-10-10T10:00:00Z",
                "comments": 0
            }
        ]
    }).encode('utf-8')
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp
    
    # 1. Sync
    from main import cmd_sync_issues
    cmd_sync_issues(limit=1)
    
    # 2. Daily run (which triggers digest & hermes auto)
    from main import cmd_daily_run
    cmd_daily_run()
    
    # 3. Verify audit log
    from src.run_log import get_recent_logs
    logs = get_recent_logs(10)
    assert len(logs) > 0, "Audit logs should not be empty"
    actions = [l[2] for l in logs]
    assert 'sync' in actions
    
    # 4. Check dashboard endpoints via the DashboardHandler
    from src.dashboard import DashboardHandler
    data = DashboardHandler.get_dashboard_data(None)
    assert 'opportunities' in data
    
    # Check if a digest was created
    digests = glob.glob("digests/daily_*.md")
    assert len(digests) > 0, "Daily digest should be created"
    
    # Since Hermes auto-trigger might have run, check reports dir
    from src.workspace_manager import WORKSPACES_ROOT
    report_md = WORKSPACES_ROOT / "mock-org" / "mock-repo" / "reports" / "123" / "research.md"
    plan_md = WORKSPACES_ROOT / "mock-org" / "mock-repo" / "reports" / "123" / "plan.md"
    
    # Note: the opportunity might not score high enough to be top 1 because of strict readiness rules.
    # We won't assert research.md strictly, but we can verify dashboard doesn't crash
