---
name: codex-error-analysis
description: Advisory Codex CLI debugging checkpoint for non-trivial failures. Use when Claude Code has already inspected an error locally and the same failure persists across consecutive attempts, or when a build, test, runtime, or tooling failure remains ambiguous after an initial local pass. Do not use for obvious typos, single-step syntax fixes, or failures with an already clear root cause.
---

# Codex Error Analysis

Get a bounded Codex debugging opinion when Claude Code is stuck on a real blocker. Treat the output as advisory only: Codex must not edit files or become the final decision-maker.

## Decide Whether To Use It

- Use this skill when the same non-trivial failure persists across two consecutive implementation attempts.
- Use it when a build, test, runtime, or tooling failure remains ambiguous after local inspection.
- Skip it for obvious syntax errors, missing imports with a clear fix, or trivial path typos.
- Run it once per failure cluster.

## Prepare A Diagnostic Brief

Create a short diagnostic brief in `/tmp` with:

- `Failure Summary`
- `What Was Attempted`
- `Exact Error Signature`
- `Pruned Log Excerpt`
- `Suspect Paths`
- `Environment Notes`
- `Known Unknowns`

See [error-brief-template.md](references/error-brief-template.md) for a ready-to-fill template.

## Run The Diagnostic Advisory

```bash
python3 scripts/run_codex_error_analysis.py \
  --project-root path/to/project \
  --brief-file /tmp/error-brief.md \
  --context-file path/to/relevant/file
```

The shared runner defaults to `gpt-5.4`. Override with `CLAUDE_CODEX_MODEL` if needed.

## Read The Output Correctly

- Expect likely causes first, then code-logic vs environment separation, then next checks.
- Treat Codex as another debugger, not the source of truth.
- Prefer the smallest next checks that can disambiguate the root cause quickly.
- If Codex is unavailable or times out, continue and note the external debugging pass was unavailable.

## Guardrails

- Codex runs in read-only sandbox mode. It cannot edit files.
- Do not call this skill before doing an initial local inspection.
- Do not pass giant unpruned logs.
- Do not treat speculative root-cause guesses as confirmed.

## Resources

- `scripts/run_codex_error_analysis.py` wraps `codex exec` with the shared advisory runner.
- [references/error-brief-template.md](references/error-brief-template.md) provides a compact diagnostic brief template.
