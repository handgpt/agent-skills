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
     --context-file <path/to/changed/file> \
     --output-file /tmp/gemini-review-$(date +%s).md
   ```

   For structural mode (shared modules, public interfaces, cross-module changes):

   ```bash
   python3 $AGENT_SKILLS_DIR/claude-code/skills/gemini-review/scripts/run_gemini_review.py \
     --mode structural \
     --project-root <path/to/project> \
     --brief-file /tmp/review-brief.md \
     --context-file <path/to/changed/file> \
     --output-file /tmp/gemini-review-$(date +%s).md
   ```

   Set `AGENT_SKILLS_DIR` to the `agent-skills` directory path, or use the absolute path directly.

   **Real-time monitoring options:**
   - `--output-file` (default for this skill): file is line-buffered, monitor with
     `tail -f /tmp/gemini-review-*.md`. Works on every Claude Code version.
   - **Monitor tool** (Claude Code v2.1.98+): instead of `tail -f`, ask Claude to
     run the same command via the `Monitor` built-in tool. Each output line is fed
     back into the conversation in real time so the LLM can react to progress
     mid-call. Use this when you want Claude itself to watch the review.
   - `--daemon` (POSIX, advanced): detach from the terminal and run in the
     background. The parent prints the daemon PID and exits 0; the actual review
     is written to `--output-file`. Useful when invoked from a hook or wrapper
     that should not block on a 30+ minute review. Requires `--output-file`.

   **OpenTelemetry**: if Claude Code's OTel tracing is enabled, the runner
   automatically detects the `TRACEPARENT` environment variable and emits a
   child span (`gemini.advisory.review`) under Claude's trace tree. Requires
   `opentelemetry-api` to be importable; otherwise it is silently skipped.

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
