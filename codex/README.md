# Codex Skills

Reusable Codex skills and install helpers for external advisory checkpoints.

This directory is the Codex-specific product line inside the larger
`agent-skills` repository. Everything needed for Codex lives under `codex/`.

## Layout

```text
agent-skills/codex/
├── skills/
│   ├── gemini-design-checkpoint/
│   ├── gemini-error-analysis/
│   ├── gemini-review/
│   ├── agy-design-checkpoint/
│   ├── agy-error-analysis/
│   ├── agy-review/
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
- `agy-design-checkpoint`, `agy-error-analysis`, `agy-review`
  Antigravity CLI equivalents of the Gemini advisory checkpoints. They run through `agy -p` print mode and intentionally do not pass a model flag because Antigravity currently selects the model itself.

The Gemini and Antigravity skills are advisory only. They do not modify files and they are designed to fail open: if the external CLI is unavailable or times out, Codex continues normally.

`pitfall-notebook` is intentionally different: it updates a project-local `.codex-pitfalls.md` memory file after a meaningful error is successfully fixed.

When the matching `AGENTS.md` rules are installed, Codex should run these advisory passes automatically at the relevant checkpoints. The user does not need to explicitly request the external reviewer on each turn.

The wrappers pass local file and directory paths to the external reviewer so it can inspect the workspace directly on disk instead of receiving large pasted file bodies.

They launch Gemini from the current single-project or multi-project workspace root in full-access mode via `--approval-mode yolo` plus `GEMINI_SANDBOX=false`, send the fully assembled advisory prompt inline, start each interactive advisory pass with an explicit `--session-id <uuid>`, and restrict Gemini review context to workspace-local files and directories only.

By default, the shared runner now uses the interactive Gemini CLI path: it opens `gemini --session-id <uuid> -i "<prompt>"` under a PTY, watches the matching project-local Gemini session file under `~/.gemini/tmp/<project>/chats/`, and extracts the final advisory when the recorded turn becomes stable. This keeps the advisory flow closer to a human interactive session while still allowing Codex to automate startup, waiting, extraction, and shutdown.

The Antigravity runner launches `agy -p "<prompt>"` from the same single-project or multi-project workspace root. It sets an explicit Antigravity CLI log file when supported, reads the matching transcript under `~/.gemini/antigravity-cli/brain/<conversation>/.system_generated/logs/transcript.jsonl` as a fallback to stdout, and prints progress from transcript records while waiting.

`--context-file` entries are treated as priority starting points rather than a hard sandbox or an exhaustive file list. The external reviewer runs from the selected workspace root and may inspect other workspace-local files when the brief requires it.

When one advisory must intentionally cover multiple projects, repeat `--project-root` for each target project root. The runner resolves those roots inside the current Codex workspace, switches the external reviewer's `cwd` to their common ancestor inside that workspace, and lists each project explicitly in the prompt with a project-scope key.

For interactive advisory runs, the runner reads only Gemini session files matching the explicit UUID session id for that invocation, so concurrent runs do not race on the newest prompt-matching chat file.

By default, the shared Gemini runner uses Gemini CLI's stable `pro` alias via `--model pro` so these skills prefer the latest Pro-class model without hard-coding a short-lived version string. Set `CODEX_GEMINI_MODEL` if you need to override that default. Antigravity skills do not pass any model flag; set `CODEX_AGY_CMD` only if the `agy` executable is not on `PATH` or you need a custom wrapper command.

If Gemini exits after recording thoughts but before a final answer, the runner does not auto-continue by default. Set `CODEX_GEMINI_CONTINUATION_RETRIES` or pass `--continuation-retries` to allow bounded same-session continuation prompts.

If the pitfall notebook is personal agent memory rather than shared team knowledge, projects should ignore `.codex-pitfalls.md`.

Codex should treat the full external wrapper timeout window as expected runtime. With the current defaults, Gemini and Antigravity advisory runs may stay quiet for up to 20 minutes without that implying failure.

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
- `tests/` provides focused coverage for the shared Gemini/Antigravity runner helpers and the
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
