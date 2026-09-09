---
name: advisor-error-analysis
description: "Get an external debugging second opinion after local inspection when a non-trivial failure persists or remains ambiguous. Skip obvious fixes and known root causes. Default provider: Antigravity CLI; Grok optional."
---

# Advisor Error Analysis

Get a bounded external debugging second opinion after Codex has already done an initial local pass. Treat the output as advice only: the advisor must not edit files, apply patches, or become the final decision-maker.

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
python3 scripts/run_advisor_error_analysis.py \
  --project-root path/to/project \
  --brief-file /tmp/error-brief.md \
  --context-file path/to/suspect/file-or-directory
```

Use the [shared runtime guide](../shared/references/advisor-runtime.md) when
running the advisor. It defines provider configuration, bounded retries, timeout,
and inspection scope once for all advisor skills.

## Read The Output Correctly

- Expect likely causes, code logic errors, environmental issues, most useful checks, recovery options, and confidence.
- Prefer discriminating checks that separate causes quickly.
- Validate any claim against the actual code, logs, and environment before acting on it.
- If the advisor is unavailable, times out, or returns noise, continue with local debugging and mention the unavailable advisory pass only if it affects confidence.

## Guardrails

- Do not ask the advisor to edit files or output patches.
- Keep logs pruned. Paste only the smallest high-signal failure excerpt.
- Do not use this skill to outsource ordinary debugging. Codex should inspect locally first.
- Avoid broad refactor prompts. Ask for likely root causes and the next checks that best separate them.

## Resources

- `scripts/run_advisor_error_analysis.py` wraps the shared advisory runner with provider routing, project-root execution, Antigravity or Grok transport selection, workspace-local path filtering, and debugging instructions.
- [references/error-brief-template.md](references/error-brief-template.md) provides a compact template for diagnostic briefs.
