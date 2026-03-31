# Claude Code Skills

Reusable skills for Claude Code that integrate Gemini CLI as an external advisory
reviewer, debugger, and design critic.

## Skills

| Skill | Slash Command | Description |
| --- | --- | --- |
| [gemini-review](skills/gemini-review/SKILL.md) | `/gemini-review` | Advisory code review after changes are complete |
| [gemini-error-analysis](skills/gemini-error-analysis/SKILL.md) | `/gemini-error-analysis` | Debugging second opinion for non-trivial failures |
| [gemini-design-checkpoint](skills/gemini-design-checkpoint/SKILL.md) | `/gemini-design-checkpoint` | Design critique before major technical decisions |
| [pitfall-notebook](skills/pitfall-notebook/SKILL.md) | `/pitfall-notebook` | Per-project pitfall memory to avoid repeating mistakes |

## Architecture

Claude Code acts as the primary agent. Gemini CLI is invoked as an external
advisory tool via Python wrapper scripts. Gemini never edits files or makes
decisions — it provides a second opinion that Claude Code evaluates.

```text
Claude Code (primary)
  └── calls Gemini CLI (advisory only)
        ├── code review
        ├── error analysis
        └── design checkpoint
```

The pitfall notebook is purely local — it reads and writes a project-local
markdown file to remember mistakes across sessions.

## Installation

### Quick Install

```bash
cd /path/to/your/project
bash /path/to/agent-skills/claude-code/scripts/install.sh
```

This copies the slash command `.md` files into your project's
`.claude/commands/` directory and resolves script paths.

### Manual Install

Copy the command files from `commands/` into your project's
`.claude/commands/` directory, then update the `$AGENT_SKILLS_DIR` paths
in each command to point to the `agent-skills` directory.

## Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) installed and in PATH
- Python 3.10+

## Configuration

All configuration is optional. The defaults work out of the box.

| Variable | Default | Description |
| --- | --- | --- |
| `CLAUDE_GEMINI_MODEL` | `pro` | Gemini model alias |
| `CLAUDE_GEMINI_RUN_MODE` | `interactive` | `interactive` or `headless` |
| `CLAUDE_GEMINI_SESSION_TTL_SECONDS` | `21600` | Session reuse TTL (6 hours) |

## Directory Structure

```text
claude-code/
├── README.md
├── commands/                          # Slash command sources
│   ├── gemini-review.md
│   ├── gemini-error-analysis.md
│   ├── gemini-design-checkpoint.md
│   └── pitfall-notebook.md
├── scripts/
│   └── install.sh                     # Install helper
└── skills/
    ├── gemini-review/
    │   ├── SKILL.md
    │   ├── scripts/run_gemini_review.py
    │   └── references/review-brief-template.md
    ├── gemini-error-analysis/
    │   ├── SKILL.md
    │   ├── scripts/run_gemini_error_analysis.py
    │   └── references/error-brief-template.md
    ├── gemini-design-checkpoint/
    │   ├── SKILL.md
    │   ├── scripts/run_gemini_design_check.py
    │   └── references/design-brief-template.md
    ├── pitfall-notebook/
    │   ├── SKILL.md
    │   ├── scripts/update_pitfall_notebook.py
    │   └── references/pitfall-entry-template.md
    └── shared/
        └── scripts/gemini_runner.py   # Shared Gemini CLI runner
```

## Design Principles

- **Advisory only.** Gemini never edits files. It provides findings that Claude
  Code evaluates and acts on.
- **Bounded.** Each advisory pass runs once per change set, failure cluster, or
  decision point. No retry loops.
- **Workspace-scoped.** Gemini only inspects files inside the current workspace.
  Out-of-workspace paths are ignored.
- **Session-reusable.** The runner reuses Gemini sessions per project and lane
  to maintain context across related advisory passes.

## Differences from Codex Version

This is adapted from the [Codex skills](../codex/). Key differences:

| Aspect | Codex | Claude Code |
| --- | --- | --- |
| Skill registration | `agents/openai.yaml` | `.claude/commands/*.md` slash commands |
| Workspace detection | `AGENTS.md` | `CLAUDE.md` (falls back to `AGENTS.md`) |
| Env var prefix | `CODEX_GEMINI_*` | `CLAUDE_GEMINI_*` |
| Pitfall file | `.codex-pitfalls.md` | `.claude-pitfalls.md` |
| Session state | `codex-lane-sessions.json` | `claude-lane-sessions.json` |
