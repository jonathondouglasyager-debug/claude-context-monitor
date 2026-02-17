"""
Convergence Engine - Debate Agent

Takes the three research outputs (root_cause, solutions, impact) and generates
a cross-agent critique. Identifies agreements, contradictions, and gaps.
Writes full transcript to data/research/{issue_id}/debate.log for auditability.
"""

import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PLUGIN_ROOT)

import json as json_module

from agents.config import get_data_dir, get_research_dir
from agents.file_lock import read_jsonl_by_id, update_jsonl_record
from agents.logger import AgentLogger
from agents.runner import run_agent, write_research_output, write_research_json


_DEBATE_PROMPT = """You are a debate and critique agent. Three independent research agents investigated
a software development issue. Your job is to compare their findings, identify where they
agree, where they contradict, and what none of them considered.

## Issue Being Investigated

ID: {issue_id}
Description: {description}

## Agent Findings

### ROOT CAUSE ANALYSIS (Researcher Agent)
{root_cause}

{root_cause_json_section}

### SOLUTION RESEARCH (Solution Finder Agent)
{solutions}

{solutions_json_section}

### IMPACT ASSESSMENT (Impact Assessor Agent)
{impact}

{impact_json_section}

## Instructions

Critically analyze these three perspectives:

1. Where do all agents agree? These are high-confidence findings.
2. Where do agents contradict each other? Which position is better supported?
3. What did NO agent consider that should be investigated?
4. Synthesize a unified assessment that is stronger than any individual agent's.

Be direct and specific. Quote from the agent outputs when referencing their positions.
If structured JSON data is available from agents, use those fields for precise comparison.

## Required Output Format

## Agreements
High-confidence findings supported by multiple agents.

## Contradictions
Where agents disagree, and which position the evidence better supports.

## Gaps
Critical considerations that no agent addressed.

## Revised Assessment
A unified position incorporating the strongest elements from all three analyses.
Include: root cause (revised), recommended fix (revised), and priority (revised).

## Structured Output

After your markdown analysis, include a JSON block with the following format:

===JSON_OUTPUT===
{{
  "agreements": ["finding 1", "finding 2"],
  "contradictions": [{{"description": "what disagrees", "better_supported": "which position wins"}}],
  "gaps": ["gap 1", "gap 2"],
  "revised_root_cause": "unified root cause",
  "revised_fix": "unified recommended fix",
  "revised_priority": "P0|P1|P2|P3"
}}
===JSON_OUTPUT_END===
"""


def _read_research_file(research_dir: str, filename: str) -> str:
    """Read a research output file, returning a fallback message if missing."""
    filepath = os.path.join(research_dir, filename)
    if not os.path.exists(filepath):
        return f"[MISSING: {filename} was not produced by its agent]"

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read().strip()

    return content if content else f"[EMPTY: {filename} was produced but contains no content]"


def _read_research_json(research_dir: str, filename: str) -> str:
    """
    Read a structured JSON research file and format it for the debate prompt.

    Returns a formatted string showing the structured data, or empty string if
    the JSON file doesn't exist.
    """
    filepath = os.path.join(research_dir, filename)
    if not os.path.exists(filepath):
        return ""

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json_module.load(f)
        return f"**Structured Data ({filename}):**\n```json\n{json_module.dumps(data, indent=2)}\n```"
    except (json_module.JSONDecodeError, Exception):
        return ""


def debate_issue(issue_id: str) -> bool:
    """
    Run the debate agent on a researched issue.

    Requires that at least one research file exists in data/research/{issue_id}/.

    Args:
        issue_id: The issue ID to debate

    Returns:
        True if debate completed successfully
    """
    log = AgentLogger(issue_id, "DEBATE")
    log.section("Cross-Agent Debate")

    # Load the issue record
    issues_path = os.path.join(get_data_dir(), "issues.jsonl")
    issue = read_jsonl_by_id(issues_path, issue_id)

    if not issue:
        log.error(f"Issue not found: {issue_id}")
        return False

    # Check research files exist
    research_dir = get_research_dir(issue_id)
    root_cause = _read_research_file(research_dir, "root_cause.md")
    solutions = _read_research_file(research_dir, "solutions.md")
    impact = _read_research_file(research_dir, "impact.md")

    # Phase 4: Load structured JSON from research agents (if available)
    root_cause_json = _read_research_json(research_dir, "root_cause.json")
    solutions_json = _read_research_json(research_dir, "solutions.json")
    impact_json = _read_research_json(research_dir, "impact.json")

    # At least one must have real content
    has_content = any(
        not content.startswith("[MISSING") and not content.startswith("[EMPTY")
        for content in [root_cause, solutions, impact]
    )

    if not has_content:
        log.error("No research outputs found. Run research first.")
        return False

    # Update status
    update_jsonl_record(issues_path, issue_id, {"status": "debating"})
    log.info("Research outputs loaded, constructing debate prompt")

    if any([root_cause_json, solutions_json, impact_json]):
        log.info("Structured JSON available from research agents — including in debate context")

    # Build the prompt
    prompt = _DEBATE_PROMPT.format(
        issue_id=issue_id,
        description=issue.get("description", "No description")[:1000],
        root_cause=root_cause,
        solutions=solutions,
        impact=impact,
        root_cause_json_section=root_cause_json,
        solutions_json_section=solutions_json,
        impact_json_section=impact_json,
    )

    # Dispatch to Claude Code headless
    result = run_agent(
        prompt=prompt,
        stage="debate",
        issue_id=issue_id,
        log=log,
    )

    if not result.success:
        log.error(f"Debate agent failed: {result.error}")
        update_jsonl_record(issues_path, issue_id, {"status": "researched"})
        return False

    # Write debate output as both .md (for convergence) and .log (for auditability)
    success_md = write_research_output(research_dir, "debate.md", result.markdown_output, log)
    success_log = write_research_output(research_dir, "debate.log", result.output, log)

    # Write structured JSON if available (Phase 4)
    if result.structured_output is not None:
        write_research_json(
            research_dir, "debate.json", result.structured_output, "debater", log
        )
    else:
        log.warn("No structured JSON in debate output (markdown-only fallback)")

    if success_md:
        update_jsonl_record(issues_path, issue_id, {"status": "debated"})
        log.info("Debate complete")

    return success_md


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m agents.debater <issue_id>", file=sys.stderr)
        sys.exit(1)

    issue_id = sys.argv[1]
    success = debate_issue(issue_id)
    sys.exit(0 if success else 1)
