---
name: agy-error-analysis
description: Advisory Antigravity CLI debugging checkpoint for non-trivial failures. Use when Codex has already inspected an error locally and the same failure persists across consecutive attempts, or when a build, test, runtime, or tooling failure remains ambiguous after an initial local pass. Focus on likely causes, code-vs-environment separation, and the highest-signal next checks. Do not use for obvious typos, single-step syntax fixes, or failures with an already clear root cause.
---

# Antigravity Error Analysis

Get a bounded Antigravity CLI debugging second opinion after Codex has already done an initial local pass. Treat the output as advice only: Antigravity must not edit files, apply patches, or become the final decision-maker.

## Decide Whether To Use It

- Use when the same non-trivial build, test, runtime, or tooling failure persists across consecutive attempts.
- Use when the root cause remains ambiguous after local inspection.
- Skip obvious typos, single-step syntax fixes, and failures whose root cause is already clear.
- Run it once per persistent failure cluster.

## Prepare An Error Brief

Create a short diagnostic brief in `/tmp` or another scratch path with:

- `Failure Summary`
- `What Was Attempted`
- `Exact Error Signature`
- `Pruned Log Excerpt`
- `Suspect Paths`
- `Environment Notes`
- `Known Unknowns`

See [error-brief-template.md](references/error-brief-template.md) for a ready-to-fill template.

## Run The Advisory Analysis

Run:

```bash
python3 scripts/run_agy_error_analysis.py \
  --project-root path/to/project \
  --brief-file /tmp/error-brief.md \
  --context-file path/to/suspect/file-or-directory
```

The wrapper launches Antigravity CLI in print mode as `agy -p "<prompt>"`. It does not pass a model flag because Antigravity uses its default latest model route.

Gemini CLI advisory skills have been removed from the Codex runtime because Gemini CLI is expected to go offline in June 2026. Migrate any old `$gemini-error-analysis` workflow to `$agy-error-analysis` as soon as possible.

`--context-file` paths are priority starting hints only. Antigravity runs from the selected workspace root and may inspect any other workspace-local files or directories it decides are relevant.

When one failure spans multiple projects, repeat `--project-root` for each target project root so Antigravity receives the correct project scope and runs from their common workspace ancestor.

## Read The Output Correctly

- Expect likely causes, code logic errors, environmental issues, most useful checks, recovery options, and confidence.
- Prefer discriminating checks that separate causes quickly.
- Validate any claim against the actual code, logs, and environment before acting on it.
- If Antigravity is unavailable, times out, or returns noise, continue with local debugging and mention the unavailable advisory pass only if it affects confidence.

## Guardrails

- Do not ask Antigravity to edit files or output patches.
- Keep logs pruned. Paste only the smallest high-signal failure excerpt.
- Do not use this skill to outsource ordinary debugging. Codex should inspect locally first.
- Avoid broad refactor prompts. Ask for likely root causes and the next checks that best separate them.

## Resources

- `scripts/run_agy_error_analysis.py` wraps Antigravity CLI with project-root execution, print-mode `agy -p` invocation, workspace-local path filtering, and debugging instructions.
- [references/error-brief-template.md](references/error-brief-template.md) provides a compact template for diagnostic briefs.
