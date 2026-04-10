---
description: Advisory Gemini CLI debugging checkpoint for non-trivial failures. Use when the same failure persists across consecutive attempts, or when a build, test, runtime, or tooling failure remains ambiguous after local inspection.
---

# Gemini Error Analysis

Get a bounded Gemini debugging opinion when stuck on a real blocker. Treat the output as advisory only: Gemini must not edit files, apply patches, or become the final decision-maker.

## Instructions

1. **Decide whether to use it.** Use when the same non-trivial failure persists across two consecutive attempts, or when a failure remains ambiguous after local inspection. Skip for obvious syntax errors, missing imports with a clear fix, or trivial path typos.

2. **Prune logs first.** Use `tail`, `rg`, or test-runner short traceback modes to isolate the failure before invoking Gemini.

3. **Prepare a diagnostic brief.** Create a short brief in `/tmp` with:
   - `Failure Summary`
   - `What Was Attempted`
   - `Exact Error Signature`
   - `Pruned Log Excerpt`
   - `Suspect Paths`
   - `Environment Notes`
   - `Known Unknowns`

   Use the template at `skills/gemini-error-analysis/references/error-brief-template.md` for reference.

4. **Run the diagnostic advisory.** Execute:

   ```bash
   python3 $AGENT_SKILLS_DIR/claude-code/skills/gemini-error-analysis/scripts/run_gemini_error_analysis.py \
     --project-root <path/to/project> \
     --brief-file /tmp/error-brief.md \
     --context-file <path/to/relevant/file-or-log> \
     --output-file /tmp/gemini-error-$(date +%s).md
   ```

   **How Claude should wait for the diagnostic (precedence order):**

   1. **`Monitor` built-in tool** — *first choice when available.* Claude
      Code v2.1.98+ in interactive mode exposes a `Monitor` tool that runs
      a command in the background and feeds each stdout line into the
      conversation as it arrives. Not available on Bedrock, Vertex AI, or
      Foundry, and not exposed in headless / Agent SDK / non-interactive
      mode (check whether `Monitor` is in your tool list before assuming).
   2. **`run_in_background` + `<task-notification>` + `Read`** — *correct
      fallback when `Monitor` is unavailable.* Run the runner with
      `--daemon` inside a `Bash` call that uses `run_in_background: true`.
      The harness returns a `task_id` and an output file path immediately,
      then sends a `<task-notification>` when the background command
      finishes. Do other useful work (or stay idle) until the notification;
      on notification, `Read` the output file. This is the canonical
      async pattern in non-interactive mode.
   3. **`tail -f` on `--output-file`** — *interactive humans only.* Useful
      when a human is watching the diagnostic live in a terminal.

   ❌ **Anti-pattern — never do this:**

   ```bash
   # WRONG. Wastes context and blocks the foreground bash thread.
   while kill -0 $DAEMON_PID 2>/dev/null; do sleep 30; done
   ```

   Use option 2 above instead — it is event-driven, not poll-driven.

   **OpenTelemetry**: when `TRACEPARENT` is set (Claude Code OTel tracing
   enabled), the runner emits a `gemini.advisory.error_analysis` span parented
   to Claude's trace tree. Silently skipped if `opentelemetry-api` is not
   installed.

5. **Read the output correctly.**
   - Expect likely causes first, then code-logic vs environment separation, then next checks.
   - Prefer the smallest next checks that can disambiguate the root cause quickly.
   - If Gemini is unavailable, times out, or returns noise, continue and note the external debugging pass was unavailable.

## Guardrails

- Do not ask Gemini to edit files or output patches.
- Do not call this skill before doing an initial local inspection.
- Do not pass giant unpruned logs.
- Do not treat speculative root-cause guesses as confirmed.

$ARGUMENTS
