# Codex Skills

Reusable Codex skills and install helpers for external advisory checkpoints.

This directory is the Codex-specific product line inside the larger
`agent-skills` repository. Runtime-specific assets live under `codex/`;
shared runner source lives under the repository-level `common/` directory and
is copied into the Codex runtime during install.

## Layout

```text
agent-skills/codex/
├── skills/
│   ├── agy-design-checkpoint/
│   ├── agy-error-analysis/
│   ├── agy-review/
│   └── pitfall-notebook/
├── templates/
│   └── home-AGENTS.snippet.md
├── tests/
│   ├── test_agy_runner.py
│   ├── test_agy_review_prompt.py
│   ├── test_advisory_common.py
│   └── test_pitfall_notebook.py
└── scripts/
    └── install.sh
```

## Included skills

- `agy-design-checkpoint`
  Use before major technical design decisions. The skill asks Antigravity CLI for a concise second opinion on architecture, protocol, repo layout, migration, and other high-impact choices, with explicit best-practice checks across both the whole design and the module boundaries, grounded in official docs and community experience when relevant.
- `agy-error-analysis`
  Use when Codex is stuck on a non-trivial failure after an initial local inspection. The skill asks Antigravity CLI to reason about likely causes, separate code logic from environmental issues, and suggest the highest-signal next checks.
- `agy-review`
  Use after meaningful code changes and before the final response. The skill asks Antigravity CLI for a concise advisory review focused on bugs, regressions, missing tests, risky assumptions, unused code, and safe simplification opportunities. At important checkpoints it also supports a structural mode that inspects code structure, module boundaries, and cross-module design risks.
- `pitfall-notebook`
  Use to maintain a concise per-project markdown notebook of previously fixed pitfalls. Codex should read it before non-trivial implementation or review work and update it after successfully fixing a meaningful blocker.

The Antigravity skills are advisory only. They do not modify files and they are designed to fail open: if Antigravity CLI is unavailable or times out, Codex continues normally.

Antigravity CLI (`agy`) is now the default Codex external advisory path. The skills pass `--model "Gemini 3.5 Flash (High)"` by default when the installed `agy` exposes `--model`. The currently supported override values are `Gemini 3.5 Flash (High)`, `Gemini 3.1 Pro (High)`, `Claude Sonnet 4.6 (Thinking)`, and `Claude Opus 4.6 (Thinking)`. The old Codex Gemini advisory skills were removed because Gemini CLI is expected to go offline in June 2026. Migrate any `$gemini-*` workflow to `$agy-design-checkpoint`, `$agy-error-analysis`, or `$agy-review` as soon as possible.

This implementation has been smoke-tested with Antigravity CLI `agy` version `1.0.7`. After upgrading `agy`, re-run the Codex tests and at least one advisory smoke test because prompt-mode flags, log wording, or transcript layout may change.

`pitfall-notebook` is intentionally different: it updates a project-local `.codex-pitfalls.md` memory file after a meaningful error is successfully fixed.

When the matching `AGENTS.md` rules are installed, Codex should run these advisory passes automatically at the relevant checkpoints. The user does not need to explicitly request the external reviewer on each turn.

The wrappers pass local file and directory paths to the external reviewer so it can inspect the workspace directly on disk instead of receiving large pasted file bodies.

The Antigravity runner launches from the same single-project or multi-project workspace root. By default it uses interactive prompt mode, `agy -i "<prompt>"`; set `CODEX_AGY_MODE=print` or `"mode": "print"` in `~/.codex/agy_cli.json` to use `agy -p "<prompt>"`. In both modes it sets an explicit Antigravity CLI log file when supported, reads the matching transcript under `~/.gemini/antigravity-cli/brain/<conversation>/.system_generated/logs/transcript.jsonl` as a fallback to stdout, and prints progress from transcript records while waiting.

If the Antigravity CLI log reports `E... You are not logged into Antigravity`, the runner treats that as a transient login failure, prints matching `W...` and `E...` log lines, and relaunches `agy` up to 5 times by default.

Use `~/.codex/agy_cli.json` to switch modes or models without editing skill code:

```json
{
  "mode": "interactive",
  "command": "agy",
  "model": "Gemini 3.5 Flash (High)",
  "print_timeout": "1200s",
  "auth_retries": 5,
  "dangerously_skip_permissions": true
}
```

If `agy` is not on `PATH`, set `"command": "~/.local/bin/agy"` or export `CODEX_AGY_CMD=~/.local/bin/agy`. Environment variables override the config file: `CODEX_AGY_MODE`, `CODEX_AGY_CMD`, `CODEX_AGY_CONFIG`, `CODEX_AGY_MODEL`, `CODEX_AGY_PRINT_TIMEOUT`, `CODEX_AGY_AUTH_RETRIES`, and `CODEX_AGY_DANGEROUSLY_SKIP_PERMISSIONS`.

`--context-file` entries are treated as priority starting points rather than a hard sandbox or an exhaustive file list. The external reviewer runs from the selected workspace root and may inspect other workspace-local files when the brief requires it.

When one advisory must intentionally cover multiple projects, repeat `--project-root` for each target project root. The runner resolves those roots inside the current Codex workspace, switches the external reviewer's `cwd` to their common ancestor inside that workspace, passes the other existing project roots with `--add-dir` when supported, and lists each project explicitly in the prompt with a project-scope key.

The runner resolves `CODEX_AGY_CMD` or the config `command` first, then tries `agy` on `PATH`, and finally checks `~/.local/bin/agy` when the command is the default `agy`. Set `CODEX_AGY_PRINT_TIMEOUT` only if you need to override the print-mode timeout passed to Antigravity CLI when supported.

If the pitfall notebook is personal agent memory rather than shared team knowledge, projects should ignore `.codex-pitfalls.md`.

Codex should treat the full external wrapper timeout window as expected runtime. With the current defaults, Antigravity advisory runs may stay quiet for up to 20 minutes without that implying failure.

## Install

From `agent-skills/codex`, install the skills into `~/.codex/skills`:

```bash
./scripts/install.sh
```

From the repository root, the equivalent command is:

```bash
./codex/scripts/install.sh
```

Install the skills and append the home-level AGENTS rules under `~/AGENTS.md`:

```bash
./scripts/install.sh --install-home-agents
```

## Development Notes

- `skills/` contains the Codex runtime source of truth.
- `../common/scripts/` contains the shared Antigravity, Codex CLI, and Gemini CLI
  runner implementation used across runtimes.
- `tests/` provides focused coverage for the shared Antigravity runner helpers and the
  pitfall notebook updater.
- `scripts/install.sh` is the supported way to install or refresh the Codex
  runtime assets locally. It copies `../common/scripts` to
  `~/.codex/skills/shared/scripts` so installed Codex skills remain
  self-contained.
- The install script writes Antigravity home-level markers and also removes the older
  Gemini marker block during upgrades.

## Notes

- `skills/` plus `../common/scripts` are the source of truth for Git sharing inside the Codex runtime.
- `~/.codex/skills` is the runtime install location used by Codex.
- The home-level `AGENTS.md` rules only apply to projects started under your home directory tree.
- Restart Codex after installing or updating skills so the runtime skill list refreshes.
