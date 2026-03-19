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

`--brief-file` and `--context-file` are local filesystem paths. The wrapper should inline the compact brief text into the prompt and tell Gemini to inspect the listed local paths directly on disk.

The wrapper should launch Gemini from the current project root, send the fully assembled prompt inline, reuse the most recent saved Gemini error-analysis session for the same project and lane when possible, run in full-access mode via `--approval-mode yolo` plus `GEMINI_SANDBOX=false`, and only pass workspace-local `--context-file` paths as priority hints.

The default execution path is interactive: `gemini -i "<prompt>"` runs under a PTY, and the shared runner watches Gemini's project session file under `~/.gemini/tmp/<project>/chats/` to detect when the current diagnostic turn is complete and recover the final answer. Keep the older headless path available for comparison with `--runner-mode headless` or `CODEX_GEMINI_RUN_MODE=headless`.

`--context-file` paths are priority starting hints only. Gemini runs from the project root and may inspect any other workspace-local files or directories it decides are relevant.

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

- `scripts/run_gemini_error_analysis.py` wraps Gemini CLI with the shared advisory runner plus per-project error-lane session reuse, interactive session-file result recovery by default, and a switchable headless fallback path.
- [error-brief-template.md](references/error-brief-template.md) provides a compact diagnostic brief template.
