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

# Required sections in research output files
_RESEARCH_REQUIRED_SECTIONS = {
    "root_cause.md": ["## Hypothesis", "## Confidence"],
    "solutions.md": ["## Recommended Approach"],
    "impact.md": ["## Severity", "## Priority Recommendation"],
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
