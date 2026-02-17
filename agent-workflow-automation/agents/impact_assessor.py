"""
Convergence Engine - Impact Assessment Agent

Evaluates severity, scope, frequency, and priority of an issue.
Reads prior issues from issues.jsonl to detect recurring patterns.
Writes findings to data/research/{issue_id}/impact.md.
"""

import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PROJECT_ROOT)

from agents.config import get_data_dir, get_research_dir
from agents.file_lock import read_jsonl, read_jsonl_by_id
from agents.logger import AgentLogger
from agents.runner import run_agent, write_research_output
from agents.sanitizer import sanitize_context


_IMPACT_PROMPT = """You are an impact assessment agent. Your job is to evaluate the severity
and priority of a software development error.

## Error Context

Tool: {tool_name}
Error: {description}
Git Branch: {git_branch}
Recently Changed Files: {recent_files}

## Historical Context

Recent issues in this project (last 10):
{recent_issues_summary}

## Instructions

Assess this error for:
- How severe is it? (Does it block work? Corrupt data? Just annoying?)
- How wide is its scope? (One file? One module? System-wide?)
- How often does it recur? (Check against historical issues for patterns)
- What priority should it receive for fixing?

## Required Output Format

Structure your response EXACTLY as follows:

## Severity
P0 (critical), P1 (high), P2 (medium), or P3 (low).
Justify your rating in 1-2 sentences.

## Scope
isolated (one file/function), module (one feature area), or system (cross-cutting).
Explain what is affected.

## Frequency
First occurrence, recurring (N times in history), or escalating.
Reference specific historical issues if similar ones exist.

## Priority Recommendation
Combine severity, scope, and frequency into a priority recommendation.
State whether this should be fixed now, soon, or later, and why.
"""


def _summarize_recent_issues(current_issue_id: str) -> str:
    """Build a summary of recent issues for pattern detection."""
    issues_path = os.path.join(get_data_dir(), "issues.jsonl")
    all_issues = read_jsonl(issues_path)

    # Exclude the current issue, take last 10
    other_issues = [i for i in all_issues if i.get("id") != current_issue_id]
    recent = other_issues[-10:]

    if not recent:
        return "No prior issues recorded."

    lines = []
    for issue in recent:
        sanitized_desc = sanitize_context(issue.get("description", ""))[:150]
        lines.append(
            f"- [{issue.get('id', '?')}] {issue.get('type', '?')} | "
            f"{issue.get('tool_name', '?')} | {sanitized_desc}"
        )

    return "\n".join(lines)


def assess_impact(issue_id: str) -> bool:
    """
    Assess the impact of a specific issue.

    Args:
        issue_id: The issue ID to assess

    Returns:
        True if assessment completed successfully
    """
    log = AgentLogger(issue_id, "IMPACT")
    log.section("Impact Assessment")

    # Load the issue record
    issues_path = os.path.join(get_data_dir(), "issues.jsonl")
    issue = read_jsonl_by_id(issues_path, issue_id)

    if not issue:
        log.error(f"Issue not found: {issue_id}")
        return False

    log.info("Issue loaded, constructing impact assessment prompt")

    # Build historical context
    recent_issues_summary = _summarize_recent_issues(issue_id)

    # Build the prompt
    prompt = _IMPACT_PROMPT.format(
        tool_name=issue.get("tool_name", "unknown"),
        description=sanitize_context(issue.get("description", "No description")),
        git_branch=issue.get("git_branch", "unknown"),
        recent_files=", ".join(issue.get("recent_files", [])) or "none",
        recent_issues_summary=recent_issues_summary,
    )

    # Dispatch to Claude Code headless
    result = run_agent(
        prompt=prompt,
        stage="research",
        issue_id=issue_id,
        log=log,
    )

    if not result.success:
        log.error(f"Impact assessor failed: {result.error}")
        return False

    # Write output
    research_dir = get_research_dir(issue_id)
    success = write_research_output(research_dir, "impact.md", result.output, log)

    if success:
        log.info("Impact assessment complete")

    return success


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m agents.impact_assessor <issue_id>", file=sys.stderr)
        sys.exit(1)

    issue_id = sys.argv[1]
    success = assess_impact(issue_id)
    sys.exit(0 if success else 1)
