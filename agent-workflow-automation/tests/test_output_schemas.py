"""
Convergence Engine - Output Schema Tests (Phase 4)

Tests for:
  1. JSON extraction from agent output (delimiter parsing)
  2. Schema validation for all agent types
  3. Markdown extraction (stripping JSON blocks)
  4. Edge cases: missing delimiters, malformed JSON, code fences
  5. Integration: write_research_json with validation
  6. validate_research_json on filesystem
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.output_schemas import (
    JSON_OUTPUT_START,
    JSON_OUTPUT_END,
    extract_json_output,
    extract_markdown_output,
    validate_against_schema,
    validate_researcher_output,
    validate_solution_output,
    validate_impact_output,
    validate_debate_output,
    validate_task,
    validate_agent_output,
    RESEARCHER_SCHEMA,
)
from agents.schema_validator import validate_research_json


# ─── JSON Extraction Tests ───────────────────────────────────────────────────


class TestExtractJsonOutput:
    """Tests for extract_json_output()."""

    def test_basic_extraction(self):
        raw = (
            "## Hypothesis\nSome analysis\n\n"
            "===JSON_OUTPUT===\n"
            '{"hypothesis": "test", "confidence": "high"}\n'
            "===JSON_OUTPUT_END==="
        )
        result = extract_json_output(raw)
        assert result is not None
        assert result["hypothesis"] == "test"
        assert result["confidence"] == "high"

    def test_extraction_with_code_fences(self):
        raw = (
            "## Analysis\n\n"
            "===JSON_OUTPUT===\n"
            "```json\n"
            '{"hypothesis": "fenced"}\n'
            "```\n"
            "===JSON_OUTPUT_END==="
        )
        result = extract_json_output(raw)
        assert result is not None
        assert result["hypothesis"] == "fenced"

    def test_extraction_without_end_delimiter(self):
        raw = (
            "## Analysis\n\n"
            "===JSON_OUTPUT===\n"
            '{"hypothesis": "no end"}\n'
        )
        result = extract_json_output(raw)
        assert result is not None
        assert result["hypothesis"] == "no end"

    def test_no_json_block(self):
        raw = "## Hypothesis\nJust markdown, no JSON block"
        result = extract_json_output(raw)
        assert result is None

    def test_malformed_json(self):
        raw = (
            "===JSON_OUTPUT===\n"
            '{"broken": json, not valid}\n'
            "===JSON_OUTPUT_END==="
        )
        result = extract_json_output(raw)
        assert result is None

    def test_empty_json_block(self):
        raw = "===JSON_OUTPUT===\n\n===JSON_OUTPUT_END==="
        result = extract_json_output(raw)
        assert result is None

    def test_list_extraction(self):
        raw = (
            "===JSON_OUTPUT===\n"
            '[{"title": "task1"}, {"title": "task2"}]\n'
            "===JSON_OUTPUT_END==="
        )
        result = extract_json_output(raw)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_nested_json(self):
        raw = (
            "===JSON_OUTPUT===\n"
            '{"solutions": [{"title": "fix", "tradeoffs": {"risk": "low"}}]}\n'
            "===JSON_OUTPUT_END==="
        )
        result = extract_json_output(raw)
        assert result["solutions"][0]["tradeoffs"]["risk"] == "low"


class TestExtractMarkdownOutput:
    """Tests for extract_markdown_output()."""

    def test_strips_json_block(self):
        raw = (
            "## Hypothesis\nAnalysis here\n\n"
            "===JSON_OUTPUT===\n"
            '{"hypothesis": "test"}\n'
            "===JSON_OUTPUT_END==="
        )
        md = extract_markdown_output(raw)
        assert "## Hypothesis" in md
        assert "Analysis here" in md
        assert "JSON_OUTPUT" not in md
        assert "hypothesis" not in md  # JSON content stripped

    def test_no_json_block(self):
        raw = "## Hypothesis\nJust markdown"
        md = extract_markdown_output(raw)
        assert md == "## Hypothesis\nJust markdown"

    def test_empty_string(self):
        assert extract_markdown_output("") == ""


# ─── Researcher Schema Validation ────────────────────────────────────────────


class TestResearcherValidation:
    """Tests for validate_researcher_output()."""

    def test_valid_output(self):
        data = {
            "hypothesis": "Missing dependency causes import failure",
            "evidence": ["Stack trace shows ModuleNotFoundError"],
            "confidence": "high",
            "confidence_reasoning": "Clear error message",
            "related_patterns": ["dependency resolution"],
        }
        is_valid, errors = validate_researcher_output(data)
        assert is_valid, errors

    def test_missing_required_field(self):
        data = {
            "hypothesis": "test",
            # missing evidence, confidence, confidence_reasoning
        }
        is_valid, errors = validate_researcher_output(data)
        assert not is_valid
        assert any("evidence" in e for e in errors)
        assert any("confidence" in e for e in errors)

    def test_invalid_confidence(self):
        data = {
            "hypothesis": "test",
            "evidence": ["e1"],
            "confidence": "very_high",  # invalid
            "confidence_reasoning": "reason",
        }
        is_valid, errors = validate_researcher_output(data)
        assert not is_valid
        assert any("confidence" in e.lower() for e in errors)

    def test_evidence_must_be_strings(self):
        data = {
            "hypothesis": "test",
            "evidence": [123, "valid"],  # 123 is not string
            "confidence": "high",
            "confidence_reasoning": "reason",
        }
        is_valid, errors = validate_researcher_output(data)
        assert not is_valid
        assert any("evidence[0]" in e for e in errors)

    def test_optional_related_patterns(self):
        data = {
            "hypothesis": "test",
            "evidence": ["e1"],
            "confidence": "low",
            "confidence_reasoning": "reason",
            # related_patterns is optional
        }
        is_valid, errors = validate_researcher_output(data)
        assert is_valid, errors


# ─── Solution Finder Schema Validation ───────────────────────────────────────


class TestSolutionValidation:
    """Tests for validate_solution_output()."""

    def test_valid_output(self):
        data = {
            "solutions": [
                {
                    "title": "Install dep",
                    "description": "npm install x",
                    "tradeoffs": {"risk": "low", "complexity": "low"},
                }
            ],
            "recommended_index": 0,
            "recommendation_reasoning": "Simplest fix",
            "implementation_steps": ["Run npm install", "Verify"],
        }
        is_valid, errors = validate_solution_output(data)
        assert is_valid, errors

    def test_recommended_index_out_of_range(self):
        data = {
            "solutions": [{"title": "Fix", "description": "do it"}],
            "recommended_index": 5,  # out of range
            "recommendation_reasoning": "reason",
            "implementation_steps": ["step"],
        }
        is_valid, errors = validate_solution_output(data)
        assert not is_valid
        assert any("out of range" in e for e in errors)

    def test_solution_item_missing_title(self):
        data = {
            "solutions": [{"description": "no title"}],  # missing title
            "recommended_index": 0,
            "recommendation_reasoning": "reason",
            "implementation_steps": ["step"],
        }
        is_valid, errors = validate_solution_output(data)
        assert not is_valid
        assert any("title" in e for e in errors)

    def test_implementation_steps_must_be_strings(self):
        data = {
            "solutions": [{"title": "Fix", "description": "do it"}],
            "recommended_index": 0,
            "recommendation_reasoning": "reason",
            "implementation_steps": [1, 2, 3],  # not strings
        }
        is_valid, errors = validate_solution_output(data)
        assert not is_valid


# ─── Impact Assessor Schema Validation ───────────────────────────────────────


class TestImpactValidation:
    """Tests for validate_impact_output()."""

    def test_valid_output(self):
        data = {
            "severity": "P2",
            "severity_reasoning": "Blocks one feature",
            "scope": "module",
            "scope_detail": "Affects auth module",
            "frequency": "first",
            "frequency_detail": "First occurrence",
            "priority": "soon",
            "priority_reasoning": "Not critical but should fix",
        }
        is_valid, errors = validate_impact_output(data)
        assert is_valid, errors

    def test_invalid_severity(self):
        data = {
            "severity": "critical",  # invalid, should be P0-P3
            "severity_reasoning": "reason",
            "scope": "module",
            "scope_detail": "detail",
            "frequency": "first",
            "priority": "now",
            "priority_reasoning": "reason",
        }
        is_valid, errors = validate_impact_output(data)
        assert not is_valid
        assert any("severity" in e.lower() for e in errors)

    def test_invalid_scope(self):
        data = {
            "severity": "P1",
            "severity_reasoning": "reason",
            "scope": "global",  # invalid
            "scope_detail": "detail",
            "frequency": "first",
            "priority": "now",
            "priority_reasoning": "reason",
        }
        is_valid, errors = validate_impact_output(data)
        assert not is_valid
        assert any("scope" in e.lower() for e in errors)

    def test_invalid_frequency(self):
        data = {
            "severity": "P3",
            "severity_reasoning": "reason",
            "scope": "isolated",
            "scope_detail": "detail",
            "frequency": "sometimes",  # invalid
            "priority": "later",
            "priority_reasoning": "reason",
        }
        is_valid, errors = validate_impact_output(data)
        assert not is_valid

    def test_optional_frequency_detail(self):
        data = {
            "severity": "P2",
            "severity_reasoning": "reason",
            "scope": "module",
            "scope_detail": "detail",
            "frequency": "first",
            # frequency_detail is optional
            "priority": "soon",
            "priority_reasoning": "reason",
        }
        is_valid, errors = validate_impact_output(data)
        assert is_valid, errors


# ─── Debate Schema Validation ────────────────────────────────────────────────


class TestDebateValidation:
    """Tests for validate_debate_output()."""

    def test_valid_output(self):
        data = {
            "agreements": ["Root cause is dependency issue"],
            "contradictions": [],
            "gaps": ["No one checked if intentionally removed"],
            "revised_root_cause": "Missing dep in package.json",
            "revised_fix": "npm install x",
            "revised_priority": "P2",
        }
        is_valid, errors = validate_debate_output(data)
        assert is_valid, errors

    def test_invalid_priority(self):
        data = {
            "agreements": ["a"],
            "contradictions": [],
            "gaps": [],
            "revised_root_cause": "cause",
            "revised_fix": "fix",
            "revised_priority": "urgent",  # invalid
        }
        is_valid, errors = validate_debate_output(data)
        assert not is_valid
        assert any("revised_priority" in e for e in errors)

    def test_with_contradiction_objects(self):
        data = {
            "agreements": ["a"],
            "contradictions": [
                {"description": "severity mismatch", "better_supported": "P2 from impact agent"}
            ],
            "gaps": [],
            "revised_root_cause": "cause",
            "revised_fix": "fix",
            "revised_priority": "P1",
        }
        is_valid, errors = validate_debate_output(data)
        assert is_valid, errors


# ─── Task Schema Validation ──────────────────────────────────────────────────


class TestTaskValidation:
    """Tests for validate_task()."""

    def test_valid_task(self):
        data = {
            "title": "Fix auth timeout",
            "description": "Increase timeout to 30s",
            "issue_id": "issue_123",
            "priority": "P1",
            "complexity": "low",
            "files_likely_affected": ["src/auth.py"],
            "suggested_approach": "Change timeout config",
        }
        is_valid, errors = validate_task(data)
        assert is_valid, errors

    def test_invalid_complexity(self):
        data = {
            "title": "Fix",
            "description": "desc",
            "issue_id": "issue_123",
            "priority": "P2",
            "complexity": "trivial",  # invalid
        }
        is_valid, errors = validate_task(data)
        assert not is_valid
        assert any("complexity" in e for e in errors)


# ─── Generic Validation ──────────────────────────────────────────────────────


class TestValidateAgentOutput:
    """Tests for the generic validate_agent_output() dispatcher."""

    def test_unknown_agent(self):
        is_valid, errors = validate_agent_output("nonexistent_agent", {})
        assert not is_valid
        assert any("Unknown agent" in e for e in errors)

    def test_dispatches_correctly(self):
        data = {
            "hypothesis": "test",
            "evidence": ["e"],
            "confidence": "low",
            "confidence_reasoning": "r",
        }
        is_valid, errors = validate_agent_output("researcher", data)
        assert is_valid, errors

    def test_not_a_dict(self):
        is_valid, errors = validate_against_schema("not a dict", RESEARCHER_SCHEMA, "test")
        assert not is_valid
        assert any("Expected dict" in e for e in errors)


# ─── Filesystem-Level JSON Validation ────────────────────────────────────────


class TestValidateResearchJson:
    """Tests for validate_research_json() on actual files."""

    def test_valid_json_files(self, tmp_path):
        research_dir = str(tmp_path)

        # Write valid root_cause.json
        with open(os.path.join(research_dir, "root_cause.json"), "w") as f:
            json.dump({
                "hypothesis": "test",
                "evidence": ["e1"],
                "confidence": "high",
                "confidence_reasoning": "clear error",
            }, f)

        # Write valid impact.json
        with open(os.path.join(research_dir, "impact.json"), "w") as f:
            json.dump({
                "severity": "P2",
                "severity_reasoning": "reason",
                "scope": "module",
                "scope_detail": "detail",
                "frequency": "first",
                "priority": "soon",
                "priority_reasoning": "reason",
            }, f)

        is_valid, errors = validate_research_json(research_dir)
        assert is_valid, errors

    def test_invalid_json_file(self, tmp_path):
        research_dir = str(tmp_path)

        # Write invalid JSON
        with open(os.path.join(research_dir, "root_cause.json"), "w") as f:
            f.write("{broken json")

        is_valid, errors = validate_research_json(research_dir)
        assert not is_valid
        assert any("Invalid JSON" in e for e in errors)

    def test_schema_violation(self, tmp_path):
        research_dir = str(tmp_path)

        # Write JSON that's valid JSON but fails schema
        with open(os.path.join(research_dir, "root_cause.json"), "w") as f:
            json.dump({"hypothesis": "test"}, f)  # missing required fields

        is_valid, errors = validate_research_json(research_dir)
        assert not is_valid
        assert any("evidence" in e for e in errors)

    def test_no_json_files(self, tmp_path):
        """No JSON files = valid (backward compatible with pre-Phase 4)."""
        is_valid, errors = validate_research_json(str(tmp_path))
        assert is_valid
        assert errors == []

    def test_nonexistent_dir(self):
        is_valid, errors = validate_research_json("/nonexistent/dir")
        assert is_valid
        assert errors == []


# ─── Mock Response JSON Extraction ───────────────────────────────────────────


class TestMockResponseJsonExtraction:
    """Verify that updated mock responses contain extractable JSON."""

    def test_research_mock_has_json(self):
        # Import runner to get mock responses
        from agents.runner import _default_mock_response

        mock = _default_mock_response("research")
        result = extract_json_output(mock)
        assert result is not None
        assert "hypothesis" in result
        assert "confidence" in result

    def test_solutions_mock_has_json(self):
        from agents.runner import _default_mock_response

        mock = _default_mock_response("solutions")
        result = extract_json_output(mock)
        assert result is not None
        assert "solutions" in result
        assert "recommended_index" in result

    def test_impact_mock_has_json(self):
        from agents.runner import _default_mock_response

        mock = _default_mock_response("impact")
        result = extract_json_output(mock)
        assert result is not None
        assert "severity" in result
        assert "scope" in result

    def test_debate_mock_has_json(self):
        from agents.runner import _default_mock_response

        mock = _default_mock_response("debate")
        result = extract_json_output(mock)
        assert result is not None
        assert "agreements" in result
        assert "revised_priority" in result

    def test_mock_json_validates(self):
        """All mock JSON blocks should pass their schema validation."""
        from agents.runner import _default_mock_response

        mocks = {
            "research": "researcher",
            "solutions": "solution_finder",
            "impact": "impact_assessor",
            "debate": "debater",
        }

        for stage, agent_name in mocks.items():
            mock = _default_mock_response(stage)
            data = extract_json_output(mock)
            assert data is not None, f"No JSON in {stage} mock"
            is_valid, errors = validate_agent_output(agent_name, data)
            assert is_valid, f"{agent_name} mock fails validation: {errors}"


# ─── AgentResult Integration ─────────────────────────────────────────────────


class TestAgentResultStructuredOutput:
    """Tests for AgentResult with structured_output field."""

    def test_result_with_json(self):
        from agents.runner import AgentResult

        result = AgentResult(
            success=True,
            output="## Hypothesis\nTest\n\n===JSON_OUTPUT===\n{\"hypothesis\": \"test\"}\n===JSON_OUTPUT_END===",
            structured_output={"hypothesis": "test"},
        )
        assert result.structured_output is not None
        assert result.structured_output["hypothesis"] == "test"
        assert "+JSON" in repr(result)

    def test_result_without_json(self):
        from agents.runner import AgentResult

        result = AgentResult(
            success=True,
            output="## Hypothesis\nTest",
        )
        assert result.structured_output is None
        assert "+JSON" not in repr(result)

    def test_markdown_output_property(self):
        from agents.runner import AgentResult

        result = AgentResult(
            success=True,
            output="## Hypothesis\nTest\n\n===JSON_OUTPUT===\n{\"h\": 1}\n===JSON_OUTPUT_END===",
        )
        md = result.markdown_output
        assert "## Hypothesis" in md
        assert "JSON_OUTPUT" not in md
