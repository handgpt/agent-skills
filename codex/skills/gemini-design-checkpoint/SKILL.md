---
name: gemini-design-checkpoint
description: Advisory Gemini CLI second-opinion for high-impact technical design decisions. Use when Codex is about to choose or recommend an overall architecture, protocol, repository layout, migration plan, runtime or infrastructure direction, security boundary, rollout strategy, or other major design choice and wants a concise external critique before proceeding. Do not use for routine implementation, small refactors, trivial edits, or low-risk questions.
---

# Gemini Design Checkpoint

Get a short, critical second opinion from Gemini before locking in a major technical direction. Treat the result as advisory only: do not let Gemini edit files, apply patches, or override Codex's own judgment.

This checkpoint is not just "spot obvious risks." It should explicitly test whether the preferred direction follows current best practices, whether the overall architecture and the module-level design both make sense, and whether the recommendation is supported by official documentation and real community experience when those sources matter. It should also look for disconfirming evidence, not just supporting evidence, before endorsing the preferred direction.

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

Prefer summaries over raw dumps. If a document is large, summarize it in the brief and point Gemini at the relevant local paths instead of pasting full file bodies.

If you already know the official docs or community references that matter, include them in the brief. If not, Gemini should still try to check official docs and community practice before concluding whenever the decision depends on frameworks, APIs, infrastructure, or standards. If the preferred direction intentionally deviates from a default best practice, make the constraint or operating tradeoff explicit so Gemini can judge whether that deviation is actually justified.

See [design-brief-template.md](references/design-brief-template.md) for a ready-to-fill template.

## Run The Advisory Pass

Run:

```bash
python3 scripts/run_gemini_design_check.py \
  --project-root path/to/android \
  --project-root path/to/ios \
  --brief-file /tmp/design-brief.md \
  --context-file path/to/doc-or-spec.md
```

Add `--context-file` only for the few files or directories Gemini should treat as priority starting points. Gemini now runs from the project root and may inspect other workspace-local files on its own when needed.

`--brief-file` and `--context-file` are local filesystem paths. The wrapper should inline the compact brief text into the prompt and tell Gemini to inspect the listed local paths directly on disk.

When one design checkpoint must intentionally cover multiple projects, repeat `--project-root` for each target project root. The runner will resolve them inside the current Codex workspace, switch Gemini's `cwd` to their common ancestor inside that workspace, list each project explicitly in the prompt, stamp the prompt with a run marker plus project-scope key, and reuse sessions by the full project set rather than by one repo root.

The wrapper should launch Gemini from the current single-project or multi-project workspace root, send the fully assembled prompt inline, reuse the most recent saved Gemini design-checkpoint session for the same project set and lane when possible, run in full-access mode via `--approval-mode yolo` plus `GEMINI_SANDBOX=false`, and only pass workspace-local `--context-file` paths as hints.

The default execution path is interactive: `gemini -i "<prompt>"` runs under a PTY, and the shared runner observes Gemini's project session file under `~/.gemini/tmp/<project>/chats/` to detect when the advisory turn is finished and recover the final answer. Keep the older headless path available for comparison with `--runner-mode headless` or `CODEX_GEMINI_RUN_MODE=headless`.

`--context-file` paths are priority starting hints only. Gemini runs from the selected workspace root and may inspect any other workspace-local files or directories it decides are relevant.

The shared runner should default to Gemini CLI's stable `pro` alias via `--model pro` so this skill stays on the latest Pro-class route without hard-coding a fast-changing version string. If needed, override it with `CODEX_GEMINI_MODEL`.

Out-of-workspace `--context-file` paths must be skipped rather than copied into the workspace for Gemini to inspect.

## Read The Output Correctly

- Expect a concise critique with sections for verdict, best-practice alignment, system-level risks, module-level risks, alternatives, open questions, and recommendation.
- Evaluate each point yourself. Accept, reject, or defer it explicitly in your own reasoning.
- Treat "best practice" as a two-level check: the whole design shape and the module boundaries must both make sense. Local module quality does not rescue a weak overall architecture.
- When Gemini relies on external guidance, prefer conclusions grounded in official documentation and community experience rather than unsupported intuition.
- Review only workspace-local files and directories. Ignore any path outside the current workspace root, even if it appears in the brief or prior thread context.
- Once the advisory process has started, treat the full configured timeout as normal waiting time. With the default configuration, allow Gemini up to 20 minutes before treating the run as timed out.
- If the Gemini process is still running but has not produced output yet, keep waiting. Do not restart it, request escalation, or assume failure solely because the run is slow.
- If Gemini is unavailable, times out, or returns low-signal output, continue without retry loops and note that the advisory pass was unavailable.

## Guardrails

- Do not ask Gemini to modify files or generate patches.
- Do not upload or paste unnecessary secrets, credentials, or huge logs.
- The default timeout is 20 minutes to accommodate slow Gemini CLI runs. Only raise it further when the user explicitly asks for a deeper external review.
- Use this skill before a major design commitment, not as a replacement for implementation work.

## Resources

- `scripts/run_gemini_design_check.py` wraps Gemini CLI with the shared advisory runner, project-root execution, per-project design-lane session reuse, interactive session-file result recovery by default, a switchable headless fallback path, workspace-root exploration, workspace-only context filtering, and result recovery.
- [references/design-brief-template.md](references/design-brief-template.md) provides a compact brief template for the advisory pass.
