---
name: agy-review
description: Advisory Antigravity CLI code review for completed code changes. Use after meaningful code changes to get a concise external review focused on bugs, regressions, missing tests, risky assumptions, edge cases, unused code, over-complicated implementations, or structural risks.
---

# Antigravity Review

Get a bounded Antigravity CLI review after code changes are complete. Treat the output as a second opinion only: Antigravity must not edit files, apply patches, or become the final decision-maker.

## Instructions

1. Decide whether to use it. Use after non-trivial code changes and before the final answer. Skip when no code changed, only tiny low-risk edits were made, or the user only asked for analysis.

2. Prepare a compact review brief in `/tmp` with `Change Summary`, `Risk Areas`, `Files Changed`, `Diff Stat`, `Selected Diff Or Excerpts`, and `Known Gaps`. Prefer compact summaries plus local file paths over dumping the entire diff.

3. Run the advisory review:

```bash
python3 $AGENT_SKILLS_DIR/claude-code/skills/agy-review/scripts/run_agy_review.py \
  --project-root <path/to/project> \
  --brief-file /tmp/review-brief.md \
  --context-file <path/to/changed/file> \
  --output-file /tmp/agy-review-$(date +%s).md
```

For structural mode:

```bash
python3 $AGENT_SKILLS_DIR/claude-code/skills/agy-review/scripts/run_agy_review.py \
  --mode structural \
  --project-root <path/to/project> \
  --brief-file /tmp/review-brief.md \
  --context-file <path/to/changed/file> \
  --output-file /tmp/agy-review-$(date +%s).md
```

4. Read the output correctly. Validate any claim against the actual diff before acting on it. If Antigravity is unavailable, times out, or returns noise, continue and note the external review was unavailable only when it affects confidence.

The runner defaults to `agy -p "<prompt>"` print mode and can use `agy -i "<prompt>"` when `CLAUDE_AGY_MODE=interactive` or `"mode": "interactive"` is set in `~/.claude/agy_cli.json`. If `agy` is not on `PATH`, set `CLAUDE_AGY_CMD` or the config file's `"command"` to the CLI path, for example `~/.local/bin/agy`.

When supported by `agy`, the runner passes `--model "Gemini 3.5 Flash (High)"` by default. Override with `CLAUDE_AGY_MODEL` or config `"model"`. Supported values are `Gemini 3.5 Flash (High)`, `Gemini 3.1 Pro (High)`, `Claude Sonnet 4.6 (Thinking)`, and `Claude Opus 4.6 (Thinking)`.

For multi-project advisory scopes, the runner passes extra project roots through repeatable `--add-dir` flags when supported by `agy`.

If `agy` reports `E... not logged into Antigravity`, the wrapper prints the matching `W...` and `E...` log lines and relaunches `agy` up to 5 times by default. If the skill command still exits with a login failure after those internal retries, rerun the same command with the same brief and context files up to 2 more times before treating Antigravity as unavailable.

This skill has been smoke-tested with Antigravity CLI `agy` version `1.0.7`. Re-run tests and both print/interactive advisory smoke tests after upgrading `agy`.

## Guardrails

- Do not ask Antigravity to edit files or output patches.
- Keep the review bounded and concise; one pass is usually enough.
- Use structural mode only when the change needs a wider design pass.

$ARGUMENTS
