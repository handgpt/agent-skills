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

The runner uses `agy -p "<prompt>"` and does not pass a model flag. Treat Antigravity as advisory only; do not ask it to edit files or output patches.

$ARGUMENTS
