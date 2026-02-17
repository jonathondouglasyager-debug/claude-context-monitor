"""Tests for convergence output integrity."""

import json
import os
import pytest

from agents.arbiter import _parse_convergence_output, _archive_previous_convergence


class TestParseConvergenceOutput:
    def test_parses_valid_output(self):
        raw = """===CONVERGENCE_REPORT===

# Convergence Report -- 2026-02-16

## Session Summary
Issues analyzed: 2 | Resolved: 0 | Pending: 2

### Issue: Module not found
- **Root Cause:** Missing dependency
- **Confidence:** high
- **Recommended Fix:** Install the package
- **Priority:** P1
- **Tasks Generated:** 1

## Cross-Issue Patterns
- Both issues relate to dependency management

## Recommended Action Order
1. Fix module import first

===TASKS_JSON===

[
  {
    "title": "Install missing button component",
    "description": "Run npx shadcn add button",
    "issue_id": "issue_001",
    "priority": "P1",
    "complexity": "low",
    "files_likely_affected": ["components/ui/button.tsx"],
    "suggested_approach": "Use shadcn CLI"
  }
]"""

        report, tasks = _parse_convergence_output(raw)

        assert "Convergence Report" in report
        assert "Session Summary" in report
        assert len(tasks) == 1
        assert tasks[0]["title"] == "Install missing button component"
        assert tasks[0]["id"] == "task_001"  # Auto-assigned
        assert tasks[0]["status"] == "pending"  # Auto-assigned

    def test_handles_missing_delimiters(self):
        raw = "Just some text without proper delimiters"
        report, tasks = _parse_convergence_output(raw)
        assert report == raw
        assert tasks == []

    def test_handles_malformed_json(self):
        raw = """===CONVERGENCE_REPORT===

# Report

===TASKS_JSON===

not valid json at all
"""
        report, tasks = _parse_convergence_output(raw)
        assert "Report" in report
        assert tasks == []  # Graceful fallback
        assert "Task extraction failed" in report

    def test_assigns_sequential_task_ids(self):
        raw = """===CONVERGENCE_REPORT===
Report
===TASKS_JSON===
[
  {"title": "Task A", "priority": "P1"},
  {"title": "Task B", "priority": "P2"},
  {"title": "Task C", "priority": "P3"}
]"""
        _, tasks = _parse_convergence_output(raw)
        assert len(tasks) == 3
        assert tasks[0]["id"] == "task_001"
        assert tasks[1]["id"] == "task_002"
        assert tasks[2]["id"] == "task_003"


class TestConvergenceDocStructure:
    """Verify convergence.md has required sections when properly generated."""

    def test_report_has_required_sections(self):
        # Simulate a well-formed report
        raw = """===CONVERGENCE_REPORT===

# Convergence Report -- 2026-02-16

## Session Summary
Issues analyzed: 1

### Issue: Test
- **Root Cause:** Test root cause
- **Confidence:** high
- **Recommended Fix:** Fix it
- **Priority:** P1
- **Tasks Generated:** 1

## Cross-Issue Patterns
- None

## Recommended Action Order
1. Fix it

===TASKS_JSON===
[{"title": "Fix", "priority": "P1"}]
"""
        report, _ = _parse_convergence_output(raw)
        assert "## Session Summary" in report
        assert "## Cross-Issue Patterns" in report
        assert "## Recommended Action Order" in report


class TestTasksJsonSchema:
    """Verify tasks.json records have the expected structure."""

    def test_task_has_required_fields(self):
        raw = """===CONVERGENCE_REPORT===
Report
===TASKS_JSON===
[{
  "title": "Fix the thing",
  "description": "Detailed description",
  "issue_id": "issue_001",
  "priority": "P1",
  "complexity": "low",
  "files_likely_affected": ["file.ts"],
  "suggested_approach": "Do this"
}]"""
        _, tasks = _parse_convergence_output(raw)
        task = tasks[0]

        assert "id" in task
        assert "status" in task
        assert task["title"] == "Fix the thing"
        assert task["priority"] == "P1"
        assert task["complexity"] == "low"
        assert isinstance(task["files_likely_affected"], list)
