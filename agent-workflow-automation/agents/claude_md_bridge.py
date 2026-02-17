"""
Convergence Engine - CLAUDE.md Bridge Writer

Phase 3: Writes compact convergence knowledge to the project's CLAUDE.md
so new Claude sessions inherit error patterns and fixes for free.

Uses section markers for safe, non-destructive updates:
  <!-- convergence-engine:start -->
  ... auto-generated content ...
  <!-- convergence-engine:end -->

Atomic writes via temp file + os.replace() with filelock protection
to prevent data loss if user is editing CLAUDE.md concurrently.

Grove-inspired applicability predicates: each row includes "Applies When"
conditions so the LLM knows when a cached fix is relevant.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

from filelock import FileLock, Timeout


# Section markers -- these delimit the auto-generated convergence block
_START_MARKER = "<!-- convergence-engine:start -->"
_END_MARKER = "<!-- convergence-engine:end -->"

# Lock config (same pattern as file_lock.py)
_LOCK_TIMEOUT = 10  # seconds


def _get_claude_md_path(project_root: str) -> str:
    """Path to the project's CLAUDE.md file."""
    return os.path.join(project_root, "CLAUDE.md")


def _get_claude_md_lock(project_root: str) -> FileLock:
    """Get a filelock for CLAUDE.md writes."""
    lock_path = os.path.join(project_root, ".claude", "CLAUDE.md.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    return FileLock(lock_path, timeout=_LOCK_TIMEOUT)


def _build_knowledge_table(issues: list[dict], research_dir_fn) -> str:
    """
    Build a compact Markdown knowledge table from converged issues.

    Each row includes Grove-inspired applicability predicates so the LLM
    can quickly determine if a cached fix applies to the current error.

    Args:
        issues: List of converged issue dicts from issues.jsonl
        research_dir_fn: Callable(issue_id) -> research dir path

    Returns:
        Markdown table string (or empty string if no issues)
    """
    if not issues:
        return ""

    rows = []
    for issue in issues:
        fp = issue.get("fingerprint", "")[:12]  # Short fingerprint for readability
        error_pattern = _extract_error_pattern(issue)
        root_cause = _extract_root_cause(issue, research_dir_fn)
        fix = _extract_fix(issue, research_dir_fn)
        applies_when = _extract_applicability(issue)
        count = issue.get("occurrence_count", 1)

        rows.append(
            f"| `{fp}` | {error_pattern} | {root_cause} | {fix} | {applies_when} | {count} |"
        )

    header = "| Fingerprint | Error Pattern | Root Cause | Fix | Applies When | Seen |"
    separator = "|---|---|---|---|---|---|"

    return "\n".join([header, separator] + rows)


def _extract_error_pattern(issue: dict) -> str:
    """Extract a concise error pattern from the issue."""
    desc = issue.get("description", "")
    # Take first line, strip tool prefix, truncate
    first_line = desc.split("\n")[0]
    # Remove "Tool 'X' failed: " prefix if present
    if "failed:" in first_line:
        first_line = first_line.split("failed:", 1)[1].strip()
    # Truncate for table readability
    if len(first_line) > 80:
        first_line = first_line[:77] + "..."
    # Escape pipe chars for markdown table
    return first_line.replace("|", "\\|")


def _extract_root_cause(issue: dict, research_dir_fn) -> str:
    """Extract root cause summary from research outputs."""
    issue_id = issue.get("id", "")
    if not issue_id:
        return "Unknown"

    # Try debate.md first (synthesized), then root_cause.md
    research_dir = research_dir_fn(issue_id)
    for filename in ("debate.md", "root_cause.md"):
        filepath = os.path.join(research_dir, filename)
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                # Extract first substantive line (skip headers)
                for line in content.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("---"):
                        if len(line) > 60:
                            line = line[:57] + "..."
                        return line.replace("|", "\\|")
            except Exception:
                pass

    return "See convergence report"


def _extract_fix(issue: dict, research_dir_fn) -> str:
    """Extract fix summary from research outputs."""
    issue_id = issue.get("id", "")
    if not issue_id:
        return "Unknown"

    research_dir = research_dir_fn(issue_id)
    filepath = os.path.join(research_dir, "solutions.md")
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            for line in content.split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("---"):
                    if len(line) > 60:
                        line = line[:57] + "..."
                    return line.replace("|", "\\|")
        except Exception:
            pass

    return "See convergence report"


def _extract_applicability(issue: dict) -> str:
    """
    Build Grove-inspired applicability predicate.

    Returns conditions under which this cached fix applies:
    tool + branch + source file context.
    """
    parts = []
    tool = issue.get("tool_name", "")
    if tool:
        parts.append(f"`{tool}`")

    branch = issue.get("git_branch", "")
    if branch and branch != "unknown":
        parts.append(f"branch:{branch}")

    files = issue.get("recent_files", [])
    if files:
        # Show first file for context
        parts.append(files[0].replace("|", "\\|"))

    return ", ".join(parts) if parts else "any context"


def _build_tasks_summary(tasks: list[dict]) -> str:
    """Build a compact active tasks list from P0/P1 tasks."""
    active = [t for t in tasks if t.get("priority") in ("P0", "P1") and t.get("status") == "pending"]
    if not active:
        return ""

    lines = ["### Active Tasks (P0/P1)"]
    for task in active[:10]:  # Cap at 10
        priority = task.get("priority", "P?")
        title = task.get("title", "Untitled")
        lines.append(f"- **[{priority}]** {title}")

    return "\n".join(lines)


def build_convergence_section(
    issues: list[dict],
    tasks: list[dict],
    research_dir_fn,
) -> str:
    """
    Build the full convergence knowledge section for CLAUDE.md.

    Args:
        issues: Converged issues from issues.jsonl
        tasks: Task list from tasks.json
        research_dir_fn: Callable(issue_id) -> research dir path

    Returns:
        Full section string including markers
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    parts = [
        _START_MARKER,
        "",
        "## Convergence Knowledge (auto-generated)",
        f"_Last updated: {now}_",
        "",
    ]

    # Knowledge table
    table = _build_knowledge_table(issues, research_dir_fn)
    if table:
        parts.append(table)
        parts.append("")

    # Active tasks
    tasks_summary = _build_tasks_summary(tasks)
    if tasks_summary:
        parts.append(tasks_summary)
        parts.append("")

    if not table and not tasks_summary:
        parts.append("_No convergence knowledge yet._")
        parts.append("")

    parts.append(_END_MARKER)

    return "\n".join(parts)


def write_to_claude_md(
    project_root: str,
    section_content: str,
    log=None,
) -> bool:
    """
    Write convergence section to the project's CLAUDE.md.

    - Reads existing CLAUDE.md (or creates new)
    - Strips old convergence section between markers
    - Appends new convergence section
    - Atomic write: temp file + os.replace()
    - Protected by filelock

    Args:
        project_root: Project root directory
        section_content: Full section string (with markers)
        log: Optional logger instance

    Returns:
        True if write succeeded
    """
    claude_md_path = _get_claude_md_path(project_root)
    lock = _get_claude_md_lock(project_root)

    try:
        with lock:
            # Read existing content
            existing = ""
            if os.path.exists(claude_md_path):
                with open(claude_md_path, "r", encoding="utf-8") as f:
                    existing = f.read()

            # Strip old convergence section
            new_content = _strip_convergence_section(existing)

            # Ensure there's a newline before our section
            if new_content and not new_content.endswith("\n\n"):
                if not new_content.endswith("\n"):
                    new_content += "\n"
                new_content += "\n"

            # Append new section
            new_content += section_content + "\n"

            # Atomic write: temp file + os.replace
            dir_name = os.path.dirname(claude_md_path) or "."
            os.makedirs(dir_name, exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=dir_name, suffix=".CLAUDE.md.tmp"
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_f:
                    tmp_f.write(new_content)
                    tmp_f.flush()
                    os.fsync(tmp_f.fileno())
                os.replace(tmp_path, claude_md_path)
            except Exception:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise

            if log:
                log.info(f"CLAUDE.md bridge updated: {claude_md_path}")

            return True

    except Timeout:
        if log:
            log.error("Could not acquire lock on CLAUDE.md — skipping bridge write")
        return False
    except Exception as e:
        if log:
            log.error(f"Failed to write CLAUDE.md bridge: {e}")
        return False


def _strip_convergence_section(content: str) -> str:
    """
    Remove the convergence-engine section from CLAUDE.md content.

    Handles:
    - Normal case: both markers present
    - Corrupt: only start marker (strip from start marker to end)
    - Corrupt: only end marker (strip from beginning to end marker)
    - Missing: neither marker (return content unchanged)
    """
    has_start = _START_MARKER in content
    has_end = _END_MARKER in content

    if has_start and has_end:
        # Normal case: strip between markers (inclusive)
        start_idx = content.index(_START_MARKER)
        end_idx = content.index(_END_MARKER) + len(_END_MARKER)
        # Also strip trailing newline after end marker
        if end_idx < len(content) and content[end_idx] == "\n":
            end_idx += 1
        return content[:start_idx].rstrip("\n") + content[end_idx:]

    elif has_start:
        # Corrupt: start marker without end — strip from start marker to end
        start_idx = content.index(_START_MARKER)
        return content[:start_idx].rstrip("\n")

    elif has_end:
        # Corrupt: end marker without start — strip from beginning to end marker
        end_idx = content.index(_END_MARKER) + len(_END_MARKER)
        if end_idx < len(content) and content[end_idx] == "\n":
            end_idx += 1
        return content[end_idx:].lstrip("\n")

    # No markers found — return unchanged
    return content


def read_knowledge_table(project_root: str) -> list[dict]:
    """
    Parse the convergence knowledge table from CLAUDE.md.

    Returns a list of dicts with keys: fingerprint, error_pattern,
    root_cause, fix, applies_when, seen_count.

    Useful for the pattern matcher to check known resolutions.
    """
    claude_md_path = _get_claude_md_path(project_root)
    if not os.path.exists(claude_md_path):
        return []

    try:
        with open(claude_md_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return []

    # Find the convergence section
    if _START_MARKER not in content or _END_MARKER not in content:
        return []

    start = content.index(_START_MARKER) + len(_START_MARKER)
    end = content.index(_END_MARKER)
    section = content[start:end]

    # Parse markdown table rows
    entries = []
    in_table = False
    for line in section.split("\n"):
        line = line.strip()
        if line.startswith("| Fingerprint"):
            in_table = True
            continue
        if line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= 6:
                entries.append({
                    "fingerprint_short": cells[0].strip("`"),
                    "error_pattern": cells[1],
                    "root_cause": cells[2],
                    "fix": cells[3],
                    "applies_when": cells[4],
                    "seen_count": int(cells[5]) if cells[5].isdigit() else 1,
                })
        elif in_table and not line.startswith("|"):
            in_table = False  # End of table

    return entries
