---
name: agy-design-checkpoint
description: Advisory Antigravity CLI second opinion for high-impact technical design decisions. Use before finalizing architecture, protocols, repository layout, migrations, runtime direction, rollout strategy, or security boundaries.
---

# Antigravity Design Checkpoint

Get a bounded Antigravity CLI critique before committing to a high-impact design direction. Treat the output as advice only: Antigravity must not edit files, apply patches, or become the final decision-maker.

## Instructions

1. Use before finalizing architecture, protocol, repository layout, migration, rollout, runtime, infrastructure, or security-boundary decisions. Skip routine implementation choices and tiny refactors.

2. Prepare a compact design brief in `/tmp` with `Decision`, `Goal`, `Constraints`, `Options Considered`, `Current Preferred Direction`, `Known Risks`, `Relevant Official Docs`, `Relevant Community References`, and `Relevant Paths`.

3. Run the advisory checkpoint:

```bash
python3 $AGENT_SKILLS_DIR/claude-code/skills/agy-design-checkpoint/scripts/run_agy_design_check.py \
  --project-root <path/to/project> \
  --brief-file /tmp/design-brief.md \
  --context-file <path/to/spec-or-module> \
  --output-file /tmp/agy-design-$(date +%s).md
```

The runner defaults to `agy -p "<prompt>"` print mode and can use `agy -i "<prompt>"` when `CLAUDE_AGY_MODE=interactive` or `"mode": "interactive"` is set in `~/.claude/agy_cli.json`. If `agy` is not on `PATH`, set `CLAUDE_AGY_CMD` or the config file's `"command"` to the CLI path, for example `~/.local/bin/agy`.

When supported by `agy`, the runner passes `--model "Gemini 3.5 Flash (High)"` by default. Override with `CLAUDE_AGY_MODEL` or config `"model"`. Supported values are `Gemini 3.5 Flash (High)`, `Gemini 3.1 Pro (High)`, `Claude Sonnet 4.6 (Thinking)`, and `Claude Opus 4.6 (Thinking)`.

For multi-project advisory scopes, the runner passes extra project roots through repeatable `--add-dir` flags when supported by `agy`.

This skill has been smoke-tested with Antigravity CLI `agy` version `1.0.7`. Re-run tests and both print/interactive advisory smoke tests after upgrading `agy`.

## Guardrails

- Do not ask Antigravity to edit files or output patches.
- Ask Antigravity to challenge both the whole-system design and module-level boundaries.
- Include official docs and community references when external best practices matter.

$ARGUMENTS
