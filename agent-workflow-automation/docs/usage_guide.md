# Agent Workflow Automation - Usage Guide

This guide explains how to use the Agent Workflow Automation system to capture issues, run multi-agent research, and generate actionable tasks.

## 1. Quick Start (Slash Commands)

The project includes custom commands (defined in `plugin.json`) to control the workflow directly from your chat interface.

| Command | Description | Usage |
|:---|:---|:---|
| `/converge` | Main interface for the Convergence Engine | `/converge [action]` |
| `/converge log` | Manually capture an issue from the current conversation | `/converge log "Description of the issue"` |
| `/converge research` | Run the research agents on a specific issue | `/converge research [issue_id]` |
| `/converge status` | Check the status of the pipeline | `/converge status` |

## 2. Real-World Workflow

### Scenario: Debugging a Complex Bug

Imagine you are working on a feature and encounter a difficult bug (e.g., "Memory leak in data processor").

1.  **Capture the Issue**:
    Instead of switching context or losing track, simply log it:
    ```
    /converge log "Memory leak in data processor when handling >1GB files. Suspect circular reference in caching layer."
    ```
    *Result*: The system creates an issue record (e.g., `issue_20240101_123`) in `data/issues.jsonl`.

2.  **Trigger Research (Automatic or Manual)**:
    The system can be configured to auto-research, or you can trigger it manually:
    ```
    /converge research issue_20240101_123
    ```
    *Behind the Scenes*:
    - **Researcher Agent**: Digs into the code to find the root cause.
    - **Solution Finder**: Proposes multiple fix options (Quick vs. Robust).
    - **Impact Assessor**: Estimates the blast radius of the bug/fix.

3.  **Cross-Agent Debate**:
    The agents then "debate" their findings to verify assumptions. They check if the proposed solution actually addresses the root cause and if the impact assessment is realistic.

4.  **Convergence & Tasks**:
    The **Arbiter** agent synthesizes everything into a **Convergence Report** and generates a list of prioritized tasks.

5.  **View Results**:
    Open the dashboard to see the full analysis and task list:
    ```
    pnpm dev
    ```
    Visit: http://localhost:3000

## 3. Configuration

Adjust the agent behavior in `config.json`:

- **`convergence.budget.max_parallel_agents`**: Control how many agents run at once.
- **`convergence.budget.timeout_seconds`**: Increase this for complex codebases (default: 60s, recommended: 300s).
- **`convergence.sandbox_mode`**: Set to `true` to test the pipeline without making real LLM calls (useful for demos).

## 4. Integration via Hooks

The system is designed to run automatically via Claude Plugin hooks:

- **`PostToolUseFailure`**: If a tool execution fails (e.g., a test fails or a script errors), the system automatically:
    1.  Logs the error.
    2.  Checks if it matches a known pattern.
    3.  Captures an issue if it's new.
    4.  Triggers research (if `auto_research` is enabled).

This means you can have the agents working in the background *while* you continue coding.
