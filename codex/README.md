# Codex Skills

Reusable Codex skills and install helpers for Gemini-based advisory checkpoints.

This directory is the Codex-specific product line inside the larger
`agent-skills` repository. Everything needed for Codex lives under `codex/`.

## Layout

```text
agent-skills/codex/
├── skills/
│   ├── gemini-design-checkpoint/
│   ├── gemini-review/
│   └── shared/
├── templates/
│   └── home-AGENTS.snippet.md
├── tests/
│   └── test_gemini_runner.py
└── scripts/
    └── install.sh
```

## Included skills

- `gemini-design-checkpoint`
  Use before major technical design decisions. The skill asks Gemini for a concise second opinion on architecture, protocol, repo layout, migration, and other high-impact choices.
- `gemini-review`
  Use after meaningful code changes and before the final response. The skill asks Gemini for a concise advisory review focused on bugs, regressions, missing tests, and risky assumptions.

Both skills are advisory only. They do not modify files and they are designed to fail open: if Gemini is unavailable or times out, Codex continues normally.

When the matching `AGENTS.md` rules are installed, Codex should run these advisory passes automatically at the relevant checkpoints. The user does not need to explicitly request Gemini on each turn.

The wrappers pass local file and directory paths to Gemini so it can inspect the workspace directly on disk instead of receiving large pasted file bodies.

They also run Gemini from the current project root, reuse the latest Gemini session for that project when available, stage advisory briefs into a hidden directory under the project root, prune stale staged brief files automatically, and restrict Gemini review context to workspace-local files and directories only.

Projects that use Git should ignore `.codex-gemini-advisories/`.

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
- `tests/test_gemini_runner.py` provides focused coverage for the shared Gemini
  runner helpers.
- `scripts/install.sh` is the supported way to install or refresh the Codex
  runtime assets locally.
- The install script intentionally preserves the legacy home-level marker names
  so an upgraded installation can replace an older `AGENTS.md` block cleanly.

## Notes

- `skills/` is the source of truth for Git sharing inside the Codex runtime.
- `~/.codex/skills` is the runtime install location used by Codex.
- The home-level `AGENTS.md` rules only apply to projects started under your home directory tree.
- Restart Codex after installing or updating skills so the runtime skill list refreshes.
