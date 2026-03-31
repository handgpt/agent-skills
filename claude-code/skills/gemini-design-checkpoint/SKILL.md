---
name: gemini-design-checkpoint
description: Advisory Gemini CLI second-opinion for high-impact technical design decisions. Use when Claude Code is about to choose or recommend an overall architecture, protocol, repository layout, migration plan, runtime or infrastructure direction, security boundary, rollout strategy, or other major design choice and wants a concise external critique before proceeding. Do not use for routine implementation, small refactors, trivial edits, or low-risk questions.
---

# Gemini Design Checkpoint

Get a short, critical second opinion from Gemini before locking in a major technical direction. Treat the result as advisory only: do not let Gemini edit files, apply patches, or override Claude Code's own judgment.

This checkpoint is not just "spot obvious risks." It should explicitly test whether the preferred direction follows current best practices, whether the overall architecture and the module-level design both make sense, and whether the recommendation is supported by official documentation and real community experience when those sources matter.

## Decide Whether To Use It

- Use this skill for decisions that are expensive to reverse: architecture, protocols, repository boundaries, migrations, deployment shape, trust boundaries, security/privacy design, or large product-level tradeoffs.
- Skip this skill for routine bug fixes, small refactors, naming tweaks, formatting, copy edits, or straightforward implementation details.
- Run it once per decision point. Do not loop on repeated Gemini passes unless the first response is clearly unusable.

## Prepare A Compact Brief

Write a short brief in `/tmp` or another scratch path with these sections:

- `Decision`
- `Goal`
- `Constraints`
- `Options Considered`
- `Current Preferred Direction`
- `Known Risks`
- `Relevant Official Docs` (optional if already known)
- `Relevant Community References` (optional if already known)
- `Relevant Paths`

See [design-brief-template.md](references/design-brief-template.md) for a ready-to-fill template.

## Run The Advisory Pass

Run:

```bash
python3 scripts/run_gemini_design_check.py \
  --project-root path/to/project \
  --brief-file /tmp/design-brief.md \
  --context-file path/to/doc-or-spec.md
```

The shared runner defaults to Gemini CLI's stable `pro` alias via `--model pro`. Override with `CLAUDE_GEMINI_MODEL` if needed.

## Read The Output Correctly

- Expect a concise critique with sections for verdict, best-practice alignment, system-level risks, module-level risks, alternatives, open questions, and recommendation.
- Evaluate each point yourself. Accept, reject, or defer it explicitly in your own reasoning.
- Treat "best practice" as a two-level check: the whole design shape and the module boundaries must both make sense.
- When Gemini relies on external guidance, prefer conclusions grounded in official documentation and community experience.
- Once the advisory process has started, treat the full configured timeout as normal waiting time (up to 20 minutes by default).
- If Gemini is unavailable, times out, or returns low-signal output, continue and note the advisory was unavailable.

## Guardrails

- Do not ask Gemini to modify files or generate patches.
- Do not upload or paste unnecessary secrets, credentials, or huge logs.
- Use this skill before a major design commitment, not as a replacement for implementation work.

## Resources

- `scripts/run_gemini_design_check.py` wraps Gemini CLI with the shared advisory runner.
- [references/design-brief-template.md](references/design-brief-template.md) provides a compact brief template for the advisory pass.
