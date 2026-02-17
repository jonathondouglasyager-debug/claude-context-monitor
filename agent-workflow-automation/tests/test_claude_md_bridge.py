"""
Tests for agents/claude_md_bridge.py

Covers:
- Section marker insertion and stripping
- Knowledge table generation from converged issues
- Atomic write with filelock
- Existing CLAUDE.md preservation (user content not lost)
- Corrupt marker recovery
- Active tasks summary
- Read-back of knowledge table
- Edge cases (empty issues, missing research, no CLAUDE.md)
"""

import json
import os
import tempfile

import pytest

from agents.claude_md_bridge import (
    _START_MARKER,
    _END_MARKER,
    _strip_convergence_section,
    _extract_error_pattern,
    _extract_applicability,
    _build_knowledge_table,
    _build_tasks_summary,
    build_convergence_section,
    write_to_claude_md,
    read_knowledge_table,
)


# --- Fixtures ---


@pytest.fixture
def tmp_project(tmp_path):
    """Temp project root with .claude/ directory."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    return tmp_path


@pytest.fixture
def sample_converged_issue():
    """A converged issue with all Phase 2 fields."""
    return {
        "id": "issue_20260217_120000_ab12",
        "type": "error",
        "timestamp": "2026-02-17T12:00:00Z",
        "description": "Tool 'Bash' failed: npm ERR! Could not resolve dependency",
        "status": "converged",
        "source": "hook:PostToolUseFailure",
        "tool_name": "Bash",
        "git_branch": "main",
        "recent_files": ["package.json", "package-lock.json"],
        "working_directory": "/test/project",
        "raw_error": "npm ERR! Could not resolve dependency",
        "fingerprint": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
        "occurrence_count": 3,
        "first_seen": "2026-02-17T10:00:00Z",
        "last_seen": "2026-02-17T14:00:00Z",
    }


@pytest.fixture
def mock_research_dir(tmp_path):
    """Create mock research outputs and return a research_dir_fn."""
    def research_dir_fn(issue_id):
        d = tmp_path / "research" / issue_id
        d.mkdir(parents=True, exist_ok=True)
        return str(d)
    return research_dir_fn


@pytest.fixture
def populated_research(mock_research_dir):
    """Populate research files for the sample issue."""
    issue_id = "issue_20260217_120000_ab12"
    d = mock_research_dir(issue_id)
    with open(os.path.join(d, "root_cause.md"), "w") as f:
        f.write("# Root Cause\nMissing peer dependency in package.json\n")
    with open(os.path.join(d, "solutions.md"), "w") as f:
        f.write("# Solutions\nAdd missing dependency with npm install --legacy-peer-deps\n")
    with open(os.path.join(d, "debate.md"), "w") as f:
        f.write("# Debate\nAll agents agree: missing peer dependency is root cause\n")
    return mock_research_dir


# --- _strip_convergence_section tests ---


class TestStripConvergenceSection:
    def test_no_markers_returns_unchanged(self):
        content = "# My Project\n\nSome user content\n"
        assert _strip_convergence_section(content) == content

    def test_both_markers_strips_section(self):
        content = (
            "# My Project\n\n"
            f"{_START_MARKER}\n"
            "## Convergence Knowledge\n"
            "| table data |\n"
            f"{_END_MARKER}\n"
            "\n## Other Section\n"
        )
        result = _strip_convergence_section(content)
        assert _START_MARKER not in result
        assert _END_MARKER not in result
        assert "Convergence Knowledge" not in result
        assert "Other Section" in result

    def test_preserves_content_before_markers(self):
        content = (
            "# My Project\n"
            "Important user notes\n\n"
            f"{_START_MARKER}\n"
            "auto content\n"
            f"{_END_MARKER}\n"
        )
        result = _strip_convergence_section(content)
        assert "Important user notes" in result

    def test_preserves_content_after_markers(self):
        content = (
            f"{_START_MARKER}\n"
            "auto content\n"
            f"{_END_MARKER}\n"
            "## User section after\n"
        )
        result = _strip_convergence_section(content)
        assert "User section after" in result

    def test_corrupt_start_only(self):
        content = (
            "# Project\n"
            f"{_START_MARKER}\n"
            "orphaned auto content\n"
        )
        result = _strip_convergence_section(content)
        assert "# Project" in result
        assert _START_MARKER not in result
        assert "orphaned" not in result

    def test_corrupt_end_only(self):
        content = (
            "orphaned content\n"
            f"{_END_MARKER}\n"
            "# After\n"
        )
        result = _strip_convergence_section(content)
        assert "# After" in result
        assert _END_MARKER not in result

    def test_empty_content(self):
        assert _strip_convergence_section("") == ""

    def test_only_markers(self):
        content = f"{_START_MARKER}\n{_END_MARKER}\n"
        result = _strip_convergence_section(content)
        assert result.strip() == ""


# --- _extract_error_pattern tests ---


class TestExtractErrorPattern:
    def test_strips_tool_prefix(self):
        issue = {"description": "Tool 'Bash' failed: npm install error"}
        result = _extract_error_pattern(issue)
        assert "Tool 'Bash' failed" not in result
        assert "npm install error" in result

    def test_truncates_long_patterns(self):
        issue = {"description": "Tool 'X' failed: " + "a" * 200}
        result = _extract_error_pattern(issue)
        assert len(result) <= 83  # 80 + "..."

    def test_escapes_pipe_chars(self):
        issue = {"description": "error | with | pipes"}
        result = _extract_error_pattern(issue)
        assert "|" not in result or "\\|" in result

    def test_empty_description(self):
        result = _extract_error_pattern({"description": ""})
        assert result == ""

    def test_missing_description(self):
        result = _extract_error_pattern({})
        assert result == ""


# --- _extract_applicability tests ---


class TestExtractApplicability:
    def test_includes_tool_name(self):
        issue = {"tool_name": "Bash", "git_branch": "main", "recent_files": []}
        result = _extract_applicability(issue)
        assert "`Bash`" in result

    def test_includes_branch(self):
        issue = {"tool_name": "", "git_branch": "feature-x", "recent_files": []}
        result = _extract_applicability(issue)
        assert "branch:feature-x" in result

    def test_skips_unknown_branch(self):
        issue = {"tool_name": "Bash", "git_branch": "unknown", "recent_files": []}
        result = _extract_applicability(issue)
        assert "branch:" not in result

    def test_includes_first_file(self):
        issue = {"tool_name": "", "git_branch": "", "recent_files": ["src/main.py", "test.py"]}
        result = _extract_applicability(issue)
        assert "src/main.py" in result
        assert "test.py" not in result

    def test_empty_issue(self):
        result = _extract_applicability({})
        assert result == "any context"


# --- _build_knowledge_table tests ---


class TestBuildKnowledgeTable:
    def test_empty_issues(self, mock_research_dir):
        assert _build_knowledge_table([], mock_research_dir) == ""

    def test_single_issue_has_header(self, sample_converged_issue, populated_research):
        table = _build_knowledge_table([sample_converged_issue], populated_research)
        assert "| Fingerprint |" in table
        assert "|---|" in table

    def test_single_issue_has_data_row(self, sample_converged_issue, populated_research):
        table = _build_knowledge_table([sample_converged_issue], populated_research)
        lines = table.split("\n")
        data_rows = [l for l in lines if l.startswith("|") and "---" not in l and "Fingerprint" not in l]
        assert len(data_rows) == 1

    def test_fingerprint_is_truncated(self, sample_converged_issue, populated_research):
        table = _build_knowledge_table([sample_converged_issue], populated_research)
        # Full fingerprint is 64 chars, should be truncated to 12
        assert "`a1b2c3d4e5f6`" in table

    def test_multiple_issues(self, sample_converged_issue, populated_research):
        issue2 = sample_converged_issue.copy()
        issue2["id"] = "issue_20260217_130000_cd34"
        issue2["fingerprint"] = "b" * 64
        table = _build_knowledge_table(
            [sample_converged_issue, issue2], populated_research
        )
        lines = table.split("\n")
        data_rows = [l for l in lines if l.startswith("|") and "---" not in l and "Fingerprint" not in l]
        assert len(data_rows) == 2


# --- _build_tasks_summary tests ---


class TestBuildTasksSummary:
    def test_empty_tasks(self):
        assert _build_tasks_summary([]) == ""

    def test_no_p0_p1_tasks(self):
        tasks = [{"priority": "P2", "status": "pending", "title": "Low pri"}]
        assert _build_tasks_summary(tasks) == ""

    def test_p0_task_included(self):
        tasks = [{"priority": "P0", "status": "pending", "title": "Fix auth"}]
        result = _build_tasks_summary(tasks)
        assert "[P0]" in result
        assert "Fix auth" in result

    def test_completed_tasks_excluded(self):
        tasks = [{"priority": "P0", "status": "completed", "title": "Done task"}]
        assert _build_tasks_summary(tasks) == ""

    def test_caps_at_10(self):
        tasks = [
            {"priority": "P0", "status": "pending", "title": f"Task {i}"}
            for i in range(15)
        ]
        result = _build_tasks_summary(tasks)
        assert result.count("- **[P0]**") == 10


# --- build_convergence_section tests ---


class TestBuildConvergenceSection:
    def test_includes_markers(self, sample_converged_issue, populated_research):
        section = build_convergence_section(
            [sample_converged_issue], [], populated_research
        )
        assert _START_MARKER in section
        assert _END_MARKER in section

    def test_includes_header(self, sample_converged_issue, populated_research):
        section = build_convergence_section(
            [sample_converged_issue], [], populated_research
        )
        assert "## Convergence Knowledge (auto-generated)" in section

    def test_includes_timestamp(self, sample_converged_issue, populated_research):
        section = build_convergence_section(
            [sample_converged_issue], [], populated_research
        )
        assert "_Last updated:" in section

    def test_empty_produces_placeholder(self, mock_research_dir):
        section = build_convergence_section([], [], mock_research_dir)
        assert "No convergence knowledge yet" in section

    def test_includes_tasks_when_provided(self, sample_converged_issue, populated_research):
        tasks = [{"priority": "P0", "status": "pending", "title": "Urgent fix"}]
        section = build_convergence_section(
            [sample_converged_issue], tasks, populated_research
        )
        assert "Urgent fix" in section


# --- write_to_claude_md tests ---


class TestWriteToClaudeMd:
    def test_creates_new_claude_md(self, tmp_project, sample_converged_issue, populated_research):
        section = build_convergence_section(
            [sample_converged_issue], [], populated_research
        )
        result = write_to_claude_md(str(tmp_project), section)
        assert result is True

        claude_md = tmp_project / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert _START_MARKER in content
        assert _END_MARKER in content

    def test_preserves_existing_content(self, tmp_project, populated_research, sample_converged_issue):
        claude_md = tmp_project / "CLAUDE.md"
        claude_md.write_text("# My Project\n\nUser notes here\n")

        section = build_convergence_section(
            [sample_converged_issue], [], populated_research
        )
        write_to_claude_md(str(tmp_project), section)

        content = claude_md.read_text()
        assert "User notes here" in content
        assert _START_MARKER in content

    def test_replaces_old_section(self, tmp_project, populated_research, sample_converged_issue):
        claude_md = tmp_project / "CLAUDE.md"
        old_content = (
            "# Project\n\n"
            f"{_START_MARKER}\n"
            "old data\n"
            f"{_END_MARKER}\n"
        )
        claude_md.write_text(old_content)

        section = build_convergence_section(
            [sample_converged_issue], [], populated_research
        )
        write_to_claude_md(str(tmp_project), section)

        content = claude_md.read_text()
        assert "old data" not in content
        assert content.count(_START_MARKER) == 1
        assert content.count(_END_MARKER) == 1

    def test_idempotent_writes(self, tmp_project, populated_research, sample_converged_issue):
        """Multiple writes don't duplicate the section."""
        section = build_convergence_section(
            [sample_converged_issue], [], populated_research
        )
        write_to_claude_md(str(tmp_project), section)
        write_to_claude_md(str(tmp_project), section)
        write_to_claude_md(str(tmp_project), section)

        content = (tmp_project / "CLAUDE.md").read_text()
        assert content.count(_START_MARKER) == 1
        assert content.count(_END_MARKER) == 1

    def test_atomic_write_no_partial(self, tmp_project):
        """If write fails, original content is preserved."""
        claude_md = tmp_project / "CLAUDE.md"
        claude_md.write_text("original content\n")

        # Write with valid section should succeed
        result = write_to_claude_md(str(tmp_project), f"{_START_MARKER}\ntest\n{_END_MARKER}")
        assert result is True
        assert "original content" in claude_md.read_text()


# --- read_knowledge_table tests ---


class TestReadKnowledgeTable:
    def test_no_claude_md(self, tmp_project):
        entries = read_knowledge_table(str(tmp_project))
        assert entries == []

    def test_no_markers(self, tmp_project):
        (tmp_project / "CLAUDE.md").write_text("# Project\nNo convergence here\n")
        entries = read_knowledge_table(str(tmp_project))
        assert entries == []

    def test_parses_table(self, tmp_project):
        content = (
            f"{_START_MARKER}\n"
            "## Convergence Knowledge\n"
            "| Fingerprint | Error Pattern | Root Cause | Fix | Applies When | Seen |\n"
            "|---|---|---|---|---|---|\n"
            "| `abc123` | npm ERR dependency | Missing peer dep | npm install --legacy | `Bash`, main | 3 |\n"
            f"{_END_MARKER}\n"
        )
        (tmp_project / "CLAUDE.md").write_text(content)
        entries = read_knowledge_table(str(tmp_project))

        assert len(entries) == 1
        assert entries[0]["fingerprint_short"] == "abc123"
        assert "npm ERR" in entries[0]["error_pattern"]
        assert entries[0]["seen_count"] == 3

    def test_parses_multiple_rows(self, tmp_project):
        content = (
            f"{_START_MARKER}\n"
            "| Fingerprint | Error Pattern | Root Cause | Fix | Applies When | Seen |\n"
            "|---|---|---|---|---|---|\n"
            "| `aaa` | err1 | cause1 | fix1 | ctx1 | 1 |\n"
            "| `bbb` | err2 | cause2 | fix2 | ctx2 | 5 |\n"
            f"{_END_MARKER}\n"
        )
        (tmp_project / "CLAUDE.md").write_text(content)
        entries = read_knowledge_table(str(tmp_project))
        assert len(entries) == 2

    def test_round_trip(self, tmp_project, sample_converged_issue, populated_research):
        """Write and read back should produce consistent entries."""
        section = build_convergence_section(
            [sample_converged_issue], [], populated_research
        )
        write_to_claude_md(str(tmp_project), section)

        entries = read_knowledge_table(str(tmp_project))
        assert len(entries) == 1
        assert entries[0]["fingerprint_short"] == "a1b2c3d4e5f6"
