"""
Convergence Engine - Agent Output Schemas (Phase 4)

Defines structured JSON schemas for inter-agent communication contracts.
Each agent produces both human-readable markdown AND machine-parseable JSON.
The JSON is extracted from agent output using the ===JSON_OUTPUT=== delimiter.

Inspired by MAST (arxiv 2503.13657): strict inter-agent contracts prevent
the dominant failure mode in multi-agent systems — output format drift.
"""

import json
import re
from typing import Any, Optional

# ─── JSON Output Delimiter ───────────────────────────────────────────────────
# Agents embed structured JSON in their output between these markers.
# This keeps markdown human-readable while providing machine-parseable data.
JSON_OUTPUT_START = "===JSON_OUTPUT==="
JSON_OUTPUT_END = "===JSON_OUTPUT_END==="


# ─── Schema Definitions ─────────────────────────────────────────────────────
# Each schema maps field names to (type, required) tuples.
# Nested schemas use dicts of the same structure.

RESEARCHER_SCHEMA = {
    "hypothesis": (str, True),
    "evidence": (list, True),
    "confidence": (str, True),          # high, medium, low
    "confidence_reasoning": (str, True),
    "related_patterns": (list, False),
}

SOLUTION_SCHEMA = {
    "solutions": (list, True),          # list of solution objects
    "recommended_index": (int, True),   # 0-based index into solutions
    "recommendation_reasoning": (str, True),
    "implementation_steps": (list, True),
}

SOLUTION_ITEM_SCHEMA = {
    "title": (str, True),
    "description": (str, True),
    "tradeoffs": (dict, False),         # {risk, complexity, side_effects}
}

IMPACT_SCHEMA = {
    "severity": (str, True),            # P0, P1, P2, P3
    "severity_reasoning": (str, True),
    "scope": (str, True),               # isolated, module, system
    "scope_detail": (str, True),
    "frequency": (str, True),           # first, recurring, escalating
    "frequency_detail": (str, False),
    "priority": (str, True),            # now, soon, later
    "priority_reasoning": (str, True),
}

DEBATE_SCHEMA = {
    "agreements": (list, True),
    "contradictions": (list, True),     # list of {description, better_supported}
    "gaps": (list, True),
    "revised_root_cause": (str, True),
    "revised_fix": (str, True),
    "revised_priority": (str, True),    # P0, P1, P2, P3
}

TASK_SCHEMA = {
    "title": (str, True),
    "description": (str, True),
    "issue_id": (str, True),
    "priority": (str, True),            # P0, P1, P2, P3
    "complexity": (str, True),          # low, medium, high
    "files_likely_affected": (list, False),
    "suggested_approach": (str, False),
}

# ─── Valid Enum Values ───────────────────────────────────────────────────────

VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_SEVERITY = {"P0", "P1", "P2", "P3"}
VALID_SCOPE = {"isolated", "module", "system"}
VALID_FREQUENCY = {"first", "recurring", "escalating"}
VALID_PRIORITY_ACTION = {"now", "soon", "later"}
VALID_COMPLEXITY = {"low", "medium", "high"}


# ─── Schema Name → Schema Mapping ───────────────────────────────────────────

SCHEMA_MAP = {
    "researcher": RESEARCHER_SCHEMA,
    "solution_finder": SOLUTION_SCHEMA,
    "impact_assessor": IMPACT_SCHEMA,
    "debater": DEBATE_SCHEMA,
    "task": TASK_SCHEMA,
}


# ─── Extraction ─────────────────────────────────────────────────────────────

def extract_json_output(raw_output: str) -> Optional[dict | list]:
    """
    Extract structured JSON from agent output using delimiters.

    Looks for content between ===JSON_OUTPUT=== and ===JSON_OUTPUT_END===.
    Falls back to finding a JSON block between ===JSON_OUTPUT=== and end of output
    if the end delimiter is missing.

    Args:
        raw_output: Full agent output string (markdown + JSON)

    Returns:
        Parsed JSON data (dict or list), or None if extraction fails
    """
    if JSON_OUTPUT_START not in raw_output:
        return None

    # Try with explicit end delimiter first
    if JSON_OUTPUT_END in raw_output:
        start_idx = raw_output.index(JSON_OUTPUT_START) + len(JSON_OUTPUT_START)
        end_idx = raw_output.index(JSON_OUTPUT_END)
        json_str = raw_output[start_idx:end_idx].strip()
    else:
        # Fallback: everything after the start delimiter
        start_idx = raw_output.index(JSON_OUTPUT_START) + len(JSON_OUTPUT_START)
        json_str = raw_output[start_idx:].strip()

    # Strip markdown code fences if present
    json_str = re.sub(r"^```(?:json)?\s*\n?", "", json_str)
    json_str = re.sub(r"\n?```\s*$", "", json_str)

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None


def extract_markdown_output(raw_output: str) -> str:
    """
    Extract the markdown portion from agent output (everything before JSON delimiter).

    Args:
        raw_output: Full agent output string

    Returns:
        Markdown content without the JSON block
    """
    if JSON_OUTPUT_START in raw_output:
        return raw_output[:raw_output.index(JSON_OUTPUT_START)].strip()
    return raw_output.strip()


# ─── Validation ─────────────────────────────────────────────────────────────

def validate_against_schema(
    data: dict,
    schema: dict[str, tuple[type, bool]],
    schema_name: str = "",
) -> tuple[bool, list[str]]:
    """
    Validate a data dict against a schema definition.

    Args:
        data: The data to validate
        schema: Schema dict mapping field names to (type, required) tuples
        schema_name: Human-readable name for error messages

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    prefix = f"[{schema_name}] " if schema_name else ""

    if not isinstance(data, dict):
        return (False, [f"{prefix}Expected dict, got {type(data).__name__}"])

    for field, (expected_type, required) in schema.items():
        if field not in data:
            if required:
                errors.append(f"{prefix}Missing required field: '{field}'")
            continue

        value = data[field]
        if not isinstance(value, expected_type):
            errors.append(
                f"{prefix}Field '{field}' expected {expected_type.__name__}, "
                f"got {type(value).__name__}"
            )

    return (len(errors) == 0, errors)


def validate_researcher_output(data: dict) -> tuple[bool, list[str]]:
    """Validate researcher agent JSON output."""
    is_valid, errors = validate_against_schema(data, RESEARCHER_SCHEMA, "researcher")

    # Validate enum values
    confidence = data.get("confidence", "")
    if isinstance(confidence, str) and confidence and confidence not in VALID_CONFIDENCE:
        errors.append(
            f"[researcher] Invalid confidence: '{confidence}'. "
            f"Valid: {VALID_CONFIDENCE}"
        )
        is_valid = False

    # Validate evidence is list of strings
    evidence = data.get("evidence", [])
    if isinstance(evidence, list):
        for i, item in enumerate(evidence):
            if not isinstance(item, str):
                errors.append(f"[researcher] evidence[{i}] must be string")
                is_valid = False

    return (is_valid, errors)


def validate_solution_output(data: dict) -> tuple[bool, list[str]]:
    """Validate solution finder agent JSON output."""
    is_valid, errors = validate_against_schema(data, SOLUTION_SCHEMA, "solution_finder")

    # Validate solutions list items
    solutions = data.get("solutions", [])
    if isinstance(solutions, list):
        for i, sol in enumerate(solutions):
            if isinstance(sol, dict):
                sol_valid, sol_errors = validate_against_schema(
                    sol, SOLUTION_ITEM_SCHEMA, f"solution_finder.solutions[{i}]"
                )
                if not sol_valid:
                    errors.extend(sol_errors)
                    is_valid = False
            else:
                errors.append(f"[solution_finder] solutions[{i}] must be dict")
                is_valid = False

        # Validate recommended_index is in range
        rec_idx = data.get("recommended_index")
        if isinstance(rec_idx, int) and solutions:
            if rec_idx < 0 or rec_idx >= len(solutions):
                errors.append(
                    f"[solution_finder] recommended_index {rec_idx} out of range "
                    f"(0-{len(solutions)-1})"
                )
                is_valid = False

    # Validate implementation_steps
    steps = data.get("implementation_steps", [])
    if isinstance(steps, list):
        for i, step in enumerate(steps):
            if not isinstance(step, str):
                errors.append(f"[solution_finder] implementation_steps[{i}] must be string")
                is_valid = False

    return (is_valid, errors)


def validate_impact_output(data: dict) -> tuple[bool, list[str]]:
    """Validate impact assessor agent JSON output."""
    is_valid, errors = validate_against_schema(data, IMPACT_SCHEMA, "impact_assessor")

    # Validate enum values
    severity = data.get("severity", "")
    if isinstance(severity, str) and severity and severity not in VALID_SEVERITY:
        errors.append(f"[impact_assessor] Invalid severity: '{severity}'. Valid: {VALID_SEVERITY}")
        is_valid = False

    scope = data.get("scope", "")
    if isinstance(scope, str) and scope and scope not in VALID_SCOPE:
        errors.append(f"[impact_assessor] Invalid scope: '{scope}'. Valid: {VALID_SCOPE}")
        is_valid = False

    frequency = data.get("frequency", "")
    if isinstance(frequency, str) and frequency and frequency not in VALID_FREQUENCY:
        errors.append(f"[impact_assessor] Invalid frequency: '{frequency}'. Valid: {VALID_FREQUENCY}")
        is_valid = False

    priority = data.get("priority", "")
    if isinstance(priority, str) and priority and priority not in VALID_PRIORITY_ACTION:
        errors.append(f"[impact_assessor] Invalid priority: '{priority}'. Valid: {VALID_PRIORITY_ACTION}")
        is_valid = False

    return (is_valid, errors)


def validate_debate_output(data: dict) -> tuple[bool, list[str]]:
    """Validate debate agent JSON output."""
    is_valid, errors = validate_against_schema(data, DEBATE_SCHEMA, "debater")

    # Validate revised_priority
    priority = data.get("revised_priority", "")
    if isinstance(priority, str) and priority and priority not in VALID_SEVERITY:
        errors.append(f"[debater] Invalid revised_priority: '{priority}'. Valid: {VALID_SEVERITY}")
        is_valid = False

    return (is_valid, errors)


def validate_task(data: dict) -> tuple[bool, list[str]]:
    """Validate a single task object."""
    is_valid, errors = validate_against_schema(data, TASK_SCHEMA, "task")

    priority = data.get("priority", "")
    if isinstance(priority, str) and priority and priority not in VALID_SEVERITY:
        errors.append(f"[task] Invalid priority: '{priority}'. Valid: {VALID_SEVERITY}")
        is_valid = False

    complexity = data.get("complexity", "")
    if isinstance(complexity, str) and complexity and complexity not in VALID_COMPLEXITY:
        errors.append(f"[task] Invalid complexity: '{complexity}'. Valid: {VALID_COMPLEXITY}")
        is_valid = False

    return (is_valid, errors)


# ─── Agent-Specific Validators (by name) ────────────────────────────────────

VALIDATOR_MAP = {
    "researcher": validate_researcher_output,
    "solution_finder": validate_solution_output,
    "impact_assessor": validate_impact_output,
    "debater": validate_debate_output,
    "task": validate_task,
}


def validate_agent_output(agent_name: str, data: dict) -> tuple[bool, list[str]]:
    """
    Validate agent output using the appropriate schema.

    Args:
        agent_name: One of: researcher, solution_finder, impact_assessor, debater, task
        data: Parsed JSON data from agent output

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    validator = VALIDATOR_MAP.get(agent_name)
    if validator is None:
        return (False, [f"Unknown agent name: '{agent_name}'"])
    return validator(data)
