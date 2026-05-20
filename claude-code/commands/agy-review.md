---
description: Advisory Antigravity CLI code review for completed code changes. Use after meaningful code changes to get a concise external review focused on bugs, regressions, missing tests, risky assumptions, edge cases, unused code, over-complicated implementations, or structural risks.
---

# Antigravity Review

Use the Antigravity review skill at:

```bash
python3 $AGENT_SKILLS_DIR/claude-code/skills/agy-review/scripts/run_agy_review.py \
  --project-root <path/to/project> \
  --brief-file /tmp/review-brief.md \
  --context-file <path/to/changed/file> \
  --output-file /tmp/agy-review-$(date +%s).md
```

For structural mode, add `--mode structural`.

The runner defaults to `agy -p "<prompt>"` and can use `agy -i "<prompt>"` via `CLAUDE_AGY_MODE=interactive` or `~/.claude/agy_cli.json`. If `agy` is not on `PATH`, set `CLAUDE_AGY_CMD` or config `"command"` to the CLI path. Tested with `agy` version `1.0.0`. It does not pass a model flag. Treat Antigravity as advisory only; do not ask it to edit files or output patches.

$ARGUMENTS
