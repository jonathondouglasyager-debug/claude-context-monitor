# claude-context-monitor

This repository contains two projects:

## Convergence Engine (Active)

A multi-agent error learning plugin for Claude Code. Located in [`agent-workflow-automation/`](agent-workflow-automation/).

**What it does:**
- Captures tool failures during Claude Code sessions
- Researches root causes using parallel agents
- Debates findings adversarially for accuracy
- Writes validated knowledge back to CLAUDE.md for cross-session learning

See the full documentation in [`agent-workflow-automation/README.md`](agent-workflow-automation/README.md).

## Chrome Extension (Archived)

A Chrome extension for monitoring Claude.ai token usage. This project is **shelved** — the files at the repo root (`background.js`, `content.js`, `popup.html`, etc.) are from this extension and are no longer actively maintained.

## License

MIT — see [LICENSE](LICENSE).
