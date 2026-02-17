# Memory

## Me
Jonathon (jonathondouglasyager@gmail.com). Building automation tools for Claude Code workflows. Family-first motivation. Values: truth-seeking, practical results.

## Projects
| Name | What | Status |
|------|------|--------|
| **convergence-engine** | Multi-agent error learning plugin for Claude Code — captures errors, researches root causes via parallel agents, debates findings, produces convergence reports with tasks | Active — plan v2 committed, execution starts next session |
| **context-monitor** | Chrome extension for estimating token usage on claude.ai | Shelved (basic, fragile selectors) |

## Terms
| Term | Meaning |
|------|---------|
| convergence | The final synthesis step where all agent findings merge into one report + task list |
| arbiter | The agent that produces the convergence report (agents/arbiter.py) |
| fingerprint | Hash of error signature for cross-session dedup — sha256 of {type, tool_name, error_normalized, source_file, git_branch} |
| CLAUDE.md bridge | Pattern of writing compact knowledge to CLAUDE.md so new sessions inherit it for free |
| applicability predicate | Grove-inspired: conditions under which a cached solution applies (error pattern + context match) |

## Architecture (convergence-engine)
- **Plugin root:** agent-workflow-automation/
- **Pipeline:** Capture → Research (3 agents parallel) → Debate → Converge
- **Agents:** researcher, solution_finder, impact_assessor, debater, arbiter
- **Runner:** spawns `claude -p` subprocesses (sandbox mode uses mocks)
- **Data:** JSONL with file locking, schema validation, quarantine for corrupt records
- **Security:** sanitizer strips paths, tokens, JWT, API keys, usernames, env vars
- **Frontend:** Next.js 16 + React 19 + shadcn/ui dashboard (app/page.tsx)
- **Hooks (actual):** convergence-dispatcher.py (PostToolUseFailure), convergence-synthesizer.py (SessionEnd)
- **CRITICAL BUG:** config.py hardcodes data paths to plugin root, not project CWD

## Active Plan v2 (cross-session plugin refactor)
→ Full plan: memory/projects/convergence-engine-refactor-plan-v2.md

### Phase 1 — Cleanup & Foundation (NEXT SESSION)
1. Fix plugin.json: reference actual hooks, remove phantom entries
2. Move misplaced React hooks out of hooks/ dir
3. Data path decoupling: config.py uses CLAUDE_PROJECT_DIR env var → getcwd fallback → plugin root fallback; all data to {project}/.claude/convergence/

### Phase 2 — Fingerprinting & Dedup
4. Create agents/fingerprint.py (multi-field sha256, normalize error messages)
5. Schema migration: add fingerprint, occurrence_count, first_seen, last_seen (optional fields, auto-migrate on read)
6. Dedup in dispatcher: check fingerprint before creating new issue
7. Harden file locking: filelock library (cross-process safe)

### Phase 3 — CLAUDE.md Bridge
8. Arbiter writes convergence knowledge to CLAUDE.md with section markers + atomic writes
9. Session-start pattern matcher hook: short-circuit re-research for known fingerprints (~15-20k token savings per match)

### Phase 4-5 — Quality & Portability (stretch)
10. Agent output JSON schemas (MAST-inspired inter-agent contract)
11. Adversarial debate roles (RedDebate-inspired)
12. Checkpoint architecture (phase re-execution without re-research)
13. Plugin install testing + documentation

## Resolved Issues (2026-02-17)
- ✅ hooks/error-logger.py, error-curator.py, command-validator.py, fix-tracker.py — NOT missing functionality. convergence-dispatcher.py and convergence-synthesizer.py replaced them. plugin.json is just out of sync.
- ✅ hooks/use-mobile.tsx and hooks/use-toast.ts — React hooks, duplicates of components/ui/ versions. Delete from hooks/, update imports if needed.

## Critical Edge Cases (must address in Phase 1-2)
- CWD resolution: use CLAUDE_PROJECT_DIR env var, not os.getcwd() alone
- Concurrent sessions: fcntl insufficient → use filelock library
- Schema migration: auto-migrate legacy records missing fingerprint field
- CLAUDE.md writes: section markers + atomic write to prevent user edit loss
- Sandbox mode: new components need mock paths for existing tests

## Research References (methodology insights)
- **Grove** (arxiv 2511.17833): hierarchical knowledge trees with applicability predicates — model for CLAUDE.md bridge
- **MAST** (arxiv 2503.13657): inter-agent misalignment is dominant multi-agent failure mode — need strict agent output schemas
- **RedDebate** (arxiv 2511.07784): adversarial debate roles improve output quality
- **AgentDebug/AgentGit** (arxiv 2509.25370): checkpoint + trajectory analysis for agent recovery
- **MCP-KG-Memory**: graph-based persistent memory for coding agents (future tier)
- **Hybrid fingerprinting**: exact hash (now) + structural LSH (later) + semantic embeddings (deferred)

## Preferences
- Truth-first, family-first
- Practical over theoretical
- Multi-session workflow: map → plan → research → replan → commit → execute
→ Full details: memory/projects/convergence-engine.md
