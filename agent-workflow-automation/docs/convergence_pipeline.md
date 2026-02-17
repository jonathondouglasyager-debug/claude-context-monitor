# Convergence Pipeline -- Architecture & Reference

## Overview

The Convergence Engine is a multi-agent pipeline that runs inside Claude Code (or any compatible IDE). It intercepts errors during development, dispatches research agents to investigate root causes, runs a cross-agent debate to strengthen findings, and produces a single convergence document with prioritized tasks.

The key principle: **separate noticing from fixing.** When you hit an issue, the system captures it silently. You keep coding. Background agents handle research. At session end (or on demand), everything converges into an actionable plan.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        CONVERGENCE ENGINE                            │
│                                                                      │
│  CAPTURE            RESEARCH              DEBATE         CONVERGE    │
│  ┌─────────┐        ┌──────────────┐      ┌─────────┐   ┌────────┐ │
│  │ Hook or │───────> │ Researcher   │─────>│ Debater │──>│Arbiter │ │
│  │ /converge│        │ (root cause) │      │ (cross- │   │(synth- │ │
│  │ log     │   ┌───> │              │      │ agent   │   │ esize) │ │
│  │         │   │     ├──────────────┤      │ critique│   │        │ │
│  │ Writes  │   │     │ Solution     │─────>│ )       │   │ Writes │ │
│  │ to      │───┘     │ Finder       │      │         │   │ conv.  │ │
│  │ issues  │   ┌───> │              │      │         │   │ .md +  │ │
│  │ .jsonl  │   │     ├──────────────┤      │         │   │ tasks  │ │
│  │         │───┘     │ Impact       │─────>│         │   │ .json  │ │
│  │         │         │ Assessor     │      │         │   │        │ │
│  └─────────┘         └──────────────┘      └─────────┘   └────────┘ │
│       │                     │                   │             │      │
│       v                     v                   v             v      │
│  data/issues.jsonl   data/research/{id}/   debate.log   convergence/ │
└──────────────────────────────────────────────────────────────────────┘
```

## Pipeline Stages

### Stage 1: Capture

**Trigger:** `PostToolUseFailure` hook or manual `/converge log "..."`

**What happens:**
1. The `convergence-dispatcher.py` hook intercepts the error payload
2. It enriches the error with git context (branch, recent files)
3. The sanitizer strips sensitive data (paths, tokens, usernames)
4. The schema validator checks the record is well-formed
5. The record is atomically appended to `data/issues.jsonl`
6. Status is set to `captured`

**No research is triggered at this point.** The system is purely observational during capture to avoid disrupting your flow.

### Stage 2: Research

**Trigger:** `/converge research` command (manual) or automated via pipeline

**What happens:**
1. Three independent agents are dispatched:
   - **Researcher** -- Analyzes root cause (Hypothesis, Evidence, Confidence, Patterns)
   - **Solution Finder** -- Researches fixes (multiple solutions with tradeoffs)
   - **Impact Assessor** -- Evaluates severity, scope, frequency, priority
2. Researcher + Solution Finder run in parallel (up to `max_parallel_agents`)
3. Impact Assessor runs after them (benefits from their context)
4. Each agent writes its findings to `data/research/{issue_id}/`
5. Issue status transitions: `captured` -> `researching` -> `researched`

**Agent execution model:** Each agent spawns a `claude -p` (print mode) subprocess, which uses your existing Claude Code subscription. No separate API keys needed.

### Stage 3: Debate

**Trigger:** `/converge debate` command (manual)

**What happens:**
1. The debate agent reads all three research outputs
2. It constructs a critique analyzing:
   - **Agreements** -- High-confidence findings all agents support
   - **Contradictions** -- Where agents disagree (and which is better supported)
   - **Gaps** -- What no agent investigated but should be considered
   - **Revised Assessment** -- Unified position stronger than any individual
3. Output written to `data/research/{issue_id}/debate.md` and `debate.log`
4. Issue status transitions: `researched` -> `debating` -> `debated`

### Stage 4: Convergence

**Trigger:** `SessionEnd` hook (automatic) or `/converge synthesize` (manual)

**What happens:**
1. The arbiter reads all debated (or researched) issues
2. Previous convergence docs are archived to `convergence/archive/`
3. The arbiter produces:
   - `convergence/convergence.md` -- Full convergence report
   - `convergence/tasks.json` -- Prioritized, actionable task list
4. Cross-issue patterns are identified (related issues, same root cause)
5. Tasks are prioritized and ordered
6. Issue statuses transition to `converged`

## Configuration Reference

All configuration lives in `config.json` under the `convergence` key:

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `enabled` | bool | `true` | Master kill switch for entire pipeline |
| `auto_research` | bool | `true` | Auto-research on capture (future) |
| `auto_converge_on_session_end` | bool | `true` | Run arbiter on SessionEnd |
| `min_issues_for_convergence` | int | `1` | Minimum issues to trigger convergence |
| `sandbox_mode` | bool | `false` | Use mock data (no real LLM calls) |
| `budget.max_parallel_agents` | int | `2` | Max concurrent agent subprocesses |
| `budget.max_tokens_per_agent` | int | `4000` | Token limit per agent call |
| `budget.max_research_rounds` | int | `3` | Max research iterations (future) |
| `budget.timeout_seconds` | int | `60` | Subprocess timeout |
| `budget.model_map.{stage}` | str | `"default"` | Model override per stage |
| `budget.fallback_model` | str | `"haiku"` | Fallback for budget/rate limits |
| `sanitizer.enabled` | bool | `true` | Enable PII/secret stripping |
| `sanitizer.strip_paths` | bool | `true` | Replace file paths with redacted |
| `sanitizer.strip_tokens` | bool | `true` | Replace API keys/tokens |
| `sanitizer.strip_usernames` | bool | `true` | Replace system username |

## Data Files

| File | Format | Purpose |
|------|--------|---------|
| `data/issues.jsonl` | JSONL | All captured issues with status tracking |
| `data/quarantine.jsonl` | JSONL | Corrupt/invalid records moved here |
| `data/agent_activity.log` | Text | Human-readable agent activity log |
| `data/agent_activity.jsonl` | JSONL | Machine-parseable agent activity log |
| `data/research/{id}/root_cause.md` | Markdown | Root cause analysis for an issue |
| `data/research/{id}/solutions.md` | Markdown | Solution research for an issue |
| `data/research/{id}/impact.md` | Markdown | Impact assessment for an issue |
| `data/research/{id}/debate.md` | Markdown | Cross-agent debate synthesis |
| `data/research/{id}/debate.log` | Text | Full debate transcript (auditability) |
| `convergence/convergence.md` | Markdown | Current convergence report |
| `convergence/tasks.json` | JSON | Current task list |
| `convergence/archive/` | Mixed | Previous convergence reports |

## Issue Record Schema

```json
{
  "id": "issue_YYYYMMDD_HHMMSS_xxxx",
  "type": "error|warning|failure|regression|performance|design|manual|unknown",
  "timestamp": "ISO 8601",
  "description": "Human-readable description of the issue",
  "status": "captured|researching|researched|debating|debated|converging|converged|resolved",
  "source": "hook:PostToolUseFailure|manual:/converge log",
  "tool_name": "Tool that failed (e.g., Bash, Execute)",
  "git_branch": "Current git branch",
  "recent_files": ["List of recently changed files"],
  "working_directory": "CWD when error occurred",
  "raw_error": "Original error text (truncated to 2000 chars)"
}
```

## Security Model

All text is sanitized before being sent to any LLM (even via Claude Code headless mode):

- **File paths:** `/Users/jonathon/project/file.ts` -> `[PATH_REDACTED]/file.ts`
- **API tokens:** `sk-abc...` -> `[TOKEN_REDACTED]`
- **JWT tokens:** `eyJ...` -> `[TOKEN_REDACTED]`
- **Usernames:** System username -> `[USER_REDACTED]`
- **Env variables:** `DATABASE_URL=...` -> `[ENV_REDACTED]`

Sanitization is configurable per-type and can be disabled entirely for debugging.

## Troubleshooting

**Pipeline not capturing errors:**
- Check `convergence.enabled` is `true` in config.json
- Verify `convergence-dispatcher.py` is listed in plugin.json under PostToolUseFailure

**Research agents failing:**
- Check `claude -p "test"` works from your terminal (Claude Code must be installed)
- Check `budget.timeout_seconds` -- increase if agents time out
- Enable `sandbox_mode: true` to test with mock data

**Convergence not running on session end:**
- Check `auto_converge_on_session_end` is `true`
- Check `min_issues_for_convergence` -- may need more issues
- Check `data/agent_activity.log` for errors

**Tests failing:**
- Run `pytest tests/ -v` from the project root
- Tests use sandbox mode and mock data, no LLM calls needed
