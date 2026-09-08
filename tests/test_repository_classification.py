import pytest
from unittest.mock import patch, MagicMock
from src.repo_classifier import classify_repository

@patch('src.repo_classifier.requests.post')
def test_normal_project(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "repository": {
                "name": "Anki-Android",
                "description": "AnkiDroid: Flashcards for Android",
                "isArchived": False,
                "isFork": False,
                "isMirror": False,
                "object": {"text": "Just a normal project"},
                "issues": {"nodes": []}
            }
        }
    }
    mock_post.return_value = mock_resp
    
    classification, eligibility, ev, up, conf = classify_repository("ankidroid/Anki-Android")
    assert classification == "NORMAL_PROJECT"
    assert eligibility == "ELIGIBLE"
    assert up is None

@patch('src.repo_classifier.requests.post')
def test_gsoc_student_repo(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "repository": {
                "name": "gsoc2026-dora-studio",
                "description": "GSoC project for dora-rs",
                "isArchived": False,
                "isFork": False,
                "isMirror": False,
                "object": {"text": "Google Summer of Code 2026"},
                "issues": {"nodes": [
                    {"title": "[Week 01] setup", "labels": {"nodes": [{"name": "gsoc"}]}},
                    {"title": "[Week 02] api", "labels": {"nodes": [{"name": "gsoc"}]}},
                    {"title": "[Week 03] tests", "labels": {"nodes": [{"name": "gsoc"}]}}
                ]}
            }
        }
    }
    mock_post.return_value = mock_resp
    
    classification, eligibility, ev, up, conf = classify_repository("dora-rs/gsoc2026-dora-studio")
    assert classification == "GSOC_PROJECT_REPOSITORY"
    assert eligibility == "BLOCKED_STUDENT_WORK_REPO"

@patch('src.repo_classifier.requests.post')
def test_fork_mirror(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "repository": {
                "name": "forked-repo",
                "isArchived": False,
                "isFork": True,
                "isMirror": False,
                "parent": {"nameWithOwner": "upstream/repo"}
            }
        }
    }
    mock_post.return_value = mock_resp
    
    classification, eligibility, ev, up, conf = classify_repository("user/forked-repo")
    assert classification == "FORK_OR_MIRROR"
    assert eligibility == "BLOCKED_FORK_OR_MIRROR"
    assert up == "upstream/repo"
    assert conf == "HIGH"

@patch('src.repo_classifier.requests.post')
def test_normal_project_with_gsoc_docs(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "repository": {
                "name": "normal-project",
                "description": "A very normal project",
                "isArchived": False,
                "isFork": False,
                "isMirror": False,
                "object": {"text": "We participate in GSoC! Apply here."},
                "issues": {"nodes": [{"title": "Bug fix", "labels": {"nodes": []}}]}
            }
        }
    }
    mock_post.return_value = mock_resp
    
    classification, eligibility, ev, up, conf = classify_repository("user/normal-project")
    assert classification == "NORMAL_PROJECT"
    assert eligibility == "ELIGIBLE"
