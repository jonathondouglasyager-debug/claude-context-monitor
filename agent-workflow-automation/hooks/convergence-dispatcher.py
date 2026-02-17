#!/usr/bin/env python3
"""
Convergence Dispatcher Hook

Runs on PostToolUseFailure. This is the sole error capture hook.
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

# Add plugin root to path so we can import agents package
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PLUGIN_ROOT)

from agents.config import is_convergence_enabled, get_data_dir, get_project_root
from agents.file_lock import atomic_append, read_jsonl, update_jsonl_record
from agents.fingerprint import compute_fingerprint, find_duplicate
from agents.sanitizer import sanitize_record
from agents.schema_validator import validate_issue, make_issue_id, migrate_issue
from agents.logger import AgentLogger


def _get_git_branch() -> str:
    """Get current git branch name, or 'unknown' if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=get_project_root()
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
            cwd=get_project_root()
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


def _emit_cached_resolution(duplicate: dict, log) -> None:
    """
    Emit cached resolution info to stderr so it surfaces in the Claude session.

    When a known-converged error recurs, this avoids re-research (~15-20k tokens)
    by pointing the session to the existing fix.
    """
    try:
        from agents.config import get_research_dir
        issue_id = duplicate.get("id", "")
        research_dir = get_research_dir(issue_id)

        # Try to load the solution summary
        solution_path = os.path.join(research_dir, "solutions.md")
        hint = ""
        if os.path.exists(solution_path):
            with open(solution_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Extract first substantive paragraph (skip headers)
            for line in content.split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("---"):
                    hint = line[:300]
                    break

        if hint:
            print(
                f"[convergence-engine] Known error (seen {duplicate.get('occurrence_count', '?')}x). "
                f"Cached fix: {hint}",
                file=sys.stderr,
            )
        else:
            print(
                f"[convergence-engine] Known error (seen {duplicate.get('occurrence_count', '?')}x). "
                f"Check convergence report for resolution.",
                file=sys.stderr,
            )
    except Exception as e:
        log.warn(f"Failed to emit cached resolution: {e}")


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
    now = datetime.now(timezone.utc).isoformat()
    issue_id = make_issue_id()
    issue = {
        "id": issue_id,
        "type": _classify_error_type(tool_name, str(error)),
        "timestamp": now,
        "description": description,
        "status": "captured",
        "source": "hook:PostToolUseFailure",
        "tool_name": tool_name,
        "git_branch": _get_git_branch(),
        "recent_files": _get_recent_changed_files(),
        "working_directory": os.getcwd(),
        "raw_error": str(error)[:2000],
    }

    # Compute fingerprint and populate Phase 2 fields
    issue["fingerprint"] = compute_fingerprint(issue)
    issue["occurrence_count"] = 1
    issue["first_seen"] = now
    issue["last_seen"] = now

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

    # Check for duplicate fingerprint in existing issues
    issues_path = os.path.join(get_data_dir(), "issues.jsonl")
    try:
        os.makedirs(get_data_dir(), exist_ok=True)

        existing_issues = read_jsonl(issues_path)
        # Auto-migrate legacy records so they have fingerprints for comparison
        for existing in existing_issues:
            migrate_issue(existing)

        duplicate = find_duplicate(sanitized_issue, existing_issues)

        if duplicate:
            # Dedup: increment occurrence count and update last_seen on existing record
            dup_id = duplicate["id"]
            new_count = duplicate.get("occurrence_count", 1) + 1
            update_jsonl_record(issues_path, dup_id, {
                "occurrence_count": new_count,
                "last_seen": now,
            })

            # Phase 3: Short-circuit for converged issues with known resolutions
            dup_status = duplicate.get("status", "")
            if dup_status == "converged" and new_count > 1:
                log.info(
                    f"Known resolution: {dup_id} (status=converged, count={new_count}) "
                    f"— skipping re-research. Check CLAUDE.md or convergence report for fix.",
                    tool=tool_name,
                )
                # Output cached resolution hint to stderr so it appears in session
                _emit_cached_resolution(duplicate, log)
            else:
                log.info(
                    f"Dedup: matched existing {dup_id} (count={new_count})",
                    tool=tool_name,
                )
        else:
            # New unique error — append
            atomic_append(issues_path, sanitized_issue)
            log.info(f"Issue captured: {tool_name} failure", tool=tool_name)

    except Exception as e:
        # Fallback: if dedup fails, still try to capture the issue
        log.error(f"Dedup check failed, falling back to append: {e}")
        try:
            atomic_append(issues_path, sanitized_issue)
            log.info(f"Issue captured (fallback): {tool_name} failure", tool=tool_name)
        except Exception as e2:
            log.error(f"Failed to write issue: {e2}")

    # Always allow -- we are an observer, not a blocker
    print(json.dumps({"result": "allow"}))


if __name__ == "__main__":
    main()
