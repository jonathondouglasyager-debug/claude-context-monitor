#!/usr/bin/env python3
"""
Convergence Synthesizer Hook

Runs on SessionEnd. Checks if there are debated/researched issues that
haven't been converged yet. If auto_converge_on_session_end is enabled,
runs the arbiter to produce the convergence report.

This hook ONLY runs on SessionEnd, NEVER per-error.

Hook input: JSON on stdin (SessionEnd payload)
Hook output: JSON on stdout with {"result": "allow"}
"""

import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PLUGIN_ROOT)

from agents.config import is_convergence_enabled, load_convergence_config
from agents.arbiter import synthesize
from agents.logger import PipelineLogger


def main():
    """Check for unconverged issues and synthesize if configured."""

    # Check kill switch
    if not is_convergence_enabled():
        print(json.dumps({"result": "allow"}))
        return

    # Check if auto-converge is enabled
    config = load_convergence_config()
    if not config.get("auto_converge_on_session_end", True):
        print(json.dumps({"result": "allow"}))
        return

    log = PipelineLogger("SESSION_END")
    log.info("Session ending -- checking for unconverged issues")

    # Read stdin payload (may be empty for SessionEnd)
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        payload = {}

    # Run convergence synthesis
    try:
        success = synthesize()
        if success:
            log.info("Auto-convergence completed successfully on session end")
        else:
            log.info("No issues eligible for convergence at session end")
    except Exception as e:
        log.error(f"Auto-convergence failed: {e}")

    # Always allow session to end
    print(json.dumps({"result": "allow"}))


if __name__ == "__main__":
    main()
