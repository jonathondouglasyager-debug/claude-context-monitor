#!/usr/bin/env python3
"""
Convergence Dispatcher Hook

Runs on PostToolUseFailure alongside the existing error-logger.py.
Captures errors as enriched issue records and writes them to data/issues.jsonl
using atomic append. Does NOT trigger research -- that is manual (/converge research)
or deferred to SessionEnd.

Hook input: JSON on stdin with tool_name, tool_input, error, etc.
Hook output: JSON on stdout with {"result": "allow"} to not block the pipeline.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

# Add project root to path so we can import agents package
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PROJECT_ROOT)

from agents.config import is_convergence_enabled, get_data_dir
from agents.file_lock import atomic_append
from agents.sanitizer import sanitize_record
from agents.schema_validator import validate_issue, make_issue_id
from agents.logger import AgentLogger


def _get_git_branch() -> str:
    """Get current git branch name, or 'unknown' if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=_PROJECT_ROOT
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _get_recent_changed_files() -> list[str]:
    """Get recently changed files from git for context."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~3"],
            capture_output=True, text=True, timeout=5,
            cwd=_PROJECT_ROOT
        )
        if result.returncode == 0:
            files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
            return files[:20]  # Cap at 20 files
    except Exception:
        pass
    return []


def _classify_error_type(tool_name: str, error_text: str) -> str:
    """Classify the error into a category based on tool and error content."""
    error_lower = error_text.lower() if error_text else ""

    if "permission" in error_lower or "access denied" in error_lower:
        return "error"
    if "timeout" in error_lower:
        return "performance"
    if "not found" in error_lower or "no such file" in error_lower:
        return "error"
    if "syntax" in error_lower or "unexpected token" in error_lower:
        return "error"
    if "deprecated" in error_lower:
        return "warning"
    if tool_name in ("Bash", "Execute"):
        return "failure"

    return "error"


def main():
    """Read hook payload from stdin, create enriched issue, write to issues.jsonl."""

    # Check kill switch
    if not is_convergence_enabled():
        print(json.dumps({"result": "allow"}))
        return

    # Read stdin payload
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        print(json.dumps({"result": "allow"}))
        return

    # Extract fields from the hook payload
    tool_name = payload.get("tool_name", "unknown")
    tool_input = payload.get("tool_input", {})
    error = payload.get("error", "")

    # Build description from available context
    if isinstance(tool_input, dict):
        input_summary = json.dumps(tool_input, indent=None, default=str)[:500]
    else:
        input_summary = str(tool_input)[:500]

    description = f"Tool '{tool_name}' failed: {error}"
    if input_summary:
        description += f"\n\nTool input: {input_summary}"

    # Create the issue record
    issue_id = make_issue_id()
    issue = {
        "id": issue_id,
        "type": _classify_error_type(tool_name, str(error)),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "description": description,
        "status": "captured",
        "source": "hook:PostToolUseFailure",
        "tool_name": tool_name,
        "git_branch": _get_git_branch(),
        "recent_files": _get_recent_changed_files(),
        "working_directory": os.getcwd(),
        "raw_error": str(error)[:2000],
    }

    # Initialize logger
    log = AgentLogger(issue_id, "CAPTURE")

    # Validate before writing
    is_valid, errors = validate_issue(issue)
    if not is_valid:
        log.error(f"Issue validation failed: {errors}")
        # Still allow the tool call to proceed
        print(json.dumps({"result": "allow"}))
        return

    # Sanitize sensitive data
    sanitized_issue = sanitize_record(issue)

    # Atomic append to issues.jsonl
    issues_path = os.path.join(get_data_dir(), "issues.jsonl")
    try:
        os.makedirs(get_data_dir(), exist_ok=True)
        atomic_append(issues_path, sanitized_issue)
        log.info(f"Issue captured: {tool_name} failure", tool=tool_name)
    except Exception as e:
        log.error(f"Failed to write issue: {e}")

    # Always allow -- we are an observer, not a blocker
    print(json.dumps({"result": "allow"}))


if __name__ == "__main__":
    main()
