import re
from pathlib import Path

from src.autonomous_guard import get_hermes_execution_handoff
from src.hermes_agent import (
    _oneshot_provider_kwargs,
    get_issue_context,
    get_reports_dir,
    run_hermes_oneshot,
)
from src.opportunity_manager import set_communication_recommendation

# Any line that starts an H1, H2, or H3 Markdown heading. Used to find the
# section boundary after a matched heading; never matches H4+ ("####"),
# headings without the required space ("#Heading"), or indented lines.
_SECTION_HEADING_RE = re.compile(r"^#{1,3} [^\n]+$", re.MULTILINE)


def _extract_section(research_content, name):
    """Extract a Markdown section by its H1, H2, or H3 heading.

    Only valid headings are recognized: one to three leading hashes followed
    by a space and the exact section name on its own line. The section runs
    to the next H1/H2/H3 heading or the end of the document.
    """
    pattern = r"^#{1,3} " + re.escape(name) + r"[ \t]*$"
    heading = re.compile(pattern, re.MULTILINE | re.IGNORECASE)
    match = heading.search(research_content)
    if not match:
        return ""
    start = match.end()
    next_heading = _SECTION_HEADING_RE.search(research_content, start)
    end = next_heading.start() if next_heading else len(research_content)
    return research_content[start:end].strip()


def _get_research_file(issue):
    repo_name = issue["repo_name"]
    repo = repo_name.split("/")[1] if "/" in repo_name else repo_name
    reports_dir = get_reports_dir(issue["org_slug"], repo, issue["issue_number"])
    return reports_dir / "research.md"


def generate_communication_recommendation(issue_url):
    """Generate and persist a human-reviewable maintainer communication recommendation."""
    issue = get_issue_context(issue_url)

    if not issue:
        raise RuntimeError(f"Issue not found: {issue_url}")

    research_file = _get_research_file(issue)
    if not research_file.exists():
        raise RuntimeError(f"Research report not found at {research_file}")

    research_content = research_file.read_text().strip()
    if not research_content:
        raise RuntimeError(f"Research report is empty: {research_file}")

    relevant_sections = []
    for name in (
        "Questions for Maintainers",
        "Recommended Next Step",
        "Constraints",
        "Unknowns",
    ):
        content = _extract_section(research_content, name)
        if content:
            relevant_sections.append(f"## {name}\n{content}")

    communication_context = "\n\n".join(relevant_sections)
    if not communication_context:
        raise RuntimeError(
            "Research report does not contain communication-relevant sections."
        )

    # Keep the communication pass deliberately small. The full research report
    # can be thousands of words, while this gate only needs unresolved intent
    # and the recommended next step.
    communication_context = communication_context[:12000]

    # Maintainer communication analysis is reasoning-heavy: use the heavy
    # route (OmniRoute when available, else the existing 3B fallback). When
    # routing defers, raise exactly as before.
    execution_ok, selected_model, execution_reason, provider_config = (
        get_hermes_execution_handoff(task_type="heavy")
    )
    if not execution_ok:
        raise RuntimeError(f"Hermes unavailable for communication analysis: {execution_reason}")

    prompt = f"""You are the communication gate for OSS Discovery Radar.

Your job is NOT to implement the issue and NOT to contact GitHub.

Based only on the issue context and research report below, determine
whether the contributor should contact the maintainer before beginning
implementation.

Return ONLY this Markdown structure:

## Recommendation
One of:
- ASK_MAINTAINER
- NO_CLARIFICATION_NEEDED

## Suggested Reply
A concise, polite GitHub issue comment. Do not claim work was completed.
Do not claim facts that are not supported by the research.

## Reason
Explain why this communication step is or is not necessary.

## Questions
List the specific questions the contributor should ask, or write:
- None

## Implementation Gate
One of:
- BLOCK_UNTIL_REPLY
- MAY_PROCEED

CRITICAL:
- Treat [FACT] as evidence.
- Treat [INFERENCE] as a deduction, not a fact.
- Treat [UNCERTAINTY] as unresolved.
- Prefer asking the maintainer when the recommended implementation depends
  on unresolved maintainer intent, product direction, release targeting,
  scope, or architectural choice.
- Check whether maintainers have already made decisions or answered questions in the issue discussion before concluding that clarification is needed.
- Do not invent maintainer preferences.
- Do not send the reply.

ISSUE:
Repository: {issue['repo_name']}
Title: {issue['title']}
URL: {issue['url']}
Discussion & Context: {issue.get('discussion_context') or issue.get('body_preview') or 'No description available.'}

COMMUNICATION-RELEVANT RESEARCH:
{communication_context}
"""

    response = run_hermes_oneshot(
        prompt,
        safe_mode=True,
        model=selected_model,
        **_oneshot_provider_kwargs(provider_config),
    ).strip()

    if not response:
        raise RuntimeError("Hermes returned an empty communication recommendation.")

    lines = response.splitlines()
    section = None
    sections = {
        "Recommendation": [],
        "Suggested Reply": [],
        "Reason": [],
        "Questions": [],
        "Implementation Gate": [],
    }

    for line in lines:
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if section in sections:
            sections[section].append(line)

    recommendation_text = "\n".join(sections["Recommendation"]).strip()
    reply = "\n".join(sections["Suggested Reply"]).strip()
    reason = "\n".join(sections["Reason"]).strip()
    gate = "\n".join(sections["Implementation Gate"]).strip()

    if "ASK_MAINTAINER" in recommendation_text:
        status = "REVIEW_REQUIRED"
    elif "NO_CLARIFICATION_NEEDED" in recommendation_text:
        status = "NOT_REQUIRED"
    else:
        raise RuntimeError(f"Hermes returned an invalid communication recommendation:\n{response}")

    if "BLOCK_UNTIL_REPLY" not in gate and "MAY_PROCEED" not in gate:
        raise RuntimeError("Hermes returned an invalid implementation gate.")

    if not reply:
        reply = "No maintainer reply is recommended."
    if not reason:
        reason = "No additional reason was provided."
    if sections["Questions"]:
        reason = f"{reason}\n\nQuestions:\n" + "\n".join(sections["Questions"]).strip()

    if status == "NOT_REQUIRED" and "MAY_PROCEED" not in gate:
        status = "REVIEW_REQUIRED"

    set_communication_recommendation(
        issue_url,
        reply,
        reason,
        status,
    )

    return {
        "status": status,
        "recommendation": reply,
        "reason": reason,
        "implementation_gate": gate,
        "model": selected_model,
        "research_file": str(research_file),
    }
