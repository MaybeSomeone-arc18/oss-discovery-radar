from pathlib import Path

from src.autonomous_guard import get_hermes_execution_plan
from src.hermes_agent import get_issue_context, get_reports_dir, run_hermes_oneshot
from src.opportunity_manager import set_communication_recommendation


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

    def extract_section(name):
        marker = f"## {name}"
        start = research_content.find(marker)
        if start == -1:
            return ""
        start += len(marker)
        end = research_content.find("\n## ", start)
        if end == -1:
            end = len(research_content)
        return research_content[start:end].strip()

    relevant_sections = []
    for name in (
        "Questions for Maintainers",
        "Recommended Next Step",
        "Constraints",
        "Unknowns",
    ):
        content = extract_section(name)
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
    # route (OmniRoute when available, else the existing 3B fallback).
    execution_ok, selected_model, execution_reason = get_hermes_execution_plan(
        task_type="heavy"
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
- Do not invent maintainer preferences.
- Do not send the reply.

ISSUE:
Repository: {issue['repo_name']}
Title: {issue['title']}
URL: {issue['url']}
Description: {issue.get('body_preview') or 'No description available.'}

COMMUNICATION-RELEVANT RESEARCH:
{communication_context}
"""

    response = run_hermes_oneshot(
        prompt,
        safe_mode=True,
        model=selected_model,
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
        raise RuntimeError("Hermes returned an invalid communication recommendation.")

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
    )

    return {
        "status": status,
        "recommendation": reply,
        "reason": reason,
        "implementation_gate": gate,
        "model": selected_model,
        "research_file": str(research_file),
    }
