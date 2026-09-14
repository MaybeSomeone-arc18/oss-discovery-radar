"""Focused regression tests for communication-gate section parsing.

Covers the parser behavior discovered during controlled E2E runs for
checkstyle/checkstyle#21528: real llama3.2:3b research output is
nondeterministic in heading depth — one run emitted H1 sections, another
emitted H3 sections. The parser must therefore accept H1, H2, and H3
headings (line-anchored) and keep rejecting H4+/malformed headings.

Tests:
- H1 / H2 / H3 extraction
- cross-level equivalence
- correct section boundary handling (including mixed levels)
- H4 rejection
- malformed-heading rejection
- missing-section behavior
- the actual #21528 research.md structures (H1 and H3)
"""

import pytest

from src.communication_gate import _extract_section, generate_communication_recommendation


H1_DOC = """# Constraints
- first
- second

# Unknowns
unknown content
"""

H2_DOC = """## Constraints
- first
- second

## Unknowns
unknown content
"""

H3_DOC = """### Constraints
- first
- second

### Unknowns
unknown content
"""


def test_extract_h1_section():
    assert _extract_section(H1_DOC, "Constraints") == "- first\n- second"


def test_extract_h2_section():
    assert _extract_section(H2_DOC, "Constraints") == "- first\n- second"


def test_extract_h3_section():
    assert _extract_section(H3_DOC, "Constraints") == "- first\n- second"


def test_h1_h2_h3_produce_identical_content():
    assert (
        _extract_section(H1_DOC, "Constraints")
        == _extract_section(H2_DOC, "Constraints")
        == _extract_section(H3_DOC, "Constraints")
    )


def test_boundary_stops_at_next_heading():
    # Mixed heading levels: an H1 section must end at the next H2 heading.
    mixed = """# Constraints
- first

## Unknowns
unknown content
"""
    assert _extract_section(mixed, "Constraints") == "- first"


def test_boundary_stops_at_mixed_h1_h2_h3_headings():
    doc = """## Constraints
- first

# Unknowns
h1 body

### More
h3 body
"""
    assert _extract_section(doc, "Constraints") == "- first"
    assert _extract_section(doc, "Unknowns") == "h1 body"
    assert _extract_section(doc, "More") == "h3 body"


def test_h3_section_stops_at_next_h3():
    assert _extract_section(H3_DOC, "Constraints") == "- first\n- second"


def test_last_section_runs_to_end_of_document():
    doc = """### Constraints
- first

### Unknowns
last section body
"""
    assert _extract_section(doc, "Unknowns") == "last section body"


def test_missing_section_returns_empty():
    assert _extract_section(H3_DOC, "NonExistent Section") == ""


def test_indented_markdown_line_is_not_a_heading_boundary():
    # An indented "# ..." line (e.g. inside a code block) is body content,
    # not a section heading: it must not terminate the section early.
    doc = """# Constraints
    # Still body content
text
"""
    content = _extract_section(doc, "Constraints")
    assert "Still body content" in content
    assert content.endswith("text")


def test_rejects_h4_and_malformed_headings():
    doc = """#### Constraints
h4 body

#Constraints
no space body

##Constraints
no space h2 body

###Constraints
no space h3 body
"""
    assert _extract_section(doc, "Constraints") == ""


def test_rejects_partial_name_match():
    doc = """# Constraints?
question body

# Constraints and Limits
other body
"""
    assert _extract_section(doc, "Constraints") == ""


# --- generate_communication_recommendation with the real #21528 structures ---

ISSUE = {
    "url": "https://github.com/checkstyle/checkstyle/issues/21528",
    "org_slug": "checkstyle",
    "repo_name": "checkstyle/checkstyle",
    "issue_number": 21528,
    "title": "Add checks for Sun Style [4.2 - Wrapping Lines]",
    "body_preview": "Add Checkstyle checks for all rules under 4.2 - Wrapping Lines.",
}

# Exact H1 structure produced by a real llama3.2:3b research run (first E2E).
REAL_21528_RESEARCH_H1 = """# Issue Summary
[FACT] The issue is about adding checks for Sun Style 4.2 - Wrapping Lines in Checkstyle.

# Repository Context
[FACT] The repository is checkstyle/checkstyle, a Java coding standard tool.

[INFERENCE] The contributor has been active and has a high contribution score, but has no experience with GSoC.

[UNCERTAINTY] The repository's CONTRIBUTING guide is missing.

# Relevant Files
[FACT] The issue mentions the CodeConventions.doc3.html#a248 page.

# Related PRs/Commits
[INFERENCE] There might be related PRs or commits related to similar issues, but no specific information is available.

# Possible Root Causes
[UNCERTAINTY] We don't know the exact root cause of the issue, but it might be related to the new checks not being compatible with existing code.

# Potential Approaches
[INFERENCE] The contributor might need to manually review and apply the new checks to existing code.

[INFERENCE] The GSoC score could be related to the complexity of the issue, but more information is needed.

# Constraints
[FACT] The repository has a No AI-generated code push without human review policy.

[FACT] The contributor has no experience with GSoC.

# Unknowns
[UNCERTAINTY] The exact extent of the issue and its impact on the repository.

[UNCERTAINTY] More information about the contribution score and how it relates to the issue.

# Questions for Maintainers
- Can you provide more information about the CONTRIBUTING guide?
- How can we better support contributors with limited experience?

# Recommended Next Step
[INFERENCE] Review the new checks and discuss with the contributor to understand their application and implementation.

Note: This output follows the exact prefixes and constraint mentioned in the prompt. The facts are extracted directly from the issue context, inferences are made based on the available information, and uncertainties indicate missing or insufficient data. The recommended next step is an educated guess based on the available information.
"""

# Exact H3 structure produced by a real llama3.2:3b research run (second E2E,
# 2026-09-13 20:13 local). Includes the Setext-title prefix the model emitted.
REAL_21528_RESEARCH_H3 = """Markdown Research Report
=====================

### Issue Summary
[FACT] The issue is asking to add checks for Sun Style [4.2 - Wrapping Lines] to the Checkstyle rules.

### Repository Context
[FACT] The repository is checkstyle/checkstyle, a maintained project under the checkstyle organization.
[INFERENCE] The repository has a low personal fit score, indicating that the contributors may not have a strong connection to the project.

### Relevant Files
[ UNCERTAINTY ] We don't know if all relevant files have been uploaded.

### Related PRs/Commits
[FACT] The issue links to parent issue #20811.

### Possible Root Causes
[INFERENCE] The bug might be that the contribution score is not high enough to warrant immediate attention.
[ UNCERTAINTY ] We don't know if the contribution score is indicative of the bug's severity or priority.

### Potential Approaches
[INFERENCE] Implementing the new checks for Sun Style [4.2 - Wrapping Lines] could address the issue.
[FACT] The issue has been labeled as approved, indicating that it is being actively worked on.

### Constraints
[FACT] The repository has a known AI policy constraint: no AI-generated code push without human review.

### Unknowns
[UNCERTAINTY ] We don't know why the contribution score is not high enough.
[UNCERTAINTY ] We don't know which specific files are being worked on to address the issue.

### Questions for Maintainers
* Can you provide more information about the contribution score and why it is not high enough?
* Which specific files are being worked on to address the issue?
* How will the new checks for Sun Style [4.2 - Wrapping Lines] be implemented?

### Recommended Next Step
[INFERENCE] It would be helpful to discuss the contribution score and the implementation plan with the maintainers before proceeding.
"""


def _run_communication_recommendation(monkeypatch, tmp_path, research_text):
    calls = []

    def fake_plan(task_type="lightweight"):
        calls.append(task_type)
        return (True, "opencode-zen/nemotron-3.5-lightning-free", "validated", None)

    monkeypatch.setattr(
        "src.communication_gate.get_hermes_execution_handoff", fake_plan
    )
    monkeypatch.setattr(
        "src.communication_gate.get_issue_context",
        lambda url: dict(ISSUE, url=url),
    )
    monkeypatch.setattr(
        "src.communication_gate.get_reports_dir",
        lambda org, repo, issue: tmp_path,
    )
    (tmp_path / "research.md").write_text(research_text)

    captured = {}

    def fake_run(prompt, **kwargs):
        captured["prompt"] = prompt
        captured.update(kwargs)
        return (
            "## Recommendation\nNO_CLARIFICATION_NEEDED\n\n"
            "## Suggested Reply\nNo contact needed.\n\n"
            "## Reason\nThe next step is unambiguous.\n\n"
            "## Questions\n- None\n\n"
            "## Implementation Gate\nMAY_PROCEED"
        )

    monkeypatch.setattr("src.communication_gate.run_hermes_oneshot", fake_run)
    monkeypatch.setattr(
        "src.communication_gate.set_communication_recommendation",
        lambda *args, **kwargs: None,
    )

    result = generate_communication_recommendation(ISSUE["url"])
    return calls, captured, result


def test_communication_recommendation_parses_real_h1_research(monkeypatch, tmp_path):
    """The real #21528 research.md (H1 headings) must reach the Hermes
    communication inference with all four communication-relevant sections."""
    calls, captured, result = _run_communication_recommendation(
        monkeypatch, tmp_path, REAL_21528_RESEARCH_H1
    )

    assert calls == ["heavy"]
    assert captured["model"] == "opencode-zen/nemotron-3.5-lightning-free"
    prompt = captured["prompt"]
    for section in (
        "Questions for Maintainers",
        "Recommended Next Step",
        "Constraints",
        "Unknowns",
    ):
        assert f"## {section}" in prompt
    assert "Can you provide more information about the CONTRIBUTING guide?" in prompt
    assert result["status"] == "NOT_REQUIRED"
    assert result["implementation_gate"] == "MAY_PROCEED"


def test_communication_recommendation_parses_real_h3_research(monkeypatch, tmp_path):
    """The real #21528 research.md (H3 headings) must reach the Hermes
    communication inference with all four communication-relevant sections."""
    calls, captured, result = _run_communication_recommendation(
        monkeypatch, tmp_path, REAL_21528_RESEARCH_H3
    )

    assert calls == ["heavy"]
    assert captured["model"] == "opencode-zen/nemotron-3.5-lightning-free"
    prompt = captured["prompt"]
    for section in (
        "Questions for Maintainers",
        "Recommended Next Step",
        "Constraints",
        "Unknowns",
    ):
        assert f"## {section}" in prompt
    assert "Which specific files are being worked on to address the issue?" in prompt
    assert "no AI-generated code push without human review" in prompt
    assert result["status"] == "NOT_REQUIRED"
    assert result["implementation_gate"] == "MAY_PROCEED"


def test_communication_gate_considers_discussion_context(monkeypatch, tmp_path):
    import src.communication_gate as gate

    mock_issue = {
        "org_slug": "checkstyle",
        "repo_name": "checkstyle/checkstyle",
        "issue_number": 21480,
        "title": "Checkstyle #21480 discussion test",
        "url": "https://github.com/checkstyle/checkstyle/issues/21480",
        "body_preview": "Truncated preview",
        "discussion_context": "=== ISSUE BODY (by author) ===\nNeed clarification on rule X.\n=== DISCUSSION HISTORY (showing 1 comment) ===\n[Comment #1 by Maintainer (MEMBER) at 2026-09-14]: Use Option B for rule X. No further questions needed."
    }

    monkeypatch.setattr(gate, "get_issue_context", lambda url: mock_issue)
    
    # Create fake research.md
    reports_dir = tmp_path / "checkstyle" / "checkstyle" / "reports" / "21480"
    reports_dir.mkdir(parents=True)
    research_file = reports_dir / "research.md"
    research_file.write_text("""# Questions for Maintainers\n- Maintainer answered Option B in discussion.\n# Recommended Next Step\nProceed with Option B implementation.\n# Constraints\nNone\n# Unknowns\nNone""")

    captured_prompt = []
    def mock_run_oneshot(prompt, safe_mode=True, model=None, **kwargs):
        captured_prompt.append(prompt)
        return """## Recommendation\nNO_CLARIFICATION_NEEDED\n\n## Suggested Reply\nN/A\n\n## Reason\nMaintainer already decided Option B in discussion.\n\n## Questions\n- None\n\n## Implementation Gate\nMAY_PROCEED"""

    monkeypatch.setattr(gate, "run_hermes_oneshot", mock_run_oneshot)
    monkeypatch.setattr("src.autonomous_guard.get_hermes_execution_handoff", lambda task_type: (True, "mock-model", "ok", {}))
    monkeypatch.setattr(gate, "set_communication_recommendation", lambda issue_url, reply, reason: None)

    res = gate.generate_communication_recommendation("https://github.com/checkstyle/checkstyle/issues/21480")

    assert res["status"] == "NOT_REQUIRED"
    assert res["implementation_gate"] == "MAY_PROCEED"
    assert len(captured_prompt) == 1
    assert "Discussion & Context:" in captured_prompt[0]
    assert "Use Option B for rule X. No further questions needed." in captured_prompt[0]