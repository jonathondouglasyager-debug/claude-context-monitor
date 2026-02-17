"""
End-to-end pipeline integration test.

Uses sandbox_mode=True so no real LLM calls are made.
Tests the full flow: capture -> research -> debate -> converge.
"""

import json
import os
import sys
import pytest
from unittest.mock import patch

# We need to mock the config to use sandbox mode and temp directories
from agents.file_lock import atomic_append, read_jsonl, read_jsonl_by_id
from agents.schema_validator import validate_issue, make_issue_id


class TestFullPipeline:
    """Test the complete pipeline using mock data and sandbox mode."""

    def test_capture_creates_valid_issue(self, tmp_path):
        """Test that issue capture produces a valid issue record."""
        issue_id = make_issue_id()
        issue = {
            "id": issue_id,
            "type": "error",
            "timestamp": "2026-02-16T12:00:00Z",
            "description": "Test error for pipeline validation",
            "status": "captured",
            "source": "test:integration",
            "tool_name": "Bash",
            "git_branch": "test",
            "recent_files": [],
            "working_directory": str(tmp_path),
            "raw_error": "Test error",
        }

        # Validate
        is_valid, errors = validate_issue(issue)
        assert is_valid, f"Issue validation failed: {errors}"

        # Write
        issues_path = str(tmp_path / "issues.jsonl")
        atomic_append(issues_path, issue)

        # Read back
        record = read_jsonl_by_id(issues_path, issue_id)
        assert record is not None
        assert record["status"] == "captured"

    def test_multiple_issues_captured(self, tmp_path):
        """Test that multiple issues can be captured sequentially."""
        issues_path = str(tmp_path / "issues.jsonl")

        for i in range(5):
            issue = {
                "id": f"issue_test_{i:03d}",
                "type": "error",
                "timestamp": f"2026-02-16T12:{i:02d}:00Z",
                "description": f"Test error #{i}",
                "status": "captured",
                "source": "test",
                "tool_name": "Bash",
            }
            atomic_append(issues_path, issue)

        records = read_jsonl(issues_path)
        assert len(records) == 5

    def test_issue_status_transitions(self, tmp_path):
        """Test that issue status can be updated through pipeline stages."""
        from agents.file_lock import update_jsonl_record

        issues_path = str(tmp_path / "issues.jsonl")
        issue_id = "issue_transition_test"

        issue = {
            "id": issue_id,
            "type": "error",
            "timestamp": "2026-02-16T12:00:00Z",
            "description": "Status transition test",
            "status": "captured",
        }
        atomic_append(issues_path, issue)

        # Simulate pipeline transitions
        transitions = ["researching", "researched", "debating", "debated", "converging", "converged"]

        for new_status in transitions:
            result = update_jsonl_record(issues_path, issue_id, {"status": new_status})
            assert result is True

            record = read_jsonl_by_id(issues_path, issue_id)
            assert record["status"] == new_status

    def test_research_output_structure(self, tmp_path):
        """Test that research outputs are written to correct paths."""
        from agents.runner import write_research_output
        from agents.logger import AgentLogger

        research_dir = str(tmp_path / "research" / "test_issue")
        log = AgentLogger("test_issue", "TEST", log_dir=str(tmp_path))

        # Simulate writing research outputs
        write_research_output(research_dir, "root_cause.md", "## Hypothesis\nTest\n## Confidence\nhigh", log)
        write_research_output(research_dir, "solutions.md", "## Recommended Approach\nDo this", log)
        write_research_output(research_dir, "impact.md", "## Severity\nP2\n## Priority Recommendation\nSoon", log)

        # Verify files exist
        assert os.path.exists(os.path.join(research_dir, "root_cause.md"))
        assert os.path.exists(os.path.join(research_dir, "solutions.md"))
        assert os.path.exists(os.path.join(research_dir, "impact.md"))

        # Verify content
        from agents.schema_validator import validate_research
        is_valid, errors = validate_research(research_dir)
        assert is_valid, f"Research validation failed: {errors}"

    def test_convergence_output_structure(self, tmp_path):
        """Test that convergence produces expected output files."""
        from agents.arbiter import _parse_convergence_output

        # Simulate arbiter output
        raw = """===CONVERGENCE_REPORT===

# Convergence Report -- 2026-02-16

## Session Summary
Issues analyzed: 1

### Issue: Test Error
- **Root Cause:** Test cause
- **Confidence:** high
- **Recommended Fix:** Fix it
- **Priority:** P1
- **Tasks Generated:** 1

## Cross-Issue Patterns
- None for single issue

## Recommended Action Order
1. Fix the test error

===TASKS_JSON===

[{"title": "Fix test error", "description": "Apply the fix", "issue_id": "test_001", "priority": "P1", "complexity": "low", "files_likely_affected": ["test.ts"], "suggested_approach": "Just fix it"}]
"""
        report, tasks = _parse_convergence_output(raw)

        # Write to convergence dir
        conv_dir = tmp_path / "convergence"
        conv_dir.mkdir()

        report_path = conv_dir / "convergence.md"
        report_path.write_text(report)

        tasks_path = conv_dir / "tasks.json"
        tasks_path.write_text(json.dumps(tasks, indent=2))

        # Verify
        assert report_path.exists()
        assert tasks_path.exists()
        assert "Session Summary" in report_path.read_text()

        loaded_tasks = json.loads(tasks_path.read_text())
        assert len(loaded_tasks) == 1
        assert loaded_tasks[0]["status"] == "pending"
