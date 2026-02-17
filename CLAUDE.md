# Memory

## Me
Jonathon (jonathondouglasyager@gmail.com). Building automation tools for Claude Code workflows. Family-first motivation. Values: truth-seeking, practical results.
- **GitHub:** jonathondouglasyager-debug

## Projects
| Name | What | Status |
|------|------|--------|
| **convergence-engine** | Multi-agent error learning plugin for Claude Code — captures errors, researches root causes via parallel agents, debates findings, produces convergence reports with tasks, bridges knowledge to CLAUDE.md | Active — Phase 5b done, ready for real-project install test |
| **context-monitor** | Chrome extension for estimating token usage on claude.ai | Shelved (basic, fragile selectors) |

**Repo:** https://github.com/jonathondouglasyager-debug/claude-context-monitor (pushed 2026-02-17)

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
- **Debater:** adversarial 3-perspective analysis (Analyst + Devil's Advocate + Skeptic), optional multi-round debate (config: debate_rounds), computes disagreement metrics (debate_metrics.json)
- **Runner:** spawns `claude -p` subprocesses (sandbox mode uses mocks); propagates CLAUDE_PROJECT_DIR env var to child processes; extracts structured JSON from agent output (Phase 4)
- **Output schemas:** agents/output_schemas.py — MAST-inspired inter-agent JSON contracts; agents produce dual markdown+JSON output; extraction via ===JSON_OUTPUT=== delimiters; per-agent validators with enum constraints
- **Debate metrics:** agents/debate_metrics.py — challenge_survival_rate, skeptic_severity_score, confidence_delta, agreement_kappa; written as debate_metrics.json per issue
- **Fingerprinting:** agents/fingerprint.py — sha256({type, tool_name, error_normalized, source_file, git_branch}); dedup in dispatcher
- **Data:** JSONL with filelock (cross-process), schema validation, quarantine for corrupt records, auto-migration for Phase 2 fields
- **Data location:** {project_root}/.claude/convergence/ (decoupled from plugin install dir as of Phase 1)
- **Security:** sanitizer strips paths, tokens, JWT, API keys, usernames, env vars
- **Frontend:** Next.js 16 + React 19 + shadcn/ui dashboard (app/page.tsx)
- **Hooks:** convergence-dispatcher.py (PostToolUseFailure), convergence-synthesizer.py (SessionEnd), fingerprint-matcher.py (PreToolUse on Bash|Execute)
- **CLAUDE.md bridge:** agents/claude_md_bridge.py — writes convergence knowledge table to {project_root}/CLAUDE.md with section markers + atomic writes + filelock
- **Checkpoints:** agents/checkpoint.py — per-issue checkpoint.json in research dir; tracks phase completion + trajectory log; enables resume-from-phase + skip-if-done; verified against output files
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

### Phase 4.1 — Agent Output JSON Schemas ✅ DONE (2026-02-17)
15. ✅ agents/output_schemas.py: JSON schemas for researcher, solution_finder, impact_assessor, debater, task — with enum validation (confidence, severity, scope, frequency, priority, complexity)
16. ✅ Dual output: agents produce markdown + ===JSON_OUTPUT=== delimited JSON; runner extracts structured_output into AgentResult
17. ✅ All 4 research agents + debater write .json alongside .md files; write_research_json validates against schema before write
18. ✅ Debater consumes upstream .json files for precise cross-agent comparison; arbiter includes structured JSON in convergence context
19. ✅ Mock responses updated with valid JSON blocks; backward-compatible (graceful fallback if no JSON in output)
20. ✅ schema_validator.py: validate_research_json() validates .json files against agent schemas
21. ✅ 198/198 tests pass (152 original + 46 new schema tests)

### Phase 4.2 — Adversarial Debate Roles ✅ DONE (2026-02-17)
22. ✅ agents/debater.py: 3-perspective adversarial prompt (Analyst, Devil's Advocate, Skeptic) + optional Round 2 resolution
23. ✅ agents/debate_metrics.py: challenge_survival_rate, skeptic_severity_score, confidence_delta, agreement_kappa — written as debate_metrics.json
24. ✅ output_schemas.py: DEBATE_SCHEMA extended with devil_advocate_challenges, skeptic_concerns, confidence_after_debate, dissent_notes (backward-compatible optional fields)
25. ✅ config.py: debate_rounds setting (default: 1), debate_round2 model_map entry, get_debate_rounds() accessor
26. ✅ runner.py: updated debate mock with adversarial fields, added debate_round2 mock
27. ✅ arbiter.py: consumes debate_metrics.json in structured data context
28. ✅ Round 2 graceful degradation: falls back to Round 1 output if Round 2 agent fails
29. ✅ 244/244 tests pass (198 original + 46 new adversarial debate tests)

### Phase 4.3 — Checkpoint Architecture ✅ DONE (2026-02-17)
30. ✅ agents/checkpoint.py: per-issue checkpoint.json with phase status + trajectory log (append-only history)
31. ✅ Pipeline integration: research_single_issue checks can_skip_phase before running; save_checkpoint after each phase
32. ✅ run_full_pipeline(): orchestrates research→debate→converge with checkpoint-aware skip/resume
33. ✅ CLI: `python -m agents.pipeline run <id> [--from <phase>] [--force]` + `checkpoint <id>`
34. ✅ Arbiter trajectory: _build_issues_block includes pipeline trajectory data for analysis
35. ✅ Output file verification: can_skip_phase checks both checkpoint status AND file existence
36. ✅ 277/277 tests pass (244 original + 33 new checkpoint tests)

### Phase 5a — Plugin Portability Setup ✅ DONE (2026-02-17)
37. ✅ .claude-plugin/plugin.json: created canonical location for `claude plugin add` discovery
38. ✅ Symlink resolution: verified get_project_root() uses os.path.realpath() on all 3 branches (env var, cwd, fallback)
39. ✅ .gitignore: expanded to cover .claude/convergence/ runtime data, legacy data/convergence dirs, lock files, test artifacts
40. ✅ Removed phantom `error-learning` command from plugin.json (file never existed)
41. ✅ 277/277 tests pass

### Phase 5b — README & Final Polish ✅ DONE (2026-02-17)
42. ✅ README.md: comprehensive docs (install, usage, architecture, config, data layout, research refs)
43. ✅ Plugin structure verification: both plugin.json valid, all 3 hooks compile, commands exist, 277/277 tests pass
44. ⏳ Live hook execution test: requires `claude plugin add` on real project (manual step)

**Next:** Run `claude plugin add` on a real project, trigger a deliberate failure, confirm dispatcher captures it and data lands in `.claude/convergence/data/`.

## Critical Edge Cases (must address in Phase 4+)
- ✅ Concurrent sessions: filelock library (Phase 2)
- ✅ Schema migration: migrate_issue() auto-populates Phase 2 fields (Phase 2)
- ✅ CLAUDE.md writes: section markers + atomic write + filelock to prevent user edit loss (Phase 3)
- ✅ Corrupt markers: graceful fallback strips partial markers (Phase 3)
- ✅ Sandbox mode: bridge write skipped in sandbox mode; matcher tests use monkeypatch (Phase 3)
- ✅ Agent output format drift: strict JSON schemas between agents with per-agent validators (Phase 4.1)
- ✅ Debate quality: adversarial roles force counterargument consideration; disagreement metrics quantify robustness (Phase 4.2)
- ✅ Multi-round debate failure: graceful fallback to Round 1 output if Round 2 agent times out (Phase 4.2)
- ✅ Pipeline interruption: checkpoint + resume enables re-running from any phase without losing prior work (Phase 4.3)
- ✅ Output file integrity: can_skip_phase verifies files actually exist, not just checkpoint status (Phase 4.3)

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
