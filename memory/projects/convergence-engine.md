# Convergence Engine — Full Codebase Map

## Overview
Multi-agent Claude Code plugin that captures errors during development, dispatches research agents, runs cross-agent debate, and produces convergence reports with prioritized tasks. Goal: learn from errors across sessions and save tokens by not re-researching known issues.

## File Map (38 files)

### Plugin Definition
| File | Purpose | Lines |
|------|---------|-------|
| plugin.json | Hook definitions + slash commands. Hooks: PreToolUse, PostToolUse, PostToolUseFailure, SessionEnd | 69 |
| config.json | Runtime config: error_learning + convergence settings, budget controls, sanitizer flags | 36 |

### Agent Pipeline (agents/)
| File | Purpose | Key Functions | Lines |
|------|---------|--------------|-------|
| config.py | Config loader, typed accessors for budget/model/sanitizer. **BUG: _PROJECT_ROOT hardcoded to plugin dir** | load_convergence_config(), get_data_dir(), get_research_dir() | 158 |
| pipeline.py | Orchestrator: dispatches research agents, manages status transitions | research_single_issue(), research_all_unresearched(), get_pipeline_status() | 200 |
| researcher.py | Root cause analysis agent. Prompt → claude -p → root_cause.md | research_issue() | 123 |
| solution_finder.py | Fix research agent. Reads root_cause if available. → solutions.md | find_solutions() | 144 |
| impact_assessor.py | Severity/priority agent. Reads issue history for pattern detection. → impact.md | assess_impact() | 156 |
| debater.py | Cross-agent critique. Reads all 3 research outputs → debate.md + debate.log | debate_issue() | 166 |
| arbiter.py | Final synthesis. Reads all debated issues → convergence.md + tasks.json. Archives previous. Parses ===CONVERGENCE_REPORT=== and ===TASKS_JSON=== delimiters | synthesize() | 298 |
| runner.py | Subprocess spawner for `claude -p`. Sandbox mode returns mocks. AgentResult class | run_agent(), write_research_output() | 253 |
| sanitizer.py | Security: regex-based stripping of paths, tokens (OpenAI/Anthropic/AWS/GitHub/GitLab/Slack/JWT), env vars, usernames | sanitize_context(), sanitize_record(), is_sensitive() | 201 |
| file_lock.py | Atomic JSONL ops with fcntl locking + exponential backoff. CRUD for issue records | atomic_append(), read_jsonl(), read_jsonl_by_id(), update_jsonl_record() | 222 |
| schema_validator.py | Validates issue records, quarantines corrupt ones. Validates research output sections | validate_issue(), validate_all_issues(), make_issue_id() | 229 |
| logger.py | Dual logging: human-readable .log + machine-parseable .jsonl. Per-issue correlation | AgentLogger, PipelineLogger | 147 |
| __init__.py | Package marker | 6 |

### Hooks (hooks/)
| File | Purpose | Lines |
|------|---------|-------|
| convergence-dispatcher.py | PostToolUseFailure hook. Enriches error with git context, sanitizes, validates, atomic appends to issues.jsonl | 156 |
| convergence-synthesizer.py | SessionEnd hook. Runs arbiter if auto_converge_on_session_end=true | 67 |
| use-mobile.tsx | **MISPLACED** — React hook, belongs in app/ | 24 |
| use-toast.ts | **MISPLACED** — React hook, belongs in app/ | 133 |

### Missing Hooks (referenced in plugin.json but don't exist)
- hooks/error-logger.py (PostToolUseFailure)
- hooks/error-curator.py (SessionEnd)
- hooks/command-validator.py (PreToolUse)
- hooks/fix-tracker.py (PostToolUse)

### Commands (commands/)
| File | Purpose |
|------|---------|
| converge.md | Full /converge command spec: log, research, debate, synthesize, status, tasks, doc, reset |

### Frontend (app/)
| File | Purpose |
|------|---------|
| page.tsx | Server component dashboard. Reads issues.jsonl + tasks.json + convergence.md. 4 stat cards + 3 tabs (Issues, Report, Tasks) |
| layout.tsx | Root layout with Inter font |
| globals.css | Tailwind + CSS variables for shadcn themes |

### Tests (tests/)
| File | What it tests |
|------|--------------|
| conftest.py | Shared fixtures: tmp dirs, mock issues, sandbox config override |
| test_file_lock.py | atomic_append concurrency, read/update JSONL ops |
| test_sanitizer.py | Token stripping, path redaction, username removal, is_sensitive() |
| test_schema_validator.py | Issue validation, quarantine logic, research validation |
| test_convergence_output.py | Arbiter output parsing, task extraction from delimited format |
| test_pipeline_integration.py | Full pipeline in sandbox mode: capture → research → status |

### Data (runtime, not committed)
| Path | Format | Content |
|------|--------|---------|
| data/issues.jsonl | JSONL | 1 issue (converged, performance type, manual source) |
| data/agent_activity.log | Text | Human-readable pipeline logs |
| data/agent_activity.jsonl | JSONL | Machine-parseable activity logs |
| data/research/ | Dirs | Per-issue research outputs |
| convergence/convergence.md | Markdown | Current report (1 issue, 2 tasks) |
| convergence/tasks.json | JSON | 2 tasks (P1 thread offload, P2 queue metrics) |
| convergence/archive/ | Mixed | Previous convergence docs |

## Critical Refactoring Needed

### 1. Data Path Decoupling
**Problem:** config.py line 13: `_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` — resolves to the PLUGIN install directory, not the project being worked on.

**Fix:** Add `get_project_data_root()` that uses `os.getcwd()` or `CLAUDE_PROJECT_DIR` env var to resolve to `{project}/.claude/convergence/`. All data functions (get_data_dir, get_research_dir, get_convergence_dir, get_archive_dir) must use this instead of _PROJECT_ROOT.

### 2. Error Fingerprinting
**New file:** agents/fingerprint.py
**Fields:** fingerprint = sha256(f"{error_type}:{tool_name}:{normalized_error}")
**On capture:** Check issues.jsonl for matching fingerprint. If found, increment count + skip research.
**Schema change:** Add `fingerprint` and `occurrence_count` fields to issue schema.

### 3. CLAUDE.md Writer
**Modify:** agents/arbiter.py synthesize() function
**After writing convergence.md + tasks.json:** Generate compact summary (under 50 lines), write/update a `## Convergence Knowledge` section in {CWD}/CLAUDE.md
**Content:** Known error patterns (fingerprint → description → fix), active P0/P1 tasks, key cross-issue patterns

### 4. Session-Start Pattern Matcher
**New hook:** Add to PreToolUse in plugin.json, or use a lightweight SessionStart check
**Behavior:** Load fingerprint index from .claude/convergence/. On error match, return cached research instead of spawning 3 agents (~15-20k tokens saved per match).

### 5. Plugin Portability
- All `${CLAUDE_PLUGIN_ROOT}` references are correct for plugin code
- Data writes to `{CWD}/.claude/convergence/` (project-scoped)
- Install: `claude plugin add /path/to/agent-workflow-automation`
- Add .gitignore for `.claude/convergence/data/` but track `.claude/convergence/convergence.md`

## Token Savings Math
- Each research cycle: ~15-20k tokens (3 agents + debate + arbiter)
- Same error hit 5x across sessions without fingerprinting: 75-100k tokens wasted
- With fingerprinting: spend once, serve cached forever
- CLAUDE.md injection: ~500-1000 tokens/session for persistent context
- Net savings compound over time as knowledge base grows
