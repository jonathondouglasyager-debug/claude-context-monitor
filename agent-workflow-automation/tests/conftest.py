"""
Convergence Engine - Test Configuration

Shared fixtures and helpers for the test suite.
All tests run in sandbox mode with mock data.
"""

import json
import os
import shutil
import tempfile

import pytest

# Ensure agents package is importable
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def tmp_project(tmp_path):
    """
    Create a temporary project directory with the expected structure.
    Returns the path to the temp project root.
    """
    # Create directory structure
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "research").mkdir()
    (tmp_path / "convergence").mkdir()
    (tmp_path / "convergence" / "archive").mkdir()

    # Create a config.json with sandbox mode enabled
    config = {
        "error_learning": {"enabled": True},
        "convergence": {
            "enabled": True,
            "auto_research": True,
            "auto_converge_on_session_end": True,
            "min_issues_for_convergence": 1,
            "sandbox_mode": True,
            "budget": {
                "max_parallel_agents": 2,
                "max_tokens_per_agent": 4000,
                "max_research_rounds": 3,
                "timeout_seconds": 10,
                "model_map": {
                    "research": "default",
                    "debate": "default",
                    "converge": "default"
                },
                "fallback_model": "haiku"
            },
            "sanitizer": {
                "enabled": True,
                "strip_paths": True,
                "strip_tokens": True,
                "strip_usernames": True
            }
        }
    }

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config, indent=2))

    return tmp_path


@pytest.fixture
def sample_issue():
    """Return a valid sample issue record."""
    return {
        "id": "issue_20260216_120000_test",
        "type": "error",
        "timestamp": "2026-02-16T12:00:00Z",
        "description": "Tool 'Bash' failed: npm ERR! Could not resolve dependency",
        "status": "captured",
        "source": "hook:PostToolUseFailure",
        "tool_name": "Bash",
        "git_branch": "main",
        "recent_files": ["package.json"],
        "working_directory": "/test/project",
        "raw_error": "npm ERR! Could not resolve dependency",
    }


@pytest.fixture
def mock_data_dir():
    """Return path to the tests/mock_data/ directory."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_data")
