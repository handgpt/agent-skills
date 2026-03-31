---
name: codex-design-checkpoint
description: Advisory Codex CLI second-opinion for high-impact technical design decisions. Use when Claude Code is about to choose or recommend an overall architecture, protocol, repository layout, migration plan, runtime or infrastructure direction, security boundary, or other major design choice and wants a concise external critique before proceeding. Do not use for routine implementation, small refactors, trivial edits, or low-risk questions.
---

# Codex Design Checkpoint

Get a short, critical second opinion from Codex before locking in a major technical direction. Treat the result as advisory only: do not let Codex edit files or override Claude Code's own judgment.

## Decide Whether To Use It

- Use this skill for decisions that are expensive to reverse: architecture, protocols, repository boundaries, migrations, deployment shape, trust boundaries, security/privacy design.
- Skip this skill for routine bug fixes, small refactors, naming tweaks, or straightforward implementation details.
- Run it once per decision point.

## Prepare A Compact Brief

Write a short brief in `/tmp` with:

- `Decision`
- `Goal`
- `Constraints`
- `Options Considered`
- `Current Preferred Direction`
- `Known Risks`
- `Relevant Official Docs` (optional)
- `Relevant Paths`

See [design-brief-template.md](references/design-brief-template.md) for a ready-to-fill template.

## Run The Advisory Pass

```bash
python3 scripts/run_codex_design_check.py \
  --project-root path/to/project \
  --brief-file /tmp/design-brief.md \
  --context-file path/to/doc-or-spec.md
```

The shared runner defaults to `gpt-5.4`. Override with `CLAUDE_CODEX_MODEL` if needed.

## Read The Output Correctly

- Expect verdict, best-practice alignment, system-level risks, module-level risks, alternatives, open questions, and recommendation.
- Evaluate each point yourself. Accept, reject, or defer it explicitly.
- If Codex is unavailable or times out, continue and note the advisory was unavailable.

## Guardrails

- Codex runs in read-only sandbox mode. It cannot edit files.
- Do not upload secrets, credentials, or huge logs.
- Use this skill before a major design commitment, not as a replacement for implementation work.

## Resources

- `scripts/run_codex_design_check.py` wraps `codex exec` with the shared advisory runner.
- [references/design-brief-template.md](references/design-brief-template.md) provides a compact brief template.
