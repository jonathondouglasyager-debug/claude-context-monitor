"""
Convergence Engine - Configuration Manager

Loads convergence settings from config.json and provides typed accessors
for budget controls, model selection, sanitizer settings, and feature flags.

Data path resolution (priority order):
  1. CLAUDE_PROJECT_DIR env var (set by Claude Code when running in a project)
  2. os.getcwd() (works when hook runs from the target project)
  3. Plugin root (fallback -- resolves relative to this file)

All runtime data goes to {project_root}/.claude/convergence/ so the plugin
doesn't pollute its own install directory with per-project data.
"""

import json
import os
from typing import Any, Optional

# Plugin install root -- where the plugin code lives (agents/ is one level deep)
_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_PLUGIN_ROOT, "config.json")

# Default convergence configuration -- used when config.json lacks the section
_DEFAULTS = {
    "enabled": True,
    "auto_research": True,
    "auto_converge_on_session_end": True,
    "min_issues_for_convergence": 1,
    "sandbox_mode": False,
    "budget": {
        "max_parallel_agents": 2,
        "max_tokens_per_agent": 4000,
        "max_research_rounds": 3,
        "timeout_seconds": 60,
        "model_map": {
            "research": "default",
            "debate": "default",
            "converge": "default"
        },
        "fallback_model": "haiku"
    },
    "sanitizer": {
        "enabled": True,
        "strip_paths": True,
        "strip_tokens": True,
        "strip_usernames": True
    }
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, preferring override values."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def get_project_root() -> str:
    """
    Resolve the target project root directory.

    Priority:
      1. CLAUDE_PROJECT_DIR env var (most reliable -- set by Claude Code)
      2. Current working directory (works when hook spawned from project)
      3. Plugin install root (last resort fallback)

    All paths are resolved through os.path.realpath() to handle symlinks.
    """
    # 1. Explicit env var (Claude Code sets this for the active project)
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_dir and os.path.isdir(env_dir):
        return os.path.realpath(env_dir)

    # 2. CWD -- reliable when Claude Code spawns the hook from the project dir
    cwd = os.getcwd()
    if cwd and os.path.isdir(cwd):
        return os.path.realpath(cwd)

    # 3. Plugin root -- data will live alongside plugin code (legacy behavior)
    return os.path.realpath(_PLUGIN_ROOT)


def get_plugin_root() -> str:
    """Absolute path to the plugin install directory (where code lives)."""
    return os.path.realpath(_PLUGIN_ROOT)


def load_config() -> dict:
    """Load the full config.json file from the plugin root."""
    if not os.path.exists(_CONFIG_PATH):
        return {}
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_convergence_config() -> dict:
    """
    Load and validate the convergence section from config.json.
    Falls back to defaults for any missing keys.
    """
    full_config = load_config()
    user_convergence = full_config.get("convergence", {})
    return _deep_merge(_DEFAULTS, user_convergence)


def is_convergence_enabled() -> bool:
    """Master kill switch for the entire convergence pipeline."""
    return load_convergence_config().get("enabled", True)


def is_sandbox() -> bool:
    """When True, agents use mock data instead of spawning real LLM calls."""
    return load_convergence_config().get("sandbox_mode", False)


def get_max_parallel() -> int:
    """Max number of concurrent agent subprocesses."""
    config = load_convergence_config()
    return config.get("budget", {}).get("max_parallel_agents", 2)


def get_max_tokens(stage: str = "research") -> int:
    """Token limit for a given pipeline stage."""
    config = load_convergence_config()
    return config.get("budget", {}).get("max_tokens_per_agent", 4000)


def get_timeout_seconds() -> int:
    """Timeout in seconds for each agent subprocess."""
    config = load_convergence_config()
    return config.get("budget", {}).get("timeout_seconds", 60)


def get_model_for_stage(stage: str) -> str:
    """
    Get the model override for a pipeline stage.
    Returns "default" to use Claude Code's default model,
    or a specific model name for --model flag.
    """
    config = load_convergence_config()
    model_map = config.get("budget", {}).get("model_map", {})
    return model_map.get(stage, "default")


def get_fallback_model() -> str:
    """Fallback model when budget is exceeded."""
    config = load_convergence_config()
    return config.get("budget", {}).get("fallback_model", "haiku")


def get_sanitizer_config() -> dict:
    """Get sanitizer settings."""
    config = load_convergence_config()
    return config.get("sanitizer", {
        "enabled": True,
        "strip_paths": True,
        "strip_tokens": True,
        "strip_usernames": True
    })


# ---------------------------------------------------------------------------
# Data directory functions -- all resolve to {project_root}/.claude/convergence/
# ---------------------------------------------------------------------------

def _convergence_base() -> str:
    """Base directory for all convergence runtime data in the target project."""
    return os.path.join(get_project_root(), ".claude", "convergence")


def get_data_dir() -> str:
    """Absolute path to the data/ directory for issues and research."""
    path = os.path.join(_convergence_base(), "data")
    os.makedirs(path, exist_ok=True)
    return path


def get_research_dir(issue_id: str) -> str:
    """Absolute path to data/research/{issue_id}/."""
    path = os.path.join(get_data_dir(), "research", issue_id)
    os.makedirs(path, exist_ok=True)
    return path


def get_convergence_dir() -> str:
    """Absolute path to the convergence output directory."""
    path = os.path.join(_convergence_base(), "output")
    os.makedirs(path, exist_ok=True)
    return path


def get_archive_dir() -> str:
    """Absolute path to convergence/archive/."""
    path = os.path.join(get_convergence_dir(), "archive")
    os.makedirs(path, exist_ok=True)
    return path
