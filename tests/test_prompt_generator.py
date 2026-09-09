import pytest
from unittest.mock import patch, MagicMock
from src.prompt_generator import generate_implementation_prompt

@patch('src.prompt_generator.get_issue_context')
@patch('src.prompt_generator.get_repo_analysis')
@patch('src.prompt_generator.get_reports_dir')
@patch('pathlib.Path.exists')
@patch('builtins.open')
def test_generate_implementation_prompt_all_data(mock_open, mock_exists, mock_get_reports_dir, mock_get_repo_analysis, mock_get_issue_context):
    mock_get_issue_context.return_value = {
        'repo_name': 'org/repo',
        'org_slug': 'org',
        'title': 'Test Issue',
        'body_preview': 'Fix a bug',
        'labels': 'bug, help wanted',
        'url': 'https://github.com/org/repo/issues/123'
    }
    mock_get_repo_analysis.return_value = {
        'pr_patterns': 'Use conventional commits',
        'build_systems': 'Maven',
        'test_frameworks': 'JUnit'
    }
    
    mock_dir = MagicMock()
    mock_file = MagicMock()
    mock_file.exists.return_value = True
    
    mock_file_open = MagicMock()
    mock_file_open.__enter__.return_value.read.side_effect = ["Research contents", "Plan contents"]
    mock_open.return_value = mock_file_open
    
    mock_dir.__truediv__.return_value = mock_file
    mock_get_reports_dir.return_value = mock_dir
    
    prompt = generate_implementation_prompt(123)
    
    assert "# Implementation Task: org/repo#123" in prompt
    assert "**Title:** Test Issue" in prompt
    assert "**Labels:** bug, help wanted" in prompt
    assert "Fix a bug" in prompt
    assert "**Build Systems:** Maven" in prompt
    assert "**Test Frameworks:** JUnit" in prompt
    assert "**Conventions/PR Patterns:** Use conventional commits" in prompt
    assert "Research contents" in prompt
    assert "Plan contents" in prompt
    assert "- **ISOLATION:** You MUST work ONLY in the isolated worktree" in prompt
    assert "- **NO EXTERNAL WRITES:** DO NOT push to GitHub" in prompt

@patch('src.prompt_generator.get_issue_context')
def test_generate_implementation_prompt_not_found(mock_get_issue_context):
    mock_get_issue_context.return_value = None
    prompt = generate_implementation_prompt(999)
    assert "Error: Issue 999 not found" in prompt

@patch('src.prompt_generator.get_issue_context')
@patch('src.prompt_generator.get_repo_analysis')
@patch('src.prompt_generator.get_reports_dir')
@patch('pathlib.Path.exists')
def test_generate_implementation_prompt_missing_data(mock_exists, mock_get_reports_dir, mock_get_repo_analysis, mock_get_issue_context):
    mock_get_issue_context.return_value = {
        'repo_name': 'org/repo',
        'org_slug': 'org',
        'title': 'Test Issue',
        'url': 'https://github.com/org/repo/issues/123'
    }
    mock_get_repo_analysis.return_value = None
    mock_dir = MagicMock()
    mock_file = MagicMock()
    mock_file.exists.return_value = False
    mock_dir.__truediv__.return_value = mock_file
    mock_get_reports_dir.return_value = mock_dir
    
    prompt = generate_implementation_prompt(123)
    
    assert "*(No repository analysis available)*" in prompt
    assert "*(No automated research available)*" in prompt
    assert "*(No automated plan available)*" in prompt
