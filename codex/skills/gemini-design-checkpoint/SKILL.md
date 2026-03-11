---
name: gemini-design-checkpoint
description: Advisory Gemini CLI second-opinion for high-impact technical design decisions. Use when Codex is about to choose or recommend an overall architecture, protocol, repository layout, migration plan, runtime or infrastructure direction, security boundary, rollout strategy, or other major design choice and wants a concise external critique before proceeding. Do not use for routine implementation, small refactors, trivial edits, or low-risk questions.
---

# Gemini Design Checkpoint

Get a short, critical second opinion from Gemini before locking in a major technical direction. Treat the result as advisory only: do not let Gemini edit files, apply patches, or override Codex's own judgment.

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
- `Relevant Paths`

Prefer summaries over raw dumps. If a document is large, summarize it in the brief and point Gemini at the relevant local paths instead of pasting full file bodies.

See [design-brief-template.md](references/design-brief-template.md) for a ready-to-fill template.

## Run The Advisory Pass

Run:

```bash
python3 scripts/run_gemini_design_check.py \
  --brief-file /tmp/design-brief.md \
  --context-file path/to/doc-or-spec.md
```

Add `--context-file` only for the few files or directories Gemini actually needs. Keep the advisory pass compact and bounded.

`--brief-file` and `--context-file` are local filesystem paths. The wrapper should tell Gemini to inspect those paths directly on disk instead of inlining their contents into the prompt.

The wrapper should run Gemini from the current project root, reuse the latest Gemini session for that project when possible, stage the brief into a hidden bridge directory under the project root, and only pass `--context-file` paths that are already inside the current workspace.

Out-of-workspace `--context-file` paths must be skipped rather than copied into the workspace for Gemini to inspect.

Bridge brief files should be treated as temporary and pruned automatically over time.

If the project uses Git, ignore `.codex-gemini-advisories/` so staged advisory brief files do not pollute working tree status.

## Read The Output Correctly

- Expect a concise critique with sections for verdict, critical risks, blind spots, alternatives, open questions, and recommendation.
- Evaluate each point yourself. Accept, reject, or defer it explicitly in your own reasoning.
- Review only workspace-local files and directories. Ignore any path outside the current project root, even if it appears in the brief or prior thread context.
- Once the advisory process has started, treat the full configured timeout as normal waiting time. With the default configuration, allow Gemini up to 20 minutes before treating the run as timed out.
- If the Gemini process is still running but has not produced output yet, keep waiting. Do not restart it, request escalation, or assume failure solely because the run is slow.
- If Gemini is unavailable, times out, or returns low-signal output, continue without retry loops and note that the advisory pass was unavailable.

## Guardrails

- Do not ask Gemini to modify files or generate patches.
- Do not upload or paste unnecessary secrets, credentials, or huge logs.
- The default timeout is 20 minutes to accommodate slow Gemini CLI runs. Only raise it further when the user explicitly asks for a deeper external review.
- Use this skill before a major design commitment, not as a replacement for implementation work.

## Resources

- `scripts/run_gemini_design_check.py` wraps Gemini CLI with timeout handling, project-root execution, per-project session reuse, workspace-only context filtering, and a positional-argument fallback if `-p/--prompt` is unavailable.
- [references/design-brief-template.md](references/design-brief-template.md) provides a compact brief template for the advisory pass.
