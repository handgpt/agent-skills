# Agent Skills

`agent-skills` is a public repository for reusable local-agent skills, prompts,
install helpers, and runtime-specific workflow assets.

The repository is organized by runtime. Each top-level directory is treated as an
independent product line with its own documentation, installation flow, and
release cadence.

## Repository Structure

```text
agent-skills/
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

- Keep each runtime self-contained. A user should be able to work only inside the
  runtime directory they need.
- Avoid a top-level shared library until a real cross-runtime maintenance burden
  exists. Small, stable helpers are cheaper to duplicate than to couple.
- Give each runtime its own `README.md` and `scripts/install.sh`.
- Let runtimes evolve independently. Stability for one runtime should not depend on
  unfinished work in another.

## Current Runtime Status

| Runtime | Status | Notes |
| --- | --- | --- |
| [codex](codex/README.md) | Available | Gemini advisory checkpoint and review skills are implemented. |
| [gemini-cli](gemini-cli/README.md) | Planned | Directory scaffold exists; runtime-specific assets are not published yet. |
| [claude-code](claude-code/README.md) | Planned | Directory scaffold exists; runtime-specific assets are not published yet. |
| [openclaw](openclaw/README.md) | Planned | Directory scaffold exists; runtime-specific assets are not published yet. |

## How To Use This Repository

1. Open the runtime directory you care about.
2. Read that runtime's `README.md`.
3. Use that runtime's install script and conventions only.

There is no repository-wide installer on purpose. Installation and configuration
are runtime-specific.

## Notes

- This repository is intended to be public and readable without private context.
- Placeholder runtime directories are included to reserve stable paths for future
  additions, not to imply current support.
