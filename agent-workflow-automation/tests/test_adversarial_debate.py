"""
Convergence Engine - Adversarial Debate Tests (Phase 4.2)

Tests for:
  1. Adversarial debate prompt construction (three perspectives)
  2. Debate disagreement metrics computation
  3. Multi-round debate flow (Round 1 + Round 2)
  4. Backward compatibility (old schema without adversarial fields)
  5. Config toggle for debate_rounds
  6. Metrics file output
"""

import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.debate_metrics import (
    compute_challenge_survival_rate,
    compute_skeptic_severity_score,
    compute_confidence_delta,
    compute_agreement_kappa,
    compute_debate_metrics,
)
from agents.output_schemas import (
    validate_debate_output,
    extract_json_output,
    JSON_OUTPUT_START,
    JSON_OUTPUT_END,
)


# ─── Debate Metrics Tests ───────────────────────────────────────────────────


class TestChallengeSurvivalRate:
    """Tests for compute_challenge_survival_rate()."""

    def test_all_survived(self):
        challenges = [
            {"claim": "A", "challenge": "X", "survived": True},
            {"claim": "B", "challenge": "Y", "survived": True},
        ]
        assert compute_challenge_survival_rate(challenges) == 1.0

    def test_none_survived(self):
        challenges = [
            {"claim": "A", "challenge": "X", "survived": False},
            {"claim": "B", "challenge": "Y", "survived": False},
        ]
        assert compute_challenge_survival_rate(challenges) == 0.0

    def test_mixed(self):
        challenges = [
            {"claim": "A", "challenge": "X", "survived": True},
            {"claim": "B", "challenge": "Y", "survived": False},
            {"claim": "C", "challenge": "Z", "survived": True},
        ]
        rate = compute_challenge_survival_rate(challenges)
        assert abs(rate - 2 / 3) < 0.001

    def test_empty_list(self):
        assert compute_challenge_survival_rate([]) is None

    def test_missing_survived_field(self):
        challenges = [{"claim": "A", "challenge": "X"}]
        assert compute_challenge_survival_rate(challenges) == 0.0


class TestSkepticSeverityScore:
    """Tests for compute_skeptic_severity_score()."""

    def test_all_high(self):
        concerns = [
            {"concern": "A", "severity": "high"},
            {"concern": "B", "severity": "high"},
        ]
        assert compute_skeptic_severity_score(concerns) == 1.0

    def test_all_low(self):
        concerns = [
            {"concern": "A", "severity": "low"},
            {"concern": "B", "severity": "low"},
        ]
        assert compute_skeptic_severity_score(concerns) == 0.25

    def test_mixed(self):
        concerns = [
            {"concern": "A", "severity": "high"},
            {"concern": "B", "severity": "medium"},
            {"concern": "C", "severity": "low"},
        ]
        expected = (1.0 + 0.5 + 0.25) / 3.0
        score = compute_skeptic_severity_score(concerns)
        assert abs(score - expected) < 0.001

    def test_empty_list(self):
        assert compute_skeptic_severity_score([]) is None

    def test_unknown_severity_defaults_low(self):
        concerns = [{"concern": "A", "severity": "unknown"}]
        assert compute_skeptic_severity_score(concerns) == 0.25


class TestConfidenceDelta:
    """Tests for compute_confidence_delta()."""

    def test_increase(self):
        assert compute_confidence_delta("low", "high") == 2

    def test_decrease(self):
        assert compute_confidence_delta("high", "low") == -2

    def test_no_change(self):
        assert compute_confidence_delta("medium", "medium") == 0

    def test_missing_pre(self):
        assert compute_confidence_delta(None, "high") is None

    def test_missing_post(self):
        assert compute_confidence_delta("low", None) is None

    def test_invalid_value(self):
        assert compute_confidence_delta("low", "invalid") is None


class TestAgreementKappa:
    """Tests for compute_agreement_kappa()."""

    def test_perfect_agreement(self):
        kappa = compute_agreement_kappa(["a", "b", "c"], [], [])
        assert kappa is not None
        assert kappa > 0.0  # More agreement than chance

    def test_no_agreement(self):
        kappa = compute_agreement_kappa([], ["a", "b", "c"], [])
        assert kappa is not None
        assert kappa < 0.0  # Less agreement than chance

    def test_balanced(self):
        kappa = compute_agreement_kappa(["a"], ["b"], ["c"])
        # Expected: 1/3 agree, expected by chance = 1/3 → kappa = 0
        assert kappa is not None
        assert abs(kappa) < 0.001

    def test_empty(self):
        assert compute_agreement_kappa([], [], []) is None


class TestComputeDebateMetrics:
    """Tests for compute_debate_metrics() — full metrics computation."""

    def test_full_metrics(self):
        debate_output = {
            "agreements": ["Finding A", "Finding B"],
            "contradictions": [{"description": "X", "better_supported": "Y"}],
            "gaps": ["Gap 1"],
            "revised_root_cause": "Test cause",
            "revised_fix": "Test fix",
            "revised_priority": "P2",
            "devil_advocate_challenges": [
                {"claim": "A", "challenge": "X", "survived": True},
                {"claim": "B", "challenge": "Y", "survived": False},
            ],
            "skeptic_concerns": [
                {"concern": "Evidence weak", "severity": "high"},
                {"concern": "Assumption unstated", "severity": "low"},
            ],
            "confidence_after_debate": "medium",
            "dissent_notes": ["Minor disagreement on priority"],
        }

        metrics = compute_debate_metrics(debate_output)

        assert metrics["challenge_survival_rate"] == 0.5
        assert metrics["challenge_count"] == 2
        assert metrics["challenges_survived"] == 1
        assert metrics["skeptic_severity_score"] is not None
        assert metrics["skeptic_concern_count"] == 2
        assert metrics["confidence_delta"] == 0  # medium → medium
        assert metrics["agreement_kappa"] is not None
        assert metrics["finding_counts"]["agreements"] == 2
        assert metrics["finding_counts"]["contradictions"] == 1
        assert metrics["finding_counts"]["gaps"] == 1
        assert metrics["dissent_notes"] == ["Minor disagreement on priority"]

    def test_metrics_without_adversarial_fields(self):
        """Backward compat: metrics from old-style debate output."""
        debate_output = {
            "agreements": ["A"],
            "contradictions": [],
            "gaps": ["G"],
            "revised_root_cause": "X",
            "revised_fix": "Y",
            "revised_priority": "P1",
        }

        metrics = compute_debate_metrics(debate_output)

        assert metrics["challenge_survival_rate"] is None
        assert metrics["challenge_count"] == 0
        assert metrics["skeptic_severity_score"] is None
        assert metrics["skeptic_concern_count"] == 0
        assert metrics["confidence_delta"] is None  # no confidence_after_debate
        assert metrics["agreement_kappa"] is not None  # computed from core fields


# ─── Adversarial Debate Prompt Tests ─────────────────────────────────────────


class TestAdversarialDebatePrompt:
    """Tests for the adversarial debate prompt structure."""

    def test_prompt_contains_three_perspectives(self):
        from agents.debater import _ADVERSARIAL_DEBATE_PROMPT

        assert "Perspective 1: Analyst" in _ADVERSARIAL_DEBATE_PROMPT
        assert "Perspective 2: Devil's Advocate" in _ADVERSARIAL_DEBATE_PROMPT
        assert "Perspective 3: Skeptic" in _ADVERSARIAL_DEBATE_PROMPT

    def test_prompt_contains_synthesis(self):
        from agents.debater import _ADVERSARIAL_DEBATE_PROMPT

        assert "Final Synthesis" in _ADVERSARIAL_DEBATE_PROMPT

    def test_prompt_requires_adversarial_json(self):
        from agents.debater import _ADVERSARIAL_DEBATE_PROMPT

        assert "devil_advocate_challenges" in _ADVERSARIAL_DEBATE_PROMPT
        assert "skeptic_concerns" in _ADVERSARIAL_DEBATE_PROMPT
        assert "confidence_after_debate" in _ADVERSARIAL_DEBATE_PROMPT

    def test_round2_prompt_exists(self):
        from agents.debater import _ROUND2_PROMPT

        assert "Round 1 Debate Output" in _ROUND2_PROMPT
        assert "Challenge Resolutions" in _ROUND2_PROMPT
        assert "Concern Responses" in _ROUND2_PROMPT


# ─── Config Tests ────────────────────────────────────────────────────────────


class TestDebateRoundsConfig:
    """Tests for debate_rounds configuration."""

    def test_default_is_one_round(self):
        from agents.config import _DEFAULTS
        assert _DEFAULTS["budget"]["debate_rounds"] == 1

    def test_get_debate_rounds_default(self):
        """get_debate_rounds returns 1 when not configured."""
        from agents.config import get_debate_rounds
        # In test env without custom config, should return default
        with patch("agents.config.load_convergence_config", return_value={"budget": {}}):
            assert get_debate_rounds() == 1

    def test_get_debate_rounds_custom(self):
        """get_debate_rounds returns configured value."""
        from agents.config import get_debate_rounds
        with patch("agents.config.load_convergence_config",
                    return_value={"budget": {"debate_rounds": 2}}):
            assert get_debate_rounds() == 2


# ─── Schema Validation Tests ────────────────────────────────────────────────


class TestAdversarialSchemaValidation:
    """Tests for validate_debate_output with adversarial fields."""

    def _base_debate(self):
        """Return a minimal valid debate output."""
        return {
            "agreements": ["Finding A"],
            "contradictions": [],
            "gaps": ["Gap 1"],
            "revised_root_cause": "Root cause",
            "revised_fix": "Fix it",
            "revised_priority": "P2",
        }

    def test_valid_without_adversarial_fields(self):
        """Backward compat: old schema still validates."""
        data = self._base_debate()
        is_valid, errors = validate_debate_output(data)
        assert is_valid, f"Validation failed: {errors}"

    def test_valid_with_adversarial_fields(self):
        data = self._base_debate()
        data["devil_advocate_challenges"] = [
            {"claim": "A", "challenge": "B", "survived": True}
        ]
        data["skeptic_concerns"] = [
            {"concern": "C", "severity": "medium"}
        ]
        data["confidence_after_debate"] = "high"
        data["dissent_notes"] = []

        is_valid, errors = validate_debate_output(data)
        assert is_valid, f"Validation failed: {errors}"

    def test_invalid_challenge_missing_fields(self):
        data = self._base_debate()
        data["devil_advocate_challenges"] = [
            {"claim": "A"}  # missing challenge and survived
        ]
        is_valid, errors = validate_debate_output(data)
        assert not is_valid
        assert any("challenge" in e for e in errors)
        assert any("survived" in e for e in errors)

    def test_invalid_concern_severity(self):
        data = self._base_debate()
        data["skeptic_concerns"] = [
            {"concern": "C", "severity": "extreme"}  # invalid severity
        ]
        is_valid, errors = validate_debate_output(data)
        assert not is_valid
        assert any("severity" in e for e in errors)

    def test_invalid_confidence_after_debate(self):
        data = self._base_debate()
        data["confidence_after_debate"] = "very_high"  # invalid
        is_valid, errors = validate_debate_output(data)
        assert not is_valid
        assert any("confidence_after_debate" in e for e in errors)

    def test_challenge_not_dict(self):
        data = self._base_debate()
        data["devil_advocate_challenges"] = ["not a dict"]
        is_valid, errors = validate_debate_output(data)
        assert not is_valid
        assert any("must be dict" in e for e in errors)

    def test_concern_not_dict(self):
        data = self._base_debate()
        data["skeptic_concerns"] = ["not a dict"]
        is_valid, errors = validate_debate_output(data)
        assert not is_valid
        assert any("must be dict" in e for e in errors)


# ─── Mock-Based Integration Tests ────────────────────────────────────────────


class TestAdversarialDebateSandbox:
    """Integration tests using sandbox mode mocks."""

    def test_mock_debate_has_adversarial_fields(self):
        """Verify the debate mock response includes adversarial JSON fields."""
        from agents.runner import _default_mock_response

        mock = _default_mock_response("debate")
        structured = extract_json_output(mock)

        assert structured is not None
        assert "devil_advocate_challenges" in structured
        assert "skeptic_concerns" in structured
        assert "confidence_after_debate" in structured
        assert len(structured["devil_advocate_challenges"]) > 0
        assert len(structured["skeptic_concerns"]) > 0

    def test_mock_debate_validates(self):
        """Verify the debate mock produces valid schema output."""
        from agents.runner import _default_mock_response

        mock = _default_mock_response("debate")
        structured = extract_json_output(mock)

        is_valid, errors = validate_debate_output(structured)
        assert is_valid, f"Mock debate validation failed: {errors}"

    def test_mock_round2_has_adversarial_fields(self):
        """Verify the round 2 mock includes adversarial JSON fields."""
        from agents.runner import _default_mock_response

        mock = _default_mock_response("debate_round2")
        structured = extract_json_output(mock)

        assert structured is not None
        assert "devil_advocate_challenges" in structured
        assert "confidence_after_debate" in structured

    def test_mock_round2_validates(self):
        """Verify the round 2 mock produces valid schema output."""
        from agents.runner import _default_mock_response

        mock = _default_mock_response("debate_round2")
        structured = extract_json_output(mock)

        is_valid, errors = validate_debate_output(structured)
        assert is_valid, f"Mock round2 validation failed: {errors}"

    def test_debate_metrics_from_mock(self):
        """Verify metrics can be computed from the mock debate output."""
        from agents.runner import _default_mock_response

        mock = _default_mock_response("debate")
        structured = extract_json_output(mock)
        metrics = compute_debate_metrics(structured)

        assert metrics["challenge_survival_rate"] == 1.0  # both survived
        assert metrics["challenge_count"] == 2
        assert metrics["skeptic_severity_score"] is not None
        assert metrics["confidence_delta"] is not None


class TestMultiRoundDebateFlow:
    """Test the multi-round debate flow end-to-end in sandbox mode."""

    def test_single_round_debate(self, tmp_path):
        """Single round debate writes debate.md/json directly."""
        from agents.debater import _run_round1
        from agents.logger import AgentLogger

        # Setup research dir with a mock file
        research_dir = str(tmp_path / "research" / "test_issue")
        os.makedirs(research_dir, exist_ok=True)
        with open(os.path.join(research_dir, "root_cause.md"), "w") as f:
            f.write("## Hypothesis\nTest root cause analysis")

        issue = {"id": "test_issue", "description": "Test error"}
        log = AgentLogger("test_issue", "TEST", log_dir=str(tmp_path))

        with patch("agents.debater.run_agent") as mock_run:
            from agents.runner import _default_mock_response, AgentResult
            from agents.output_schemas import extract_json_output as ejo

            mock_output = _default_mock_response("debate")
            mock_run.return_value = AgentResult(
                success=True,
                output=mock_output,
                structured_output=ejo(mock_output),
            )

            success, raw, structured = _run_round1(
                "test_issue", issue, research_dir, log, multi_round=False,
            )

        assert success
        assert os.path.exists(os.path.join(research_dir, "debate.md"))
        # Should NOT have round1 files
        assert not os.path.exists(os.path.join(research_dir, "debate_round1.md"))

    def test_multi_round_writes_round1_files(self, tmp_path):
        """Multi-round debate writes round1 intermediates first."""
        from agents.debater import _run_round1
        from agents.logger import AgentLogger

        research_dir = str(tmp_path / "research" / "test_issue")
        os.makedirs(research_dir, exist_ok=True)
        with open(os.path.join(research_dir, "root_cause.md"), "w") as f:
            f.write("## Hypothesis\nTest root cause")

        issue = {"id": "test_issue", "description": "Test error"}
        log = AgentLogger("test_issue", "TEST", log_dir=str(tmp_path))

        with patch("agents.debater.run_agent") as mock_run:
            from agents.runner import _default_mock_response, AgentResult
            from agents.output_schemas import extract_json_output as ejo

            mock_output = _default_mock_response("debate")
            mock_run.return_value = AgentResult(
                success=True,
                output=mock_output,
                structured_output=ejo(mock_output),
            )

            success, raw, structured = _run_round1(
                "test_issue", issue, research_dir, log, multi_round=True,
            )

        assert success
        assert os.path.exists(os.path.join(research_dir, "debate_round1.md"))
        # Should NOT have final debate files yet
        assert not os.path.exists(os.path.join(research_dir, "debate.md"))

    def test_round2_writes_final_files(self, tmp_path):
        """Round 2 writes to debate.md/json as final output."""
        from agents.debater import _run_round2
        from agents.logger import AgentLogger

        research_dir = str(tmp_path / "research" / "test_issue")
        os.makedirs(research_dir, exist_ok=True)

        issue = {"id": "test_issue", "description": "Test error"}
        log = AgentLogger("test_issue", "TEST", log_dir=str(tmp_path))

        with patch("agents.debater.run_agent") as mock_run:
            from agents.runner import _default_mock_response, AgentResult
            from agents.output_schemas import extract_json_output as ejo

            mock_output = _default_mock_response("debate_round2")
            mock_run.return_value = AgentResult(
                success=True,
                output=mock_output,
                structured_output=ejo(mock_output),
            )

            success, structured = _run_round2(
                "test_issue", issue, research_dir,
                round1_output="Round 1 content",
                round1_json={"agreements": ["test"]},
                log=log,
            )

        assert success
        assert os.path.exists(os.path.join(research_dir, "debate.md"))

    def test_round2_fallback_on_failure(self, tmp_path):
        """Round 2 failure falls back to Round 1 output."""
        from agents.debater import _run_round2
        from agents.logger import AgentLogger

        research_dir = str(tmp_path / "research" / "test_issue")
        os.makedirs(research_dir, exist_ok=True)

        # Write round1 files to verify fallback copies them
        with open(os.path.join(research_dir, "debate_round1.md"), "w") as f:
            f.write("Round 1 markdown")
        with open(os.path.join(research_dir, "debate_round1.json"), "w") as f:
            json.dump({"agreements": ["from_round1"]}, f)

        issue = {"id": "test_issue", "description": "Test error"}
        log = AgentLogger("test_issue", "TEST", log_dir=str(tmp_path))

        r1_json = {"agreements": ["from_round1"]}

        with patch("agents.debater.run_agent") as mock_run:
            from agents.runner import AgentResult

            mock_run.return_value = AgentResult(
                success=False,
                output="",
                error="Timeout",
            )

            success, structured = _run_round2(
                "test_issue", issue, research_dir,
                round1_output="Round 1 content",
                round1_json=r1_json,
                log=log,
            )

        # Should succeed via fallback
        assert success
        assert structured == r1_json

        # Verify round1 files were copied to final locations
        assert os.path.exists(os.path.join(research_dir, "debate.md"))
        with open(os.path.join(research_dir, "debate.md")) as f:
            assert f.read() == "Round 1 markdown"


class TestMetricsFileOutput:
    """Tests for debate_metrics.json file writing."""

    def test_write_metrics(self, tmp_path):
        """Verify _write_metrics writes debate_metrics.json."""
        from agents.debater import _write_metrics
        from agents.logger import AgentLogger

        research_dir = str(tmp_path / "research" / "test_issue")
        log = AgentLogger("test_issue", "TEST", log_dir=str(tmp_path))

        debate_json = {
            "agreements": ["A"],
            "contradictions": [],
            "gaps": [],
            "revised_root_cause": "X",
            "revised_fix": "Y",
            "revised_priority": "P2",
            "devil_advocate_challenges": [
                {"claim": "A", "challenge": "B", "survived": True},
            ],
            "skeptic_concerns": [
                {"concern": "C", "severity": "medium"},
            ],
            "confidence_after_debate": "high",
            "dissent_notes": [],
        }

        success = _write_metrics(research_dir, debate_json, log)
        assert success

        metrics_path = os.path.join(research_dir, "debate_metrics.json")
        assert os.path.exists(metrics_path)

        with open(metrics_path) as f:
            metrics = json.load(f)

        assert metrics["challenge_survival_rate"] == 1.0
        assert metrics["challenge_count"] == 1
        assert metrics["skeptic_concern_count"] == 1
        assert "agreement_kappa" in metrics
