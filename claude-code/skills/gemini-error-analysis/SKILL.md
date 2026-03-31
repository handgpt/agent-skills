---
name: gemini-error-analysis
description: Advisory Gemini CLI debugging checkpoint for non-trivial failures. Use when Claude Code has already inspected an error locally and the same failure persists across consecutive attempts, or when a build, test, runtime, or tooling failure remains ambiguous after an initial local pass. Focus on likely causes, code-vs-environment separation, and the highest-signal next checks. Do not use for obvious typos, single-step syntax fixes, or failures with an already clear root cause.
---

# Gemini Error Analysis

Get a bounded Gemini debugging opinion when Claude Code is stuck on a real blocker. Treat the output as advisory only: Gemini must not edit files, apply patches, or become the final decision-maker.

## Decide Whether To Use It

- Use this skill when the same non-trivial failure persists across two consecutive implementation attempts.
- Use it when a build, test, runtime, or tooling failure remains ambiguous after an initial local inspection.
- Skip it for obvious syntax errors, missing imports with a clear fix, single failed assertions with an obvious cause, or trivial path typos.
- Run it once per failure cluster. Do not call it on every intermediate stack trace.

## Prepare A Diagnostic Brief

Before invoking Gemini, prune the failure locally. Do not dump giant raw logs into the prompt flow.

Create a short diagnostic brief in `/tmp` or another scratch path with:

- `Failure Summary`
- `What Was Attempted`
- `Exact Error Signature`
- `Pruned Log Excerpt`
- `Suspect Paths`
- `Environment Notes`
- `Known Unknowns`

See [error-brief-template.md](references/error-brief-template.md) for a ready-to-fill template.

## Prune Logs First

- Use local tools such as `tail`, `rg`, or test-runner short traceback modes to isolate the failure hunk before invoking Gemini.
- Prefer the smallest log excerpt that still shows the error signature.
- If the blocker might be environmental, summarize the environment signal explicitly.

## Run The Diagnostic Advisory

Run:

```bash
python3 scripts/run_gemini_error_analysis.py \
  --project-root path/to/project \
  --brief-file /tmp/error-brief.md \
  --context-file path/to/relevant/file-or-log
```

Attach only the few source files, config files, or log excerpts that matter.

The shared runner defaults to `gemini-2.5-pro`. Override with `CLAUDE_GEMINI_MODEL` if needed.

## Read The Output Correctly

- Expect likely causes first, then code-logic vs environment separation, then the most useful next checks.
- Treat Gemini as another debugger, not the source of truth.
- Ask Gemini to distinguish between code logic errors, environmental issues, and insufficient evidence.
- Prefer the smallest next checks that can disambiguate the root cause quickly.
- If Gemini is unavailable, times out, or returns noise, continue and note the external debugging pass was unavailable.

## Guardrails

- Do not ask Gemini to edit files or output patches.
- Do not call this skill before doing an initial local inspection.
- Do not pass giant unpruned logs when a short excerpt would do.
- Do not treat speculative root-cause guesses as confirmed.

## Resources

- `scripts/run_gemini_error_analysis.py` wraps Gemini CLI with the shared advisory runner.
- [references/error-brief-template.md](references/error-brief-template.md) provides a compact diagnostic brief template.
