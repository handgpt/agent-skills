# Codex Skills

Reusable Codex skills and install helpers for Gemini-based advisory checkpoints.

This directory is the Codex-specific product line inside the larger
`agent-skills` repository. Everything needed for Codex lives under `codex/`.

## Layout

```text
agent-skills/codex/
├── skills/
│   ├── gemini-design-checkpoint/
│   ├── gemini-error-analysis/
│   ├── gemini-review/
│   ├── pitfall-notebook/
│   └── shared/
├── templates/
│   └── home-AGENTS.snippet.md
├── tests/
│   ├── test_gemini_runner.py
│   └── test_pitfall_notebook.py
└── scripts/
    └── install.sh
```

## Included skills

- `gemini-design-checkpoint`
  Use before major technical design decisions. The skill asks Gemini for a concise second opinion on architecture, protocol, repo layout, migration, and other high-impact choices, with explicit best-practice checks across both the whole design and the module boundaries, grounded in official docs and community experience when relevant.
- `gemini-error-analysis`
  Use when Codex is stuck on a non-trivial failure after an initial local inspection. The skill asks Gemini to reason about likely causes, separate code logic from environmental issues, and suggest the highest-signal next checks.
- `pitfall-notebook`
  Use to maintain a concise per-project markdown notebook of previously fixed pitfalls. Codex should read it before non-trivial implementation or review work and update it after successfully fixing a meaningful blocker.
- `gemini-review`
  Use after meaningful code changes and before the final response. The skill asks Gemini for a concise advisory review focused on bugs, regressions, missing tests, risky assumptions, unused code, and safe simplification opportunities. At important checkpoints it also supports a structural mode that inspects code structure, module boundaries, and cross-module design risks.

The Gemini skills are advisory only. They do not modify files and they are designed to fail open: if Gemini is unavailable or times out, Codex continues normally.

`pitfall-notebook` is intentionally different: it updates a project-local `.codex-pitfalls.md` memory file after a meaningful error is successfully fixed.

When the matching `AGENTS.md` rules are installed, Codex should run these advisory passes automatically at the relevant checkpoints. The user does not need to explicitly request Gemini on each turn.

The wrappers pass local file and directory paths to Gemini so it can inspect the workspace directly on disk instead of receiving large pasted file bodies.

They launch Gemini from the current project root in full-access mode via `--approval-mode yolo` plus `GEMINI_SANDBOX=false`, send the fully assembled advisory prompt inline, reuse the most recent saved Gemini session for the same project and advisory lane when available, and restrict Gemini review context to workspace-local files and directories only.

By default, the shared runner now uses the interactive Gemini CLI path: it opens `gemini -i "<prompt>"` under a PTY, watches the project-local Gemini session file under `~/.gemini/tmp/<project>/chats/`, and extracts the final advisory when the recorded turn becomes stable. This keeps the advisory flow closer to a human interactive session while still allowing Codex to automate startup, waiting, extraction, and shutdown.

The previous headless non-interactive path is still kept in code for comparison and rollback. Switch between the two with `--runner-mode interactive|headless` or `CODEX_GEMINI_RUN_MODE=interactive|headless`.

`--context-file` entries are treated as priority starting points rather than a hard sandbox or an exhaustive file list. Gemini runs from the project root and may inspect other workspace-local files when the brief requires it.

By default, the shared Gemini runner uses Gemini CLI's stable `pro` alias via `--model pro` so these skills prefer the latest Pro-class model without hard-coding a short-lived version string. Set `CODEX_GEMINI_MODEL` if you need to override that default.

If the pitfall notebook is personal agent memory rather than shared team knowledge, projects should ignore `.codex-pitfalls.md`.

Codex should treat the full Gemini wrapper timeout window as expected runtime. With the current defaults, a Gemini advisory run may stay quiet for up to 20 minutes without that implying failure.

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
- `tests/` provides focused coverage for the shared Gemini runner helpers and the
  pitfall notebook updater.
- `scripts/install.sh` is the supported way to install or refresh the Codex
  runtime assets locally.
- The install script intentionally preserves the legacy home-level marker names
  so an upgraded installation can replace an older `AGENTS.md` block cleanly.

## Notes

- `skills/` is the source of truth for Git sharing inside the Codex runtime.
- `~/.codex/skills` is the runtime install location used by Codex.
- The home-level `AGENTS.md` rules only apply to projects started under your home directory tree.
- Restart Codex after installing or updating skills so the runtime skill list refreshes.
