from pathlib import Path


def generate_contribution_package(reports_dir: Path, issue_id: int, *, success: bool = False, test_results=None, diff_stat: str = ""):
    summary = reports_dir / "summary.md"
    review = reports_dir / "review.md"
    implementation = reports_dir / "implementation.md"
    patch = reports_dir / "patch.diff"

    out = reports_dir / "final-report.md"

    def read(path):
        return path.read_text() if path.exists() else "Not available."

    pr_title = f"Fix issue #{issue_id}"
    status = "READY FOR HUMAN REVIEW" if success else "IMPLEMENTATION FAILED - DO NOT SUBMIT"
    tests_text = str(test_results) if test_results else "No test results recorded."

    report = f"""# Contribution Package: #{issue_id}

## Status
{status}

## Implementation
{read(implementation)}

## Review
{read(review)}

## Validation
### Test Results
{tests_text}

### Diff Stat
{diff_stat or "Not available."}

## Changed Patch
`{patch}`

## Suggested PR Title
{pr_title}

## Suggested PR Description

### Summary
See the implementation and review reports above.

### Testing
See recorded test results above.

## Suggested Commit Message
Fix issue #{issue_id}

## Human Submission Checklist
- Review `patch.diff`
- Review `review.md`
- Confirm tests and build results
- Commit locally
- Push your branch
- Open the pull request
- Paste the suggested title and description
- Respond to maintainer feedback manually

## Maintainer Communication
Do not send automatically. Review the issue/PR context and communicate with maintainers yourself.
"""

    out.write_text(report)
    return out
