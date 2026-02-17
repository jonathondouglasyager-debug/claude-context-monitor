"""
Convergence Engine - Solution Finder Agent

Researches potential fixes for an issue. Can optionally read the root cause
analysis first for informed solution research. Writes findings to
data/research/{issue_id}/solutions.md.
"""

import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PROJECT_ROOT)

from agents.config import get_data_dir, get_research_dir
from agents.file_lock import read_jsonl_by_id
from agents.logger import AgentLogger
from agents.runner import run_agent, write_research_output
from agents.sanitizer import sanitize_context


_SOLUTION_PROMPT = """You are a solution research agent. Your job is to find practical fixes
for a software development error.

## Error Context

Tool: {tool_name}
Error: {description}
Git Branch: {git_branch}
Recently Changed Files: {recent_files}

{root_cause_section}

## Instructions

Research solutions for this error. Consider:
- Quick fixes that resolve the immediate problem
- Longer-term fixes that prevent recurrence
- Tradeoffs of each approach (risk, complexity, side effects)
- Implementation steps that are specific and actionable

## Required Output Format

Structure your response EXACTLY as follows:

## Solution 1
Describe the first solution approach.
**Tradeoffs:** Risk, complexity, side effects.

## Solution 2
Describe an alternative approach.
**Tradeoffs:** Risk, complexity, side effects.

## Recommended Approach
Which solution you recommend and why.

## Implementation Steps
Numbered, specific steps to implement the recommended fix.
"""


def _load_root_cause(issue_id: str) -> str:
    """Try to load existing root cause analysis if available."""
    research_dir = get_research_dir(issue_id)
    root_cause_path = os.path.join(research_dir, "root_cause.md")

    if os.path.exists(root_cause_path):
        with open(root_cause_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content:
            return f"## Root Cause Analysis (from prior research)\n\n{content}"

    return ""


def find_solutions(issue_id: str) -> bool:
    """
    Research solutions for a specific issue.

    Args:
        issue_id: The issue ID to research solutions for

    Returns:
        True if research completed successfully
    """
    log = AgentLogger(issue_id, "SOLUTIONS")
    log.section("Solution Research")

    # Load the issue record
    issues_path = os.path.join(get_data_dir(), "issues.jsonl")
    issue = read_jsonl_by_id(issues_path, issue_id)

    if not issue:
        log.error(f"Issue not found: {issue_id}")
        return False

    log.info("Issue loaded, constructing solution prompt")

    # Try to incorporate root cause if available
    root_cause_section = _load_root_cause(issue_id)
    if root_cause_section:
        log.info("Root cause analysis available, incorporating into prompt")

    # Build the prompt
    prompt = _SOLUTION_PROMPT.format(
        tool_name=issue.get("tool_name", "unknown"),
        description=sanitize_context(issue.get("description", "No description")),
        git_branch=issue.get("git_branch", "unknown"),
        recent_files=", ".join(issue.get("recent_files", [])) or "none",
        root_cause_section=root_cause_section,
    )

    # Dispatch to Claude Code headless
    result = run_agent(
        prompt=prompt,
        stage="research",
        issue_id=issue_id,
        log=log,
    )

    if not result.success:
        log.error(f"Solution finder failed: {result.error}")
        return False

    # Write output
    research_dir = get_research_dir(issue_id)
    success = write_research_output(research_dir, "solutions.md", result.output, log)

    if success:
        log.info("Solution research complete")

    return success


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m agents.solution_finder <issue_id>", file=sys.stderr)
        sys.exit(1)

    issue_id = sys.argv[1]
    success = find_solutions(issue_id)
    sys.exit(0 if success else 1)
