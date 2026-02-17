"""
Convergence Engine - Pipeline Orchestrator

Coordinates the full issue processing pipeline:
  capture -> research (parallel) -> debate -> converge

Respects budget controls (max_parallel_agents) and updates issue status
at each stage transition.
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PLUGIN_ROOT)

from agents.config import (
    get_data_dir,
    get_max_parallel,
    is_convergence_enabled,
    get_research_dir,
)
from agents.file_lock import read_jsonl, read_jsonl_by_id, update_jsonl_record
from agents.logger import AgentLogger, PipelineLogger
from agents.schema_validator import validate_issue, validate_all_issues
from agents.researcher import research_issue
from agents.solution_finder import find_solutions
from agents.impact_assessor import assess_impact


def research_single_issue(issue_id: str) -> dict:
    """
    Run all three research agents on a single issue.

    Researcher and solution_finder run in parallel (up to max_parallel_agents),
    then impact_assessor runs after (it benefits from having solutions context).

    Args:
        issue_id: Issue to research

    Returns:
        Dict with per-agent success status
    """
    log = PipelineLogger("PIPELINE")
    issues_path = os.path.join(get_data_dir(), "issues.jsonl")

    # Verify issue exists
    issue = read_jsonl_by_id(issues_path, issue_id)
    if not issue:
        log.error(f"Issue not found: {issue_id}")
        return {"researcher": False, "solution_finder": False, "impact_assessor": False}

    # Update status to researching
    update_jsonl_record(issues_path, issue_id, {"status": "researching"})
    log.info(f"Starting research pipeline for {issue_id}")

    results = {"researcher": False, "solution_finder": False, "impact_assessor": False}
    max_parallel = get_max_parallel()

    # Phase 1: Run researcher + solution_finder in parallel
    with ThreadPoolExecutor(max_workers=min(max_parallel, 2)) as executor:
        futures = {
            executor.submit(research_issue, issue_id): "researcher",
            executor.submit(find_solutions, issue_id): "solution_finder",
        }
        for future in as_completed(futures):
            agent_name = futures[future]
            try:
                results[agent_name] = future.result()
            except Exception as e:
                log.error(f"Agent {agent_name} raised exception: {e}")
                results[agent_name] = False

    # Phase 2: Run impact_assessor after (it can reference research outputs)
    try:
        results["impact_assessor"] = assess_impact(issue_id)
    except Exception as e:
        log.error(f"Impact assessor raised exception: {e}")
        results["impact_assessor"] = False

    # Update status based on results
    any_success = any(results.values())
    new_status = "researched" if any_success else "captured"  # Fall back if all failed
    update_jsonl_record(issues_path, issue_id, {"status": new_status})

    log.info(
        f"Research pipeline complete for {issue_id}",
        results=str(results),
        status=new_status,
    )

    return results


def research_all_unresearched() -> dict:
    """
    Find all issues with status 'captured' and research them.

    Returns:
        Dict mapping issue_id -> per-agent results
    """
    log = PipelineLogger("PIPELINE")
    issues_path = os.path.join(get_data_dir(), "issues.jsonl")

    # Validate issues first
    validation = validate_all_issues(issues_path)
    if validation["quarantined"] > 0:
        log.warn(
            f"Quarantined {validation['quarantined']} corrupt issue records",
            errors=str(validation["errors"][:5]),
        )

    all_issues = read_jsonl(issues_path)
    captured = [i for i in all_issues if i.get("status") == "captured"]

    if not captured:
        log.info("No unresearched issues found")
        return {}

    log.info(f"Found {len(captured)} unresearched issues")

    all_results = {}
    for issue in captured:
        issue_id = issue.get("id")
        if issue_id:
            all_results[issue_id] = research_single_issue(issue_id)

    return all_results


def get_pipeline_status() -> dict:
    """
    Get a summary of the pipeline state.

    Returns:
        Dict with counts per status and total issues
    """
    issues_path = os.path.join(get_data_dir(), "issues.jsonl")
    all_issues = read_jsonl(issues_path)

    status_counts = {}
    for issue in all_issues:
        status = issue.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "total": len(all_issues),
        "by_status": status_counts,
    }


def list_issues(status_filter: Optional[str] = None) -> list[dict]:
    """
    List issues, optionally filtered by status.

    Args:
        status_filter: Only return issues with this status (or None for all)

    Returns:
        List of issue records
    """
    issues_path = os.path.join(get_data_dir(), "issues.jsonl")
    all_issues = read_jsonl(issues_path)

    if status_filter:
        return [i for i in all_issues if i.get("status") == status_filter]

    return all_issues


if __name__ == "__main__":
    """CLI interface for the pipeline."""
    if len(sys.argv) < 2:
        print("Usage:", file=sys.stderr)
        print("  python -m agents.pipeline research <issue_id>", file=sys.stderr)
        print("  python -m agents.pipeline research-all", file=sys.stderr)
        print("  python -m agents.pipeline status", file=sys.stderr)
        sys.exit(1)

    action = sys.argv[1]

    if action == "research" and len(sys.argv) >= 3:
        results = research_single_issue(sys.argv[2])
        print(f"Research results: {results}")
    elif action == "research-all":
        results = research_all_unresearched()
        print(f"Researched {len(results)} issues")
        for issue_id, result in results.items():
            print(f"  {issue_id}: {result}")
    elif action == "status":
        import json
        status = get_pipeline_status()
        print(json.dumps(status, indent=2))
    else:
        print(f"Unknown action: {action}", file=sys.stderr)
        sys.exit(1)
