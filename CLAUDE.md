# Memory

## Me
Jonathon (jonathondouglasyager@gmail.com). Building automation tools for Claude Code workflows. Family-first motivation. Values: truth-seeking, practical results.

## Projects
| Name | What | Status |
|------|------|--------|
| **convergence-engine** | Multi-agent error learning plugin for Claude Code — captures errors, researches root causes via parallel agents, debates findings, produces convergence reports with tasks, bridges knowledge to CLAUDE.md | Active — Phase 3 done, Phase 4 next |
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
- **Runner:** spawns `claude -p` subprocesses (sandbox mode uses mocks); propagates CLAUDE_PROJECT_DIR env var to child processes
- **Fingerprinting:** agents/fingerprint.py — sha256({type, tool_name, error_normalized, source_file, git_branch}); dedup in dispatcher
- **Data:** JSONL with filelock (cross-process), schema validation, quarantine for corrupt records, auto-migration for Phase 2 fields
- **Data location:** {project_root}/.claude/convergence/ (decoupled from plugin install dir as of Phase 1)
- **Security:** sanitizer strips paths, tokens, JWT, API keys, usernames, env vars
- **Frontend:** Next.js 16 + React 19 + shadcn/ui dashboard (app/page.tsx)
- **Hooks:** convergence-dispatcher.py (PostToolUseFailure), convergence-synthesizer.py (SessionEnd), fingerprint-matcher.py (PreToolUse on Bash|Execute)
- **CLAUDE.md bridge:** agents/claude_md_bridge.py — writes convergence knowledge table to {project_root}/CLAUDE.md with section markers + atomic writes + filelock
- **Path resolution:** config.get_project_root() — CLAUDE_PROJECT_DIR env var → os.getcwd() → plugin root fallback

## Active Plan v2 (cross-session plugin refactor)
→ Full plan: memory/projects/convergence-engine-refactor-plan-v2.md

### Phase 1 — Cleanup & Foundation ✅ DONE (2026-02-17)
1. ✅ plugin.json: removed phantom hooks, only references convergence-dispatcher + convergence-synthesizer
2. ✅ React hooks: imports updated to @/components/ui/, duplicates deleted from hooks/
3. ✅ config.py: 3-tier project root (CLAUDE_PROJECT_DIR → cwd → plugin root); data to {project}/.claude/convergence/
4. ✅ runner.py: propagates CLAUDE_PROJECT_DIR to subprocess env
5. ✅ All _PROJECT_ROOT → _PLUGIN_ROOT for clarity (only used for sys.path)
6. ✅ 59/59 tests pass

### Phase 2 — Fingerprinting & Dedup ✅ DONE (2026-02-17)
4. ✅ agents/fingerprint.py: multi-field sha256 + normalize_error_message (strips paths, timestamps, UUIDs, hashes, PIDs, addrs)
5. ✅ Schema migration: fingerprint, occurrence_count, first_seen, last_seen (optional fields, auto-migrate via migrate_issue())
6. ✅ Dedup in dispatcher: compute fingerprint → find_duplicate → increment occurrence_count or append new
7. ✅ file_lock.py: replaced fcntl with filelock library (cross-process safe, 20 retries, 2s max backoff)
8. ✅ 101/101 tests pass (59 original + 42 new fingerprint tests)

### Phase 3 — CLAUDE.md Bridge ✅ DONE (2026-02-17)
9. ✅ agents/claude_md_bridge.py: builds Grove-inspired knowledge table (fingerprint, error pattern, root cause, fix, applicability predicate, seen count)
10. ✅ Arbiter integration: synthesize() writes convergence section to {project_root}/CLAUDE.md with `<!-- convergence-engine:start/end -->` markers + atomic write + filelock
11. ✅ Dispatcher enhancement: converged fingerprint matches emit cached resolution to stderr, skip re-research (~15-20k token savings per match)
12. ✅ hooks/fingerprint-matcher.py: PreToolUse on Bash|Execute — loads known patterns from CLAUDE.md knowledge table, warns on pattern match
13. ✅ plugin.json v3.0.0: added PreToolUse hook for fingerprint-matcher
14. ✅ 152/152 tests pass (101 original + 43 bridge tests + 8 matcher tests)

### Phase 4-5 — Quality & Portability (NEXT SESSION)
10. Agent output JSON schemas (MAST-inspired inter-agent contract)
11. Adversarial debate roles (RedDebate-inspired)
12. Checkpoint architecture (phase re-execution without re-research)
13. Plugin install testing + documentation

## Critical Edge Cases (must address in Phase 4+)
- ✅ Concurrent sessions: filelock library (Phase 2)
- ✅ Schema migration: migrate_issue() auto-populates Phase 2 fields (Phase 2)
- ✅ CLAUDE.md writes: section markers + atomic write + filelock to prevent user edit loss (Phase 3)
- ✅ Corrupt markers: graceful fallback strips partial markers (Phase 3)
- ✅ Sandbox mode: bridge write skipped in sandbox mode; matcher tests use monkeypatch (Phase 3)
- Agent output format drift: need strict JSON schemas between agents (Phase 4)

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
