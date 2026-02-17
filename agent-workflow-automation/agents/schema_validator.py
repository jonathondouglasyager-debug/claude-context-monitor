"""
Convergence Engine - Schema Validator

Validates JSONL records and research outputs before agents process them.
Corrupt records are quarantined rather than blocking the pipeline.
"""

import json
import os
import shutil
from datetime import datetime, timezone
from typing import Optional

from agents.config import get_data_dir
from agents.file_lock import atomic_append
from agents.fingerprint import compute_fingerprint
from agents.output_schemas import validate_agent_output


# Required fields for an issue record
_ISSUE_REQUIRED_FIELDS = {
    "id": str,
    "type": str,
    "timestamp": str,
    "description": str,
    "status": str,
}

# Valid statuses in the pipeline
_VALID_STATUSES = {
    "captured",
    "researching",
    "researched",
    "debating",
    "debated",
    "converging",
    "converged",
    "resolved",
    "quarantined",
}

# Valid issue types
_VALID_TYPES = {
    "error",
    "warning",
    "failure",
    "regression",
    "performance",
    "design",
    "manual",
    "unknown",
}

# Optional fields added in Phase 2 (fingerprinting & dedup)
# These are auto-populated on read if missing (migration on access)
_PHASE2_OPTIONAL_FIELDS = {
    "fingerprint": str,        # sha256 hex digest
    "occurrence_count": int,   # how many times this error has been seen
    "first_seen": str,         # ISO 8601 timestamp of first occurrence
    "last_seen": str,          # ISO 8601 timestamp of most recent occurrence
}

# Required sections in research output files (markdown validation)
_RESEARCH_REQUIRED_SECTIONS = {
    "root_cause.md": ["## Hypothesis", "## Confidence"],
    "solutions.md": ["## Recommended Approach"],
    "impact.md": ["## Severity", "## Priority Recommendation"],
}

# Phase 4: JSON file → agent name mapping for structured validation
_RESEARCH_JSON_AGENTS = {
    "root_cause.json": "researcher",
    "solutions.json": "solution_finder",
    "impact.json": "impact_assessor",
    "debate.json": "debater",
}


class ValidationError(Exception):
    """Raised when a record fails validation."""
    pass


def validate_issue(record: dict) -> tuple[bool, list[str]]:
    """
    Validate a single issue record against the schema.

    Args:
        record: Dictionary to validate

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []

    # Check required fields exist and have correct types
    for field, expected_type in _ISSUE_REQUIRED_FIELDS.items():
        if field not in record:
            errors.append(f"Missing required field: '{field}'")
        elif not isinstance(record[field], expected_type):
            errors.append(
                f"Field '{field}' expected {expected_type.__name__}, "
                f"got {type(record[field]).__name__}"
            )

    # Validate status value
    status = record.get("status", "")
    if status and status not in _VALID_STATUSES:
        errors.append(f"Invalid status: '{status}'. Valid: {_VALID_STATUSES}")

    # Validate type value
    issue_type = record.get("type", "")
    if issue_type and issue_type not in _VALID_TYPES:
        errors.append(f"Invalid type: '{issue_type}'. Valid: {_VALID_TYPES}")

    # Validate id format (should be non-empty)
    issue_id = record.get("id", "")
    if isinstance(issue_id, str) and not issue_id.strip():
        errors.append("Field 'id' cannot be empty")

    # Validate timestamp format (ISO 8601)
    timestamp = record.get("timestamp", "")
    if isinstance(timestamp, str) and timestamp:
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"Field 'timestamp' is not valid ISO 8601: '{timestamp}'")

    return (len(errors) == 0, errors)


def validate_research(research_dir: str) -> tuple[bool, list[str]]:
    """
    Validate that research output files exist and contain required sections.

    Args:
        research_dir: Path to data/research/{issue_id}/

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []

    if not os.path.isdir(research_dir):
        return (False, [f"Research directory does not exist: {research_dir}"])

    for filename, required_sections in _RESEARCH_REQUIRED_SECTIONS.items():
        filepath = os.path.join(research_dir, filename)
        if not os.path.exists(filepath):
            errors.append(f"Missing research file: {filename}")
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        for section in required_sections:
            if section not in content:
                errors.append(f"{filename} missing required section: '{section}'")

    return (len(errors) == 0, errors)


def validate_research_json(research_dir: str) -> tuple[bool, list[str]]:
    """
    Validate structured JSON output files from research agents (Phase 4).

    Checks that JSON files exist, are valid JSON, and conform to their
    agent's output schema. This is complementary to validate_research()
    which checks markdown files.

    Args:
        research_dir: Path to data/research/{issue_id}/

    Returns:
        Tuple of (is_valid, list_of_errors).
        Returns (True, []) if no JSON files exist (backward-compatible).
    """
    errors = []

    if not os.path.isdir(research_dir):
        return (True, [])  # No dir = nothing to validate (not an error)

    found_any = False
    for json_file, agent_name in _RESEARCH_JSON_AGENTS.items():
        filepath = os.path.join(research_dir, json_file)
        if not os.path.exists(filepath):
            continue

        found_any = True

        # Parse JSON
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"{json_file}: Invalid JSON — {e}")
            continue

        # Validate against schema
        if isinstance(data, dict):
            is_valid, schema_errors = validate_agent_output(agent_name, data)
            if not is_valid:
                for err in schema_errors:
                    errors.append(f"{json_file}: {err}")

    return (len(errors) == 0, errors)


def validate_all_issues(issues_path: Optional[str] = None) -> dict:
    """
    Scan issues.jsonl, validate all records, and quarantine corrupt ones.

    Args:
        issues_path: Path to issues.jsonl (defaults to data/issues.jsonl)

    Returns:
        Summary dict: {"valid": count, "quarantined": count, "errors": [...]}
    """
    if issues_path is None:
        issues_path = os.path.join(get_data_dir(), "issues.jsonl")

    quarantine_path = os.path.join(get_data_dir(), "quarantine.jsonl")

    summary = {"valid": 0, "quarantined": 0, "errors": []}

    if not os.path.exists(issues_path):
        return summary

    valid_records = []
    quarantined = []

    with open(issues_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            # Try to parse JSON
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                error_msg = f"Line {line_num}: Invalid JSON -- {e}"
                summary["errors"].append(error_msg)
                quarantined.append({
                    "raw_line": line,
                    "error": str(e),
                    "line_number": line_num,
                    "quarantined_at": datetime.now(timezone.utc).isoformat(),
                })
                summary["quarantined"] += 1
                continue

            # Validate schema
            is_valid, errors = validate_issue(record)
            if is_valid:
                valid_records.append(record)
                summary["valid"] += 1
            else:
                error_msg = f"Line {line_num} (id={record.get('id', '?')}): {'; '.join(errors)}"
                summary["errors"].append(error_msg)
                record["_quarantine_reason"] = errors
                record["_quarantined_at"] = datetime.now(timezone.utc).isoformat()
                quarantined.append(record)
                summary["quarantined"] += 1

    # Write quarantined records
    if quarantined:
        for record in quarantined:
            atomic_append(quarantine_path, record)

    # Rewrite issues.jsonl with only valid records if any were quarantined
    if summary["quarantined"] > 0:
        tmp_path = issues_path + ".validated.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            for record in valid_records:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        os.replace(tmp_path, issues_path)

    return summary


def migrate_issue(record: dict) -> dict:
    """
    Auto-migrate a legacy issue record to include Phase 2 fields.

    Adds fingerprint, occurrence_count, first_seen, last_seen if missing.
    This is a non-destructive operation — only adds fields, never removes.

    Args:
        record: Issue record dict (may or may not have Phase 2 fields)

    Returns:
        Record with Phase 2 fields populated (mutates and returns same dict)
    """
    migrated = False

    # Add fingerprint if missing
    if "fingerprint" not in record:
        record["fingerprint"] = compute_fingerprint(record)
        migrated = True

    # Add occurrence_count if missing (first time = 1)
    if "occurrence_count" not in record:
        record["occurrence_count"] = 1
        migrated = True

    # Add first_seen / last_seen from timestamp if missing
    timestamp = record.get("timestamp", datetime.now(timezone.utc).isoformat())
    if "first_seen" not in record:
        record["first_seen"] = timestamp
        migrated = True
    if "last_seen" not in record:
        record["last_seen"] = timestamp
        migrated = True

    return record


def migrate_issues_file(issues_path: Optional[str] = None) -> dict:
    """
    Migrate an entire issues.jsonl file in-place, adding Phase 2 fields
    to all records that are missing them.

    Uses atomic write (temp file + os.replace) for safety.

    Args:
        issues_path: Path to issues.jsonl (defaults to data/issues.jsonl)

    Returns:
        Summary: {"total": count, "migrated": count, "already_current": count}
    """
    if issues_path is None:
        issues_path = os.path.join(get_data_dir(), "issues.jsonl")

    summary = {"total": 0, "migrated": 0, "already_current": 0}

    if not os.path.exists(issues_path):
        return summary

    records = []
    with open(issues_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                summary["total"] += 1

                needs_migration = any(
                    field not in record
                    for field in _PHASE2_OPTIONAL_FIELDS
                )

                migrate_issue(record)

                if needs_migration:
                    summary["migrated"] += 1
                else:
                    summary["already_current"] += 1

                records.append(record)
            except json.JSONDecodeError:
                # Preserve corrupt lines as-is (handled by quarantine elsewhere)
                continue

    # Atomic rewrite
    if summary["migrated"] > 0:
        tmp_path = issues_path + ".migration.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        os.replace(tmp_path, issues_path)

    return summary


def make_issue_id() -> str:
    """
    Generate a unique issue ID using timestamp + short random suffix.

    Format: issue_{YYYYMMDD}_{HHMMSS}_{random4}
    """
    import random
    import string
    now = datetime.now(timezone.utc)
    date_part = now.strftime("%Y%m%d_%H%M%S")
    rand_part = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"issue_{date_part}_{rand_part}"
