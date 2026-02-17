# /converge -- Convergence Engine Command

The `/converge` command manages the issue convergence pipeline. It captures issues,
dispatches research agents, runs cross-agent debate, and produces convergence reports
with actionable tasks.

## Usage

### Quick Reference

| Command | Description |
|---------|-------------|
| `/converge` | Show convergence doc summary (or status if none exists) |
| `/converge log "description"` | Manually capture an issue |
| `/converge research [issue_id]` | Research a specific issue or all unresearched |
| `/converge debate [issue_id]` | Run debate on a researched issue or all eligible |
| `/converge synthesize` | Generate/update the convergence doc |
| `/converge status` | Show pipeline status counts |
| `/converge tasks` | List tasks from convergence |
| `/converge doc` | Display full convergence.md |
| `/converge reset` | Archive everything and start fresh |

## Detailed Actions

### `/converge` (no arguments)

Show a quick summary. If a convergence.md exists, display its Session Summary section.
Otherwise, show pipeline status.

### `/converge log "description"`

Manually capture an issue without waiting for an error to trigger the hook.

**Implementation:** Run this Python script:
```bash
python3 -c "
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath('$0'))))
from agents.config import get_data_dir
from agents.file_lock import atomic_append
from agents.schema_validator import make_issue_id
from agents.sanitizer import sanitize_record
from datetime import datetime, timezone

description = '''$ARGUMENTS'''
issue_id = make_issue_id()
issue = {
    'id': issue_id,
    'type': 'manual',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'description': description,
    'status': 'captured',
    'source': 'manual:/converge log',
    'tool_name': 'manual',
    'git_branch': 'unknown',
    'recent_files': [],
    'working_directory': os.getcwd(),
    'raw_error': description,
}
sanitized = sanitize_record(issue)
issues_path = os.path.join(get_data_dir(), 'issues.jsonl')
os.makedirs(get_data_dir(), exist_ok=True)
atomic_append(issues_path, sanitized)
print(f'Issue captured: {issue_id}')
print(f'Description: {description}')
print(f'Status: captured')
print(f'Run /converge research {issue_id} to investigate.')
"
```

Alternatively, you can directly create and append the issue record to `data/issues.jsonl`
using the same schema:

```json
{
  "id": "issue_YYYYMMDD_HHMMSS_xxxx",
  "type": "manual",
  "timestamp": "ISO8601",
  "description": "user's description",
  "status": "captured",
  "source": "manual:/converge log",
  "tool_name": "manual",
  "git_branch": "current branch",
  "recent_files": [],
  "working_directory": "cwd",
  "raw_error": "user's description"
}
```

### `/converge research [issue_id]`

Run the research pipeline on an issue (or all unresearched issues).

**Implementation:** Run:
```bash
# Specific issue:
python3 -m agents.pipeline research <issue_id>

# All unresearched:
python3 -m agents.pipeline research-all
```

This dispatches three agents (researcher, solution_finder, impact_assessor),
with researcher and solution_finder running in parallel, then impact_assessor.

Report the results: which agents succeeded, what they found (summarize key findings).

### `/converge debate [issue_id]`

Run the cross-agent debate on a researched issue.

**Implementation:** Run:
```bash
python3 -m agents.debater <issue_id>
```

Report: Summarize the debate findings -- agreements, contradictions, gaps, and revised assessment.

### `/converge synthesize`

Generate the convergence report and task list from all debated/researched issues.

**Implementation:** Run:
```bash
python3 -m agents.arbiter
```

This archives previous convergence docs, synthesizes all findings, and produces:
- `convergence/convergence.md` -- The convergence report
- `convergence/tasks.json` -- Actionable tasks

Report: Display the convergence report summary and task count.

### `/converge status`

Show pipeline status.

**Implementation:** Run:
```bash
python3 -m agents.pipeline status
```

Display the output as a formatted summary:
```
Pipeline Status:
  Captured:  N (awaiting research)
  Researched: N (awaiting debate)
  Debated:   N (awaiting convergence)
  Converged: N (in convergence doc)
  Resolved:  N
  Total:     N
```

### `/converge tasks`

Display tasks from the convergence.

**Implementation:** Read and display `convergence/tasks.json`. Format each task as:
```
[P1] Task Title (complexity: medium)
  Description: ...
  Files: file1.ts, file2.ts
  Approach: ...
  Status: pending
```

### `/converge doc`

Display the full convergence report.

**Implementation:** Read and display `convergence/convergence.md`.

### `/converge reset`

Archive everything and start fresh.

**Implementation:**
1. Archive `convergence/convergence.md` and `convergence/tasks.json` to `convergence/archive/`
2. Archive `data/issues.jsonl` to `data/archive/issues_TIMESTAMP.jsonl`
3. Create fresh empty `data/issues.jsonl`
4. Report what was archived

## Full Pipeline Shortcut

To run the complete pipeline on all captured issues:

```
/converge research      # Research all unresearched
/converge debate        # Debate all researched (run per-issue)
/converge synthesize    # Produce convergence doc
```

Or describe what you want and Claude will orchestrate the right steps.
