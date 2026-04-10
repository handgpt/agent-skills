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

   **How Claude should wait for the review (precedence order):**

   1. **`Monitor` built-in tool** — *first choice when available.* Claude Code
      v2.1.98+ in interactive mode exposes a `Monitor` tool that runs a
      command in the background and feeds each stdout line into the
      conversation as it arrives. Ask Claude to run the runner via `Monitor`
      and Claude will react to progress mid-call without polling. Not
      available on Amazon Bedrock, Google Vertex AI, or Microsoft Foundry,
      and not exposed in headless / Agent SDK / non-interactive mode (check
      whether `Monitor` is in your tool list before assuming).
   2. **`run_in_background` + `<task-notification>` + `Read`** — *correct
      fallback when `Monitor` is unavailable.* Run the runner with
      `--daemon` (or `--output-file` + appending `&`) inside a `Bash` call
      that uses `run_in_background: true`. The harness returns a `task_id`
      and an output file path immediately, then sends a `<task-notification>`
      when the background command finishes. While waiting, Claude should do
      other useful work (or simply stay idle); on notification, `Read` the
      output file. This is the canonical async pattern in non-interactive
      mode and is documented in the deprecated `TaskOutput` tool's own
      description ("Prefer using the Read tool on the task's output file
      path instead").
   3. **`tail -f` on `--output-file`** — *interactive humans only.* Useful
      when a human is watching the review live in a terminal. Claude should
      not do this from inside a chat turn.

   ❌ **Anti-pattern — never do this:**

   ```bash
   # WRONG. Wastes context, blocks the foreground bash thread,
   # and produces no useful information per loop iteration.
   while kill -0 $DAEMON_PID 2>/dev/null; do sleep 30; done
   ```

   This pattern shows up when Claude has neither `Monitor` nor a clear
   mental model of `run_in_background` + `<task-notification>`. Use option
   2 above instead — it is event-driven, not poll-driven.

   **Argument flags reference:**
   - `--output-file <path>`: write all output (stdout + stderr) to a
     line-buffered file instead of the console. Required for `--daemon`.
   - `--daemon` (POSIX only): detach from the controlling terminal via
     POSIX double-fork; the parent prints the real daemon PID and exits 0.
     Combine with `--output-file` and either `run_in_background: true`
     (preferred) or shell `&` backgrounding (interactive humans only).

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
