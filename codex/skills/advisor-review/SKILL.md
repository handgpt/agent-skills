---
name: advisor-review
description: "Review existing code or artifacts when explicitly requested, including audits without a diff. Automatically review completed high-risk changes for bugs, regressions, structural risks, and missing validation. Skip automatic review for ordinary low-risk edits. Default provider: Antigravity CLI; Grok optional."
---

# Advisor Review

Get a bounded external advisor review of completed changes or an explicitly requested audit of existing work. Treat the output as a second opinion only: the advisor must not edit files, apply patches, or become the final decision-maker.

## Decide Whether To Use It

- Honor explicit requests for advisor review, including read-only audits with no diff.
- Automatically review completed changes affecting core/shared modules, public interfaces, dependencies, security boundaries, migrations, or cross-module behavior. For ordinary local changes, complete appropriate validation and use an advisor only when an unresolved risk warrants it.
- Use this skill for finished artifacts such as articles, docs, specs, and prompts when a general design checkpoint is the wrong shape.
- Skip automatic invocation for low-risk edits and analysis-only work; this heuristic never suppresses an explicit review request.
- Run once per completed change set or requested audit. Do not repeat after addressing findings unless a new material risk remains.
- Use `--mode structural` at important checkpoints: shared or core modules, public interfaces, dependency wiring, top-level configuration, cross-module changes, or any edit that can change module boundaries and ownership.
- Use `--focus article`, `--focus doc`, `--focus spec`, `--focus prompt`, or `--focus general` for non-code artifacts.
- When `--mode structural` is combined with a non-code focus, the review checks artifact structure, argument flow, evidence dependencies, terminology, and audience fit rather than code module boundaries.

## Prepare A Review Brief

Create a short review brief in `/tmp` or another scratch path. For an existing-work audit, identify scope and baseline and mark diff fields not applicable. Include:

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
python3 scripts/run_advisor_review.py \
  --project-root path/to/android \
  --project-root path/to/ios \
  --brief-file /tmp/review-brief.md \
  --context-file path/to/changed/file.ext
```

For important checkpoints that need a broader module and architecture pass, run:

```bash
python3 scripts/run_advisor_review.py \
  --mode structural \
  --project-root path/to/android \
  --project-root path/to/ios \
  --project-root path/to/server \
  --brief-file /tmp/review-brief.md \
  --context-file path/to/changed/file.ext \
  --context-file path/to/relevant/module-or-directory
```

For artifact review, run:

```bash
python3 scripts/run_advisor_review.py \
  --focus article \
  --project-root path/to/project \
  --brief-file /tmp/review-brief.md \
  --context-file path/to/article-or-doc.md
```

`--brief-file` and `--context-file` are local filesystem paths. The wrapper inlines the compact brief text into the prompt and tells the selected advisor to inspect the listed local paths directly on disk.

When one advisory pass must intentionally cover multiple projects, repeat `--project-root` for each target project root. The runner resolves them inside the current Codex workspace, switches the advisor CLI's `cwd` to their common ancestor inside that workspace, passes the other existing project roots through provider-specific mechanisms when supported, and lists each project explicitly in the prompt with a project-scope key.

Use the [shared runtime guide](../shared/references/advisor-runtime.md) when
running the advisor. It defines provider configuration, bounded retries, timeout,
and inspection scope once for all advisor skills.

## Read The Output Correctly

- Expect findings-first output: top findings, regression risks, missing tests, things to verify, and an overall assessment.
- In code structural mode, expect an additional `Structural & Architectural Risks` section focused on module boundaries, coupling, ownership, and interface design.
- In artifact structural mode, expect `Structure & Organization Risks` focused on argument flow, evidence, terminology, and audience contract.
- In artifact focus, expect findings on accuracy, evidence, structure, clarity, missing checks, and things to verify.
- Treat the selected advisor as another reviewer, not the source of truth.
- Validate any claim against the actual diff before acting on it.
- Ask the advisor to look not only for behavioral bugs, but also for dead code, stale compatibility branches, duplicated logic, and implementation bloat that can be safely simplified.
- Once the advisory process has started, treat the full configured timeout as normal waiting time. With the default configuration, allow the advisor up to 20 minutes before treating the run as timed out.
- If the advisor is unavailable, times out, or returns noise, continue and note that the external review pass was unavailable.

## Guardrails

- Do not ask the advisor to edit files or output patches.
- Use the design checkpoint for a new architectural decision; review existing designs or prompts here when the user requests an audit.
- Keep the review bounded and concise; one pass is usually enough.
- Prefer changed-file and directory paths over huge prompt bodies. Add excerpts only when path-based inspection would miss important context.
- Prefer concrete simplification opportunities over vague style commentary. Only call out removable code or complexity when the reasoning is specific and safe.
- Treat "safe simplification" narrowly: preserved behavior, preserved failure handling, and clearer code. Reject clever rewrites that merely compress lines.

## Resources

- `scripts/run_advisor_review.py` wraps the shared advisory runner with provider routing, project-root execution, Antigravity or Grok transport selection, workspace-local context filtering, and stable review instructions.
- [references/review-brief-template.md](references/review-brief-template.md) provides a compact template for review briefs.
