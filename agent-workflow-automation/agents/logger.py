"""
Convergence Engine - Structured Agent Logger

Provides unified logging for all pipeline stages with consistent
format, dual output (human-readable log + machine-parseable JSONL),
and per-issue tracking.
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional

from agents.config import get_data_dir


# Log levels
DEBUG = "DEBUG"
INFO = "INFO"
WARN = "WARN"
ERROR = "ERROR"

_LEVEL_PRIORITY = {DEBUG: 0, INFO: 1, WARN: 2, ERROR: 3}


class AgentLogger:
    """
    Structured logger for convergence pipeline agents.

    Usage:
        log = AgentLogger("issue_abc123", "RESEARCH")
        log.info("Starting root cause analysis")
        log.warn("Context exceeds token limit, truncating")
        log.error("Agent subprocess timed out", error=str(e))
    """

    def __init__(
        self,
        issue_id: str,
        stage: str,
        min_level: str = INFO,
        log_dir: Optional[str] = None,
    ):
        """
        Args:
            issue_id: The issue being processed (used as correlation ID)
            stage: Pipeline stage name (CAPTURE, RESEARCH, DEBATE, CONVERGE, etc.)
            min_level: Minimum log level to output (DEBUG, INFO, WARN, ERROR)
            log_dir: Override for log directory (defaults to data/)
        """
        self.issue_id = issue_id
        self.stage = stage.upper()
        self.min_level = min_level

        self._log_dir = log_dir or get_data_dir()
        os.makedirs(self._log_dir, exist_ok=True)

        self._human_log_path = os.path.join(self._log_dir, "agent_activity.log")
        self._jsonl_log_path = os.path.join(self._log_dir, "agent_activity.jsonl")

    def debug(self, message: str, **extra) -> None:
        """Log a debug message."""
        self._log(DEBUG, message, **extra)

    def info(self, message: str, **extra) -> None:
        """Log an info message."""
        self._log(INFO, message, **extra)

    def warn(self, message: str, **extra) -> None:
        """Log a warning message."""
        self._log(WARN, message, **extra)

    def error(self, message: str, **extra) -> None:
        """Log an error message."""
        self._log(ERROR, message, **extra)

    def _log(self, level: str, message: str, **extra) -> None:
        """
        Core logging method. Writes to both human-readable and JSONL logs.

        Format (human): [UTC_TIMESTAMP] [ISSUE_ID] [STAGE] [LEVEL] message
        Format (JSONL): {"timestamp": "...", "issue_id": "...", "stage": "...", ...}
        """
        # Check minimum level
        if _LEVEL_PRIORITY.get(level, 0) < _LEVEL_PRIORITY.get(self.min_level, 0):
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Human-readable line
        human_line = f"[{timestamp}] [{self.issue_id}] [{self.stage}] [{level}] {message}"
        if extra:
            extra_str = " | ".join(f"{k}={v}" for k, v in extra.items())
            human_line += f" | {extra_str}"

        # JSONL record
        jsonl_record = {
            "timestamp": timestamp,
            "issue_id": self.issue_id,
            "stage": self.stage,
            "level": level,
            "message": message,
        }
        if extra:
            jsonl_record["extra"] = extra

        # Write to human log
        try:
            with open(self._human_log_path, "a", encoding="utf-8") as f:
                f.write(human_line + "\n")
        except Exception as e:
            print(f"[LOGGER_ERROR] Could not write to {self._human_log_path}: {e}", file=sys.stderr)

        # Write to JSONL log
        try:
            with open(self._jsonl_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(jsonl_record, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            print(f"[LOGGER_ERROR] Could not write to {self._jsonl_log_path}: {e}", file=sys.stderr)

        # Also write to stderr for immediate visibility during development
        if level in (WARN, ERROR):
            print(human_line, file=sys.stderr)

    def section(self, title: str) -> None:
        """
        Log a visual section separator for readability in the human log.
        Does not appear in JSONL.
        """
        separator = f"\n{'='*60}\n  [{self.issue_id}] {self.stage}: {title}\n{'='*60}"
        try:
            with open(self._human_log_path, "a", encoding="utf-8") as f:
                f.write(separator + "\n")
        except Exception:
            pass


class PipelineLogger(AgentLogger):
    """
    Logger for pipeline-level events (not tied to a specific issue).
    Uses "PIPELINE" as the issue_id.
    """

    def __init__(self, stage: str = "SYSTEM", min_level: str = INFO):
        super().__init__(issue_id="PIPELINE", stage=stage, min_level=min_level)
