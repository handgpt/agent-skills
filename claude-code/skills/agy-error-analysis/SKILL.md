---
name: agy-error-analysis
description: Advisory Antigravity CLI debugging checkpoint for non-trivial failures. Use after an initial local pass when a build, test, runtime, or tooling failure remains ambiguous or persists across attempts.
---

# Antigravity Error Analysis

Get a bounded Antigravity CLI debugging second opinion after an initial local pass. Treat the output as advice only: Antigravity must not edit files, apply patches, or become the final decision-maker.

## Instructions

1. Use when the same non-trivial failure persists across consecutive attempts, or when the root cause remains ambiguous after local inspection. Skip obvious typos and failures with a clear root cause.

2. Prepare a compact diagnostic brief in `/tmp` with `Failure Summary`, `What Was Attempted`, `Exact Error Signature`, `Pruned Log Excerpt`, `Suspect Paths`, `Environment Notes`, and `Known Unknowns`.

3. Run the advisory analysis:

```bash
python3 $AGENT_SKILLS_DIR/claude-code/skills/agy-error-analysis/scripts/run_agy_error_analysis.py \
  --project-root <path/to/project> \
  --brief-file /tmp/error-brief.md \
  --context-file <path/to/suspect/file-or-directory> \
  --output-file /tmp/agy-error-$(date +%s).md
```

The runner uses `agy -p "<prompt>"` print mode and does not pass a model flag because Antigravity currently selects the model itself.

## Guardrails

- Do not ask Antigravity to edit files or output patches.
- Keep logs pruned to the smallest high-signal failure excerpt.
- Prefer discriminating checks over broad refactor suggestions.

$ARGUMENTS
