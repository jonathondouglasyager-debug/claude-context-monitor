"""
Convergence Engine - Security Sanitizer

Strips sensitive data (paths, tokens, usernames, environment variables)
from text and records before they are sent to any LLM, even via
Claude Code headless mode. Defense-in-depth.
"""

import os
import re
from typing import Any, Optional

from agents.config import get_sanitizer_config


# --- Regex patterns for sensitive data detection ---

# File paths: /Users/..., /home/..., C:\Users\..., /var/..., etc.
_PATH_PATTERNS = [
    re.compile(r"(/Users/[^\s:\"']+)", re.IGNORECASE),
    re.compile(r"(/home/[^\s:\"']+)", re.IGNORECASE),
    re.compile(r"([A-Z]:\\Users\\[^\s:\"']+)", re.IGNORECASE),
    re.compile(r"(/var/[^\s:\"']+)", re.IGNORECASE),
    re.compile(r"(/tmp/[^\s:\"']+)", re.IGNORECASE),
    re.compile(r"(/opt/[^\s:\"']+)", re.IGNORECASE),
    re.compile(r"(/etc/[^\s:\"']+)", re.IGNORECASE),
]

# API keys, tokens, secrets
_TOKEN_PATTERNS = [
    # OpenAI
    re.compile(r"(sk-[a-zA-Z0-9]{20,})", re.IGNORECASE),
    # Anthropic
    re.compile(r"(sk-ant-[a-zA-Z0-9\-]{20,})", re.IGNORECASE),
    # AWS
    re.compile(r"(AKIA[0-9A-Z]{16})", re.IGNORECASE),
    re.compile(r"(aws_secret_access_key\s*=\s*[^\s]+)", re.IGNORECASE),
    # Generic secrets
    re.compile(r"(ghp_[a-zA-Z0-9]{36,})", re.IGNORECASE),  # GitHub PAT
    re.compile(r"(gho_[a-zA-Z0-9]{36,})", re.IGNORECASE),  # GitHub OAuth
    re.compile(r"(glpat-[a-zA-Z0-9\-]{20,})", re.IGNORECASE),  # GitLab PAT
    re.compile(r"(xoxb-[a-zA-Z0-9\-]{20,})", re.IGNORECASE),  # Slack bot token
    re.compile(r"(xoxp-[a-zA-Z0-9\-]{20,})", re.IGNORECASE),  # Slack user token
    # JWT tokens
    re.compile(r"(eyJ[a-zA-Z0-9_\-]{10,}\.eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]+)"),
    # Generic key=value for common secret env names
    re.compile(
        r"((API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY|ACCESS_KEY)\s*[=:]\s*['\"]?[^\s'\"]{8,}['\"]?)",
        re.IGNORECASE
    ),
]

# Environment variable patterns with sensitive names
_ENV_PATTERNS = [
    re.compile(
        r"((?:export\s+)?(?:DATABASE_URL|DB_PASSWORD|REDIS_URL|SUPABASE_KEY|"
        r"STRIPE_SECRET|NEXTAUTH_SECRET|JWT_SECRET|ENCRYPTION_KEY|"
        r"PRIVATE_KEY|SSH_KEY)\s*=\s*[^\s]+)",
        re.IGNORECASE
    ),
]

# Username detection
_USERNAME_PATTERN = None  # Populated lazily


def _get_current_username() -> str:
    """Get the current system username for stripping."""
    try:
        return os.getlogin()
    except OSError:
        return os.environ.get("USER", os.environ.get("USERNAME", ""))


def _get_username_pattern() -> Optional[re.Pattern]:
    """Lazily compile a pattern for the current username."""
    global _USERNAME_PATTERN
    if _USERNAME_PATTERN is None:
        username = _get_current_username()
        if username and len(username) >= 3:  # Don't match very short usernames
            _USERNAME_PATTERN = re.compile(
                rf"\b{re.escape(username)}\b",
                re.IGNORECASE
            )
    return _USERNAME_PATTERN


def sanitize_context(text: str) -> str:
    """
    Strip sensitive data from text content.

    Applies configured stripping rules (paths, tokens, usernames)
    and returns the sanitized text.

    Args:
        text: Raw text that may contain sensitive data

    Returns:
        Sanitized text with sensitive data replaced by placeholders
    """
    if not text:
        return text

    config = get_sanitizer_config()

    if not config.get("enabled", True):
        return text

    result = text

    # Strip tokens first (most critical)
    if config.get("strip_tokens", True):
        for pattern in _TOKEN_PATTERNS:
            result = pattern.sub("[TOKEN_REDACTED]", result)
        for pattern in _ENV_PATTERNS:
            result = pattern.sub("[ENV_REDACTED]", result)

    # Strip file paths (preserve filename for context)
    if config.get("strip_paths", True):
        for pattern in _PATH_PATTERNS:
            def _path_replacer(match: re.Match) -> str:
                path = match.group(1)
                # Keep the filename, strip the directory structure
                basename = os.path.basename(path)
                if basename:
                    return f"[PATH_REDACTED]/{basename}"
                return "[PATH_REDACTED]"
            result = pattern.sub(_path_replacer, result)

    # Strip usernames
    if config.get("strip_usernames", True):
        username_pattern = _get_username_pattern()
        if username_pattern:
            result = username_pattern.sub("[USER_REDACTED]", result)

    return result


def sanitize_record(record: dict) -> dict:
    """
    Deep-sanitize all string fields in a record dictionary.

    Recursively walks the record and applies sanitize_context
    to every string value.

    Args:
        record: Dictionary that may contain sensitive string values

    Returns:
        New dictionary with all string values sanitized
    """
    config = get_sanitizer_config()
    if not config.get("enabled", True):
        return record

    return _sanitize_value(record)


def _sanitize_value(value: Any) -> Any:
    """Recursively sanitize a value."""
    if isinstance(value, str):
        return sanitize_context(value)
    elif isinstance(value, dict):
        return {k: _sanitize_value(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value


def is_sensitive(text: str) -> bool:
    """
    Check if text contains any sensitive data without modifying it.
    Useful for validation and logging decisions.

    Args:
        text: Text to check

    Returns:
        True if any sensitive patterns are detected
    """
    if not text:
        return False

    for pattern in _TOKEN_PATTERNS:
        if pattern.search(text):
            return True

    for pattern in _ENV_PATTERNS:
        if pattern.search(text):
            return True

    for pattern in _PATH_PATTERNS:
        if pattern.search(text):
            return True

    username_pattern = _get_username_pattern()
    if username_pattern and username_pattern.search(text):
        return True

    return False
