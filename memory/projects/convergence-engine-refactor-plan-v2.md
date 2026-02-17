# Convergence Engine Refactor Plan v2

**Date:** 2026-02-17
**Status:** APPROVED — ready for execution next session
**Previous plan:** CLAUDE.md "Active Plan (cross-session plugin refactor)" — superseded by this

---

## Research Findings Summary

### Missing Hooks Verdict
The 4 "missing" hooks (error-logger, error-curator, command-validator, fix-tracker) were **replaced** by convergence-dispatcher.py and convergence-synthesizer.py. plugin.json is simply out of sync. No new hooks need to be created for the original 4 — only plugin.json needs updating.

### Critical Edge Cases Found
1. **CWD resolution** — `os.getcwd()` unreliable mid-session; must use `CLAUDE_PROJECT_DIR` env var
2. **Concurrent session locking** — fcntl advisory locks insufficient for cross-process; consider `filelock` library
3. **Schema migration** — adding fingerprint/occurrence_count fields breaks existing issues.jsonl records
4. **CLAUDE.md race conditions** — need section markers + atomic writes to prevent user edit loss
5. **Sandbox mode** — new components (fingerprint.py, CLAUDE.md writer) need mock paths for tests

### Methodology Research Insights (Integration Candidates)
- **Grove** (hierarchical knowledge trees): applicability predicates on CLAUDE.md entries
- **MAST taxonomy**: inter-agent misalignment is dominant failure mode → strict JSON schemas between agents
- **Hybrid fingerprinting**: exact + structural levels (semantic level deferred)
- **RedDebate**: adversarial debate roles improve output quality
- **AgentDebug/AgentGit**: checkpoint architecture enables phase re-execution
- **MCP-KG-Memory**: graph-based persistent memory pattern (future tier)

---

## Execution Plan (Ordered by Dependency)

### Phase 1: Cleanup & Foundation (Session 1)

#### 1.1 Fix plugin.json hook references
- [ ] Update PostToolUseFailure to reference `convergence-dispatcher.py`
- [ ] Update SessionEnd to reference `convergence-synthesizer.py`
- [ ] Remove PreToolUse (command-validator.py) — not needed, Claude has built-in safety
- [ ] Remove PostToolUse (fix-tracker.py) — success tracking creates noise
- [ ] Update convergence-dispatcher.py comment (line 5) to remove stale "alongside error-logger" note

#### 1.2 Move misplaced React hooks
- [ ] Delete `hooks/use-mobile.tsx` and `hooks/use-toast.ts` (duplicates of components/ui/ versions)
- [ ] Verify `components/ui/toaster.tsx` imports from `@/hooks/use-toast` — update to `@/components/ui/use-toast` if needed
- [ ] Verify `components/ui/sidebar.tsx` imports from `@/hooks/use-mobile` — update similarly
- [ ] Run `pnpm build` to confirm no broken imports

#### 1.3 Data path decoupling (CRITICAL)
- [ ] Modify `agents/config.py`:
  - Replace `_PROJECT_ROOT` resolution with `get_project_root()` function
  - Priority: `CLAUDE_PROJECT_DIR` env var → `os.getcwd()` fallback → plugin root fallback
  - All path functions (get_data_dir, get_research_dir, get_convergence_dir, get_archive_dir) resolve to `{project_root}/.claude/convergence/`
  - Use `os.path.realpath()` to resolve symlinks
- [ ] Modify `hooks/convergence-dispatcher.py` lines 21-22: use config.get_project_root() instead of local resolution
- [ ] Modify `hooks/convergence-synthesizer.py`: same
- [ ] Modify `agents/runner.py` line 103: remove hardcoded `cwd=get_project_root()`, pass project dir via env var to subprocess
- [ ] Add `.claude/convergence/` directory auto-creation on first write

### Phase 2: Fingerprinting & Dedup (Session 2)

#### 2.1 Create agents/fingerprint.py
- [ ] `compute_fingerprint(issue)` — sha256 of normalized {type, tool_name, error_normalized, source_file, git_branch}
- [ ] `normalize_error_message(msg)` — strip paths, timestamps, UUIDs, hashes
- [ ] Level 1 (exact) fingerprint only for now; structural/semantic levels deferred
- [ ] Unit tests in tests/test_fingerprint.py

#### 2.2 Schema migration
- [ ] Add optional fields to schema_validator.py: fingerprint (str), occurrence_count (int), first_seen (str), last_seen (str)
- [ ] Add auto-migrate logic in `read_jsonl()`: compute fingerprint for legacy records missing it, set occurrence_count=1, set first_seen from timestamp
- [ ] Write migration function that rewrites issues.jsonl with new fields (run once)
- [ ] Update conftest.py mock data to include new fields

#### 2.3 Dedup in dispatcher
- [ ] In convergence-dispatcher.py: after creating issue, compute fingerprint
- [ ] Check existing issues for matching fingerprint
- [ ] If match: increment occurrence_count + update last_seen, skip new issue creation
- [ ] If no match: append as new issue
- [ ] Log dedup decisions to agent_activity.log

#### 2.4 Harden file locking
- [ ] Add `filelock` to requirements (pip package, mature, handles cross-process + NFS better)
- [ ] Replace fcntl usage in file_lock.py with filelock.FileLock
- [ ] Increase max retry patience: 20 retries, 2s max backoff cap
- [ ] Add test for concurrent writes (multiprocessing test)

### Phase 3: CLAUDE.md Bridge (Session 3)

#### 3.1 Arbiter CLAUDE.md writer
- [ ] After synthesize() writes convergence.md + tasks.json:
  - Generate compact summary (<50 lines)
  - Use section markers: `<!-- convergence-engine:start -->` / `<!-- convergence-engine:end -->`
  - Read existing CLAUDE.md, strip old convergence section, append new
  - Atomic write: temp file + os.replace()
  - fcntl lock on `.claude/CLAUDE.md.lock` during write
- [ ] Skip CLAUDE.md write in sandbox mode
- [ ] Content format (Grove-inspired applicability predicates):
  ```
  ## Convergence Knowledge (auto-generated)
  | Fingerprint | Error Pattern | Root Cause | Fix | Applies When |
  |---|---|---|---|---|
  | abc123... | NPE in auth | Missing null check | Add guard | auth module, login flow |
  ```
- [ ] Active P0/P1 tasks list
- [ ] Last updated timestamp

#### 3.2 Session-start pattern matcher (PreToolUse hook)
- [ ] New hook: `hooks/fingerprint-matcher.py`
- [ ] Add to plugin.json PreToolUse on `Bash|Execute`
- [ ] On error detection in PostToolUseFailure: compute fingerprint
- [ ] Check `.claude/convergence/issues.jsonl` for match
- [ ] If high-confidence match (status=converged + occurrence_count>1): inject cached solution into stderr message instead of spawning 3 research agents
- [ ] Token savings: ~15-20k per matched error

### Phase 4: Quality Improvements (Session 4, stretch)

#### 4.1 Agent output schemas (MAST-inspired)
- [ ] Define JSON schemas for each agent output:
  - researcher: `{root_cause, evidence[], confidence, dependencies[]}`
  - solution_finder: `{solution, steps[], tradeoffs[], validation_method}`
  - impact_assessor: `{severity: 0-10, affected_systems[], downstream_risks[]}`
- [ ] Add pre-debate schema validation in pipeline.py
- [ ] Reject malformed outputs with structured feedback

#### 4.2 Debate improvements (RedDebate-inspired, deferred)
- [ ] Adversarial roles: Devil's Advocate, Angel's Advocate, Skeptic
- [ ] Disagreement metrics in convergence reports
- [ ] Multi-round debate iteration
- [ ] Inter-agent Kappa scores

#### 4.3 Checkpoint architecture (AgentDebug-inspired, deferred)
- [ ] Save state after research, debate, convergence phases
- [ ] Enable re-running downstream phases without re-research
- [ ] Trajectory analysis in arbiter

### Phase 5: Plugin Portability (Session 4-5)

- [ ] Test `claude plugin add /path/to/agent-workflow-automation`
- [ ] Verify $CLAUDE_PLUGIN_ROOT resolves correctly with symlinks
- [ ] Add .gitignore: track `.claude/convergence/convergence.md`, ignore `data/`
- [ ] Document install in README
- [ ] Document data location and troubleshooting

---

## Execution Order Summary

| Session | Phase | Focus | Blocking? |
|---------|-------|-------|-----------|
| Next | 1 | Cleanup + data path decoupling | Yes — everything depends on correct paths |
| +1 | 2 | Fingerprinting + dedup + locking | Yes — saves tokens, prevents data loss |
| +2 | 3 | CLAUDE.md bridge + pattern matcher | No — additive feature |
| +3 | 4-5 | Quality + portability | No — stretch goals |

---

## Token Savings Projection (Updated)

| Scenario | Without Fingerprinting | With Fingerprinting | Savings |
|----------|----------------------|--------------------|---------|
| Same error 5x across sessions | 75-100k tokens | 15-20k (first) + 5x~500 (dedup check) | ~70-95k |
| CLAUDE.md bridge per session | 0 (no context) | ~500-1000 tokens | Enables continuity |
| Pattern matcher short-circuit | 15-20k per re-research | ~200 tokens (fingerprint check) | ~15-19k per match |

---

## Risk Register

| Risk | Severity | Mitigation |
|------|----------|------------|
| CLAUDE_PROJECT_DIR env var not set by Claude Code | Critical | Fallback chain: env var → getcwd → plugin root |
| filelock pip dependency not available | Medium | Keep fcntl as fallback, document pip install |
| Fingerprint false positives (dedup wrong error) | Medium | Multi-field hash, log dedup decisions, manual override via /converge reset |
| CLAUDE.md section markers corrupted by user edit | Low | Graceful fallback: append new section if markers missing |
| Large issues.jsonl (>10k records) | Low | Archive converged issues >30 days old (Phase 4) |

---

## Future Tier — Revisit Once Phases 1-3 Are Solid

### MCP-KG-Memory Integration
Wrap convergence knowledge as an MCP server so other tools (Cursor, Windsurf, etc.) can query it. Graph-based persistent memory instead of flat CLAUDE.md. **Do not start until:** Phase 3 CLAUDE.md bridge is working and validated across 5+ real sessions. The flat bridge has to prove its value before adding graph complexity.

### Integration Candidates Parking Lot
These were surfaced during methodology research (2026-02-17). Each has a specific phase where it applies, but none are blocking:

| Candidate | What It Does | Where It Fits | Revisit When |
|-----------|-------------|---------------|--------------|
| **Grove applicability predicates** | "When does this fix apply?" conditions on CLAUDE.md entries | Phase 3 (arbiter writer) | Phase 3 begins |
| **MAST agent output schemas** | Strict JSON contracts between agents to prevent misinterpretation | Phase 4.1 | Pipeline runs 10+ real issues without schema |
| **RedDebate adversarial roles** | Devil's Advocate / Skeptic roles in debate step | Phase 4.2 | Debater produces 5+ real debate outputs to baseline against |
| **AgentDebug checkpoints** | Save state between pipeline phases, re-run from midpoint | Phase 4.3 | Pipeline fails mid-run and requires full re-research |
| **Hybrid fingerprinting (structural/semantic)** | LSH + embeddings for fuzzy error matching beyond exact hash | Phase 2 extension | Exact fingerprinting misses obvious duplicates in practice |
| **MCP-KG-Memory** | Graph-based cross-tool knowledge persistence | New phase | Phases 1-3 stable, cross-tool need demonstrated |

**Principle:** Each candidate earns its way in by solving a problem we actually hit, not a problem we imagine.
