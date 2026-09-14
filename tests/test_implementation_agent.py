"""Focused regression tests for the implementation-agent behavior fix.

These tests verify that the implementation agent:
1. Receives the correct worktree cwd
2. Is explicitly instructed to directly edit files (no escape hatch)
3. A no-diff implementation is rejected (fails fast with clear error)
4. A real file modification passes the guardrail path
"""

import subprocess
from unittest.mock import MagicMock

import pytest

from src.hermes_agent import implement_issue_with_hermes
from src.implementer import check_diff_guardrails, implement

# Explicit execution-provider handoff produced by the routing layer for a
# successful tool-required implementation (carries the env var NAME, never the
# credential value).
HANDOFF = {
    "provider_id": "omniroute",
    "base_url": "http://127.0.0.1:20128/v1",
    "api_key_env": "OMNIROUTE_API_KEY",
    "model": "auto/coding:free",
}


def setup_clean_repo(tmp_path):
    """Create a real, clean git repo in tmp_path on a non-default branch.

    The autouse test DB fixture writes ``test_radar.db`` into the same
    tmp_path before each test body, so the initial commit must include
    everything already present; otherwise the worktree is never clean and
    the `main` default branch trips the guardrail's default-branch check.
    """
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    # Avoid the default branch name, which the guardrails reject.
    subprocess.run(["git", "checkout", "-b", "issue-42"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)


class TestImplementationAgentBehavior:
    """Tests for the implementation agent's direct file editing behavior."""

    def test_implementation_prompt_contains_no_escape_hatch(self, monkeypatch, tmp_path):
        """The implementation prompt must not contain the old escape hatch
        that allowed outputting patches instead of editing files."""
        captured_prompt = {}

        def fake_run_hermes(prompt, **kwargs):
            captured_prompt["prompt"] = prompt
            return "dummy response"

        monkeypatch.setattr("src.hermes_agent.run_hermes_oneshot", fake_run_hermes)
        monkeypatch.setattr("src.hermes_agent.verify_local_provider", lambda: None)
        # Pass the post-execution edit check by reporting a dirty worktree.
        monkeypatch.setattr(
            "src.hermes_agent.subprocess.run",
            lambda *a, **k: MagicMock(stdout=" M README.md\n", returncode=0),
        )

        implement_issue_with_hermes(tmp_path, "test context")

        prompt = captured_prompt["prompt"]

        # Old escape hatch must be removed
        assert "If you don't have tools to apply changes" not in prompt
        assert "output the full file modifications or patches" not in prompt

        # New explicit instructions must be present
        assert "MUST directly create and edit files" in prompt
        assert "Use shell commands to write files" in prompt
        assert "run `git diff` and `git status` to verify" in prompt
        assert "Do NOT output patches or descriptions instead of editing files" in prompt

    def test_implementation_runs_in_correct_worktree_cwd(self, monkeypatch, tmp_path):
        """Hermes must be invoked with the worktree as its working directory."""
        captured_kwargs = {}

        def fake_run_hermes(prompt, **kwargs):
            captured_kwargs["cwd"] = kwargs.get("cwd")
            return "dummy response"

        monkeypatch.setattr("src.hermes_agent.run_hermes_oneshot", fake_run_hermes)
        monkeypatch.setattr("src.hermes_agent.verify_local_provider", lambda: None)
        # Pass the post-execution edit check by reporting a dirty worktree.
        monkeypatch.setattr(
            "src.hermes_agent.subprocess.run",
            lambda *a, **k: MagicMock(stdout=" M README.md\n", returncode=0),
        )

        implement_issue_with_hermes(tmp_path, "test context")

        assert captured_kwargs["cwd"] == str(tmp_path)

    def test_no_diff_implementation_fails_fast(self, monkeypatch, tmp_path):
        """If Hermes returns but no files are modified, a clear RuntimeError
        must be raised before the guardrail stage."""
        monkeypatch.setattr("src.hermes_agent.run_hermes_oneshot", lambda *a, **k: "dummy response")
        monkeypatch.setattr("src.hermes_agent.verify_local_provider", lambda: None)

        # Set up git repo so post-execution check runs
        (tmp_path / ".git").mkdir()
        (tmp_path / "README.md").write_text("# Test\n")
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
        subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True)

        # Make subprocess.run return empty stdout for git status (no changes)
        def fake_subprocess_run(cmd, **kwargs):
            if cmd[:2] == ["git", "status"]:
                result = MagicMock()
                result.stdout = ""
                result.returncode = 0
                return result
            return subprocess.run(cmd, **kwargs)

        monkeypatch.setattr("src.hermes_agent.subprocess.run", fake_subprocess_run)

        with pytest.raises(RuntimeError, match="no files were modified"):
            implement_issue_with_hermes(tmp_path, "test context")

    def test_real_file_modification_passes_guardrail(self, tmp_path):
        """A real file modification in the worktree should pass the diff guardrails."""
        setup_clean_repo(tmp_path)
        # Simulate the implementation agent editing a tracked file.
        (tmp_path / "README.md").write_text("# Test\nchanged by implementation\n")

        passed, msg = check_diff_guardrails(tmp_path)
        assert passed is True
        assert "Guardrails passed" in msg

    def test_no_files_changed_fails_guardrail(self, tmp_path):
        """The existing guardrail correctly rejects when no files are changed."""
        setup_clean_repo(tmp_path)

        passed, msg = check_diff_guardrails(tmp_path)
        assert passed is False
        assert "No files were changed" in msg


class TestImplementationIntegration:
    """Integration tests for the full implementation path."""

    def test_implement_calls_hermes_with_correct_cwd(self, monkeypatch, tmp_path):
        """The implement() function must pass the correct worktree to the agent."""
        captured_cwd = {}

        def fake_hermes(worktree_path, context, model=None, provider_config=None):
            captured_cwd["worktree"] = str(worktree_path)
            return "dummy"

        monkeypatch.setattr("src.implementer.implement_issue_with_hermes", fake_hermes)
        monkeypatch.setattr("src.implementer.check_diff_guardrails", lambda *a: (True, "OK"))
        monkeypatch.setattr("src.implementer.discover_and_run_tests", lambda *a: [])
        monkeypatch.setattr("src.implementer.generate_reports", lambda *a, **k: None)
        # Worktree and reports are siblings, exactly like the real layout.
        worktree_dir = tmp_path / "worktree"
        worktree_dir.mkdir()
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        monkeypatch.setattr("src.implementer.create_worktree", lambda *a: worktree_dir)
        monkeypatch.setattr("src.implementer.requests.get", lambda *a, **k: MagicMock(status_code=200, json=lambda: {"title": "Test"}))
        monkeypatch.setattr("src.implementer.get_reports_dir", lambda *a: reports_dir)
        monkeypatch.setattr("src.implementer.get_hermes_execution_handoff", lambda **kwargs: (True, "auto/coding:free", "OK", HANDOFF))
        monkeypatch.setattr("src.implementer.get_issue_context_by_url", lambda *a: {"url": "http://test/1", "issue_number": 1, "org_slug": "test", "repo_name": "test/repo", "title": "Test", "body_preview": "body"})
        monkeypatch.setattr("src.opportunity_manager.communication_allows_implementation", lambda *a: True)
        monkeypatch.setattr("src.opportunity_manager.transition_status", lambda *a, **k: None)

        # Plan file must live where the (mocked) reports dir points.
        (reports_dir / "plan.md").write_text("PLAN")

        implement("http://test/1")
        assert captured_cwd["worktree"] == str(worktree_dir)

    def test_implement_fails_fast_on_no_diff(self, monkeypatch, tmp_path):
        """A no-diff agent response must be rejected by the strict guardrail:
        implement() returns failure instead of claiming implementation success."""
        def fake_hermes_no_changes(worktree_path, context, model=None, provider_config=None):
            return "dummy response"

        monkeypatch.setattr("src.implementer.implement_issue_with_hermes", fake_hermes_no_changes)
        monkeypatch.setattr("src.implementer.discover_and_run_tests", lambda *a: [])
        monkeypatch.setattr("src.implementer.generate_reports", lambda *a, **k: None)
        # Worktree and reports are siblings, exactly like the real layout.
        worktree_dir = tmp_path / "worktree"
        worktree_dir.mkdir()
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        monkeypatch.setattr("src.implementer.create_worktree", lambda *a: worktree_dir)
        monkeypatch.setattr("src.implementer.requests.get", lambda *a, **k: MagicMock(status_code=200, json=lambda: {"title": "Test"}))
        monkeypatch.setattr("src.implementer.get_reports_dir", lambda *a: reports_dir)
        monkeypatch.setattr("src.implementer.get_hermes_execution_handoff", lambda **kwargs: (True, "auto/coding:free", "OK", HANDOFF))
        monkeypatch.setattr("src.implementer.get_issue_context_by_url", lambda *a: {"url": "http://test/1", "issue_number": 1, "org_slug": "test", "repo_name": "test/repo", "title": "Test", "body_preview": "body"})
        monkeypatch.setattr("src.opportunity_manager.communication_allows_implementation", lambda *a: True)
        monkeypatch.setattr("src.opportunity_manager.transition_status", lambda *a, **k: None)

        # Plan file must live where the (mocked) reports dir points.
        (reports_dir / "plan.md").write_text("PLAN")

        # Real git repo with a clean working tree: the agent changed nothing,
        # so the strict check_diff_guardrails must reject it.
        setup_clean_repo(worktree_dir)

        success, test_results, diff_stat = implement("http://test/1")

        assert success is False
        assert test_results is None
        assert diff_stat == ""