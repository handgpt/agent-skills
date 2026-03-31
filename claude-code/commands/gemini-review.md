---
description: Advisory Gemini CLI code review for completed code changes. Use after meaningful code changes to get a concise external review focused on bugs, regressions, missing tests, risky assumptions, edge cases, unused code, over-complicated implementations, or structural risks.
---

# Gemini Review

Get a bounded Gemini review after code changes are complete. Treat the output as a second opinion only: Gemini must not edit files, apply patches, or become the final decision-maker.

## Instructions

1. **Decide whether to use it.** Use after non-trivial code changes and before the final answer. Skip when no code changed, when only tiny low-risk edits were made, or when the user only asked for analysis. Run once per finished change set.

2. **Prepare a review brief.** Create a short review brief in `/tmp` with:
   - `Change Summary`
   - `Risk Areas`
   - `Files Changed`
   - `Diff Stat`
   - `Selected Diff Or Excerpts`
   - `Known Gaps`

   Use the template at `skills/gemini-review/references/review-brief-template.md` for reference. Use `git diff` to auto-generate the diff stat and excerpts. Prefer compact summaries plus local file paths over dumping the entire diff.

3. **Run the advisory review.** Execute:

   ```bash
   python3 $AGENT_SKILLS_DIR/claude-code/skills/gemini-review/scripts/run_gemini_review.py \
     --project-root <path/to/project> \
     --brief-file /tmp/review-brief.md \
     --context-file <path/to/changed/file>
   ```

   For structural mode (shared modules, public interfaces, cross-module changes):

   ```bash
   python3 $AGENT_SKILLS_DIR/claude-code/skills/gemini-review/scripts/run_gemini_review.py \
     --mode structural \
     --project-root <path/to/project> \
     --brief-file /tmp/review-brief.md \
     --context-file <path/to/changed/file>
   ```

   Set `AGENT_SKILLS_DIR` to the `agent-skills` directory path, or use the absolute path directly.

4. **Read the output correctly.**
   - Expect findings-first output: top findings, regression risks, missing tests, things to verify, and overall assessment.
   - In structural mode, expect an additional `Structural & Architectural Risks` section.
   - Validate any claim against the actual diff before acting on it.
   - If Gemini is unavailable, times out, or returns noise, continue and note the external review was unavailable.

## Guardrails

- Do not ask Gemini to edit files or output patches.
- Do not use this skill before code exists; use gemini-design-checkpoint instead.
- Keep the review bounded and concise; one pass is usually enough.
- Use structural mode only when the change actually needs a wider design pass.

$ARGUMENTS
