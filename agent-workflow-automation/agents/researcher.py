"""
Convergence Engine - Root Cause Research Agent

Analyzes an issue to determine its root cause. Reads the issue record
from issues.jsonl, constructs a research prompt, dispatches to Claude Code
headless mode, and writes findings to data/research/{issue_id}/root_cause.md.
"""

import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PLUGIN_ROOT)

from agents.config import get_data_dir, get_research_dir
from agents.file_lock import read_jsonl_by_id
from agents.logger import AgentLogger
from agents.runner import run_agent, write_research_output
from agents.sanitizer import sanitize_context


_RESEARCH_PROMPT = """You are a root cause analysis agent. Your job is to investigate an error
that occurred during software development and determine WHY it happened.

## Error Context

Tool: {tool_name}
Error: {description}
Working Directory: {working_directory}
Git Branch: {git_branch}
Recently Changed Files: {recent_files}

## Instructions

Analyze this error carefully. Consider:
- What the tool was trying to do
- Why it failed based on the error message
- What conditions or prior changes could have caused this
- Whether this is a symptom of a deeper issue

## Required Output Format

Structure your response EXACTLY as follows:

## Hypothesis
State your primary hypothesis for the root cause. Be specific.

## Evidence
List the evidence from the error context that supports your hypothesis.

## Confidence
State: high, medium, or low -- with a brief justification.

## Related Patterns
Note any patterns this error shares with common development issues
(dependency problems, state management bugs, configuration drift, etc.)
"""


def research_issue(issue_id: str) -> bool:
    """
    Run root cause analysis on a specific issue.

    Args:
        issue_id: The issue ID to research

    Returns:
        True if research completed successfully
    """
    log = AgentLogger(issue_id, "RESEARCH")
    log.section("Root Cause Analysis")

    # Load the issue record
    issues_path = os.path.join(get_data_dir(), "issues.jsonl")
    issue = read_jsonl_by_id(issues_path, issue_id)

    if not issue:
        log.error(f"Issue not found: {issue_id}")
        return False

    log.info("Issue loaded, constructing research prompt")

    # Build the prompt with issue context
    prompt = _RESEARCH_PROMPT.format(
        tool_name=issue.get("tool_name", "unknown"),
        description=sanitize_context(issue.get("description", "No description")),
        working_directory=issue.get("working_directory", "unknown"),
        git_branch=issue.get("git_branch", "unknown"),
        recent_files=", ".join(issue.get("recent_files", [])) or "none",
    )

    # Dispatch to Claude Code headless
    result = run_agent(
        prompt=prompt,
        stage="research",
        issue_id=issue_id,
        log=log,
    )

    if not result.success:
        log.error(f"Research agent failed: {result.error}")
        return False

    # Write output
    research_dir = get_research_dir(issue_id)
    success = write_research_output(research_dir, "root_cause.md", result.output, log)

    if success:
        log.info("Root cause analysis complete")

    return success


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m agents.researcher <issue_id>", file=sys.stderr)
        sys.exit(1)

    issue_id = sys.argv[1]
    success = research_issue(issue_id)
    sys.exit(0 if success else 1)
