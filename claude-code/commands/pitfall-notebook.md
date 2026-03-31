---
description: Maintain a concise per-project pitfall notebook after non-trivial errors are fixed. Read previously hit pitfalls before implementation or review, and append entries after meaningful blockers are resolved to avoid repeating the same mistake.
---

# Pitfall Notebook

Maintain a short project-local markdown notebook of mistakes that were already paid for once.

This skill intentionally updates a local memory file in the current project.

## Notebook Location

- Default path: `<project-root>/.claude-pitfalls.md`
- Recommended: add `.claude-pitfalls.md` to `.gitignore` if this is personal agent memory rather than team knowledge.

## Instructions

### When to read it

- At the start of non-trivial implementation work, if `.claude-pitfalls.md` exists
- At the start of a final code review, if `.claude-pitfalls.md` exists
- Before investigating a new error that feels similar to a past failure

### When to update it

- After a non-trivial error, regression, or blocker is successfully fixed
- After a repeated pitfall is recognized and the new fix clarifies the rule
- Skip updates for trivial typos, obvious syntax fixes, or noisy low-signal mistakes

### How to update

Run:

```bash
python3 $AGENT_SKILLS_DIR/claude-code/skills/pitfall-notebook/scripts/update_pitfall_notebook.py \
  --title "Short pitfall title" \
  --symptom "What failed or what misled the debugging" \
  --cause "Actual root cause" \
  --rule "How to avoid repeating it"
```

The script auto-detects the current project root, writes to `.claude-pitfalls.md`, dedupes entries by normalized title, and keeps only the newest entries.

### How to read it correctly

- Treat the notebook as a pre-flight checklist, not a full design history.
- Apply the `Rule` lines first. They are the core "do not repeat this" memory.
- Keep entries concrete.

## Guardrails

- Do not dump stack traces or long logs into the notebook.
- Do not create entries before the fix is actually confirmed.
- Do not record secrets, credentials, or sensitive production data.

$ARGUMENTS
