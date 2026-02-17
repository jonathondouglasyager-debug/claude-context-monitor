"""
Convergence Engine - Debate Disagreement Metrics (Phase 4.2)

Computes quantitative metrics from adversarial debate output:
  - challenge_survival_rate: fraction of devil's advocate challenges survived
  - skeptic_severity_score: weighted severity of skeptic concerns (0.0-1.0)
  - confidence_delta: change from pre-debate to post-debate confidence
  - agreement_kappa: simplified inter-agent agreement coefficient

Metrics are written as debate_metrics.json alongside debate.json.
"""

from typing import Any, Optional


# Confidence level ordinals for delta computation
_CONFIDENCE_ORDINAL = {"low": 0, "medium": 1, "high": 2}

# Severity weights for skeptic score
_SEVERITY_WEIGHT = {"low": 0.25, "medium": 0.5, "high": 1.0}


def compute_challenge_survival_rate(
    challenges: list[dict[str, Any]],
) -> Optional[float]:
    """
    Fraction of devil's advocate challenges where the original claim survived.

    Args:
        challenges: List of {claim, challenge, survived: bool} dicts

    Returns:
        Float 0.0-1.0, or None if no challenges provided
    """
    if not challenges:
        return None

    survived_count = sum(1 for ch in challenges if ch.get("survived", False))
    return survived_count / len(challenges)


def compute_skeptic_severity_score(
    concerns: list[dict[str, Any]],
) -> Optional[float]:
    """
    Weighted severity score from skeptic concerns.

    Returns 0.0 (no concerns or all low) to 1.0 (all high severity).
    Weights: low=0.25, medium=0.5, high=1.0

    Args:
        concerns: List of {concern, severity} dicts

    Returns:
        Float 0.0-1.0, or None if no concerns provided
    """
    if not concerns:
        return None

    total_weight = sum(
        _SEVERITY_WEIGHT.get(c.get("severity", "low"), 0.25)
        for c in concerns
    )
    max_weight = len(concerns) * 1.0  # All high severity

    return total_weight / max_weight if max_weight > 0 else 0.0


def compute_confidence_delta(
    pre_confidence: Optional[str],
    post_confidence: Optional[str],
) -> Optional[int]:
    """
    Compute change in confidence level after adversarial review.

    Returns:
        Integer delta (-2 to +2): positive means debate increased confidence,
        negative means debate decreased confidence. None if either input missing.
    """
    if not pre_confidence or not post_confidence:
        return None

    pre = _CONFIDENCE_ORDINAL.get(pre_confidence.lower())
    post = _CONFIDENCE_ORDINAL.get(post_confidence.lower())

    if pre is None or post is None:
        return None

    return post - pre


def compute_agreement_kappa(
    agreements: list,
    contradictions: list,
    gaps: list,
) -> Optional[float]:
    """
    Simplified inter-agent agreement coefficient.

    Approximates Cohen's Kappa using the ratio of agreements to total findings.
    This is a simplified version since we don't have full pairwise agent ratings.

    Formula: kappa = (agreements - expected) / (total - expected)
    Where expected = total / 3 (random chance agreement among 3 agents)

    Args:
        agreements: List of agreed-upon findings
        contradictions: List of contradictions
        gaps: List of gaps identified

    Returns:
        Float -1.0 to 1.0, or None if no findings
    """
    n_agree = len(agreements) if agreements else 0
    n_contradict = len(contradictions) if contradictions else 0
    n_gaps = len(gaps) if gaps else 0

    total = n_agree + n_contradict + n_gaps
    if total == 0:
        return None

    # Expected agreement by chance (1/3 of findings)
    expected = total / 3.0

    if total == expected:
        return 0.0

    kappa = (n_agree - expected) / (total - expected)
    # Clamp to [-1, 1]
    return max(-1.0, min(1.0, kappa))


def compute_debate_metrics(debate_output: dict) -> dict:
    """
    Compute all disagreement metrics from a structured debate output.

    Args:
        debate_output: Parsed debate JSON with fields from DEBATE_SCHEMA

    Returns:
        Dict with all computed metrics, suitable for writing as debate_metrics.json
    """
    challenges = debate_output.get("devil_advocate_challenges", [])
    concerns = debate_output.get("skeptic_concerns", [])
    agreements = debate_output.get("agreements", [])
    contradictions = debate_output.get("contradictions", [])
    gaps = debate_output.get("gaps", [])

    # Pre-debate confidence: infer from researcher output if available,
    # otherwise default to the revised_priority as a proxy
    post_confidence = debate_output.get("confidence_after_debate")

    # For pre-debate confidence, we use "medium" as baseline since we don't
    # have it in the debate output itself (it comes from the research phase)
    pre_confidence = "medium"

    survival_rate = compute_challenge_survival_rate(challenges)
    severity_score = compute_skeptic_severity_score(concerns)
    confidence_delta = compute_confidence_delta(pre_confidence, post_confidence)
    kappa = compute_agreement_kappa(agreements, contradictions, gaps)

    return {
        "challenge_survival_rate": survival_rate,
        "challenge_count": len(challenges),
        "challenges_survived": sum(1 for ch in challenges if ch.get("survived", False)),
        "skeptic_severity_score": severity_score,
        "skeptic_concern_count": len(concerns),
        "confidence_delta": confidence_delta,
        "confidence_before": pre_confidence,
        "confidence_after": post_confidence,
        "agreement_kappa": round(kappa, 3) if kappa is not None else None,
        "finding_counts": {
            "agreements": len(agreements),
            "contradictions": len(contradictions),
            "gaps": len(gaps),
        },
        "dissent_notes": debate_output.get("dissent_notes", []),
    }
