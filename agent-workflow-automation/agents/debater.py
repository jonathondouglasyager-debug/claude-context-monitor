"""
Convergence Engine - Adversarial Debate Agent (Phase 4.2)

Takes the three research outputs (root_cause, solutions, impact) and generates
a multi-perspective adversarial critique. Three roles analyze the findings:
  - Analyst: straightforward comparison (original Phase 4.1 behavior)
  - Devil's Advocate: challenges every finding, proposes alternatives
  - Skeptic: questions evidence quality and unstated assumptions

Optionally runs a second round to resolve adversarial challenges.
Writes full transcript to data/research/{issue_id}/debate.log for auditability.

Inspired by RedDebate (arxiv 2511.07784): adversarial debate roles improve
output quality by forcing consideration of counterarguments.
"""

import json as json_module
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PLUGIN_ROOT)

from agents.config import get_data_dir, get_research_dir, get_debate_rounds
from agents.debate_metrics import compute_debate_metrics
from agents.file_lock import read_jsonl_by_id, update_jsonl_record
from agents.logger import AgentLogger
from agents.runner import run_agent, write_research_output, write_research_json


# ─── Adversarial Debate Prompt (Phase 4.2) ──────────────────────────────────

_ADVERSARIAL_DEBATE_PROMPT = """You are a multi-perspective debate agent. Three independent research agents
investigated a software development issue. Your job is to analyze their findings
from THREE adversarial perspectives, then synthesize a final position that is
stronger than any individual analysis.

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

## Instructions: Three-Perspective Analysis

You MUST analyze from all three perspectives below before synthesizing.

### Perspective 1: Analyst
Compare the three research outputs objectively:
1. Where do all agents agree? These are high-confidence findings.
2. Where do agents contradict each other? Which position is better supported?
3. What did NO agent consider that should be investigated?
Be direct and specific. Quote from the agent outputs when referencing their positions.
If structured JSON data is available from agents, use those fields for precise comparison.

### Perspective 2: Devil's Advocate
Now actively challenge the findings. For EACH major conclusion from the research agents:
- Propose at least one plausible alternative explanation
- Identify the weakest piece of evidence supporting the conclusion
- Argue why the proposed fix might fail, cause regressions, or create new problems
- Consider: what if the root cause is actually a symptom of something deeper?
Be adversarial but constructive — the goal is to stress-test, not to dismiss.

### Perspective 3: Skeptic
Question the quality and completeness of the analysis:
- Is the evidence sufficient to support the conclusions with high confidence?
- What assumptions are unstated or taken for granted?
- What environmental factors or edge cases could change the conclusion?
- If the evidence is circumstantial, say so explicitly.
Rate each concern as high/medium/low severity.

## Final Synthesis
Reconcile the three perspectives into a unified assessment:
- For positions that survived the Devil's Advocate challenge: confidence INCREASES
- For positions that were successfully challenged: REVISE them
- For Skeptic concerns rated "high": these MUST be addressed in the revised assessment
- Note any unresolved disagreements as dissent notes

Include your post-debate confidence level (high/medium/low) — this reflects
how robust the conclusions are AFTER adversarial review.

## Required Output Format

### Analyst Assessment
(agreements, contradictions, gaps)

### Devil's Advocate Challenges
(for each major finding: the claim, your challenge, whether the claim survived)

### Skeptic Review
(evidence concerns with severity ratings)

### Revised Assessment
Root cause (revised), recommended fix (revised), priority (revised).
Post-debate confidence level.
Any unresolved dissent.

### Structured Output

After your markdown analysis, include a JSON block with the following format:

===JSON_OUTPUT===
{{
  "agreements": ["finding 1", "finding 2"],
  "contradictions": [{{"description": "what disagrees", "better_supported": "which position wins"}}],
  "gaps": ["gap 1", "gap 2"],
  "revised_root_cause": "unified root cause",
  "revised_fix": "unified recommended fix",
  "revised_priority": "P0|P1|P2|P3",
  "devil_advocate_challenges": [
    {{"claim": "original finding", "challenge": "why it might be wrong", "survived": true}}
  ],
  "skeptic_concerns": [
    {{"concern": "what's questionable", "severity": "high|medium|low"}}
  ],
  "confidence_after_debate": "high|medium|low",
  "dissent_notes": ["any unresolved minority positions"]
}}
===JSON_OUTPUT_END===
"""


# ─── Round 2 Prompt (for multi-round debate) ────────────────────────────────

_ROUND2_PROMPT = """You are a debate resolution agent. A first round of adversarial debate has been
conducted on a software development issue. The Devil's Advocate raised challenges
and the Skeptic flagged concerns. Your job is to provide definitive resolutions.

## Issue Being Investigated

ID: {issue_id}
Description: {description}

## Round 1 Debate Output

{round1_output}

{round1_json_section}

## Instructions

For EACH Devil's Advocate challenge:
- Provide a definitive resolution: is the original claim correct, or should it be revised?
- If revised, state the new position clearly
- Provide additional evidence or reasoning that wasn't in Round 1

For EACH Skeptic concern rated "high" or "medium":
- Address the concern directly with additional reasoning
- If the concern is valid, explain how it changes the assessment
- If the concern is addressed by evidence the Skeptic missed, cite that evidence

Produce a FINAL assessment that incorporates Round 2 resolutions.
Your confidence level should reflect the additional scrutiny.

## Required Output Format

### Challenge Resolutions
(for each challenge from Round 1)

### Concern Responses
(for each high/medium skeptic concern)

### Final Assessment
Root cause (final), recommended fix (final), priority (final).
Post-debate confidence level (after two rounds of adversarial review).

### Structured Output

===JSON_OUTPUT===
{{
  "agreements": ["finding 1", "finding 2"],
  "contradictions": [{{"description": "what disagrees", "better_supported": "which position wins"}}],
  "gaps": ["gap 1", "gap 2"],
  "revised_root_cause": "final root cause after 2 rounds",
  "revised_fix": "final recommended fix",
  "revised_priority": "P0|P1|P2|P3",
  "devil_advocate_challenges": [
    {{"claim": "original finding", "challenge": "round 1 challenge", "survived": true}}
  ],
  "skeptic_concerns": [
    {{"concern": "what was questionable", "severity": "high|medium|low"}}
  ],
  "confidence_after_debate": "high|medium|low",
  "dissent_notes": ["any still-unresolved positions after 2 rounds"]
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


def _write_metrics(research_dir: str, debate_json: dict, log: AgentLogger) -> bool:
    """
    Compute and write debate disagreement metrics.

    Args:
        research_dir: Path to data/research/{issue_id}/
        debate_json: Parsed structured debate output
        log: Logger instance

    Returns:
        True if metrics written successfully
    """
    try:
        metrics = compute_debate_metrics(debate_json)
        filepath = os.path.join(research_dir, "debate_metrics.json")
        os.makedirs(research_dir, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json_module.dump(metrics, f, indent=2, ensure_ascii=False)
        log.info(
            "Debate metrics written",
            survival_rate=metrics.get("challenge_survival_rate"),
            skeptic_score=metrics.get("skeptic_severity_score"),
            kappa=metrics.get("agreement_kappa"),
        )
        return True
    except Exception as e:
        log.warn(f"Failed to write debate metrics (non-fatal): {e}")
        return False


def _run_round1(
    issue_id: str,
    issue: dict,
    research_dir: str,
    log: AgentLogger,
    multi_round: bool,
) -> tuple[bool, str, dict | None]:
    """
    Run Round 1 of adversarial debate.

    Args:
        issue_id: The issue ID
        issue: The issue record
        research_dir: Path to research directory
        log: Logger instance
        multi_round: If True, save as round1 files instead of final

    Returns:
        Tuple of (success, raw_output, structured_output)
    """
    root_cause = _read_research_file(research_dir, "root_cause.md")
    solutions = _read_research_file(research_dir, "solutions.md")
    impact = _read_research_file(research_dir, "impact.md")

    # Phase 4: Load structured JSON from research agents
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
        return (False, "", None)

    if any([root_cause_json, solutions_json, impact_json]):
        log.info("Structured JSON available from research agents — including in debate context")

    prompt = _ADVERSARIAL_DEBATE_PROMPT.format(
        issue_id=issue_id,
        description=issue.get("description", "No description")[:1000],
        root_cause=root_cause,
        solutions=solutions,
        impact=impact,
        root_cause_json_section=root_cause_json,
        solutions_json_section=solutions_json,
        impact_json_section=impact_json,
    )

    result = run_agent(
        prompt=prompt,
        stage="debate",
        issue_id=issue_id,
        log=log,
    )

    if not result.success:
        return (False, "", None)

    # Write outputs
    if multi_round:
        # Save as round 1 intermediates
        write_research_output(research_dir, "debate_round1.md", result.markdown_output, log)
        write_research_output(research_dir, "debate_round1.log", result.output, log)
        if result.structured_output is not None:
            write_research_json(
                research_dir, "debate_round1.json", result.structured_output, "debater", log
            )
    else:
        # Single round — write as final
        write_research_output(research_dir, "debate.md", result.markdown_output, log)
        write_research_output(research_dir, "debate.log", result.output, log)
        if result.structured_output is not None:
            write_research_json(
                research_dir, "debate.json", result.structured_output, "debater", log
            )

    return (True, result.output, result.structured_output)


def _run_round2(
    issue_id: str,
    issue: dict,
    research_dir: str,
    round1_output: str,
    round1_json: dict | None,
    log: AgentLogger,
) -> tuple[bool, dict | None]:
    """
    Run Round 2 of adversarial debate — resolves challenges from Round 1.

    Args:
        issue_id: The issue ID
        issue: The issue record
        research_dir: Path to research directory
        round1_output: Raw output from Round 1
        round1_json: Structured JSON from Round 1 (if available)
        log: Logger instance

    Returns:
        Tuple of (success, structured_output)
    """
    log.section("Adversarial Debate — Round 2")

    round1_json_section = ""
    if round1_json is not None:
        round1_json_section = (
            f"**Round 1 Structured Data:**\n"
            f"```json\n{json_module.dumps(round1_json, indent=2)}\n```"
        )

    prompt = _ROUND2_PROMPT.format(
        issue_id=issue_id,
        description=issue.get("description", "No description")[:1000],
        round1_output=round1_output,
        round1_json_section=round1_json_section,
    )

    result = run_agent(
        prompt=prompt,
        stage="debate_round2",
        issue_id=issue_id,
        log=log,
    )

    if not result.success:
        log.warn("Round 2 failed — using Round 1 output as final")
        # Fall back: copy round1 files to final locations
        for ext in (".md", ".json"):
            r1_path = os.path.join(research_dir, f"debate_round1{ext}")
            final_path = os.path.join(research_dir, f"debate{ext}")
            if os.path.exists(r1_path):
                with open(r1_path, "r", encoding="utf-8") as f:
                    content = f.read()
                with open(final_path, "w", encoding="utf-8") as f:
                    f.write(content)
        return (True, round1_json)  # Graceful degradation

    # Write final outputs
    write_research_output(research_dir, "debate.md", result.markdown_output, log)
    write_research_output(research_dir, "debate.log", result.output, log)
    if result.structured_output is not None:
        write_research_json(
            research_dir, "debate.json", result.structured_output, "debater", log
        )

    return (True, result.structured_output)


def debate_issue(issue_id: str) -> bool:
    """
    Run the adversarial debate agent on a researched issue.

    Uses three perspectives (Analyst, Devil's Advocate, Skeptic) to stress-test
    research findings. Optionally runs a second round to resolve challenges.

    Args:
        issue_id: The issue ID to debate

    Returns:
        True if debate completed successfully
    """
    log = AgentLogger(issue_id, "DEBATE")
    log.section("Adversarial Cross-Agent Debate")

    # Load the issue record
    issues_path = os.path.join(get_data_dir(), "issues.jsonl")
    issue = read_jsonl_by_id(issues_path, issue_id)

    if not issue:
        log.error(f"Issue not found: {issue_id}")
        return False

    research_dir = get_research_dir(issue_id)
    debate_rounds = get_debate_rounds()

    # Update status
    update_jsonl_record(issues_path, issue_id, {"status": "debating"})
    log.info(f"Starting adversarial debate (rounds={debate_rounds})")

    # ── Round 1: Three-perspective adversarial analysis ──
    multi_round = debate_rounds >= 2
    success, raw_output, structured_output = _run_round1(
        issue_id, issue, research_dir, log, multi_round=multi_round,
    )

    if not success:
        log.error("Debate Round 1 failed")
        update_jsonl_record(issues_path, issue_id, {"status": "researched"})
        return False

    # ── Round 2 (optional): Resolve adversarial challenges ──
    final_structured = structured_output
    if multi_round:
        log.info("Multi-round debate enabled — starting Round 2")
        r2_success, r2_structured = _run_round2(
            issue_id, issue, research_dir, raw_output, structured_output, log,
        )
        if r2_success and r2_structured is not None:
            final_structured = r2_structured

    # ── Compute and write disagreement metrics ──
    if final_structured is not None and isinstance(final_structured, dict):
        _write_metrics(research_dir, final_structured, log)
    else:
        log.warn("No structured JSON in debate output — skipping metrics")

    # Update status
    update_jsonl_record(issues_path, issue_id, {"status": "debated"})
    log.info(f"Adversarial debate complete (rounds={debate_rounds})")

    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m agents.debater <issue_id>", file=sys.stderr)
        sys.exit(1)

    issue_id = sys.argv[1]
    success = debate_issue(issue_id)
    sys.exit(0 if success else 1)
