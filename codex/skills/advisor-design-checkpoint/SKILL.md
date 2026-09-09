---
name: advisor-design-checkpoint
description: "Get an external second opinion before major architecture, protocol, migration, runtime, rollout, or security decisions. Skip routine implementation and small refactors. Default provider: Antigravity CLI; Grok optional."
---

# Advisor Design Checkpoint

Get a bounded external critique before Codex commits to a high-impact design direction. Treat the output as advice only: the advisor must not edit files, apply patches, or become the final decision-maker.

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
python3 scripts/run_advisor_design_check.py \
  --project-root path/to/project-a \
  --project-root path/to/project-b \
  --brief-file /tmp/design-brief.md \
  --context-file path/to/spec-or-module
```

Use the [shared runtime guide](../shared/references/advisor-runtime.md) when
running the advisor. It defines provider configuration, bounded retries, timeout,
and inspection scope once for all advisor skills.

## Read The Output Correctly

- Expect a concise verdict, best-practice alignment, system-level risks, module-level risks, alternatives, open questions, and recommendations.
- Check whether the advisor compared the preferred direction against both official documentation and community practice when the topic depends on external frameworks, APIs, infrastructure, or standards.
- Treat the selected advisor as another reviewer, not the source of truth.
- Validate any claim against local code, docs, and project constraints before acting on it.
- If the advisor is unavailable, times out, or returns noise, continue and note that the advisory pass was unavailable only when it materially affects confidence.

## Guardrails

- Do not ask the advisor to edit files or output patches.
- Keep the brief compact. Prefer local paths plus summaries over huge pasted docs.
- Ask the advisor to challenge both the whole-system design and module-level boundaries; a locally clean module can still be part of a poor overall architecture.
- If external best-practice evidence matters, include the official or community references you already know in the brief so the advisor can evaluate them instead of guessing.

## Resources

- `scripts/run_advisor_design_check.py` wraps the shared advisory runner with provider routing, project-root execution, Antigravity or Grok transport selection, workspace-local path filtering, and design-review instructions.
- [references/design-brief-template.md](references/design-brief-template.md) provides a compact template for design briefs.
