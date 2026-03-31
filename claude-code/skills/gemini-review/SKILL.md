---
name: gemini-review
description: Advisory Gemini CLI code review for completed code changes. Use when Claude Code has already modified code and wants a concise external review focused on bugs, regressions, missing tests, risky assumptions, overlooked edge cases, unused code, over-complicated implementations, or structural risks at important checkpoints before the final response. Use only after meaningful code changes or non-trivial diffs. Do not use for design-only conversations, trivial edits, or when no code was changed.
---

# Gemini Review

Get a bounded Gemini review after code changes are complete. Treat the output as a second opinion only: Gemini must not edit files, apply patches, or become the final decision-maker.

## Decide Whether To Use It

- Use this skill after non-trivial code changes and before the final answer.
- Skip it when no code changed, when only tiny low-risk edits were made, or when the user only asked for analysis.
- Run it once per finished change set. Do not call it during every implementation step.
- Use `--mode structural` at important checkpoints: shared or core modules, public interfaces, dependency wiring, top-level configuration, cross-module changes, or any edit that can change module boundaries and ownership.

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
  --project-root path/to/project \
  --brief-file /tmp/review-brief.md \
  --context-file path/to/changed/file.ext
```

For important checkpoints that need a broader module and architecture pass, run:

```bash
python3 scripts/run_gemini_review.py \
  --mode structural \
  --project-root path/to/project \
  --brief-file /tmp/review-brief.md \
  --context-file path/to/changed/file.ext \
  --context-file path/to/relevant/module-or-directory
```

Attach only the key changed files or targeted excerpts that matter to the review. Gemini runs from the workspace root and may inspect additional workspace-local files on its own when needed.

`--brief-file` and `--context-file` are local filesystem paths. The wrapper inlines the compact brief text into the prompt and tells Gemini to inspect the listed local paths directly on disk.

When one advisory pass must intentionally cover multiple projects, repeat `--project-root` for each target project root.

The wrapper launches Gemini from the workspace root, sends the fully assembled prompt inline, reuses the most recent saved Gemini review session for the same project set and lane when possible, runs in full-access mode via `--approval-mode yolo` plus `GEMINI_SANDBOX=false`, and only passes workspace-local `--context-file` paths as priority hints.

The default execution path is interactive: `gemini -i "<prompt>"` runs under a PTY, and the shared runner watches Gemini's workspace session file to detect when the current review turn is complete and recover the final answer.

The shared runner defaults to Gemini CLI's stable `pro` alias via `--model pro`. Override with `CLAUDE_GEMINI_MODEL` if needed.

## Read The Output Correctly

- Expect findings-first output: top findings, regression risks, missing tests, things to verify, and an overall assessment.
- In structural mode, expect an additional `Structural & Architectural Risks` section.
- Treat Gemini as another reviewer, not the source of truth.
- Validate any claim against the actual diff before acting on it.
- Ask Gemini to look not only for behavioral bugs, but also for dead code, stale compatibility branches, duplicated logic, and implementation bloat.
- Once the advisory process has started, treat the full configured timeout as normal waiting time (up to 20 minutes by default).
- If Gemini is unavailable, times out, or returns noise, continue and note the external review was unavailable.

## Guardrails

- Do not ask Gemini to edit files or output patches.
- Do not use this skill before code exists; use a design checkpoint instead.
- Keep the review bounded and concise; one pass is usually enough.
- Use structural mode only when the change actually needs a wider design pass.

## Resources

- `scripts/run_gemini_review.py` wraps Gemini CLI with the shared advisory runner.
- [references/review-brief-template.md](references/review-brief-template.md) provides a compact template for review briefs.
