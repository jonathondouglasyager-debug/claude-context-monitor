"""
Tests for agents/fingerprint.py

Covers:
- Error message normalization (paths, timestamps, UUIDs, hashes, etc.)
- Fingerprint computation determinism
- Fingerprint stability across cosmetically different errors
- Duplicate detection
- Edge cases (empty fields, missing fields)
"""

import pytest
from agents.fingerprint import (
    normalize_error_message,
    compute_fingerprint,
    fingerprints_match,
    find_duplicate,
)


# --- normalize_error_message tests ---


class TestNormalizeErrorMessage:
    def test_empty_string(self):
        assert normalize_error_message("") == ""

    def test_none_returns_empty(self):
        assert normalize_error_message(None) == ""

    def test_strips_file_paths(self):
        msg = "FileNotFoundError: /Users/jonathon/project/src/index.ts not found"
        result = normalize_error_message(msg)
        assert "/Users/jonathon" not in result
        assert "<path>" in result  # lowercased after normalization

    def test_strips_windows_paths(self):
        msg = "Error in C:\\Users\\jonathon\\project\\main.py"
        result = normalize_error_message(msg)
        assert "C:\\Users" not in result

    def test_strips_iso_timestamps(self):
        msg = "Error at 2026-02-17T12:30:45Z: connection refused"
        result = normalize_error_message(msg)
        assert "2026-02-17" not in result
        assert "<TIMESTAMP>" in result.upper()

    def test_strips_timestamps_with_offset(self):
        msg = "Failed at 2026-02-17T12:30:45+05:00"
        result = normalize_error_message(msg)
        assert "2026-02-17" not in result

    def test_strips_uuids(self):
        msg = "Request 550e8400-e29b-41d4-a716-446655440000 failed"
        result = normalize_error_message(msg)
        assert "550e8400" not in result
        assert "<uuid>" in result

    def test_strips_hex_hashes(self):
        msg = "Checksum mismatch: expected abc123def456abc123def456abc123de"
        result = normalize_error_message(msg)
        assert "abc123def456" not in result
        assert "<hash>" in result

    def test_strips_memory_addresses(self):
        msg = "Segfault at 0x7fff5fbff8c0"
        result = normalize_error_message(msg)
        assert "0x7fff5fbff8c0" not in result
        assert "<addr>" in result

    def test_strips_pids(self):
        msg = "Process pid=12345 terminated"
        result = normalize_error_message(msg)
        assert "12345" not in result
        assert "<pid>" in result

    def test_strips_port_numbers(self):
        msg = "EADDRINUSE: port 3000 already in use"
        result = normalize_error_message(msg)
        assert "3000" not in result

    def test_strips_long_numbers(self):
        msg = "Error code 123456789"
        result = normalize_error_message(msg)
        assert "123456789" not in result
        assert "<num>" in result

    def test_collapses_whitespace(self):
        msg = "Error:   too   many   spaces"
        result = normalize_error_message(msg)
        assert "  " not in result

    def test_lowercases_output(self):
        msg = "FATAL ERROR: Module Not Found"
        result = normalize_error_message(msg)
        assert result == result.lower()

    def test_same_error_different_paths_normalize_equal(self):
        """Core dedup scenario: same error, different file paths."""
        msg1 = "ModuleNotFoundError: No module named 'foo' at /Users/alice/project/main.py"
        msg2 = "ModuleNotFoundError: No module named 'foo' at /Users/bob/project/main.py"
        assert normalize_error_message(msg1) == normalize_error_message(msg2)

    def test_same_error_different_timestamps_normalize_equal(self):
        msg1 = "Error at 2026-02-17T12:00:00Z: connection reset"
        msg2 = "Error at 2026-02-17T14:30:00Z: connection reset"
        assert normalize_error_message(msg1) == normalize_error_message(msg2)

    def test_different_errors_normalize_different(self):
        msg1 = "ModuleNotFoundError: No module named 'foo'"
        msg2 = "ImportError: cannot import name 'bar'"
        assert normalize_error_message(msg1) != normalize_error_message(msg2)


# --- compute_fingerprint tests ---


class TestComputeFingerprint:
    @pytest.fixture
    def base_issue(self):
        return {
            "id": "issue_20260217_120000_test",
            "type": "error",
            "timestamp": "2026-02-17T12:00:00Z",
            "description": "Tool 'Bash' failed: npm ERR! Could not resolve dependency",
            "status": "captured",
            "tool_name": "Bash",
            "git_branch": "main",
            "recent_files": ["package.json"],
            "raw_error": "npm ERR! Could not resolve dependency",
        }

    def test_deterministic(self, base_issue):
        """Same issue produces same fingerprint every time."""
        fp1 = compute_fingerprint(base_issue)
        fp2 = compute_fingerprint(base_issue)
        assert fp1 == fp2

    def test_hex_format(self, base_issue):
        """Fingerprint is a 64-char hex string (sha256)."""
        fp = compute_fingerprint(base_issue)
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_different_timestamp_same_fingerprint(self, base_issue):
        """Timestamp is NOT part of fingerprint — same error at different times matches."""
        issue2 = {**base_issue, "timestamp": "2026-02-17T18:00:00Z"}
        assert compute_fingerprint(base_issue) == compute_fingerprint(issue2)

    def test_different_id_same_fingerprint(self, base_issue):
        """ID is NOT part of fingerprint."""
        issue2 = {**base_issue, "id": "issue_20260217_180000_abcd"}
        assert compute_fingerprint(base_issue) == compute_fingerprint(issue2)

    def test_different_status_same_fingerprint(self, base_issue):
        """Status is NOT part of fingerprint."""
        issue2 = {**base_issue, "status": "researched"}
        assert compute_fingerprint(base_issue) == compute_fingerprint(issue2)

    def test_different_error_different_fingerprint(self, base_issue):
        """Different error content produces different fingerprint."""
        issue2 = {**base_issue, "raw_error": "npm ERR! Missing peer dependency"}
        assert compute_fingerprint(base_issue) != compute_fingerprint(issue2)

    def test_different_tool_different_fingerprint(self, base_issue):
        """Different tool produces different fingerprint."""
        issue2 = {**base_issue, "tool_name": "Write"}
        assert compute_fingerprint(base_issue) != compute_fingerprint(issue2)

    def test_different_type_different_fingerprint(self, base_issue):
        """Different type produces different fingerprint."""
        issue2 = {**base_issue, "type": "warning"}
        assert compute_fingerprint(base_issue) != compute_fingerprint(issue2)

    def test_different_branch_different_fingerprint(self, base_issue):
        """Different branch produces different fingerprint."""
        issue2 = {**base_issue, "git_branch": "feature/auth"}
        assert compute_fingerprint(base_issue) != compute_fingerprint(issue2)

    def test_different_source_file_different_fingerprint(self, base_issue):
        """Different source file produces different fingerprint."""
        issue2 = {**base_issue, "recent_files": ["tsconfig.json"]}
        assert compute_fingerprint(base_issue) != compute_fingerprint(issue2)

    def test_missing_optional_fields_uses_defaults(self):
        """Minimal issue still produces a valid fingerprint."""
        minimal = {
            "id": "issue_test",
            "type": "error",
            "timestamp": "2026-02-17T12:00:00Z",
            "description": "something broke",
            "status": "captured",
        }
        fp = compute_fingerprint(minimal)
        assert len(fp) == 64

    def test_cosmetic_path_differences_same_fingerprint(self, base_issue):
        """Same npm error with different absolute paths → same fingerprint."""
        issue1 = {**base_issue, "raw_error": "npm ERR! Could not resolve dependency at /Users/alice/project"}
        issue2 = {**base_issue, "raw_error": "npm ERR! Could not resolve dependency at /Users/bob/project"}
        assert compute_fingerprint(issue1) == compute_fingerprint(issue2)

    def test_falls_back_to_description_if_no_raw_error(self, base_issue):
        """If raw_error is missing, uses description for normalization."""
        issue_no_raw = {k: v for k, v in base_issue.items() if k != "raw_error"}
        fp = compute_fingerprint(issue_no_raw)
        assert len(fp) == 64


# --- fingerprints_match tests ---


class TestFingerprintsMatch:
    def test_identical(self):
        assert fingerprints_match("abc123", "abc123") is True

    def test_different(self):
        assert fingerprints_match("abc123", "def456") is False

    def test_empty_first(self):
        assert fingerprints_match("", "abc123") is False

    def test_empty_second(self):
        assert fingerprints_match("abc123", "") is False

    def test_both_empty(self):
        assert fingerprints_match("", "") is False

    def test_none_first(self):
        assert fingerprints_match(None, "abc123") is False

    def test_none_second(self):
        assert fingerprints_match("abc123", None) is False


# --- find_duplicate tests ---


class TestFindDuplicate:
    @pytest.fixture
    def existing_issues(self):
        """Three existing issues with pre-computed fingerprints."""
        issues = [
            {
                "id": "issue_001",
                "type": "error",
                "tool_name": "Bash",
                "raw_error": "npm ERR! Could not resolve dependency",
                "git_branch": "main",
                "recent_files": ["package.json"],
                "timestamp": "2026-02-17T10:00:00Z",
                "description": "Tool 'Bash' failed",
                "status": "captured",
            },
            {
                "id": "issue_002",
                "type": "failure",
                "tool_name": "Write",
                "raw_error": "Permission denied: /etc/hosts",
                "git_branch": "main",
                "recent_files": [],
                "timestamp": "2026-02-17T11:00:00Z",
                "description": "Tool 'Write' failed",
                "status": "captured",
            },
        ]
        # Pre-compute fingerprints
        for issue in issues:
            issue["fingerprint"] = compute_fingerprint(issue)
        return issues

    def test_finds_exact_duplicate(self, existing_issues):
        new_issue = {
            "type": "error",
            "tool_name": "Bash",
            "raw_error": "npm ERR! Could not resolve dependency",
            "git_branch": "main",
            "recent_files": ["package.json"],
        }
        dup = find_duplicate(new_issue, existing_issues)
        assert dup is not None
        assert dup["id"] == "issue_001"

    def test_finds_cosmetic_duplicate(self, existing_issues):
        """Same error with different path noise still matches when both have paths."""
        # Both issues have the same error with paths that normalize away
        existing_issues[0]["raw_error"] = "npm ERR! Could not resolve dependency at /Users/alice/project"
        existing_issues[0]["fingerprint"] = compute_fingerprint(existing_issues[0])

        new_issue = {
            "type": "error",
            "tool_name": "Bash",
            "raw_error": "npm ERR! Could not resolve dependency at /Users/bob/project",
            "git_branch": "main",
            "recent_files": ["package.json"],
        }
        dup = find_duplicate(new_issue, existing_issues)
        assert dup is not None
        assert dup["id"] == "issue_001"

    def test_no_duplicate_found(self, existing_issues):
        new_issue = {
            "type": "error",
            "tool_name": "Bash",
            "raw_error": "ENOENT: no such file or directory",
            "git_branch": "main",
            "recent_files": ["src/app.ts"],
        }
        dup = find_duplicate(new_issue, existing_issues)
        assert dup is None

    def test_no_duplicate_in_empty_list(self):
        new_issue = {"type": "error", "tool_name": "Bash", "raw_error": "fail"}
        assert find_duplicate(new_issue, []) is None

    def test_skips_issues_without_fingerprint(self):
        """Existing issues without fingerprint field are skipped."""
        existing = [{"id": "old_issue", "type": "error"}]  # no fingerprint
        new_issue = {"type": "error", "tool_name": "Bash", "raw_error": "fail"}
        assert find_duplicate(new_issue, existing) is None
