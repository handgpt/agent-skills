---
description: Advisory Antigravity CLI design critique before major technical decisions.
---

# Antigravity Design Checkpoint

Use the Antigravity design checkpoint skill at:

```bash
python3 $AGENT_SKILLS_DIR/claude-code/skills/agy-design-checkpoint/scripts/run_agy_design_check.py \
  --project-root <path/to/project> \
  --brief-file /tmp/design-brief.md \
  --context-file <path/to/spec-or-module> \
  --output-file /tmp/agy-design-$(date +%s).md
```

The runner defaults to `agy -p "<prompt>"` and can use `agy -i "<prompt>"` via `CLAUDE_AGY_MODE=interactive` or `~/.claude/agy_cli.json`. If `agy` is not on `PATH`, set `CLAUDE_AGY_CMD` or config `"command"` to the CLI path. It passes `--model "Gemini 3.5 Flash (High)"` by default when supported; override with `CLAUDE_AGY_MODEL` or config `"model"`. Supported models are `Gemini 3.5 Flash (High)`, `Gemini 3.1 Pro (High)`, `Claude Sonnet 4.6 (Thinking)`, and `Claude Opus 4.6 (Thinking)`. Multi-project scopes pass extra roots via `--add-dir` when supported. Tested with `agy` version `1.0.7`. Treat Antigravity as advisory only; do not ask it to edit files or output patches.

$ARGUMENTS
