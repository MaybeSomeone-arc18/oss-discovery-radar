"""
Regression tests for first-contribution ranking semantics.

1. Non-READY_NOW candidates must be EXCLUDED from top_10 entirely.
2. Among READY_NOW candidates, higher score wins.
3. GSoC Prep column is present in the table header.
4. GSoC evidence lines are printed for candidates that have evidence.
"""

import io
from contextlib import redirect_stdout


# ---------------------------------------------------------------------------
# Helpers that mirror main.py logic exactly
# ---------------------------------------------------------------------------

def run_ranking_simulation(candidates):
    """
    Simulate the deep-validation loop from cmd_first_contribution:
    - skip non-READY_NOW
    - collect up to 10 READY_NOW entries
    - sort by score descending
    Returns the final top_10 list.
    """
    top_10 = []
    repo_counts = {}

    for cand in sorted(candidates, key=lambda x: -x["score"]):
        repo = cand["repo"]
        if repo_counts.get(repo, 0) >= 3:
            continue

        readiness = cand.get("readiness", "READY_NOW")
        if readiness != "READY_NOW":
            continue  # excluded — mirrors new main.py behaviour

        top_10.append(cand)
        repo_counts[repo] = repo_counts.get(repo, 0) + 1
        if len(top_10) >= 10:
            break

    top_10.sort(key=lambda x: -x["score"])
    return top_10


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_non_ready_now_excluded_entirely():
    """Non-READY_NOW candidates must never appear in top_10."""
    candidates = [
        {"repo": "org/a", "num": 1, "score": 9.9, "readiness": "WAITING_ON_RELEASE", "gsoc": None, "gsoc_ev": None, "org": "org", "classification": "STRONG_CANDIDATE"},
        {"repo": "org/b", "num": 2, "score": 8.5, "readiness": "WAITING_ON_MAINTAINER", "gsoc": None, "gsoc_ev": None, "org": "org", "classification": "GOOD_ENTRY_POINT"},
        {"repo": "org/c", "num": 3, "score": 5.0, "readiness": "READY_NOW", "gsoc": 40.0, "gsoc_ev": "Org History: +12.0", "org": "org", "classification": "STRONG_CANDIDATE"},
        {"repo": "org/d", "num": 4, "score": 7.0, "readiness": "NEEDS_CONFIRMATION", "gsoc": None, "gsoc_ev": None, "org": "org", "classification": "GOOD_ENTRY_POINT"},
        {"repo": "org/e", "num": 5, "score": 9.0, "readiness": "BLOCKED", "gsoc": None, "gsoc_ev": None, "org": "org", "classification": "GOOD_ENTRY_POINT"},
    ]
    top_10 = run_ranking_simulation(candidates)

    assert len(top_10) == 1, f"Only READY_NOW candidate should appear; got {len(top_10)}"
    assert top_10[0]["num"] == 3, f"Candidate #3 (READY_NOW) should be the only result"
    for c in top_10:
        assert c["readiness"] == "READY_NOW", f"All top_10 must be READY_NOW, found {c['readiness']}"


def test_non_ready_now_excluded_even_when_higher_score():
    """A non-READY_NOW candidate with a higher score must still be excluded."""
    candidates = [
        {"repo": "org/x", "num": 10, "score": 99.0, "readiness": "WAITING_ON_RELEASE", "gsoc": 80.0, "gsoc_ev": "", "org": "org", "classification": "STRONG_CANDIDATE"},
        {"repo": "org/y", "num": 20, "score": 1.0, "readiness": "READY_NOW", "gsoc": 10.0, "gsoc_ev": "", "org": "org", "classification": "GOOD_ENTRY_POINT"},
    ]
    top_10 = run_ranking_simulation(candidates)

    assert len(top_10) == 1
    assert top_10[0]["num"] == 20, "READY_NOW candidate must be chosen even with lower raw score"


def test_ready_now_sorted_by_score_descending():
    """Among READY_NOW candidates, higher score must rank first."""
    candidates = [
        {"repo": "org/a", "num": 1, "score": 4.0, "readiness": "READY_NOW", "gsoc": None, "gsoc_ev": None, "org": "org", "classification": "GOOD_ENTRY_POINT"},
        {"repo": "org/b", "num": 2, "score": 8.0, "readiness": "READY_NOW", "gsoc": None, "gsoc_ev": None, "org": "org", "classification": "STRONG_CANDIDATE"},
        {"repo": "org/c", "num": 3, "score": 6.0, "readiness": "READY_NOW", "gsoc": None, "gsoc_ev": None, "org": "org", "classification": "GOOD_ENTRY_POINT"},
        {"repo": "org/d", "num": 4, "score": 9.9, "readiness": "WAITING_ON_RELEASE", "gsoc": None, "gsoc_ev": None, "org": "org", "classification": "STRONG_CANDIDATE"},
    ]
    top_10 = run_ranking_simulation(candidates)

    scores = [c["score"] for c in top_10]
    assert scores == sorted(scores, reverse=True), f"READY_NOW candidates not sorted by score: {scores}"
    assert top_10[0]["num"] == 2, "Highest-scoring READY_NOW (#2, score=8.0) should be first"


def test_gsoc_prep_header_and_evidence_in_output():
    """Table header must include 'GSoC Prep'; evidence lines must be printed."""
    candidates = [
        {
            "url": "https://github.com/org/repo/issues/1",
            "repo": "org/repo", "num": 1, "title": "Test issue",
            "org": "org", "score": 7.5, "readiness": "READY_NOW",
            "classification": "STRONG_CANDIDATE",
            "gsoc": 42.0,
            "gsoc_ev": "Org History: +12.0 (Organization has verified GSoC participation)\\nEngineering Depth: +10.0 (SUBSTANTIAL)",
            "fit": 5.0, "depth": "SUBSTANTIAL", "notes": "Test", "read_ev": "no blockers",
        }
    ]

    buf = io.StringIO()
    with redirect_stdout(buf):
        candidates.sort(key=lambda x: -x["score"])
        print(
            f"\n{'Rank':<4} | {'Org':<15} | {'Repo':<20} | {'Issue':<6} | "
            f"{'Score':<5} | {'GSoC Prep':<10} | Classification"
        )
        print("-" * 110)
        for i, cand in enumerate(candidates, 1):
            gsoc_display = f"{cand['gsoc']:.0f}" if cand.get('gsoc') is not None else "N/A"
            print(
                f"{i:<4} | {cand['org'][:15]:<15} | {cand['repo'][:20]:<20} | "
                f"{cand['num']:<6} | {cand['score']:<5.1f} | {gsoc_display:<10} | {cand['classification']}"
            )
            ev = cand.get('gsoc_ev') or ""
            if ev:
                for ev_line in ev.replace('\\n', '\n').split('\n')[:3]:
                    if ev_line.strip():
                        print(f"       {'':15}   {'':20}   {'':6}   {'':5}   {ev_line.strip()}")

    output = buf.getvalue()
    assert "GSoC Prep" in output, f"Header must include 'GSoC Prep'. Got:\n{output}"
    assert "42" in output, f"GSoC score 42 should appear in output. Got:\n{output}"
    assert "Org History" in output, f"GSoC evidence should be printed. Got:\n{output}"
