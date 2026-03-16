---
name: gemini-error-analysis
description: Advisory Gemini CLI debugging checkpoint for non-trivial failures. Use when Codex has already inspected an error locally and the same failure persists across consecutive attempts, or when a build, test, runtime, or tooling failure remains ambiguous after an initial local pass. Focus on likely causes, code-vs-environment separation, and the highest-signal next checks. Do not use for obvious typos, single-step syntax fixes, or failures with an already clear root cause.
---

# Gemini Error Analysis

Get a bounded Gemini debugging opinion when Codex is stuck on a real blocker. Treat the output as advisory only: Gemini must not edit files, apply patches, or become the final decision-maker.

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
- Prefer the smallest log excerpt that still shows the error signature, nearest stack frames, and the immediate surrounding context.
- If the error output only exists in the terminal, write a compact excerpt into the diagnostic brief or a temporary file in `/tmp`.
- If the blocker might be environmental, summarize the environment signal explicitly instead of pasting unrelated source.

## Run The Diagnostic Advisory

Run:

```bash
python3 scripts/run_gemini_error_analysis.py \
  --brief-file /tmp/error-brief.md \
  --context-file path/to/relevant/file-or-log
```

Attach only the few source files, config files, or log excerpts that matter to the diagnosis.

`--brief-file` and `--context-file` are local filesystem paths. The wrapper should tell Gemini to inspect those paths directly on disk instead of inlining their contents into the prompt.

The wrapper should run Gemini from the current project root, reuse the latest Gemini session for that project when possible, stage advisory briefs into a hidden directory under the project root, and only pass `--context-file` paths that are already inside the current workspace.

By default, the shared runner uses expanded-module context: it keeps the explicit suspect files and logs, then automatically adds a bounded set of nearby parent/module directories so Gemini can inspect adjacent code and configs without jumping to a full-repo scan. Use `--strict-paths` only when the debugging pass must stay surgically narrow.

The shared runner should default to Gemini CLI's stable `pro` alias via `--model pro` so this skill stays on the latest Pro-class route without hard-coding a fast-changing version string. If needed, override it with `CODEX_GEMINI_MODEL`.

Out-of-workspace `--context-file` paths must be skipped rather than copied into the workspace for Gemini to inspect.

## Read The Output Correctly

- Expect likely causes first, then code-logic vs environment separation, then the most useful next checks.
- Treat Gemini as another debugger, not the source of truth.
- Ask Gemini to distinguish between code logic errors, environmental issues, and insufficient evidence.
- Prefer the smallest next checks that can disambiguate the root cause quickly.
- If Gemini is unavailable, times out, or returns noise, continue and note that the external debugging pass was unavailable.

## Guardrails

- Do not ask Gemini to edit files or output patches.
- Do not call this skill before doing an initial local inspection.
- Do not pass giant unpruned logs when a short excerpt would do.
- Do not treat speculative root-cause guesses as confirmed.
- Keep the debugging pass bounded and concise; one pass per failure cluster is usually enough.

## Resources

- `scripts/run_gemini_error_analysis.py` wraps Gemini CLI with the shared advisory runner.
- [error-brief-template.md](references/error-brief-template.md) provides a compact diagnostic brief template.
