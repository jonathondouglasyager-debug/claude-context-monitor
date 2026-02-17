#!/usr/bin/env python3
"""
Fingerprint Matcher Hook

Phase 3: Runs on PreToolUse for Bash|Execute tools. Checks if the tool
invocation context matches known error fingerprints from the convergence
knowledge base. If a high-confidence match is found, emits a warning to
stderr so the session can apply the cached fix proactively.

This is the "session-start pattern matcher" from the Phase 3 plan.
It reads the CLAUDE.md knowledge table (populated by the arbiter bridge
writer) and issues.jsonl to find converged resolutions.

Hook input: JSON on stdin with tool_name, tool_input
Hook output: JSON on stdout with {"result": "allow"} — never blocks.

Token savings: ~15-20k per matched error (avoids full research pipeline).
"""

import json
import os
import sys

# Add plugin root to path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PLUGIN_ROOT)

from agents.config import is_convergence_enabled, get_data_dir, get_project_root
from agents.claude_md_bridge import read_knowledge_table
from agents.file_lock import read_jsonl
from agents.logger import AgentLogger


def _load_converged_patterns() -> list[dict]:
    """
    Load known error patterns from two sources:
    1. CLAUDE.md knowledge table (fast, compact)
    2. issues.jsonl converged records (full detail fallback)

    Returns list of pattern dicts with at minimum:
    - fingerprint_short or fingerprint
    - error_pattern
    - fix
    """
    patterns = []

    # Source 1: CLAUDE.md knowledge table (preferred — already compact)
    try:
        project_root = get_project_root()
        entries = read_knowledge_table(project_root)
        for entry in entries:
            patterns.append({
                "source": "claude_md",
                "fingerprint_short": entry.get("fingerprint_short", ""),
                "error_pattern": entry.get("error_pattern", ""),
                "fix": entry.get("fix", ""),
                "root_cause": entry.get("root_cause", ""),
                "applies_when": entry.get("applies_when", ""),
            })
    except Exception:
        pass  # Non-fatal

    # Source 2: issues.jsonl converged records (if CLAUDE.md is stale/missing)
    if not patterns:
        try:
            issues_path = os.path.join(get_data_dir(), "issues.jsonl")
            issues = read_jsonl(issues_path)
            for issue in issues:
                if issue.get("status") == "converged":
                    patterns.append({
                        "source": "issues_jsonl",
                        "fingerprint": issue.get("fingerprint", ""),
                        "error_pattern": issue.get("description", "")[:100],
                        "tool_name": issue.get("tool_name", ""),
                        "occurrence_count": issue.get("occurrence_count", 1),
                    })
        except Exception:
            pass

    return patterns


def _check_tool_input_matches(tool_input: dict, patterns: list[dict]) -> list[dict]:
    """
    Check if the current tool input context matches any known error patterns.

    Uses simple heuristic matching:
    - Tool name matches applies_when context
    - Command or input text contains keywords from known error patterns

    Returns matching patterns (may be empty).
    """
    matches = []

    # Extract searchable text from tool input
    input_text = ""
    if isinstance(tool_input, dict):
        input_text = json.dumps(tool_input, default=str).lower()
    else:
        input_text = str(tool_input).lower()

    for pattern in patterns:
        # Check applies_when context
        applies = pattern.get("applies_when", "").lower()
        error = pattern.get("error_pattern", "").lower()

        # Simple keyword overlap check
        # Extract meaningful words from error pattern (>3 chars, not common words)
        error_words = {
            w for w in error.split()
            if len(w) > 3 and w not in {"tool", "failed", "error", "the", "with", "from", "that"}
        }

        if error_words:
            overlap = sum(1 for w in error_words if w in input_text)
            if overlap >= max(1, len(error_words) // 3):
                matches.append(pattern)

    return matches


def main():
    """Read hook payload, check for known patterns, emit warnings if matched."""

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

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    log = AgentLogger("PATTERN_MATCH", "PRETOOL")

    # Load known patterns
    try:
        patterns = _load_converged_patterns()
    except Exception as e:
        log.warn(f"Failed to load patterns: {e}")
        print(json.dumps({"result": "allow"}))
        return

    if not patterns:
        # No known patterns yet — pass through
        print(json.dumps({"result": "allow"}))
        return

    # Check for matches
    matches = _check_tool_input_matches(tool_input, patterns)

    if matches:
        # Emit warnings to stderr (surfaces in Claude session)
        for match in matches[:3]:  # Cap at 3 warnings
            fix = match.get("fix", "See convergence report")
            error = match.get("error_pattern", "unknown pattern")
            print(
                f"[convergence-engine] ⚠ Known error pattern detected: {error}\n"
                f"  Cached fix: {fix}",
                file=sys.stderr,
            )
        log.info(
            f"Pattern match: {len(matches)} known pattern(s) for {tool_name}",
            tool=tool_name,
        )

    # Always allow — we are an observer
    print(json.dumps({"result": "allow"}))


if __name__ == "__main__":
    main()
