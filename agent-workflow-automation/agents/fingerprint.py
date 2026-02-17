"""
Convergence Engine - Error Fingerprinting

Computes deterministic fingerprints (sha256) for issue records to enable
cross-session deduplication. Two issues with the same fingerprint represent
the same underlying error, even if captured at different times.

Fingerprint fields: {type, tool_name, error_normalized, source_file, git_branch}

Normalization strips noise from error messages: paths, timestamps, UUIDs,
hex hashes, line numbers, PIDs, and memory addresses. This ensures that
cosmetically different instances of the same error converge to one fingerprint.
"""

import hashlib
import json
import re
from typing import Optional


# --- Normalization patterns ---
# Order matters: more specific patterns first to avoid partial matches.

_NORMALIZATION_PATTERNS = [
    # UUIDs: 8-4-4-4-12 hex
    (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE),
     "<UUID>"),

    # ISO 8601 timestamps: 2026-02-17T12:30:45Z or with offset
    (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})"),
     "<TIMESTAMP>"),

    # Date-time with space separator: 2026-02-17 12:30:45
    (re.compile(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}"),
     "<TIMESTAMP>"),

    # Hex hashes (sha256, sha1, md5) — 32+ hex chars in a row
    (re.compile(r"\b[0-9a-f]{32,}\b", re.IGNORECASE),
     "<HASH>"),

    # File paths: /foo/bar/baz.py or C:\foo\bar
    (re.compile(r"(?:/[^\s:\"']+(?:\.[a-zA-Z0-9]+)?|[A-Z]:\\[^\s:\"']+)"),
     "<PATH>"),

    # Line numbers: :42, line 42, Line 42, L42
    (re.compile(r"(?::|[Ll]ine\s*|[Ll])(\d+)"),
     "<LINE>"),

    # PIDs and process IDs: pid=12345, PID 12345, process 12345
    (re.compile(r"(?:pid|PID|process)\s*[=:]?\s*\d+"),
     "<PID>"),

    # Memory addresses: 0x7fff5fbff8c0
    (re.compile(r"0x[0-9a-fA-F]{4,}"),
     "<ADDR>"),

    # Port numbers in error context: port 3000, :8080
    (re.compile(r"(?:port\s+)\d{2,5}", re.IGNORECASE),
     "port <PORT>"),

    # Numeric sequences 4+ digits (but not inside words): catch remaining IDs
    (re.compile(r"\b\d{4,}\b"),
     "<NUM>"),
]


def normalize_error_message(msg: str) -> str:
    """
    Normalize an error message by stripping volatile components.

    Removes: paths, timestamps, UUIDs, hex hashes, line numbers,
    PIDs, memory addresses, and long numeric sequences.

    Collapses whitespace to single spaces and lowercases the result
    for case-insensitive matching.

    Args:
        msg: Raw error message string

    Returns:
        Normalized, lowered error string suitable for hashing
    """
    if not msg:
        return ""

    result = msg

    for pattern, replacement in _NORMALIZATION_PATTERNS:
        result = pattern.sub(replacement, result)

    # Collapse whitespace
    result = re.sub(r"\s+", " ", result).strip()

    # Lowercase for case-insensitive dedup
    return result.lower()


def compute_fingerprint(issue: dict) -> str:
    """
    Compute a deterministic sha256 fingerprint for an issue record.

    The fingerprint is derived from:
    - type: error classification (error, warning, failure, etc.)
    - tool_name: which tool failed
    - error_normalized: normalized error message (noise stripped)
    - source_file: primary file involved (first in recent_files, or empty)
    - git_branch: branch where the error occurred

    Two issues with the same fingerprint are considered the same
    underlying error and candidates for deduplication.

    Args:
        issue: Issue record dictionary

    Returns:
        64-char hex sha256 digest string
    """
    # Extract fingerprint fields with defaults
    issue_type = issue.get("type", "unknown")
    tool_name = issue.get("tool_name", "unknown")
    git_branch = issue.get("git_branch", "unknown")

    # Use raw_error for normalization (richer than description)
    raw_error = issue.get("raw_error", issue.get("description", ""))
    error_normalized = normalize_error_message(raw_error)

    # Source file: first entry in recent_files, or empty
    recent_files = issue.get("recent_files", [])
    source_file = recent_files[0] if recent_files else ""

    # Build canonical representation for hashing
    # Using JSON with sorted keys for determinism
    fingerprint_data = {
        "type": issue_type,
        "tool_name": tool_name,
        "error_normalized": error_normalized,
        "source_file": source_file,
        "git_branch": git_branch,
    }

    canonical = json.dumps(fingerprint_data, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprints_match(fp1: str, fp2: str) -> bool:
    """
    Compare two fingerprints for equality.

    Trivial now (exact match), but this function exists as the
    extension point for future hybrid matching (exact hash now,
    structural LSH later, semantic embeddings deferred).

    Args:
        fp1: First fingerprint hex string
        fp2: Second fingerprint hex string

    Returns:
        True if fingerprints match
    """
    if not fp1 or not fp2:
        return False
    return fp1 == fp2


def find_duplicate(issue: dict, existing_issues: list[dict]) -> Optional[dict]:
    """
    Check if an issue has a fingerprint match in the existing issue list.

    Args:
        issue: New issue to check (must have 'fingerprint' field or will be computed)
        existing_issues: List of existing issue records

    Returns:
        The matching existing issue dict, or None if no duplicate found
    """
    new_fp = issue.get("fingerprint") or compute_fingerprint(issue)

    for existing in existing_issues:
        existing_fp = existing.get("fingerprint")
        if existing_fp and fingerprints_match(new_fp, existing_fp):
            return existing

    return None
