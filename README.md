# Agent Skills

`agent-skills` is a public repository for reusable local-agent skills, prompts,
install helpers, and runtime-specific workflow assets.

The repository is organized by runtime. Each top-level directory is treated as an
independent product line with its own documentation, installation flow, and
release cadence.

## Repository Structure

```text
agent-skills/
├── common/
│   └── scripts/
├── codex/
│   ├── README.md
│   ├── skills/
│   ├── scripts/
│   ├── templates/
│   └── tests/
├── gemini-cli/
│   ├── README.md
│   └── scripts/
├── claude-code/
│   ├── README.md
│   └── scripts/
└── openclaw/
    ├── README.md
    └── scripts/
```

## Design Principles

- Keep each runtime install self-contained. A user should be able to install only
  the runtime directory they need.
- Keep cross-runtime advisory runner logic in `common/scripts` once there is a
  real maintenance burden. Runtime directories should contain thin platform
  adapters, docs, and install scripts rather than duplicated runner logic.
- Give each runtime its own `README.md` and `scripts/install.sh`.
- Let runtimes evolve independently. Stability for one runtime should not depend on
  unfinished work in another.

## Current Runtime Status

| Runtime | Status | Notes |
| --- | --- | --- |
| [codex](codex/README.md) | Available | Antigravity CLI design, review, error-analysis, and pitfall-notebook skills are implemented and smoke-tested with `agy` 1.0.7. Gemini CLI advisory skills were removed because Gemini CLI is expected to go offline in June 2026. |
| [gemini-cli](gemini-cli/README.md) | Planned | Directory scaffold exists; runtime-specific assets are not published yet. |
| [claude-code](claude-code/README.md) | Available | Gemini, Antigravity CLI, Codex CLI, and pitfall-notebook advisory skills are implemented. |
| [openclaw](openclaw/README.md) | Planned | Directory scaffold exists; runtime-specific assets are not published yet. |

## How To Use This Repository

1. Open the runtime directory you care about.
2. Read that runtime's `README.md`.
3. Use that runtime's install script and conventions only.

There is no repository-wide installer on purpose. Installation and configuration
are runtime-specific.

`common/scripts` is source code shared by those runtime installers; it is not a
standalone runtime and has no separate installer.

## Notes

- This repository is intended to be public and readable without private context.
- Placeholder runtime directories are included to reserve stable paths for future
  additions, not to imply current support.
