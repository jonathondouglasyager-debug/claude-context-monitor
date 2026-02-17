"""
Convergence Engine - Checkpoint Manager (Phase 4.3)

Saves pipeline state after each phase completion per issue, enabling:
  - Re-running downstream phases without re-research
  - Resuming interrupted pipelines from the last successful phase
  - Trajectory analysis in the arbiter (timing + phase history)

Checkpoint file: data/research/{issue_id}/checkpoint.json

Inspired by AgentDebug/AgentGit (arxiv 2509.25370): checkpoint + trajectory
analysis for agent recovery.
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

from agents.config import get_research_dir


# Valid pipeline phases in execution order
PIPELINE_PHASES = ("research", "debate", "convergence")

# Phase statuses
PHASE_COMPLETED = "completed"
PHASE_FAILED = "failed"
PHASE_SKIPPED = "skipped"
PHASE_IN_PROGRESS = "in_progress"


def _checkpoint_path(issue_id: str) -> str:
    """Return the absolute path to the checkpoint file for an issue."""
    return os.path.join(get_research_dir(issue_id), "checkpoint.json")


def load_checkpoint(issue_id: str) -> dict:
    """
    Load the checkpoint for an issue.

    Returns:
        Checkpoint dict, or empty structure if no checkpoint exists.
    """
    path = _checkpoint_path(issue_id)
    if not os.path.exists(path):
        return _empty_checkpoint(issue_id)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Ensure required keys exist
        data.setdefault("issue_id", issue_id)
        data.setdefault("phases", {})
        data.setdefault("trajectory", [])
        return data
    except (json.JSONDecodeError, Exception):
        return _empty_checkpoint(issue_id)


def save_checkpoint(
    issue_id: str,
    phase: str,
    status: str = PHASE_COMPLETED,
    details: Optional[dict] = None,
) -> bool:
    """
    Save or update a phase checkpoint for an issue.

    Records the phase completion (or failure) and appends to the trajectory
    log for post-hoc analysis.

    Args:
        issue_id: The issue being processed
        phase: Pipeline phase name (research, debate, convergence)
        status: Phase status (completed, failed, skipped, in_progress)
        details: Optional per-phase metadata (e.g., agent results, round count)

    Returns:
        True if checkpoint saved successfully
    """
    if phase not in PIPELINE_PHASES:
        return False

    now = datetime.now(timezone.utc).isoformat()
    checkpoint = load_checkpoint(issue_id)

    # Update phase record
    phase_record = {
        "status": status,
        "timestamp": now,
    }
    if details:
        phase_record["details"] = details

    checkpoint["phases"][phase] = phase_record
    checkpoint["last_updated"] = now

    # Append to trajectory log (immutable history)
    checkpoint["trajectory"].append({
        "phase": phase,
        "status": status,
        "timestamp": now,
        "details": details,
    })

    # Write checkpoint
    path = _checkpoint_path(issue_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def get_completed_phases(issue_id: str) -> list[str]:
    """
    Return list of completed phase names for an issue, in pipeline order.

    Only includes phases with status == "completed".
    """
    checkpoint = load_checkpoint(issue_id)
    phases = checkpoint.get("phases", {})
    return [
        p for p in PIPELINE_PHASES
        if phases.get(p, {}).get("status") == PHASE_COMPLETED
    ]


def is_phase_completed(issue_id: str, phase: str) -> bool:
    """Check if a specific phase has been completed for an issue."""
    checkpoint = load_checkpoint(issue_id)
    return checkpoint.get("phases", {}).get(phase, {}).get("status") == PHASE_COMPLETED


def can_skip_phase(issue_id: str, phase: str) -> bool:
    """
    Determine if a phase can be safely skipped (already completed with valid outputs).

    Checks both the checkpoint status AND that expected output files exist.
    This prevents skipping when outputs were manually deleted.
    """
    if not is_phase_completed(issue_id, phase):
        return False

    # Verify output files actually exist
    research_dir = get_research_dir(issue_id)

    if phase == "research":
        # At least one research output must exist
        research_files = ("root_cause.md", "solutions.md", "impact.md")
        return any(
            os.path.exists(os.path.join(research_dir, f))
            for f in research_files
        )
    elif phase == "debate":
        # Debate output must exist
        return os.path.exists(os.path.join(research_dir, "debate.md"))
    elif phase == "convergence":
        # Convergence is always re-run (it aggregates all issues)
        return False

    return False


def clear_checkpoint(issue_id: str, from_phase: Optional[str] = None) -> bool:
    """
    Clear checkpoint data from a specific phase onward.

    If from_phase is None, clears the entire checkpoint.
    If from_phase is specified, clears that phase and all downstream phases.

    This enables re-running phases: clearing "debate" also clears "convergence"
    so both will re-run.

    Args:
        issue_id: The issue to clear
        from_phase: Phase to clear from (inclusive), or None for all

    Returns:
        True if checkpoint was modified
    """
    checkpoint = load_checkpoint(issue_id)

    if from_phase is None:
        # Clear everything
        checkpoint["phases"] = {}
        checkpoint["last_updated"] = datetime.now(timezone.utc).isoformat()
        checkpoint["trajectory"].append({
            "phase": "all",
            "status": "cleared",
            "timestamp": checkpoint["last_updated"],
            "details": None,
        })
    elif from_phase in PIPELINE_PHASES:
        # Clear from this phase onward
        phase_idx = PIPELINE_PHASES.index(from_phase)
        for phase in PIPELINE_PHASES[phase_idx:]:
            if phase in checkpoint["phases"]:
                del checkpoint["phases"][phase]
        checkpoint["last_updated"] = datetime.now(timezone.utc).isoformat()
        checkpoint["trajectory"].append({
            "phase": from_phase,
            "status": "cleared_from",
            "timestamp": checkpoint["last_updated"],
            "details": {"cleared_phases": list(PIPELINE_PHASES[phase_idx:])},
        })
    else:
        return False

    path = _checkpoint_path(issue_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def get_trajectory(issue_id: str) -> list[dict]:
    """
    Return the full trajectory log for an issue.

    The trajectory is an append-only history of all phase transitions,
    useful for arbiter analysis and debugging.
    """
    checkpoint = load_checkpoint(issue_id)
    return checkpoint.get("trajectory", [])


def get_resume_phase(issue_id: str) -> Optional[str]:
    """
    Determine which phase to resume from for an interrupted pipeline.

    Returns the first non-completed phase in pipeline order, or None
    if all phases are complete.
    """
    completed = set(get_completed_phases(issue_id))
    for phase in PIPELINE_PHASES:
        if phase not in completed:
            return phase
    return None


def _empty_checkpoint(issue_id: str) -> dict:
    """Return an empty checkpoint structure."""
    return {
        "issue_id": issue_id,
        "phases": {},
        "trajectory": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
