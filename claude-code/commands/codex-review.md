---
description: Advisory Codex CLI code review for completed code changes. Uses the built-in `codex review` command to get a concise external review focused on bugs, regressions, missing tests, and risky assumptions.
---

# Codex Review

Get a bounded Codex review after code changes are complete. Treat the output as a second opinion only.

## Instructions

1. **Decide whether to use it.** Use after non-trivial code changes. Skip for trivial edits or analysis-only tasks.

2. **Run the review.** Execute one of:

   ```bash
   # Review uncommitted changes
   python3 $AGENT_SKILLS_DIR/claude-code/skills/codex-review/scripts/run_codex_review.py \
     --project-root <path/to/project> \
     --uncommitted

   # Review against a base branch
   python3 $AGENT_SKILLS_DIR/claude-code/skills/codex-review/scripts/run_codex_review.py \
     --project-root <path/to/project> \
     --base main

   # Review a specific commit
   python3 $AGENT_SKILLS_DIR/claude-code/skills/codex-review/scripts/run_codex_review.py \
     --project-root <path/to/project> \
     --commit <sha>
   ```

3. **Read the output.** Validate claims against the actual diff before acting.

## Guardrails

- Codex runs in read-only sandbox mode.
- One pass per change set is usually enough.

$ARGUMENTS
