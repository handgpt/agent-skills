---
description: Advisory Codex CLI debugging checkpoint for non-trivial failures. Use when the same failure persists across consecutive attempts, or when a failure remains ambiguous after local inspection.
---

# Codex Error Analysis

Get a bounded Codex debugging opinion when stuck on a real blocker.

## Instructions

1. **Decide whether to use it.** Use when a non-trivial failure persists across two consecutive attempts. Skip for obvious syntax errors.

2. **Prune logs first.** Isolate the failure before invoking Codex.

3. **Prepare a diagnostic brief** in `/tmp` with failure summary, error signature, pruned log excerpt, and suspect paths.

4. **Run the diagnostic advisory.** Execute:

   ```bash
   python3 $AGENT_SKILLS_DIR/claude-code/skills/codex-error-analysis/scripts/run_codex_error_analysis.py \
     --project-root <path/to/project> \
     --brief-file /tmp/error-brief.md \
     --context-file <path/to/relevant/file>
   ```

5. **Read the output.** Prefer the smallest next checks that disambiguate the root cause.

## Guardrails

- Codex runs in read-only sandbox mode.
- Do not pass giant unpruned logs.
- Do not treat speculative guesses as confirmed.

$ARGUMENTS
