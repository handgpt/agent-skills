---
name: gemini-review
description: Advisory Gemini CLI code review for completed code changes. Use when Codex has already modified code and wants a concise external review focused on bugs, regressions, missing tests, risky assumptions, overlooked edge cases, unused code, over-complicated implementations, or structural risks at important checkpoints before the final response. Use only after meaningful code changes or non-trivial diffs. Do not use for design-only conversations, trivial edits, or when no code was changed.
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
  --brief-file /tmp/review-brief.md \
  --context-file path/to/changed/file.ext
```

For important checkpoints that need a broader module and architecture pass, run:

```bash
python3 scripts/run_gemini_review.py \
  --mode structural \
  --brief-file /tmp/review-brief.md \
  --context-file path/to/changed/file.ext \
  --context-file path/to/relevant/module-or-directory
```

Attach only the key changed files or targeted excerpts that matter to the review. Gemini now runs from the workspace root and may inspect additional workspace-local files on its own when needed.

`--brief-file` and `--context-file` are local filesystem paths. The wrapper should inline the compact brief text into the prompt and tell Gemini to inspect the listed local paths directly on disk. Prefer passing changed-file paths over pasting large hunks when local path access is sufficient.

The wrapper should launch Gemini from the current project root in headless mode, send the fully assembled prompt inline, prefer Gemini CLI's official machine-readable output via `--output-format json`, reuse the most recent saved Gemini review session for the same project when possible, run in full-access mode via `--approval-mode yolo` plus `GEMINI_SANDBOX=false`, and only pass workspace-local `--context-file` paths as priority hints.

`--context-file` paths are priority starting hints only. Gemini runs from the project root and may inspect any other workspace-local files or directories it decides are relevant.

The shared runner should default to Gemini CLI's stable `pro` alias via `--model pro` so this skill stays on the latest Pro-class route without hard-coding a fast-changing version string. If needed, override it with `CODEX_GEMINI_MODEL`.

Out-of-workspace `--context-file` paths must be skipped rather than copied into the workspace for Gemini to inspect.

## Read The Output Correctly

- Expect findings-first output: top findings, regression risks, missing tests, things to verify, and an overall assessment.
- In structural mode, expect an additional `Structural & Architectural Risks` section focused on module boundaries, coupling, ownership, and interface design.
- Treat Gemini as another reviewer, not the source of truth.
- Validate any claim against the actual diff before acting on it.
- Review only workspace-local files and directories. Ignore any path outside the current project root, even if it appears in the brief or prior thread context.
- Ask Gemini to look not only for behavioral bugs, but also for dead code, stale compatibility branches, duplicated logic, and implementation bloat that can be safely simplified.
- At important checkpoints, ask Gemini to zoom out from the changed files and inspect the surrounding modules and directories for structural issues.
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
- Use structural mode only when the change actually needs a wider design pass. Do not turn every routine diff review into a full-repo audit.

## Resources

- `scripts/run_gemini_review.py` wraps Gemini CLI with the shared headless advisory runner, project-root execution, per-project review-lane session reuse, official JSON result parsing, workspace-root exploration, workspace-only context filtering, and stable review instructions.
- [references/review-brief-template.md](references/review-brief-template.md) provides a compact template for review briefs.
