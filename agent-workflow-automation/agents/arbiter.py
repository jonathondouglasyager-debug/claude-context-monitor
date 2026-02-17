"""
Convergence Engine - Arbiter / Convergence Synthesizer

Reads all debated issues and produces two convergence artifacts:
  1. convergence/convergence.md  -- Human-readable convergence report
  2. convergence/tasks.json      -- Machine-parseable task list

This is the final stage of the pipeline. It runs on SessionEnd (via hook)
or manually via /converge synthesize. It NEVER runs per-error.
"""

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from typing import Optional

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PLUGIN_ROOT)

from agents.config import (
    get_data_dir,
    get_research_dir,
    get_convergence_dir,
    get_archive_dir,
    load_convergence_config,
)
from agents.file_lock import read_jsonl, update_jsonl_record
from agents.logger import AgentLogger, PipelineLogger
from agents.runner import run_agent, write_research_output


_CONVERGENCE_PROMPT = """You are the convergence arbiter. Multiple issues have been researched and debated
by independent agents. Your job is to synthesize everything into a single, actionable
convergence report and generate specific tasks.

## Issues to Converge

{issues_block}

## Instructions

Produce a convergence report that:
1. Summarizes each issue with its root cause, recommended fix, and priority
2. Identifies cross-issue patterns (are multiple issues related? same root cause?)
3. Generates a prioritized list of concrete tasks
4. Recommends an action order (what to fix first and why)

Each task must include:
- A clear title (imperative verb, e.g., "Fix authentication timeout")
- Specific description of what to do
- Priority (P0-P3)
- Complexity estimate (low/medium/high)
- Which files are likely affected
- A suggested approach

## Required Output Format

Produce your output in TWO CLEARLY SEPARATED SECTIONS using these exact delimiters:

===CONVERGENCE_REPORT===

# Convergence Report -- {date}

## Session Summary
Issues analyzed: N | Resolved: M | Pending: K

(For each issue:)
### Issue: [title]
- **Root Cause:** ...
- **Confidence:** high/medium/low
- **Recommended Fix:** ...
- **Priority:** P0-P3
- **Tasks Generated:** N

## Cross-Issue Patterns
- (any observations about related issues)

## Recommended Action Order
1. (highest priority task first)
2. ...

===TASKS_JSON===

[
  {{
    "title": "...",
    "description": "...",
    "issue_id": "...",
    "priority": "P1",
    "complexity": "low",
    "files_likely_affected": ["..."],
    "suggested_approach": "..."
  }}
]
"""


def _build_issues_block(issues: list[dict]) -> str:
    """
    Build the context block containing all issue research for the arbiter.
    """
    blocks = []

    for issue in issues:
        issue_id = issue.get("id", "unknown")
        research_dir = get_research_dir(issue_id)

        block = f"### Issue: {issue_id}\n"
        block += f"**Type:** {issue.get('type', 'unknown')}\n"
        block += f"**Tool:** {issue.get('tool_name', 'unknown')}\n"
        block += f"**Description:** {issue.get('description', 'N/A')[:500]}\n\n"

        # Load debate output (preferred) or individual research files
        debate_path = os.path.join(research_dir, "debate.md")
        if os.path.exists(debate_path):
            with open(debate_path, "r", encoding="utf-8") as f:
                block += f"**Debate Synthesis:**\n{f.read()}\n\n"
        else:
            # Fall back to individual research files
            for filename in ("root_cause.md", "solutions.md", "impact.md"):
                filepath = os.path.join(research_dir, filename)
                if os.path.exists(filepath):
                    with open(filepath, "r", encoding="utf-8") as f:
                        label = filename.replace(".md", "").replace("_", " ").title()
                        block += f"**{label}:**\n{f.read()}\n\n"

        blocks.append(block)

    return "\n---\n\n".join(blocks)


def _archive_previous_convergence() -> None:
    """Move existing convergence.md and tasks.json to archive/."""
    convergence_dir = get_convergence_dir()
    archive_dir = get_archive_dir()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    for filename in ("convergence.md", "tasks.json"):
        src = os.path.join(convergence_dir, filename)
        if os.path.exists(src):
            name, ext = os.path.splitext(filename)
            dst = os.path.join(archive_dir, f"{name}_{timestamp}{ext}")
            shutil.move(src, dst)


def _parse_convergence_output(raw_output: str) -> tuple[str, list[dict]]:
    """
    Parse the arbiter's output into report markdown and tasks JSON.

    Returns:
        Tuple of (report_markdown, tasks_list)
    """
    report = ""
    tasks = []

    if "===CONVERGENCE_REPORT===" in raw_output and "===TASKS_JSON===" in raw_output:
        parts = raw_output.split("===TASKS_JSON===")
        report_part = parts[0].replace("===CONVERGENCE_REPORT===", "").strip()
        tasks_part = parts[1].strip() if len(parts) > 1 else "[]"

        report = report_part

        # Parse tasks JSON
        try:
            # Find the JSON array in the tasks section
            json_start = tasks_part.find("[")
            json_end = tasks_part.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                tasks = json.loads(tasks_part[json_start:json_end])
            else:
                 # No JSON array found
                 raise json.JSONDecodeError("No parsed tasks found", tasks_part, 0)
        except json.JSONDecodeError:
            # If JSON parsing fails, include raw text as a note
            report += f"\n\n---\n\n**Note:** Task extraction failed. Raw output:\n{tasks_part}"
    else:
        # Fallback: treat entire output as the report
        report = raw_output

    # Add task IDs and status
    for i, task in enumerate(tasks):
        task["id"] = f"task_{i+1:03d}"
        task["status"] = "pending"

    return report, tasks


def synthesize(issue_filter: Optional[str] = None) -> bool:
    """
    Run the arbiter to produce convergence artifacts.

    Processes all issues with status 'debated' (or 'researched' if no debated
    issues exist). Archives previous convergence docs before writing new ones.

    Args:
        issue_filter: Optional specific issue ID to converge (or None for all eligible)

    Returns:
        True if convergence completed successfully
    """
    log = PipelineLogger("CONVERGE")
    log.section("Convergence Synthesis")

    issues_path = os.path.join(get_data_dir(), "issues.jsonl")
    all_issues = read_jsonl(issues_path)

    # Find eligible issues
    if issue_filter:
        eligible = [i for i in all_issues if i.get("id") == issue_filter]
    else:
        # Prefer debated, fall back to researched
        eligible = [i for i in all_issues if i.get("status") == "debated"]
        if not eligible:
            eligible = [i for i in all_issues if i.get("status") == "researched"]

    config = load_convergence_config()
    min_issues = config.get("min_issues_for_convergence", 1)

    if len(eligible) < min_issues:
        log.info(
            f"Not enough eligible issues ({len(eligible)}) for convergence "
            f"(minimum: {min_issues})"
        )
        return False

    log.info(f"Converging {len(eligible)} issues")

    # Archive previous convergence
    _archive_previous_convergence()

    # Build the context block
    issues_block = _build_issues_block(eligible)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Build prompt
    prompt = _CONVERGENCE_PROMPT.format(
        issues_block=issues_block,
        date=date_str,
    )

    # Dispatch to arbiter
    result = run_agent(
        prompt=prompt,
        stage="converge",
        issue_id="CONVERGENCE",
        log=log,
    )

    if not result.success:
        log.error(f"Arbiter failed: {result.error}")
        return False

    # Parse output
    report, tasks = _parse_convergence_output(result.output)

    # Write convergence.md
    convergence_dir = get_convergence_dir()
    report_path = os.path.join(convergence_dir, "convergence.md")
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        log.info(f"Convergence report written: {report_path}")
    except Exception as e:
        log.error(f"Failed to write convergence report: {e}")
        return False

    # Write tasks.json
    tasks_path = os.path.join(convergence_dir, "tasks.json")
    try:
        with open(tasks_path, "w", encoding="utf-8") as f:
            json.dump(tasks, f, indent=2, ensure_ascii=False)
        log.info(f"Tasks written: {len(tasks)} tasks to {tasks_path}")
    except Exception as e:
        log.error(f"Failed to write tasks: {e}")
        return False

    # Update issue statuses
    for issue in eligible:
        issue_id = issue.get("id")
        if issue_id:
            update_jsonl_record(issues_path, issue_id, {"status": "converged"})

    log.info(f"Convergence complete: {len(eligible)} issues, {len(tasks)} tasks")
    return True


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        success = synthesize(issue_filter=sys.argv[1])
    else:
        success = synthesize()

    sys.exit(0 if success else 1)
