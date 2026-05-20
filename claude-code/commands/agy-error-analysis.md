---
description: Advisory Antigravity CLI debugging checkpoint for non-trivial or persistent failures.
---

# Antigravity Error Analysis

Use the Antigravity error-analysis skill at:

```bash
python3 $AGENT_SKILLS_DIR/claude-code/skills/agy-error-analysis/scripts/run_agy_error_analysis.py \
  --project-root <path/to/project> \
  --brief-file /tmp/error-brief.md \
  --context-file <path/to/suspect/file-or-directory> \
  --output-file /tmp/agy-error-$(date +%s).md
```

The runner defaults to `agy -p "<prompt>"` and can use `agy -i "<prompt>"` via `CLAUDE_AGY_MODE=interactive` or `~/.claude/agy_cli.json`. If `agy` is not on `PATH`, set `CLAUDE_AGY_CMD` or config `"command"` to the CLI path. Tested with `agy` version `1.0.0`. It does not pass a model flag. Treat Antigravity as advisory only; do not ask it to edit files or output patches.

$ARGUMENTS
