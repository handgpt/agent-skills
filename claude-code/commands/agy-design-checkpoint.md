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

The runner uses `agy -p "<prompt>"` and does not pass a model flag. Treat Antigravity as advisory only; do not ask it to edit files or output patches.

$ARGUMENTS
