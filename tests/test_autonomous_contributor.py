from pathlib import Path

from src.autonomous_contributor import run_autonomous_by_url


def test_retry_defers_when_hermes_unavailable(monkeypatch):
    url = "https://github.com/example/repo/issues/25"

    monkeypatch.setattr(
        "src.autonomous_contributor.get_issue_context_by_url",
        lambda issue_url: {
            "issue_number": 25,
            "org_slug": "example",
            "repo_name": "example/repo",
        },
    )
    monkeypatch.setattr(
        "src.autonomous_contributor.validate_autonomous_run_by_url",
        lambda issue_url: (False, "Insufficient memory headroom"),
    )

    result = run_autonomous_by_url(url)

    assert result is None


def test_retry_uses_exact_url(monkeypatch):
    url = "https://github.com/example/repo/issues/25"
    calls = []

    monkeypatch.setattr(
        "src.autonomous_contributor.get_issue_context_by_url",
        lambda issue_url: {
            "issue_number": 25,
            "org_slug": "example",
            "repo_name": "example/repo",
        },
    )
    monkeypatch.setattr(
        "src.autonomous_contributor.validate_autonomous_run_by_url",
        lambda issue_url: (True, "Autonomous run validated."),
    )
    monkeypatch.setattr(
        "src.autonomous_contributor.get_hermes_execution_plan",
        lambda: (True, "llama3.2:3b", "validated"),
    )
    monkeypatch.setattr(
        "src.autonomous_contributor._run_pipeline",
        lambda issue_url: (
            Path("/tmp/summary.md"),
            True,
            [{"framework": "pytest", "result": {"success": True}}],
            "1 file changed",
        ),
    )
    monkeypatch.setattr(
        "src.autonomous_contributor.get_reports_dir",
        lambda *args: Path("/tmp"),
    )
    monkeypatch.setattr(
        "src.autonomous_contributor.generate_contribution_package",
        lambda *args, **kwargs: Path("/tmp/package"),
    )

    def record_pipeline(issue_url):
        calls.append(issue_url)
        return (
            Path("/tmp/summary.md"),
            True,
            [{"framework": "pytest", "result": {"success": True}}],
            "1 file changed",
        )

    monkeypatch.setattr(
        "src.autonomous_contributor._run_pipeline",
        record_pipeline,
    )

    result = run_autonomous_by_url(url)

    assert calls == [url]
    assert result == Path("/tmp/package")
