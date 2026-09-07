import pytest
from src import personal_fit

def test_calculate_overlap():
    text_fields = ["A cool Python project", "Uses AI and Machine Learning"]
    target_list = ["Python", "Java", "AI"]
    
    score, matches = personal_fit.calculate_overlap(text_fields, target_list)
    assert "python" in [m.lower() for m in matches]
    assert "ai" in [m.lower() for m in matches]
    assert "java" not in [m.lower() for m in matches]
    assert score > 0
    assert len(matches) == 2

def test_missing_profile_fields():
    score, matches = personal_fit.calculate_overlap(["Python"], [])
    assert score == 0
    assert len(matches) == 0

def test_score_opportunity():
    res = personal_fit.score_opportunity("Python ML System", "Building a cool ML AI tool.", "Python, C++")
    
    assert res['score'] >= 0
    assert len(res['matched_skills']) >= 0
    assert 'why_it_fits' in res
