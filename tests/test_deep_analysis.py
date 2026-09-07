import pytest
from src.deep_analysis import (
    classify_issue_quality,
    classify_contribution_type,
    estimate_engineering_depth,
    calculate_gsoc_score,
    find_likely_files
)

def test_classify_issue_quality():
    assert classify_issue_quality("Small issue", "fix it") == "VAGUE"
    assert classify_issue_quality("Bigger issue", "a" * 150) == "PARTIALLY_DEFINED"
    assert classify_issue_quality("Good issue", "a" * 550 + "```python\nprint(1)\n```") == "CLEAR"

def test_classify_contribution_type():
    assert classify_contribution_type(["bug"], "Crash on startup") == "BUG_FIX"
    assert classify_contribution_type(["documentation"], "Fix typo in readme") == "DOCUMENTATION"
    assert classify_contribution_type([], "Refactor the database module") == "REFACTOR"

def test_estimate_engineering_depth():
    assert estimate_engineering_depth("Fix typo", "typo here", []) == "TRIVIAL"
    assert estimate_engineering_depth("Refactor database", "", []) == "MEDIUM"
    assert estimate_engineering_depth("Fix race condition in thread pool", "concurrency issue", []) == "SUBSTANTIAL"
    assert estimate_engineering_depth("Add new button", "", []) == "SMALL"

def test_calculate_gsoc_score():
    # TRIVIAL docs should be penalized heavily
    assert calculate_gsoc_score("TRIVIAL", "DOCUMENTATION") == 0.0
    
    # SUBSTANTIAL bug fix should be highly rewarded
    assert calculate_gsoc_score("SUBSTANTIAL", "BUG_FIX") >= 100.0
    
    # MEDIUM feature should be good
    assert calculate_gsoc_score("MEDIUM", "FEATURE") == 90.0

def test_find_likely_files():
    files = find_likely_files("Please update src/database.py and tests/test_deep.cpp!")
    assert "src/database.py" in files
    assert "tests/test_deep.cpp" in files
    
    # ensure it doesn't match normal periods
    files2 = find_likely_files("This is a sentence. It ends here.")
    assert len(files2) == 0
