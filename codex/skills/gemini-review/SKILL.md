---
name: gemini-review
description: Advisory Gemini CLI code review for completed code changes. Use when Codex has already modified code and wants a concise external review focused on bugs, regressions, missing tests, risky assumptions, overlooked edge cases, unused code, or over-complicated implementations before the final response. Use only after meaningful code changes or non-trivial diffs. Do not use for design-only conversations, trivial edits, or when no code was changed.
---

# Gemini Review

Get a bounded Gemini review after code changes are complete. Treat the output as a second opinion only: Gemini must not edit files, apply patches, or become the final decision-maker.

## Decide Whether To Use It

- Use this skill after non-trivial code changes and before the final answer.
- Skip it when no code changed, when only tiny low-risk edits were made, or when the user only asked for analysis.
- Run it once per finished change set. Do not call it during every implementation step.

## Prepare A Review Brief

Create a short review brief in `/tmp` or another scratch path with:

- `Change Summary`
- `Risk Areas`
- `Files Changed`
- `Diff Stat`
- `Selected Diff Or Excerpts`
- `Known Gaps`

Use excerpts only when they add signal. Prefer a compact summary plus local file and directory paths instead of dumping the entire repository diff.

See [review-brief-template.md](references/review-brief-template.md) for a ready-to-fill template.

## Run The Advisory Review

Run:

```bash
python3 scripts/run_gemini_review.py \
  --brief-file /tmp/review-brief.md \
  --context-file path/to/changed/file.ext
```

Attach only the key changed files or targeted excerpts that matter to the review.

`--brief-file` and `--context-file` are local filesystem paths. The wrapper should tell Gemini to inspect those paths directly on disk instead of inlining their contents into the prompt. Prefer passing changed-file paths over pasting large hunks when local path access is sufficient.

The wrapper should run Gemini from the current project root, reuse the latest Gemini session for that project when possible, stage the brief into a hidden bridge directory under the project root, and only pass `--context-file` paths that are already inside the current workspace.

Out-of-workspace `--context-file` paths must be skipped rather than copied into the workspace for Gemini to inspect.

Bridge brief files should be treated as temporary and pruned automatically over time.

If the project uses Git, ignore `.codex-gemini-advisories/` so staged advisory brief files do not pollute working tree status.

## Read The Output Correctly

- Expect findings-first output: top findings, regression risks, missing tests, things to verify, and an overall assessment.
- Treat Gemini as another reviewer, not the source of truth.
- Validate any claim against the actual diff before acting on it.
- Review only workspace-local files and directories. Ignore any path outside the current project root, even if it appears in the brief or prior thread context.
- Ask Gemini to look not only for behavioral bugs, but also for dead code, stale compatibility branches, duplicated logic, and implementation bloat that can be safely simplified.
- Once the advisory process has started, treat the full configured timeout as normal waiting time. With the default configuration, allow Gemini up to 20 minutes before treating the run as timed out.
- If the Gemini process is still running but has not produced output yet, keep waiting. Do not restart it, request escalation, or assume failure solely because the run is slow.
- If Gemini is unavailable, times out, or returns noise, continue and note that the external review pass was unavailable.

## Guardrails

- Do not ask Gemini to edit files or output patches.
- Do not use this skill before code exists; use a design checkpoint instead if the task is still architectural.
- Keep the review bounded and concise; one pass is usually enough.
- Prefer changed-file and directory paths over huge prompt bodies. Add excerpts only when path-based inspection would miss important context.
- Prefer concrete simplification opportunities over vague style commentary. Only call out removable code or complexity when the reasoning is specific and safe.
- Treat "safe simplification" narrowly: preserved behavior, preserved failure handling, and clearer code. Reject clever rewrites that merely compress lines.

## Resources

- `scripts/run_gemini_review.py` wraps Gemini CLI with timeout handling, project-root execution, per-project session reuse, workspace-only context filtering, and stable review instructions.
- [references/review-brief-template.md](references/review-brief-template.md) provides a compact template for review briefs.
