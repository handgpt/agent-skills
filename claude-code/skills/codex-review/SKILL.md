---
name: codex-review
description: Advisory Codex CLI code review for completed code changes. Use when Claude Code has already modified code and wants a concise external review focused on bugs, regressions, missing tests, risky assumptions, overlooked edge cases, unused code, or over-complicated implementations. Use only after meaningful code changes or non-trivial diffs. Do not use for design-only conversations, trivial edits, or when no code was changed.
---

# Codex Review

Get a bounded Codex review after code changes are complete. Treat the output as a second opinion only: Codex must not edit files or become the final decision-maker.

This skill uses `codex review`, the built-in review subcommand of the Codex CLI. It operates in read-only mode and outputs structured review findings.

## Decide Whether To Use It

- Use this skill after non-trivial code changes and before the final answer.
- Skip it when no code changed, when only tiny low-risk edits were made, or when the user only asked for analysis.
- Run it once per finished change set. Do not call it during every implementation step.

## Run The Review

For reviewing uncommitted changes:

```bash
python3 scripts/run_codex_review.py \
  --project-root path/to/project \
  --uncommitted
```

For reviewing changes against a base branch:

```bash
python3 scripts/run_codex_review.py \
  --project-root path/to/project \
  --base main
```

For reviewing a specific commit:

```bash
python3 scripts/run_codex_review.py \
  --project-root path/to/project \
  --commit abc1234
```

The shared runner defaults to `gpt-5.4`. Override with `CLAUDE_CODEX_MODEL` if needed.

## Read The Output Correctly

- Treat Codex as another reviewer, not the source of truth.
- Validate any claim against the actual diff before acting on it.
- If Codex is unavailable or times out, continue and note the external review was unavailable.

## Guardrails

- Codex runs in read-only sandbox mode. It cannot edit files.
- Do not use this skill before code exists; use a design checkpoint instead.
- Keep the review bounded; one pass is usually enough.

## Resources

- `scripts/run_codex_review.py` wraps `codex review` with model configuration and timeout.
- [references/review-brief-template.md](references/review-brief-template.md) provides guidance on structuring custom review prompts.
