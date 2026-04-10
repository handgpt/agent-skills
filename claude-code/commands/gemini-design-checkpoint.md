---
description: Advisory Gemini CLI second-opinion for high-impact technical design decisions. Use before locking in architecture, protocol, migration plan, runtime direction, security boundary, or other major design choice.
---

# Gemini Design Checkpoint

Get a short, critical second opinion from Gemini before locking in a major technical direction. Treat the result as advisory only: do not let Gemini edit files, apply patches, or override your own judgment.

This checkpoint explicitly tests whether the preferred direction follows current best practices, whether the architecture and module-level design both make sense, and whether the recommendation is supported by official documentation and real community experience.

## Instructions

1. **Decide whether to use it.** Use for decisions that are expensive to reverse: architecture, protocols, repository boundaries, migrations, deployment shape, trust boundaries, security/privacy design, or large product-level tradeoffs. Skip for routine bug fixes, small refactors, or straightforward implementation details.

2. **Prepare a compact brief.** Write a short brief in `/tmp` with:
   - `Decision`
   - `Goal`
   - `Constraints`
   - `Options Considered`
   - `Current Preferred Direction`
   - `Known Risks`
   - `Relevant Official Docs` (optional)
   - `Relevant Community References` (optional)
   - `Relevant Paths`

   Use the template at `skills/gemini-design-checkpoint/references/design-brief-template.md` for reference.

3. **Run the advisory pass.** Execute:

   ```bash
   python3 $AGENT_SKILLS_DIR/claude-code/skills/gemini-design-checkpoint/scripts/run_gemini_design_check.py \
     --project-root <path/to/project> \
     --brief-file /tmp/design-brief.md \
     --context-file <path/to/doc-or-spec.md> \
     --output-file /tmp/gemini-design-$(date +%s).md
   ```

   **How Claude should wait for the design pass (precedence order):**

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
      when a human is watching the design pass live in a terminal.

   ❌ **Anti-pattern — never do this:**

   ```bash
   # WRONG. Wastes context and blocks the foreground bash thread.
   while kill -0 $DAEMON_PID 2>/dev/null; do sleep 30; done
   ```

   Use option 2 above instead — it is event-driven, not poll-driven.

   **OpenTelemetry**: when `TRACEPARENT` is set (Claude Code OTel tracing
   enabled), the runner emits a `gemini.advisory.design` span parented to
   Claude's trace tree. Silently skipped if `opentelemetry-api` is not
   installed.

4. **Read the output correctly.**
   - Expect verdict, best-practice alignment, system-level risks, module-level risks, alternatives, open questions, and recommendation.
   - Evaluate each point yourself. Accept, reject, or defer it explicitly.
   - When Gemini relies on external guidance, prefer conclusions grounded in official documentation.
   - If Gemini is unavailable, times out, or returns low-signal output, continue and note the advisory was unavailable.

## Guardrails

- Do not ask Gemini to modify files or generate patches.
- Do not upload secrets, credentials, or huge logs.
- Use this skill before a major design commitment, not as a replacement for implementation work.

$ARGUMENTS
