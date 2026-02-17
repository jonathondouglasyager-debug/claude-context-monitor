"""
Convergence Engine - Agent Runner

Shared utility for spawning Claude Code headless sessions as agent subprocesses.
Uses `claude -p` (print mode) to run prompts via the user's existing subscription
without requiring separate API keys.
"""

import json
import os
import subprocess
import sys
from typing import Optional

from agents.config import (
    get_model_for_stage,
    get_max_tokens,
    get_timeout_seconds,
    is_sandbox,
    get_project_root,
)
from agents.logger import AgentLogger
from agents.output_schemas import (
    extract_json_output,
    extract_markdown_output,
    validate_agent_output,
)
from agents.sanitizer import sanitize_context


class AgentResult:
    """Encapsulates the output of an agent subprocess."""

    def __init__(
        self,
        success: bool,
        output: str,
        error: str = "",
        timed_out: bool = False,
        structured_output: Optional[dict | list] = None,
    ):
        self.success = success
        self.output = output  # Full raw output (markdown + JSON)
        self.error = error
        self.timed_out = timed_out
        self.structured_output = structured_output  # Parsed JSON (Phase 4)

    @property
    def markdown_output(self) -> str:
        """Return just the markdown portion (stripping JSON block)."""
        return extract_markdown_output(self.output)

    def __repr__(self):
        status = "OK" if self.success else ("TIMEOUT" if self.timed_out else "FAIL")
        json_tag = "+JSON" if self.structured_output else ""
        return f"AgentResult({status}{json_tag}, {len(self.output)} chars)"


def run_agent(
    prompt: str,
    stage: str,
    issue_id: str,
    log: AgentLogger,
    max_tokens: Optional[int] = None,
    timeout: Optional[int] = None,
    mock_response: Optional[str] = None,
) -> AgentResult:
    """
    Execute a prompt via Claude Code headless mode (claude -p).

    In sandbox mode, returns mock_response instead of spawning a subprocess.

    Args:
        prompt: The full prompt to send to the agent
        stage: Pipeline stage name (for model selection from config)
        issue_id: Issue being processed (for logging)
        log: AgentLogger instance for this agent
        max_tokens: Override max tokens (defaults to config value)
        timeout: Override timeout seconds (defaults to config value)
        mock_response: Response to return in sandbox mode

    Returns:
        AgentResult with the agent's output
    """
    # Sandbox mode -- return mock data without making real calls
    if is_sandbox():
        log.info("Sandbox mode: returning mock response")
        mock = mock_response or _default_mock_response(stage)
        structured = extract_json_output(mock)
        return AgentResult(success=True, output=mock, structured_output=structured)

    # Sanitize the prompt before sending
    sanitized_prompt = sanitize_context(prompt)

    # Build the claude command
    model = get_model_for_stage(stage)
    effective_timeout = timeout or get_timeout_seconds()
    effective_max_tokens = max_tokens or get_max_tokens(stage)

    cmd = ["claude", "-p"]

    # Add model flag if not default
    if model != "default":
        cmd.extend(["--model", model])

    # Add max tokens
    # cmd.extend(["--max-tokens", str(effective_max_tokens)])

    log.info(
        f"Spawning agent subprocess",
        model=model,
        timeout=effective_timeout,
        prompt_length=len(sanitized_prompt),
    )

    # Pass project root via env var so child processes resolve paths correctly
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = get_project_root()

    try:
        result = subprocess.run(
            cmd,
            input=sanitized_prompt,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
            cwd=get_project_root(),
            env=env,
        )

        if result.returncode == 0:
            output = result.stdout.strip()
            # Phase 4: extract structured JSON if present
            structured = extract_json_output(output)
            if structured is not None:
                log.info("Structured JSON extracted from agent output")
            log.info(f"Agent completed successfully", output_length=len(output))
            return AgentResult(success=True, output=output, structured_output=structured)
        else:
            error_msg = result.stderr.strip() or f"Exit code {result.returncode}"
            log.error(f"Agent subprocess failed: {error_msg}")
            return AgentResult(success=False, output="", error=error_msg)

    except subprocess.TimeoutExpired:
        log.error(f"Agent timed out after {effective_timeout}s")
        return AgentResult(
            success=False,
            output="",
            error=f"Timed out after {effective_timeout} seconds",
            timed_out=True,
        )
    except FileNotFoundError:
        log.error("Claude CLI not found. Is Claude Code installed and in PATH?")
        return AgentResult(
            success=False,
            output="",
            error="claude CLI not found in PATH",
        )
    except Exception as e:
        log.error(f"Unexpected error spawning agent: {e}")
        return AgentResult(success=False, output="", error=str(e))


def write_research_output(
    research_dir: str,
    filename: str,
    content: str,
    log: AgentLogger,
) -> bool:
    """
    Write agent output to a research file.

    Args:
        research_dir: Path to data/research/{issue_id}/
        filename: Output filename (e.g., root_cause.md)
        content: The agent's output to write
        log: Logger instance

    Returns:
        True if written successfully
    """
    os.makedirs(research_dir, exist_ok=True)
    filepath = os.path.join(research_dir, filename)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        log.info(f"Wrote research output: {filename}", path=filepath)
        return True
    except Exception as e:
        log.error(f"Failed to write {filename}: {e}")
        return False


def write_research_json(
    research_dir: str,
    filename: str,
    data: dict | list,
    agent_name: str,
    log: AgentLogger,
) -> bool:
    """
    Write validated agent JSON output to a research file.

    Validates the data against the agent's schema before writing.
    Writes even if validation fails (with warning), so downstream
    agents have something to work with.

    Args:
        research_dir: Path to data/research/{issue_id}/
        filename: Output filename (e.g., root_cause.json)
        data: Parsed JSON data from agent output
        agent_name: Agent name for schema validation
        log: Logger instance

    Returns:
        True if written successfully (regardless of validation)
    """
    os.makedirs(research_dir, exist_ok=True)
    filepath = os.path.join(research_dir, filename)

    # Validate against schema
    if isinstance(data, dict):
        is_valid, errors = validate_agent_output(agent_name, data)
        if not is_valid:
            log.warn(
                f"Schema validation warnings for {filename}: {'; '.join(errors)}",
                agent=agent_name,
            )
        else:
            log.info(f"Schema validation passed for {filename}", agent=agent_name)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log.info(f"Wrote structured output: {filename}", path=filepath)
        return True
    except Exception as e:
        log.error(f"Failed to write {filename}: {e}")
        return False


def _default_mock_response(stage: str) -> str:
    """Generate a default mock response for sandbox mode."""
    return {
        "research": (
            "## Hypothesis\n"
            "The error appears to be caused by a missing dependency.\n\n"
            "## Evidence\n"
            "Stack trace indicates import failure at module initialization.\n\n"
            "## Confidence\n"
            "medium\n\n"
            "## Related Patterns\n"
            "Similar to dependency resolution issues seen in Node.js projects.\n\n"
            "===JSON_OUTPUT===\n"
            '{\n'
            '  "hypothesis": "The error appears to be caused by a missing dependency.",\n'
            '  "evidence": ["Stack trace indicates import failure at module initialization."],\n'
            '  "confidence": "medium",\n'
            '  "confidence_reasoning": "Error message clearly indicates missing module, but root package unclear.",\n'
            '  "related_patterns": ["dependency resolution", "Node.js import failures"]\n'
            '}\n'
            "===JSON_OUTPUT_END==="
        ),
        "solutions": (
            "## Solution 1\n"
            "Install the missing dependency via package manager.\n"
            "**Tradeoffs:** Simple fix, low risk.\n\n"
            "## Solution 2\n"
            "Refactor to remove the dependency entirely.\n"
            "**Tradeoffs:** More work, but reduces future dependency issues.\n\n"
            "## Recommended Approach\n"
            "Solution 1 for immediate fix, consider Solution 2 for long-term.\n\n"
            "## Implementation Steps\n"
            "1. Identify the exact missing package\n"
            "2. Add to package.json\n"
            "3. Run install\n"
            "4. Verify fix\n\n"
            "===JSON_OUTPUT===\n"
            '{\n'
            '  "solutions": [\n'
            '    {"title": "Install missing dependency", "description": "Install the missing dependency via package manager.", "tradeoffs": {"risk": "low", "complexity": "low", "side_effects": "none"}},\n'
            '    {"title": "Remove dependency", "description": "Refactor to remove the dependency entirely.", "tradeoffs": {"risk": "medium", "complexity": "high", "side_effects": "requires code changes"}}\n'
            '  ],\n'
            '  "recommended_index": 0,\n'
            '  "recommendation_reasoning": "Solution 1 for immediate fix, consider Solution 2 for long-term.",\n'
            '  "implementation_steps": ["Identify the exact missing package", "Add to package.json", "Run install", "Verify fix"]\n'
            '}\n'
            "===JSON_OUTPUT_END==="
        ),
        "impact": (
            "## Severity\n"
            "P2 - Blocks specific functionality but not entire system.\n\n"
            "## Scope\n"
            "Module-level -- affects one feature area.\n\n"
            "## Frequency\n"
            "First occurrence in this session.\n\n"
            "## Priority Recommendation\n"
            "Fix during current development session to prevent cascade.\n\n"
            "===JSON_OUTPUT===\n"
            '{\n'
            '  "severity": "P2",\n'
            '  "severity_reasoning": "Blocks specific functionality but not entire system.",\n'
            '  "scope": "module",\n'
            '  "scope_detail": "Affects one feature area.",\n'
            '  "frequency": "first",\n'
            '  "frequency_detail": "First occurrence in this session.",\n'
            '  "priority": "now",\n'
            '  "priority_reasoning": "Fix during current development session to prevent cascade."\n'
            '}\n'
            "===JSON_OUTPUT_END==="
        ),
        "debate": (
            "## Agreements\n"
            "All agents agree the root cause is a missing dependency.\n\n"
            "## Contradictions\n"
            "None significant.\n\n"
            "## Gaps\n"
            "No agent checked if this dependency was intentionally removed.\n\n"
            "## Revised Assessment\n"
            "High confidence: reinstall the dependency as the primary fix.\n\n"
            "===JSON_OUTPUT===\n"
            '{\n'
            '  "agreements": ["Root cause is a missing dependency"],\n'
            '  "contradictions": [],\n'
            '  "gaps": ["No agent checked if dependency was intentionally removed"],\n'
            '  "revised_root_cause": "Missing dependency due to incomplete package.json",\n'
            '  "revised_fix": "Reinstall the dependency via npm install",\n'
            '  "revised_priority": "P2"\n'
            '}\n'
            "===JSON_OUTPUT_END==="
        ),
        "converge": (
            "===CONVERGENCE_REPORT===\n\n"
            "# Convergence Report -- 2026-02-16\n\n"
            "## Session Summary\n"
            "Issues analyzed: 1 | Resolved: 0 | Pending: 1\n\n"
            "### Issue: issue_20260216_195214_87l1\n"
            "- **Root Cause:** Blocking operation in main event loop\n"
            "- **Confidence:** high\n"
            "- **Recommended Fix:** Offload processing to background thread\n"
            "- **Priority:** P1\n"
            "- **Tasks Generated:** 2\n\n"
            "## Cross-Issue Patterns\n"
            "None (single issue)\n\n"
            "## Recommended Action Order\n"
            "1. Offload processing first to unblock loop\n"
            "2. Add metrics to monitor queue size\n\n"
            "===TASKS_JSON===\n\n"
            "[\n"
            "  {\n"
            "    \"title\": \"Offload message processing to thread\",\n"
            "    \"description\": \"Move the queue processing logic from the main loop to a separate worker thread.\",\n"
            "    \"issue_id\": \"issue_20260216_195214_87l1\",\n"
            "    \"priority\": \"P1\",\n"
            "    \"complexity\": \"medium\",\n"
            "    \"files_likely_affected\": [\"src/event_loop.py\", \"src/queue.py\"],\n"
            "    \"suggested_approach\": \"Use threading.Thread or asyncio.to_thread\"\n"
            "  },\n"
            "  {\n"
            "    \"title\": \"Add queue size metrics\",\n"
            "    \"description\": \"Instrument the queue to report size and processing time.\",\n"
            "    \"issue_id\": \"issue_20260216_195214_87l1\",\n"
            "    \"priority\": \"P2\",\n"
            "    \"complexity\": \"low\",\n"
            "    \"files_likely_affected\": [\"src/queue.py\"],\n"
            "    \"suggested_approach\": \"Use standard metrics library\"\n"
            "  }\n"
            "]"
        ),
    }.get(stage, f"Mock response for stage: {stage}")
