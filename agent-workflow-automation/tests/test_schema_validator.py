"""Tests for agents/schema_validator.py"""

import json
import os
import pytest

from agents.schema_validator import validate_issue, validate_research, make_issue_id


class TestValidateIssue:
    def test_valid_issue_passes(self, sample_issue):
        is_valid, errors = validate_issue(sample_issue)
        assert is_valid is True
        assert errors == []

    def test_missing_required_field_fails(self, sample_issue):
        del sample_issue["id"]
        is_valid, errors = validate_issue(sample_issue)
        assert is_valid is False
        assert any("id" in e for e in errors)

    def test_missing_multiple_fields(self):
        is_valid, errors = validate_issue({"type": "error"})
        assert is_valid is False
        assert len(errors) >= 3  # Missing id, timestamp, description, status

    def test_wrong_type_for_field(self, sample_issue):
        sample_issue["id"] = 12345  # Should be str
        is_valid, errors = validate_issue(sample_issue)
        assert is_valid is False
        assert any("expected str" in e for e in errors)

    def test_invalid_status(self, sample_issue):
        sample_issue["status"] = "banana"
        is_valid, errors = validate_issue(sample_issue)
        assert is_valid is False
        assert any("Invalid status" in e for e in errors)

    def test_invalid_type(self, sample_issue):
        sample_issue["type"] = "cosmic_ray"
        is_valid, errors = validate_issue(sample_issue)
        assert is_valid is False
        assert any("Invalid type" in e for e in errors)

    def test_empty_id_fails(self, sample_issue):
        sample_issue["id"] = "   "
        is_valid, errors = validate_issue(sample_issue)
        assert is_valid is False
        assert any("empty" in e for e in errors)

    def test_invalid_timestamp(self, sample_issue):
        sample_issue["timestamp"] = "not-a-date"
        is_valid, errors = validate_issue(sample_issue)
        assert is_valid is False
        assert any("ISO 8601" in e for e in errors)

    def test_valid_statuses(self, sample_issue):
        for status in ["captured", "researching", "researched", "debating", "debated", "converged"]:
            sample_issue["status"] = status
            is_valid, _ = validate_issue(sample_issue)
            assert is_valid is True

    def test_valid_types(self, sample_issue):
        for issue_type in ["error", "warning", "failure", "manual", "unknown"]:
            sample_issue["type"] = issue_type
            is_valid, _ = validate_issue(sample_issue)
            assert is_valid is True


class TestValidateResearch:
    def test_missing_directory(self):
        is_valid, errors = validate_research("/nonexistent/path")
        assert is_valid is False
        assert any("does not exist" in e for e in errors)

    def test_valid_research_directory(self, tmp_path):
        # Create research files with required sections
        (tmp_path / "root_cause.md").write_text("## Hypothesis\nTest\n## Confidence\nhigh")
        (tmp_path / "solutions.md").write_text("## Recommended Approach\nDo this")
        (tmp_path / "impact.md").write_text("## Severity\nP2\n## Priority Recommendation\nSoon")

        is_valid, errors = validate_research(str(tmp_path))
        assert is_valid is True
        assert errors == []

    def test_missing_research_file(self, tmp_path):
        (tmp_path / "root_cause.md").write_text("## Hypothesis\nTest\n## Confidence\nhigh")
        # Missing solutions.md and impact.md

        is_valid, errors = validate_research(str(tmp_path))
        assert is_valid is False
        assert any("solutions.md" in e for e in errors)

    def test_missing_required_section(self, tmp_path):
        (tmp_path / "root_cause.md").write_text("Some text without proper sections")
        (tmp_path / "solutions.md").write_text("## Recommended Approach\nDo this")
        (tmp_path / "impact.md").write_text("## Severity\nP2\n## Priority Recommendation\nSoon")

        is_valid, errors = validate_research(str(tmp_path))
        assert is_valid is False
        assert any("Hypothesis" in e for e in errors)


class TestMakeIssueId:
    def test_format(self):
        issue_id = make_issue_id()
        assert issue_id.startswith("issue_")
        parts = issue_id.split("_")
        assert len(parts) == 4  # issue, date, time, random

    def test_uniqueness(self):
        ids = {make_issue_id() for _ in range(100)}
        assert len(ids) == 100  # All unique
