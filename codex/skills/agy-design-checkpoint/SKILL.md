---
name: agy-design-checkpoint
description: Advisory Antigravity CLI second opinion for high-impact technical design decisions. Use before finalizing architecture, protocols, repository layout, migrations, runtime direction, rollout strategy, or security boundaries. Do not use for routine implementation, small refactors, trivial edits, or low-risk questions.
---

# Antigravity Design Checkpoint

Get a bounded Antigravity CLI critique before Codex commits to a high-impact design direction. Treat the output as advice only: Antigravity must not edit files, apply patches, or become the final decision-maker.

## Decide Whether To Use It

- Use before finalizing architecture, protocol, repository layout, migration, rollout, runtime, infrastructure, or security-boundary decisions.
- Skip routine implementation choices, tiny refactors, obvious local fixes, and low-risk questions.
- Run it once per real decision checkpoint.

## Prepare A Design Brief

Create a short design brief in `/tmp` or another scratch path with:

- `Decision`
- `Goal`
- `Constraints`
- `Options Considered`
- `Current Preferred Direction`
- `Known Risks`
- `Relevant Official Docs`
- `Relevant Community References`
- `Relevant Paths`

See [design-brief-template.md](references/design-brief-template.md) for a ready-to-fill template.

## Run The Advisory Checkpoint

Run:

```bash
python3 scripts/run_agy_design_check.py \
  --project-root path/to/project-a \
  --project-root path/to/project-b \
  --brief-file /tmp/design-brief.md \
  --context-file path/to/spec-or-module
```

The wrapper launches Antigravity CLI in print mode as `agy -p "<prompt>"`. It does not pass a model flag because Antigravity uses its default latest model route.

Gemini CLI advisory skills have been removed from the Codex runtime because Gemini CLI is expected to go offline in June 2026. Migrate any old `$gemini-design-checkpoint` workflow to `$agy-design-checkpoint` as soon as possible.

`--context-file` paths are priority starting hints only. Antigravity runs from the selected workspace root and may inspect any other workspace-local files or directories it decides are relevant.

When one advisory pass must intentionally cover multiple projects, repeat `--project-root` for each target project root. The runner resolves them inside the current Codex workspace, switches Antigravity CLI's `cwd` to their common ancestor inside that workspace, and lists each project explicitly in the prompt.

## Read The Output Correctly

- Expect a concise verdict, best-practice alignment, system-level risks, module-level risks, alternatives, open questions, and recommendations.
- Check whether Antigravity compared the preferred direction against both official documentation and community practice when the topic depends on external frameworks, APIs, infrastructure, or standards.
- Treat Antigravity as another reviewer, not the source of truth.
- Validate any claim against local code, docs, and project constraints before acting on it.
- If Antigravity is unavailable, times out, or returns noise, continue and note that the advisory pass was unavailable only when it materially affects confidence.

## Guardrails

- Do not ask Antigravity to edit files or output patches.
- Keep the brief compact. Prefer local paths plus summaries over huge pasted docs.
- Ask Antigravity to challenge both the whole-system design and module-level boundaries; a locally clean module can still be part of a poor overall architecture.
- If external best-practice evidence matters, include the official or community references you already know in the brief so Antigravity can evaluate them instead of guessing.

## Resources

- `scripts/run_agy_design_check.py` wraps Antigravity CLI with project-root execution, print-mode `agy -p` invocation, workspace-local path filtering, and design-review instructions.
- [references/design-brief-template.md](references/design-brief-template.md) provides a compact template for design briefs.
