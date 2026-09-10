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

def test_pipeline_blocks_before_plan_when_communication_needs_review(monkeypatch, tmp_path):
    url = "https://github.com/example/repo/issues/25"
    plan_called = False

    monkeypatch.setattr(
        "src.autonomous_contributor.get_issue_context_by_url",
        lambda issue_url: {
            "issue_number": 25,
            "org_slug": "example",
            "repo_name": "example/repo",
            "url": url,
        },
    )
    monkeypatch.setattr(
        "src.autonomous_contributor.research",
        lambda issue_url: True,
    )
    monkeypatch.setattr(
        "src.autonomous_contributor.get_reports_dir",
        lambda *args: tmp_path,
    )
    (tmp_path / "research.md").write_text("# Research\n")
    monkeypatch.setattr(
        "src.autonomous_contributor.generate_communication_recommendation",
        lambda issue_url: {"status": "REVIEW_REQUIRED"},
    )
    monkeypatch.setattr(
        "src.autonomous_contributor.get_communication_state",
        lambda issue_url: {"communication_status": "REVIEW_REQUIRED"},
    )
    monkeypatch.setattr(
        "src.autonomous_contributor.communication_allows_implementation",
        lambda issue_url: False,
    )

    def unexpected_plan(issue_url):
        nonlocal plan_called
        plan_called = True
        return True

    monkeypatch.setattr("src.autonomous_contributor.plan", unexpected_plan)

    try:
        from src.autonomous_contributor import _run_pipeline
        _run_pipeline(url)
    except RuntimeError as exc:
        assert "Communication gate blocked implementation" in str(exc)
    else:
        raise AssertionError("Expected communication gate to block pipeline")

    assert plan_called is False


def test_pipeline_proceeds_when_communication_is_not_required(monkeypatch, tmp_path):
    url = "https://github.com/example/repo/issues/25"

    monkeypatch.setattr(
        "src.autonomous_contributor.get_issue_context_by_url",
        lambda issue_url: {
            "issue_number": 25,
            "org_slug": "example",
            "repo_name": "example/repo",
            "url": url,
        },
    )
    monkeypatch.setattr(
        "src.autonomous_contributor.research",
        lambda issue_url: True,
    )
    monkeypatch.setattr(
        "src.autonomous_contributor.get_reports_dir",
        lambda *args: tmp_path,
    )
    (tmp_path / "research.md").write_text("# Research\n")
    monkeypatch.setattr(
        "src.autonomous_contributor.generate_communication_recommendation",
        lambda issue_url: {"status": "NOT_REQUIRED"},
    )
    monkeypatch.setattr(
        "src.autonomous_contributor.get_communication_state",
        lambda issue_url: {"communication_status": "NOT_REQUIRED"},
    )
    monkeypatch.setattr(
        "src.autonomous_contributor.communication_allows_implementation",
        lambda issue_url: True,
    )
    monkeypatch.setattr(
        "src.autonomous_contributor.plan",
        lambda issue_url: True,
    )
    (tmp_path / "plan.md").write_text("# Plan\n")
    monkeypatch.setattr(
        "src.autonomous_contributor.implement",
        lambda issue_url: (True, [], "0 files changed"),
    )
    (tmp_path / "summary.md").write_text("# Summary\n")

    result = __import__("src.autonomous_contributor", fromlist=["_run_pipeline"])._run_pipeline(url)

    assert result[0] == tmp_path / "summary.md"
    assert result[1] is True
