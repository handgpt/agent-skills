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

   **Real-time monitoring options:**
   - `--output-file` (default): line-buffered file, monitor with
     `tail -f /tmp/gemini-design-*.md`.
   - **Monitor tool** (Claude Code v2.1.98+): run the same command via the
     `Monitor` built-in tool so Claude sees each output line in conversation.
   - `--daemon` (POSIX, advanced): detach and run in the background. Requires
     `--output-file`. Useful when wrapping the runner in a hook or async job.

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
