"""
Tests for Phase 4.3 — Checkpoint Architecture

Tests cover:
  - save/load checkpoint lifecycle
  - phase completion queries
  - can_skip_phase with output file verification
  - clear_checkpoint (full and partial)
  - trajectory logging
  - resume phase detection
  - edge cases (corrupt files, missing dirs)
  - full pipeline integration with checkpoints
"""

import json
import os
import pytest

from agents.checkpoint import (
    PIPELINE_PHASES,
    PHASE_COMPLETED,
    PHASE_FAILED,
    PHASE_IN_PROGRESS,
    PHASE_SKIPPED,
    can_skip_phase,
    clear_checkpoint,
    get_completed_phases,
    get_resume_phase,
    get_trajectory,
    is_phase_completed,
    load_checkpoint,
    save_checkpoint,
    _checkpoint_path,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def issue_id():
    return "test_issue_checkpoint_001"


@pytest.fixture
def research_dir(tmp_path, monkeypatch, issue_id):
    """Set up a temp research dir and patch get_research_dir."""
    rd = tmp_path / "research" / issue_id
    rd.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "agents.checkpoint.get_research_dir",
        lambda iid: str(rd) if iid == issue_id else str(tmp_path / "research" / iid),
    )
    return rd


# ─── Basic Save/Load ────────────────────────────────────────────────────────


class TestSaveLoad:
    def test_load_empty_checkpoint(self, issue_id, research_dir):
        """Loading a non-existent checkpoint returns empty structure."""
        cp = load_checkpoint(issue_id)
        assert cp["issue_id"] == issue_id
        assert cp["phases"] == {}
        assert cp["trajectory"] == []

    def test_save_and_load_checkpoint(self, issue_id, research_dir):
        """Save a checkpoint and verify it loads correctly."""
        assert save_checkpoint(issue_id, "research", PHASE_COMPLETED, details={"agents": {"r": True}})

        cp = load_checkpoint(issue_id)
        assert cp["issue_id"] == issue_id
        assert "research" in cp["phases"]
        assert cp["phases"]["research"]["status"] == PHASE_COMPLETED
        assert cp["phases"]["research"]["details"]["agents"]["r"] is True

    def test_save_multiple_phases(self, issue_id, research_dir):
        """Save checkpoints for multiple phases sequentially."""
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        save_checkpoint(issue_id, "debate", PHASE_COMPLETED)
        save_checkpoint(issue_id, "convergence", PHASE_COMPLETED)

        cp = load_checkpoint(issue_id)
        assert len(cp["phases"]) == 3
        for phase in PIPELINE_PHASES:
            assert cp["phases"][phase]["status"] == PHASE_COMPLETED

    def test_save_overwrites_phase(self, issue_id, research_dir):
        """Saving the same phase twice overwrites the previous record."""
        save_checkpoint(issue_id, "research", PHASE_IN_PROGRESS)
        save_checkpoint(issue_id, "research", PHASE_COMPLETED, details={"agents": {"r": True}})

        cp = load_checkpoint(issue_id)
        assert cp["phases"]["research"]["status"] == PHASE_COMPLETED

    def test_save_invalid_phase_returns_false(self, issue_id, research_dir):
        """Saving an invalid phase name returns False."""
        assert save_checkpoint(issue_id, "not_a_phase", PHASE_COMPLETED) is False

    def test_corrupt_checkpoint_returns_empty(self, issue_id, research_dir):
        """A corrupt checkpoint file returns empty structure."""
        path = _checkpoint_path(issue_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("{corrupt json!!!")

        cp = load_checkpoint(issue_id)
        assert cp["phases"] == {}
        assert cp["trajectory"] == []


# ─── Phase Queries ──────────────────────────────────────────────────────────


class TestPhaseQueries:
    def test_get_completed_phases_empty(self, issue_id, research_dir):
        """No completed phases for a fresh issue."""
        assert get_completed_phases(issue_id) == []

    def test_get_completed_phases_order(self, issue_id, research_dir):
        """Completed phases returned in pipeline order regardless of save order."""
        save_checkpoint(issue_id, "convergence", PHASE_COMPLETED)
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)

        completed = get_completed_phases(issue_id)
        assert completed == ["research", "convergence"]

    def test_failed_phases_not_in_completed(self, issue_id, research_dir):
        """Failed phases are not counted as completed."""
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        save_checkpoint(issue_id, "debate", PHASE_FAILED)

        completed = get_completed_phases(issue_id)
        assert "research" in completed
        assert "debate" not in completed

    def test_is_phase_completed(self, issue_id, research_dir):
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        assert is_phase_completed(issue_id, "research") is True
        assert is_phase_completed(issue_id, "debate") is False


# ─── Can Skip Phase ────────────────────────────────────────────────────────


class TestCanSkipPhase:
    def test_cannot_skip_without_checkpoint(self, issue_id, research_dir):
        """Cannot skip a phase with no checkpoint."""
        assert can_skip_phase(issue_id, "research") is False

    def test_cannot_skip_with_checkpoint_but_no_files(self, issue_id, research_dir):
        """Cannot skip research even with checkpoint if output files are missing."""
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        assert can_skip_phase(issue_id, "research") is False

    def test_can_skip_research_with_files(self, issue_id, research_dir):
        """Can skip research when checkpoint is complete AND output files exist."""
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        (research_dir / "root_cause.md").write_text("# Root cause analysis")
        assert can_skip_phase(issue_id, "research") is True

    def test_can_skip_research_any_file(self, issue_id, research_dir):
        """Any single research file is sufficient to skip."""
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        (research_dir / "solutions.md").write_text("# Solutions")
        assert can_skip_phase(issue_id, "research") is True

    def test_can_skip_debate_with_file(self, issue_id, research_dir):
        """Can skip debate when checkpoint + debate.md exist."""
        save_checkpoint(issue_id, "debate", PHASE_COMPLETED)
        (research_dir / "debate.md").write_text("# Debate output")
        assert can_skip_phase(issue_id, "debate") is True

    def test_cannot_skip_debate_without_file(self, issue_id, research_dir):
        """Cannot skip debate even with checkpoint if debate.md missing."""
        save_checkpoint(issue_id, "debate", PHASE_COMPLETED)
        assert can_skip_phase(issue_id, "debate") is False

    def test_convergence_never_skipped(self, issue_id, research_dir):
        """Convergence can never be skipped (always re-run since it aggregates)."""
        save_checkpoint(issue_id, "convergence", PHASE_COMPLETED)
        assert can_skip_phase(issue_id, "convergence") is False


# ─── Clear Checkpoint ───────────────────────────────────────────────────────


class TestClearCheckpoint:
    def test_clear_all(self, issue_id, research_dir):
        """Clear all phases."""
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        save_checkpoint(issue_id, "debate", PHASE_COMPLETED)

        assert clear_checkpoint(issue_id) is True

        cp = load_checkpoint(issue_id)
        assert cp["phases"] == {}

    def test_clear_from_phase(self, issue_id, research_dir):
        """Clear from debate onward keeps research."""
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        save_checkpoint(issue_id, "debate", PHASE_COMPLETED)
        save_checkpoint(issue_id, "convergence", PHASE_COMPLETED)

        assert clear_checkpoint(issue_id, "debate") is True

        cp = load_checkpoint(issue_id)
        assert "research" in cp["phases"]
        assert "debate" not in cp["phases"]
        assert "convergence" not in cp["phases"]

    def test_clear_from_research_clears_all_phases(self, issue_id, research_dir):
        """Clearing from research clears everything downstream."""
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        save_checkpoint(issue_id, "debate", PHASE_COMPLETED)

        clear_checkpoint(issue_id, "research")

        cp = load_checkpoint(issue_id)
        assert cp["phases"] == {}

    def test_clear_invalid_phase(self, issue_id, research_dir):
        """Clearing an invalid phase returns False."""
        assert clear_checkpoint(issue_id, "not_a_phase") is False

    def test_clear_adds_trajectory_entry(self, issue_id, research_dir):
        """Clearing adds an entry to the trajectory log."""
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        clear_checkpoint(issue_id, "research")

        trajectory = get_trajectory(issue_id)
        cleared = [t for t in trajectory if t["status"] == "cleared_from"]
        assert len(cleared) == 1
        assert "research" in cleared[0]["details"]["cleared_phases"]


# ─── Trajectory ─────────────────────────────────────────────────────────────


class TestTrajectory:
    def test_trajectory_accumulates(self, issue_id, research_dir):
        """Each save appends to trajectory."""
        save_checkpoint(issue_id, "research", PHASE_IN_PROGRESS)
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        save_checkpoint(issue_id, "debate", PHASE_IN_PROGRESS)
        save_checkpoint(issue_id, "debate", PHASE_FAILED)

        trajectory = get_trajectory(issue_id)
        assert len(trajectory) == 4
        assert trajectory[0]["phase"] == "research"
        assert trajectory[0]["status"] == PHASE_IN_PROGRESS
        assert trajectory[1]["status"] == PHASE_COMPLETED
        assert trajectory[3]["status"] == PHASE_FAILED

    def test_trajectory_survives_clear(self, issue_id, research_dir):
        """Trajectory is preserved even when phases are cleared."""
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        save_checkpoint(issue_id, "debate", PHASE_COMPLETED)
        clear_checkpoint(issue_id)

        trajectory = get_trajectory(issue_id)
        # 2 saves + 1 clear = 3 entries
        assert len(trajectory) == 3


# ─── Resume Phase Detection ────────────────────────────────────────────────


class TestResumePhase:
    def test_resume_from_start(self, issue_id, research_dir):
        """Fresh issue resumes from research."""
        assert get_resume_phase(issue_id) == "research"

    def test_resume_after_research(self, issue_id, research_dir):
        """After research completes, resume from debate."""
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        assert get_resume_phase(issue_id) == "debate"

    def test_resume_after_debate(self, issue_id, research_dir):
        """After debate completes, resume from convergence."""
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        save_checkpoint(issue_id, "debate", PHASE_COMPLETED)
        assert get_resume_phase(issue_id) == "convergence"

    def test_resume_all_complete(self, issue_id, research_dir):
        """All phases complete returns None."""
        for phase in PIPELINE_PHASES:
            save_checkpoint(issue_id, phase, PHASE_COMPLETED)
        assert get_resume_phase(issue_id) is None

    def test_resume_skips_failed(self, issue_id, research_dir):
        """Failed phases are not treated as completed for resume."""
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        save_checkpoint(issue_id, "debate", PHASE_FAILED)
        assert get_resume_phase(issue_id) == "debate"


# ─── Pipeline Integration ──────────────────────────────────────────────────


class TestPipelineIntegration:
    """Test that pipeline.research_single_issue respects checkpoints."""

    def test_research_skips_when_checkpoint_complete(
        self, issue_id, research_dir, monkeypatch
    ):
        """research_single_issue skips when checkpoint + files exist."""
        # Set up completed checkpoint with output file
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        (research_dir / "root_cause.md").write_text("# Root cause")

        # Patch pipeline imports to avoid real file_lock calls
        from agents import pipeline

        result = pipeline.research_single_issue(issue_id)
        assert result == {"researcher": True, "solution_finder": True, "impact_assessor": True}

    def test_research_runs_with_force(
        self, issue_id, research_dir, monkeypatch, tmp_path
    ):
        """research_single_issue runs even with checkpoint when force=True."""
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        (research_dir / "root_cause.md").write_text("# Root cause")

        # Patch to avoid real agent calls — make it look like the issue doesn't exist
        # so we get the "not found" early exit (simpler than mocking the whole pipeline)
        from agents import pipeline

        monkeypatch.setattr(
            "agents.pipeline.read_jsonl_by_id", lambda path, iid: None
        )
        # Patch get_data_dir to use temp dir
        monkeypatch.setattr(
            "agents.pipeline.get_data_dir", lambda: str(tmp_path / "data")
        )

        result = pipeline.research_single_issue(issue_id, force=True)
        # Should attempt to run (and fail because issue not found)
        assert result == {"researcher": False, "solution_finder": False, "impact_assessor": False}


# ─── run_full_pipeline Tests ────────────────────────────────────────────────


class TestRunFullPipeline:
    """Test the run_full_pipeline orchestrator."""

    def test_run_full_pipeline_from_scratch(self, issue_id, research_dir, monkeypatch, tmp_path):
        """Full pipeline runs all phases from scratch."""
        from agents import pipeline

        # Set up mock data dir with an issue
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)
        issues_path = data_dir / "issues.jsonl"
        issue_record = {
            "id": issue_id,
            "type": "error",
            "timestamp": "2026-02-17T00:00:00+00:00",
            "description": "Test error",
            "status": "captured",
            "source": "test",
            "tool_name": "Bash",
        }
        with open(issues_path, "w") as f:
            f.write(json.dumps(issue_record) + "\n")

        monkeypatch.setattr("agents.pipeline.get_data_dir", lambda: str(data_dir))
        monkeypatch.setattr("agents.config.get_data_dir", lambda: str(data_dir))

        # Mock sandbox mode ON so agents return mock data
        monkeypatch.setattr("agents.config.is_sandbox", lambda: True)
        monkeypatch.setattr("agents.runner.is_sandbox", lambda: True)

        # Mock get_research_dir to use our temp
        def mock_research_dir(iid):
            rd = tmp_path / "research" / iid
            rd.mkdir(parents=True, exist_ok=True)
            return str(rd)

        monkeypatch.setattr("agents.pipeline.get_research_dir", mock_research_dir)
        monkeypatch.setattr("agents.config.get_research_dir", mock_research_dir)
        monkeypatch.setattr("agents.checkpoint.get_research_dir", mock_research_dir)

        # Patch researcher, solution_finder, impact_assessor to succeed
        monkeypatch.setattr("agents.pipeline.research_issue", lambda iid: True)
        monkeypatch.setattr("agents.pipeline.find_solutions", lambda iid: True)
        monkeypatch.setattr("agents.pipeline.assess_impact", lambda iid: True)

        # Write mock research files so debate can find them
        rd = tmp_path / "research" / issue_id
        rd.mkdir(parents=True, exist_ok=True)
        (rd / "root_cause.md").write_text("# Mock root cause")
        (rd / "solutions.md").write_text("# Mock solutions")
        (rd / "impact.md").write_text("# Mock impact")

        # Mock debater and arbiter to avoid full agent calls
        monkeypatch.setattr("agents.debater.get_data_dir", lambda: str(data_dir))
        monkeypatch.setattr("agents.debater.get_research_dir", mock_research_dir)
        monkeypatch.setattr("agents.arbiter.get_data_dir", lambda: str(data_dir))
        monkeypatch.setattr("agents.arbiter.get_research_dir", mock_research_dir)
        monkeypatch.setattr("agents.arbiter.get_convergence_dir", lambda: str(tmp_path / "output"))
        monkeypatch.setattr("agents.arbiter.get_archive_dir", lambda: str(tmp_path / "archive"))
        monkeypatch.setattr("agents.arbiter.get_project_root", lambda: str(tmp_path))
        monkeypatch.setattr("agents.arbiter.is_sandbox", lambda: True)

        results = pipeline.run_full_pipeline(issue_id, force=True)

        assert results["research"] is not None
        assert any(results["research"].values()) if isinstance(results["research"], dict) else results["research"]

    def test_resume_skips_completed_phases(self, issue_id, research_dir, monkeypatch):
        """Pipeline skips phases that are checkpointed + have output files."""
        from agents import pipeline

        # Mark research as complete with files
        save_checkpoint(issue_id, "research", PHASE_COMPLETED)
        (research_dir / "root_cause.md").write_text("# Root cause")

        # Track whether debate was called
        debate_called = {"value": False}

        def mock_debate(iid):
            debate_called["value"] = True
            return True

        def mock_synthesize(issue_filter=None):
            return True

        monkeypatch.setattr("agents.debater.debate_issue", mock_debate)
        monkeypatch.setattr("agents.arbiter.synthesize", mock_synthesize)

        results = pipeline.run_full_pipeline(issue_id, from_phase="debate")

        # Research should be skipped
        assert results["research"] == {"skipped": True}
        # Debate should have been called
        assert debate_called["value"] is True
