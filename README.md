# Codex Skills

Reusable Codex skills and install helpers for Gemini-based advisory checkpoints.

## Layout

```text
codex-skills/
├── skills/
│   ├── gemini-design-checkpoint/
│   └── gemini-review/
├── templates/
│   └── home-AGENTS.snippet.md
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

Install the skills into `~/.codex/skills`:

```bash
./scripts/install.sh
```

Install the skills and append the home-level AGENTS rules under `~/AGENTS.md`:

```bash
./scripts/install.sh --install-home-agents
```

## Notes

- `skills/` is the source of truth for Git sharing.
- `~/.codex/skills` is the runtime install location used by Codex.
- The home-level `AGENTS.md` rules only apply to projects started under your home directory tree.
- Restart Codex after installing or updating skills so the runtime skill list refreshes.
