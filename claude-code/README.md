# Claude Code Skills

Reusable skills for Claude Code that integrate external CLI agents (Gemini CLI,
Antigravity CLI, and Codex CLI) as advisory reviewers, debuggers, and design critics.

## Skills

### Gemini CLI Skills

| Skill | Slash Command | Description |
| --- | --- | --- |
| [gemini-review](skills/gemini-review/SKILL.md) | `/gemini-review` | Advisory code review after changes are complete |
| [gemini-error-analysis](skills/gemini-error-analysis/SKILL.md) | `/gemini-error-analysis` | Debugging second opinion for non-trivial failures |
| [gemini-design-checkpoint](skills/gemini-design-checkpoint/SKILL.md) | `/gemini-design-checkpoint` | Design critique before major technical decisions |

### Antigravity CLI Skills

| Skill | Slash Command | Description |
| --- | --- | --- |
| [agy-review](skills/agy-review/SKILL.md) | `/agy-review` | Advisory code review via Antigravity CLI |
| [agy-error-analysis](skills/agy-error-analysis/SKILL.md) | `/agy-error-analysis` | Debugging second opinion via Antigravity CLI |
| [agy-design-checkpoint](skills/agy-design-checkpoint/SKILL.md) | `/agy-design-checkpoint` | Design critique via Antigravity CLI |

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
  ├── calls Antigravity CLI (advisory only)
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
- Antigravity CLI `agy` installed and in PATH (for Antigravity skills)
- [Codex CLI](https://github.com/openai/codex) installed and in PATH (for Codex skills)
- Python 3.10+

## Configuration

All configuration is optional. The defaults work out of the box.

| Variable | Default | Description |
| --- | --- | --- |
| `CLAUDE_GEMINI_MODEL` | `gemini-3.1-pro-preview` | Gemini model alias |
| `CLAUDE_GEMINI_CONTINUATION_RETRIES` | `0` | Bounded same-session continuation retries after Gemini exits or times out without a final answer |
| `CLAUDE_AGY_CMD` | `agy` | Antigravity CLI command or wrapper |
| `CLAUDE_AGY_MODE` | `print` | Antigravity prompt mode: `print` for `agy -p`, `interactive` for `agy -i` |
| `CLAUDE_AGY_CONFIG` | `~/.claude/agy_cli.json` | Optional Antigravity CLI config JSON path |
| `CLAUDE_AGY_MODEL` | `Gemini 3.5 Flash (High)` | Antigravity model passed through `--model` when supported. Supported: `Gemini 3.5 Flash (High)`, `Gemini 3.1 Pro (High)`, `Claude Sonnet 4.6 (Thinking)`, `Claude Opus 4.6 (Thinking)` |
| `CLAUDE_AGY_PRINT_TIMEOUT` | `1200s` | Antigravity print-mode timeout passed to `agy` when supported |
| `CLAUDE_AGY_AUTH_RETRIES` | `5` | Relaunch count for transient `E... not logged into Antigravity` CLI log failures |
| `CLAUDE_AGY_DANGEROUSLY_SKIP_PERMISSIONS` | `true` | Auto-approve Antigravity CLI tool permissions when supported |
| `CLAUDE_CODEX_MODEL` | `gpt-5.4` | Codex model |

The Antigravity integration has been smoke-tested with Antigravity CLI `agy` version `1.0.7`. After upgrading `agy`, re-run the local tests and both print and interactive advisory smoke tests because prompt-mode flags, log wording, or transcript layout may change. If `agy` is not on `PATH`, set `CLAUDE_AGY_CMD=~/.local/bin/agy` or put `"command": "~/.local/bin/agy"` in `~/.claude/agy_cli.json`.

## Directory Structure

```text
claude-code/
├── README.md
├── commands/                          # Slash command sources
│   ├── gemini-review.md
│   ├── gemini-error-analysis.md
│   ├── gemini-design-checkpoint.md
│   ├── agy-review.md
│   ├── agy-error-analysis.md
│   ├── agy-design-checkpoint.md
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
    ├── agy-review/
    │   ├── SKILL.md
    │   ├── scripts/run_agy_review.py
    │   └── references/review-brief-template.md
    ├── agy-error-analysis/
    │   ├── SKILL.md
    │   ├── scripts/run_agy_error_analysis.py
    │   └── references/error-brief-template.md
    ├── agy-design-checkpoint/
    │   ├── SKILL.md
    │   ├── scripts/run_agy_design_check.py
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
```

The Antigravity, Gemini CLI, and Codex CLI runner implementations live once in
`../common/scripts`. The scripts under `skills/*/scripts` are runtime adapters
that locate those common runners.

## Design Principles

- **Advisory only.** External agents never edit files. They provide findings
  that Claude Code evaluates and acts on.
- **Bounded.** Each advisory pass runs once per change set, failure cluster, or
  decision point. Only transient Antigravity login-state failures use a bounded
  relaunch loop.
- **Workspace-scoped.** Agents only inspect files inside the current workspace.
  Out-of-workspace paths are ignored.
- **Read-only sandbox.** Codex CLI skills run in read-only sandbox mode.
- **Fresh interactive sessions.** Gemini advisory passes start fresh and
  use an explicit `--session-id <uuid>` for each advisory run to avoid
  stale-context contamination and concurrent prompt-matching races.
- **Configurable Antigravity prompt mode.** Antigravity advisory passes default
  to `agy -p`, can switch to `agy -i` with `CLAUDE_AGY_MODE=interactive` or
  `"mode": "interactive"` in `~/.claude/agy_cli.json`, pass
  `--model "Gemini 3.5 Flash (High)"` by default when supported, and pass
  extra multi-project roots through repeatable `--add-dir` flags. Transient
  `E... not logged into Antigravity` failures are relaunched up to 5 times by
  default, with matching `W...` and `E...` log lines printed for diagnosis.

## Differences from Codex Version

This is adapted from the [Codex skills](../codex/). Key differences:

| Aspect | Codex | Claude Code |
| --- | --- | --- |
| Skill registration | `agents/openai.yaml` | `.claude/commands/*.md` slash commands |
| Workspace detection | `AGENTS.md` | `CLAUDE.md` (falls back to `AGENTS.md`) |
| Env var prefix | `CODEX_GEMINI_*` | `CLAUDE_GEMINI_*` |
| Antigravity env var prefix | `CODEX_AGY_*` | `CLAUDE_AGY_*` |
| Pitfall file | `.codex-pitfalls.md` | `.claude-pitfalls.md` |
