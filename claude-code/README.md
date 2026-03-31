# Claude Code Skills

Reusable skills for Claude Code that integrate external CLI agents (Gemini CLI
and Codex CLI) as advisory reviewers, debuggers, and design critics.

## Skills

### Gemini CLI Skills

| Skill | Slash Command | Description |
| --- | --- | --- |
| [gemini-review](skills/gemini-review/SKILL.md) | `/gemini-review` | Advisory code review after changes are complete |
| [gemini-error-analysis](skills/gemini-error-analysis/SKILL.md) | `/gemini-error-analysis` | Debugging second opinion for non-trivial failures |
| [gemini-design-checkpoint](skills/gemini-design-checkpoint/SKILL.md) | `/gemini-design-checkpoint` | Design critique before major technical decisions |

### Codex CLI Skills

| Skill | Slash Command | Description |
| --- | --- | --- |
| [codex-review](skills/codex-review/SKILL.md) | `/codex-review` | Advisory code review via `codex review` |
| [codex-error-analysis](skills/codex-error-analysis/SKILL.md) | `/codex-error-analysis` | Debugging second opinion via `codex exec` |
| [codex-design-checkpoint](skills/codex-design-checkpoint/SKILL.md) | `/codex-design-checkpoint` | Design critique via `codex exec` |

### Utility Skills

| Skill | Slash Command | Description |
| --- | --- | --- |
| [pitfall-notebook](skills/pitfall-notebook/SKILL.md) | `/pitfall-notebook` | Per-project pitfall memory to avoid repeating mistakes |

## Architecture

Claude Code acts as the primary agent. External CLI agents are invoked as
advisory tools via Python wrapper scripts. They never edit files or make
decisions — they provide second opinions that Claude Code evaluates.

```text
Claude Code (primary)
  ├── calls Gemini CLI (advisory only)
  │     ├── code review
  │     ├── error analysis
  │     └── design checkpoint
  └── calls Codex CLI (advisory only)
        ├── code review (codex review)
        ├── error analysis (codex exec, read-only)
        └── design checkpoint (codex exec, read-only)
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
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) installed and in PATH (for Gemini skills)
- [Codex CLI](https://github.com/openai/codex) installed and in PATH (for Codex skills)
- Python 3.10+

## Configuration

All configuration is optional. The defaults work out of the box.

| Variable | Default | Description |
| --- | --- | --- |
| `CLAUDE_GEMINI_MODEL` | `gemini-3.1-pro-preview` | Gemini model alias |
| `CLAUDE_GEMINI_SESSION_TTL_SECONDS` | `21600` | Session reuse TTL (6 hours) |
| `CLAUDE_CODEX_MODEL` | `gpt-5.4` | Codex model |

## Directory Structure

```text
claude-code/
├── README.md
├── commands/                          # Slash command sources
│   ├── gemini-review.md
│   ├── gemini-error-analysis.md
│   ├── gemini-design-checkpoint.md
│   ├── codex-review.md
│   ├── codex-error-analysis.md
│   ├── codex-design-checkpoint.md
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
    ├── codex-review/
    │   ├── SKILL.md
    │   ├── scripts/run_codex_review.py
    │   └── references/review-brief-template.md
    ├── codex-error-analysis/
    │   ├── SKILL.md
    │   ├── scripts/run_codex_error_analysis.py
    │   └── references/error-brief-template.md
    ├── codex-design-checkpoint/
    │   ├── SKILL.md
    │   ├── scripts/run_codex_design_check.py
    │   └── references/design-brief-template.md
    └── shared/
        └── scripts/
            ├── gemini_runner.py        # Shared Gemini CLI runner
            └── codex_runner.py         # Shared Codex CLI runner
```

## Design Principles

- **Advisory only.** External agents never edit files. They provide findings
  that Claude Code evaluates and acts on.
- **Bounded.** Each advisory pass runs once per change set, failure cluster, or
  decision point. No retry loops.
- **Workspace-scoped.** Agents only inspect files inside the current workspace.
  Out-of-workspace paths are ignored.
- **Read-only sandbox.** Codex CLI skills run in read-only sandbox mode.
- **Session-reusable.** The Gemini runner reuses sessions per project and lane
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
