---
name: agy-review
description: Advisory Antigravity CLI code review for completed code changes. Use after meaningful code changes to get a concise external review focused on bugs, regressions, missing tests, risky assumptions, edge cases, unused code, over-complicated implementations, or structural risks.
---

# Antigravity Review

Get a bounded Antigravity CLI review after code changes are complete. Treat the output as a second opinion only: Antigravity must not edit files, apply patches, or become the final decision-maker.

## Instructions

1. Decide whether to use it. Use after non-trivial code changes and before the final answer. Skip when no code changed, only tiny low-risk edits were made, or the user only asked for analysis.

2. Prepare a compact review brief in `/tmp` with `Change Summary`, `Risk Areas`, `Files Changed`, `Diff Stat`, `Selected Diff Or Excerpts`, and `Known Gaps`. Prefer compact summaries plus local file paths over dumping the entire diff.

3. Run the advisory review:

```bash
python3 $AGENT_SKILLS_DIR/claude-code/skills/agy-review/scripts/run_agy_review.py \
  --project-root <path/to/project> \
  --brief-file /tmp/review-brief.md \
  --context-file <path/to/changed/file> \
  --output-file /tmp/agy-review-$(date +%s).md
```

For structural mode:

```bash
python3 $AGENT_SKILLS_DIR/claude-code/skills/agy-review/scripts/run_agy_review.py \
  --mode structural \
  --project-root <path/to/project> \
  --brief-file /tmp/review-brief.md \
  --context-file <path/to/changed/file> \
  --output-file /tmp/agy-review-$(date +%s).md
```

4. Read the output correctly. Validate any claim against the actual diff before acting on it. If Antigravity is unavailable, times out, or returns noise, continue and note the external review was unavailable only when it affects confidence.

The runner uses `agy -p "<prompt>"` print mode and does not pass a model flag because Antigravity currently selects the model itself.

## Guardrails

- Do not ask Antigravity to edit files or output patches.
- Keep the review bounded and concise; one pass is usually enough.
- Use structural mode only when the change needs a wider design pass.

$ARGUMENTS
