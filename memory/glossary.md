# Glossary

## Project Terms
| Term | Meaning | Context |
|------|---------|---------|
| convergence | Final synthesis where all agent findings merge into one report + task list | agents/arbiter.py |
| arbiter | Agent that produces the convergence report | Stage 4 of pipeline |
| debater | Agent that critiques findings across researcher, solution_finder, and impact_assessor | Stage 3 |
| fingerprint | Hash of error signature for cross-session dedup | Planned feature |
| CLAUDE.md bridge | Writing compact knowledge to CLAUDE.md so new sessions inherit it automatically | Key cross-session mechanism |
| sandbox mode | Mock responses instead of real LLM calls, for testing | config.json: sandbox_mode=true |
| quarantine | Where corrupt/invalid issue records go | data/quarantine.jsonl |
| atomic append | JSONL write with fcntl locking + fsync | agents/file_lock.py |

## Pipeline Statuses
| Status | Meaning |
|--------|---------|
| captured | Issue logged, no research yet |
| researching | Agents dispatched |
| researched | At least one agent completed |
| debating | Debate agent running |
| debated | Debate complete |
| converging | Arbiter running |
| converged | In convergence report |
| resolved | Fixed by developer |
| quarantined | Corrupt record isolated |

## File Conventions
| Pattern | Meaning |
|---------|---------|
| .jsonl | Newline-delimited JSON (one record per line) |
| .lock | Sidecar file for fcntl locking |
| data/research/{id}/ | Per-issue research outputs (root_cause.md, solutions.md, impact.md, debate.md) |
| convergence/archive/ | Timestamped previous convergence reports |
