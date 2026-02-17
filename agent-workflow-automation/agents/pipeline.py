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
from agents.checkpoint import (
    save_checkpoint,
    can_skip_phase,
    get_resume_phase,
    clear_checkpoint,
    get_completed_phases,
    PHASE_COMPLETED,
    PHASE_FAILED,
)
from agents.file_lock import read_jsonl, read_jsonl_by_id, update_jsonl_record
from agents.logger import AgentLogger, PipelineLogger
from agents.schema_validator import validate_issue, validate_all_issues
from agents.researcher import research_issue
from agents.solution_finder import find_solutions
from agents.impact_assessor import assess_impact


def research_single_issue(issue_id: str, force: bool = False) -> dict:
    """
    Run all three research agents on a single issue.

    Researcher and solution_finder run in parallel (up to max_parallel_agents),
    then impact_assessor runs after (it benefits from having solutions context).

    Phase 4.3: Checks checkpoint before running. If research is already completed
    and outputs exist, skips re-research unless force=True.

    Args:
        issue_id: Issue to research
        force: If True, ignore checkpoint and re-run research

    Returns:
        Dict with per-agent success status
    """
    log = PipelineLogger("PIPELINE")
    issues_path = os.path.join(get_data_dir(), "issues.jsonl")

    # Phase 4.3: Check checkpoint — skip if already done
    if not force and can_skip_phase(issue_id, "research"):
        log.info(f"Checkpoint: research already completed for {issue_id}, skipping")
        return {"researcher": True, "solution_finder": True, "impact_assessor": True}

    # Verify issue exists
    issue = read_jsonl_by_id(issues_path, issue_id)
    if not issue:
        log.error(f"Issue not found: {issue_id}")
        return {"researcher": False, "solution_finder": False, "impact_assessor": False}

    # Mark phase in-progress in checkpoint
    save_checkpoint(issue_id, "research", "in_progress")

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

    # Phase 4.3: Save checkpoint
    checkpoint_status = PHASE_COMPLETED if any_success else PHASE_FAILED
    save_checkpoint(issue_id, "research", checkpoint_status, details={
        "agents": results,
    })

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


def run_full_pipeline(
    issue_id: str,
    from_phase: Optional[str] = None,
    force: bool = False,
) -> dict:
    """
    Run the full pipeline for an issue: research → debate → converge.

    Phase 4.3: Supports resuming from a specific phase. Phases before
    from_phase are skipped if their checkpoint is completed.

    Args:
        issue_id: Issue to process
        from_phase: Phase to start from (None = auto-detect via checkpoint)
        force: If True, ignore checkpoints and re-run everything

    Returns:
        Dict with per-phase results
    """
    from agents.debater import debate_issue
    from agents.arbiter import synthesize

    log = PipelineLogger("PIPELINE")
    pipeline_results = {"research": None, "debate": None, "convergence": None}

    # Determine starting phase
    if force:
        clear_checkpoint(issue_id)
        start_phase = "research"
    elif from_phase:
        if from_phase not in ("research", "debate", "convergence"):
            log.error(f"Invalid phase: {from_phase}")
            return pipeline_results
        # Clear from this phase onward so they re-run
        clear_checkpoint(issue_id, from_phase)
        start_phase = from_phase
    else:
        start_phase = get_resume_phase(issue_id) or "research"

    log.info(f"Running full pipeline for {issue_id} starting from '{start_phase}'")

    phase_idx = list(("research", "debate", "convergence")).index(start_phase)

    # ── Research ──
    if phase_idx <= 0:
        research_results = research_single_issue(issue_id, force=force)
        pipeline_results["research"] = research_results
        if not any(research_results.values()):
            log.error("Research failed — stopping pipeline")
            return pipeline_results
    else:
        log.info("Skipping research (checkpoint completed)")
        pipeline_results["research"] = {"skipped": True}

    # ── Debate ──
    if phase_idx <= 1:
        if not force and can_skip_phase(issue_id, "debate"):
            log.info("Checkpoint: debate already completed, skipping")
            pipeline_results["debate"] = True
        else:
            save_checkpoint(issue_id, "debate", "in_progress")
            debate_success = debate_issue(issue_id)
            pipeline_results["debate"] = debate_success
            save_checkpoint(
                issue_id, "debate",
                PHASE_COMPLETED if debate_success else PHASE_FAILED,
            )
            if not debate_success:
                log.warn("Debate failed — continuing to convergence with research only")
    else:
        log.info("Skipping debate (checkpoint completed)")
        pipeline_results["debate"] = True

    # ── Convergence ──
    if phase_idx <= 2:
        save_checkpoint(issue_id, "convergence", "in_progress")
        converge_success = synthesize(issue_filter=issue_id)
        pipeline_results["convergence"] = converge_success
        save_checkpoint(
            issue_id, "convergence",
            PHASE_COMPLETED if converge_success else PHASE_FAILED,
        )
    else:
        pipeline_results["convergence"] = True

    log.info(f"Full pipeline complete for {issue_id}: {pipeline_results}")
    return pipeline_results


if __name__ == "__main__":
    """CLI interface for the pipeline."""
    if len(sys.argv) < 2:
        print("Usage:", file=sys.stderr)
        print("  python -m agents.pipeline research <issue_id>", file=sys.stderr)
        print("  python -m agents.pipeline research-all", file=sys.stderr)
        print("  python -m agents.pipeline run <issue_id> [--from <phase>] [--force]", file=sys.stderr)
        print("  python -m agents.pipeline status", file=sys.stderr)
        print("  python -m agents.pipeline checkpoint <issue_id>", file=sys.stderr)
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
    elif action == "run" and len(sys.argv) >= 3:
        issue_id = sys.argv[2]
        from_phase = None
        force = "--force" in sys.argv
        if "--from" in sys.argv:
            from_idx = sys.argv.index("--from")
            if from_idx + 1 < len(sys.argv):
                from_phase = sys.argv[from_idx + 1]
        results = run_full_pipeline(issue_id, from_phase=from_phase, force=force)
        import json as json_mod
        print(json_mod.dumps(results, indent=2, default=str))
    elif action == "checkpoint" and len(sys.argv) >= 3:
        import json as json_mod
        from agents.checkpoint import load_checkpoint
        cp = load_checkpoint(sys.argv[2])
        print(json_mod.dumps(cp, indent=2))
    elif action == "status":
        import json
        status = get_pipeline_status()
        print(json.dumps(status, indent=2))
    else:
        print(f"Unknown action: {action}", file=sys.stderr)
        sys.exit(1)
