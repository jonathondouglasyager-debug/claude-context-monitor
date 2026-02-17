"""Tests for agents/sanitizer.py"""

import os
import pytest
from unittest.mock import patch

from agents.sanitizer import sanitize_context, sanitize_record, is_sensitive


class TestSanitizeContext:
    def test_strips_openai_key(self):
        text = "Error with key sk-abcdefghijklmnopqrstuvwxyz12345678"
        result = sanitize_context(text)
        assert "sk-abcdef" not in result
        assert "[TOKEN_REDACTED]" in result

    def test_strips_anthropic_key(self):
        text = "Using key sk-ant-api03-abcdefghijklmnopqrstuvwxyz"
        result = sanitize_context(text)
        assert "sk-ant" not in result
        assert "[TOKEN_REDACTED]" in result

    def test_strips_github_pat(self):
        text = "Token: ghp_abcdefghijklmnopqrstuvwxyz1234567890"
        result = sanitize_context(text)
        assert "ghp_" not in result
        assert "[TOKEN_REDACTED]" in result

    def test_strips_jwt(self):
        text = "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature_here"
        result = sanitize_context(text)
        assert "eyJ" not in result
        assert "[TOKEN_REDACTED]" in result

    def test_strips_aws_key(self):
        text = "AWS key: AKIAIOSFODNN7EXAMPLE"
        result = sanitize_context(text)
        assert "AKIA" not in result

    def test_strips_home_path(self):
        text = "Error in /Users/jonathon/projects/myapp/src/index.ts"
        result = sanitize_context(text)
        assert "jonathon" not in result
        assert "[PATH_REDACTED]" in result
        assert "index.ts" in result  # Filename preserved

    def test_strips_linux_path(self):
        text = "File at /home/developer/project/main.py"
        result = sanitize_context(text)
        assert "developer" not in result
        assert "[PATH_REDACTED]" in result
        assert "main.py" in result

    def test_strips_env_variables(self):
        text = "export DATABASE_URL=postgres://user:pass@host/db"
        result = sanitize_context(text)
        assert "postgres://" not in result
        assert "[ENV_REDACTED]" in result

    def test_preserves_normal_text(self):
        text = "The function returned undefined instead of an array"
        result = sanitize_context(text)
        assert result == text

    def test_empty_string(self):
        assert sanitize_context("") == ""

    def test_none_input(self):
        assert sanitize_context(None) is None

    @patch("agents.sanitizer.get_sanitizer_config")
    def test_disabled_sanitizer(self, mock_config):
        mock_config.return_value = {"enabled": False}
        text = "sk-abcdefghijklmnopqrstuvwxyz12345678"
        result = sanitize_context(text)
        assert result == text  # Unchanged when disabled

    @patch("agents.sanitizer.get_sanitizer_config")
    def test_disabled_path_stripping(self, mock_config):
        mock_config.return_value = {
            "enabled": True,
            "strip_paths": False,
            "strip_tokens": True,
            "strip_usernames": True,
        }
        text = "Error in /Users/dev/project/file.ts"
        result = sanitize_context(text)
        assert "/Users/dev" in result  # Path preserved


class TestSanitizeRecord:
    def test_deep_sanitizes_strings(self):
        record = {
            "id": "test_001",
            "description": "Failed at /Users/dev/project/app.ts",
            "nested": {
                "key": "sk-abcdefghijklmnopqrstuvwxyz12345678"
            },
            "list_field": ["/home/user/file.py", "normal text"],
            "number": 42,
        }
        result = sanitize_record(record)

        assert result["id"] == "test_001"  # Short strings without patterns unchanged
        assert "[PATH_REDACTED]" in result["description"]
        assert "[TOKEN_REDACTED]" in result["nested"]["key"]
        assert "[PATH_REDACTED]" in result["list_field"][0]
        assert result["list_field"][1] == "normal text"
        assert result["number"] == 42


class TestIsSensitive:
    def test_detects_api_key(self):
        assert is_sensitive("sk-abcdefghijklmnopqrstuvwxyz12345678") is True

    def test_detects_path(self):
        assert is_sensitive("/Users/dev/secret/file.ts") is True

    def test_normal_text_not_sensitive(self):
        assert is_sensitive("This is a normal error message") is False

    def test_empty_not_sensitive(self):
        assert is_sensitive("") is False
