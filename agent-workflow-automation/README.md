# Convergence Engine

A multi-agent error learning plugin for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) that captures tool failures, researches root causes via parallel agents, debates findings adversarially, and produces convergence reports with actionable tasks. Knowledge bridges to your project's `CLAUDE.md` so future sessions inherit fixes automatically.

## How It Works

When a tool fails during a Claude Code session, the plugin silently captures the error. At session end (or on demand), it runs a multi-agent pipeline:

```
Capture → Research (3 agents in parallel) → Adversarial Debate → Convergence Report
                                                                       ↓
                                                              CLAUDE.md Bridge
                                                        (cross-session learning)
```

**Capture:** The dispatcher hook intercepts tool failures, sanitizes sensitive data, computes a fingerprint for deduplication, and appends the issue to a JSONL store.

**Research:** Three agents run in parallel — a root cause researcher, a solution finder, and an impact assessor. Each produces structured JSON output validated against strict schemas.

**Debate:** An adversarial debater evaluates the research from three perspectives (Analyst, Devil's Advocate, Skeptic), stress-testing every finding. Optional multi-round debate resolves disagreements. Quantitative metrics (challenge survival rate, skeptic severity, confidence delta) measure debate quality.

**Convergence:** The arbiter synthesizes everything into a human-readable report with prioritized tasks. It also writes a compact knowledge table to your project's `CLAUDE.md`, so the next session can recognize known errors and skip re-research entirely — saving ~15-20k tokens per matched pattern.

## Installation

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI installed
- Python 3.10+
- `filelock` package: `pip install filelock`

### Local Development / Testing

Load the plugin directly with the `--plugin-dir` flag:

```bash
claude --plugin-dir /path/to/agent-workflow-automation
```

Or clone and test:

```bash
git clone https://github.com/jonathondouglasyager-debug/claude-context-monitor.git
claude --plugin-dir claude-context-monitor/agent-workflow-automation
```

### Install from a Marketplace

If published to a plugin marketplace, install with:

```bash
/plugin install claude-error-learning@marketplace-name
```

### Hooks

Hooks are defined in `hooks/hooks.json` and loaded automatically by Claude Code:

| Hook | Trigger | What It Does |
|------|---------|--------------|
| `convergence-dispatcher` | PostToolUseFailure | Captures errors, deduplicates via fingerprint |
| `fingerprint-matcher` | PreToolUse (Bash/Execute) | Warns if command matches a known error pattern |
| `convergence-synthesizer` | SessionEnd | Runs the full convergence pipeline |

### Verify

Once loaded, run `/help` — you should see `/claude-error-learning:converge` listed.

## Usage

### Automatic Mode (Default)

Just use Claude Code normally. Errors are captured silently, and convergence runs at session end when `auto_converge_on_session_end` is enabled in config.

### Manual Commands

```bash
# View captured issues
/converge log

# Research a specific issue
/converge research <issue_id>

# Run adversarial debate on researched issues
/converge debate <issue_id>

# Trigger full convergence synthesis
/converge synthesize

# Check pipeline status
/converge status

# View generated tasks
/converge tasks

# Reset all data (use with caution)
/converge reset
```

### Full Pipeline CLI

```bash
# Run the complete pipeline for an issue
python -m agents.pipeline run <issue_id>

# Resume from a specific phase
python -m agents.pipeline run <issue_id> --from debate

# Force re-run (ignore checkpoints)
python -m agents.pipeline run <issue_id> --force

# View checkpoint status
python -m agents.pipeline checkpoint <issue_id>
```

## Configuration

Edit `config.json` in the plugin root:

```json
{
  "convergence": {
    "enabled": true,
    "auto_research": true,
    "auto_converge_on_session_end": true,
    "min_issues_for_convergence": 1,
    "sandbox_mode": false,
    "budget": {
      "max_parallel_agents": 2,
      "max_tokens_per_agent": 4000,
      "timeout_seconds": 300,
      "model_map": {
        "research": "default",
        "debate": "default",
        "debate_round2": "default",
        "converge": "default"
      },
      "fallback_model": "haiku"
    },
    "debate_rounds": 1,
    "sanitizer": {
      "enabled": true,
      "strip_paths": true,
      "strip_tokens": true,
      "strip_usernames": true
    }
  }
}
```

Key settings:

- **`sandbox_mode`**: When `true`, uses mock responses instead of calling Claude. Useful for testing.
- **`debate_rounds`**: Set to `2` for multi-round adversarial debate (Round 2 resolves challenges from Round 1).
- **`max_parallel_agents`**: Number of research agents to run concurrently.
- **`model_map`**: Override models per pipeline stage (e.g., use `opus` for convergence, `haiku` for research).

## Data Storage

All runtime data lives in `{your_project}/.claude/convergence/`, not in the plugin directory:

```
.claude/convergence/
├── data/
│   ├── issues.jsonl              # Captured error records
│   ├── agent_activity.log        # Human-readable agent logs
│   ├── agent_activity.jsonl      # Machine-readable agent logs
│   └── research/
│       └── {issue_id}/
│           ├── root_cause.md     # Researcher output
│           ├── root_cause.json   # Structured researcher data
│           ├── solutions.md      # Solution finder output
│           ├── solutions.json    # Structured solution data
│           ├── impact.md         # Impact assessor output
│           ├── impact.json       # Structured impact data
│           ├── debate.md         # Adversarial debate output
│           ├── debate.json       # Structured debate data
│           ├── debate.log        # Full debate transcript
│           ├── debate_metrics.json
│           └── checkpoint.json   # Pipeline state for resume
└── convergence/
    ├── convergence.md            # Latest convergence report
    ├── tasks.json                # Prioritized task list
    └── archive/                  # Previous reports
```

## Architecture

### Agent Output Contracts

All agents produce dual output: human-readable markdown plus structured JSON delimited by `===JSON_OUTPUT===` markers. JSON is validated against per-agent schemas (see `agents/output_schemas.py`) to prevent format drift between agents — a critical failure mode in multi-agent systems.

### Fingerprinting & Deduplication

Errors are fingerprinted via SHA-256 hash of `{type, tool_name, normalized_error, source_file, git_branch}`. The normalizer strips volatile components (timestamps, UUIDs, PIDs, paths, line numbers) so the same logical error produces the same fingerprint across sessions. Duplicates increment `occurrence_count` instead of creating new records.

### CLAUDE.md Bridge

After convergence, a compact knowledge table is written to your project's `CLAUDE.md` between `<!-- convergence-engine:start -->` and `<!-- convergence-engine:end -->` markers. Each row contains the error fingerprint, pattern, root cause, fix, applicability predicate, and seen count. New Claude Code sessions read this table and can match incoming errors against known fixes without running the full pipeline.

### Security

All error context is sanitized before being sent to any LLM. The sanitizer strips file paths, API tokens (OpenAI, Anthropic, AWS, GitHub, GitLab, Slack, JWT), environment variables (DATABASE_URL, secrets, etc.), and the current system username.

### Checkpoints

The pipeline saves checkpoints after each phase (research, debate, convergence). If a session is interrupted, the next run can resume from the last completed phase. Checkpoints also verify that expected output files actually exist — status alone isn't enough.

## Testing

```bash
cd agent-workflow-automation
pip install -r requirements.txt
pytest tests/ -v
```

All 277 tests pass. Tests run in sandbox mode with mock data — no LLM calls required.

## Project Structure

```
agent-workflow-automation/
├── agents/                    # Core Python modules
│   ├── arbiter.py             # Convergence synthesis
│   ├── checkpoint.py          # Pipeline state management
│   ├── claude_md_bridge.py    # Cross-session knowledge persistence
│   ├── config.py              # Configuration + project root resolution
│   ├── debate_metrics.py      # Quantitative debate quality metrics
│   ├── debater.py             # Adversarial multi-perspective debate
│   ├── file_lock.py           # Atomic JSONL operations (filelock)
│   ├── fingerprint.py         # Error fingerprinting + dedup
│   ├── impact_assessor.py     # Severity/priority assessment
│   ├── logger.py              # Dual-output structured logging
│   ├── output_schemas.py      # Inter-agent JSON contracts
│   ├── pipeline.py            # Pipeline orchestrator
│   ├── researcher.py          # Root cause analysis
│   ├── runner.py              # Claude subprocess executor
│   ├── sanitizer.py           # Security: strip sensitive data
│   ├── schema_validator.py    # Issue record validation + migration
│   └── solution_finder.py     # Solution research
├── hooks/                     # Claude Code plugin hooks
│   ├── convergence-dispatcher.py   # PostToolUseFailure
│   ├── convergence-synthesizer.py  # SessionEnd
│   └── fingerprint-matcher.py      # PreToolUse (Bash|Execute)
├── tests/                     # 277 pytest tests
├── app/                       # Next.js dashboard (page.tsx)
├── docs/                      # Architecture + usage guides
├── commands/                  # Plugin command definitions
├── plugin.json                # Plugin manifest (v3.0.0)
├── .claude-plugin/plugin.json # Plugin discovery location
├── config.json                # Default configuration
└── requirements.txt           # Python dependencies
```

## Research Foundations

The design draws on several research insights:

- **Grove** (arxiv 2511.17833) — Hierarchical knowledge trees with applicability predicates, the model for the CLAUDE.md bridge pattern.
- **MAST** (arxiv 2503.13657) — Inter-agent misalignment as the dominant multi-agent failure mode, motivating strict JSON schema contracts between agents.
- **RedDebate** (arxiv 2511.07784) — Adversarial debate roles improve output quality, the basis for the Devil's Advocate and Skeptic perspectives.
- **AgentDebug/AgentGit** (arxiv 2509.25370) — Checkpoint and trajectory analysis for agent recovery, inspiring the checkpoint architecture.

## License

Proprietary. See LICENSE for terms.
