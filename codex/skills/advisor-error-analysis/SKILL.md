---
name: advisor-error-analysis
description: Advisory external debugging checkpoint for non-trivial failures. Use when Codex has already inspected an error locally and the same failure persists across consecutive attempts, or when a build, test, runtime, or tooling failure remains ambiguous after an initial local pass. Default provider is Antigravity CLI; Grok CLI can be selected by configuration. Focus on likely causes, code-vs-environment separation, and the highest-signal next checks. Do not use for obvious typos, single-step syntax fixes, or failures with an already clear root cause.
---

# Advisor Error Analysis

Get a bounded external debugging second opinion after Codex has already done an initial local pass. Treat the output as advice only: the advisor must not edit files, apply patches, or become the final decision-maker.

## Decide Whether To Use It

- Use when the same non-trivial build, test, runtime, or tooling failure persists across consecutive attempts.
- Use when the root cause remains ambiguous after local inspection.
- Skip obvious typos, single-step syntax fixes, and failures whose root cause is already clear.
- Run it once per persistent failure cluster.

## Prepare An Error Brief

Create a short diagnostic brief in `/tmp` or another scratch path with:

- `Failure Summary`
- `What Was Attempted`
- `Exact Error Signature`
- `Pruned Log Excerpt`
- `Suspect Paths`
- `Environment Notes`
- `Known Unknowns`

See [error-brief-template.md](references/error-brief-template.md) for a ready-to-fill template.

## Run The Advisory Analysis

Run:

```bash
python3 scripts/run_advisor_error_analysis.py \
  --project-root path/to/project \
  --brief-file /tmp/error-brief.md \
  --context-file path/to/suspect/file-or-directory
```

The wrapper defaults to Antigravity CLI. Select a provider with `CODEX_ADVISOR_PROVIDER=agy|grok`, `--provider agy|grok`, or `"provider": "agy"` in `~/.codex/advisor_cli.json`.

Antigravity launches with the configured prompt mode and model. Default is interactive prompt mode, `agy -i "<prompt>"`, with `--model "Gemini 3.5 Flash (High)"` when supported. Set `CODEX_AGY_MODE=print` or `"mode": "print"` in `~/.codex/agy_cli.json` to use `agy -p "<prompt>"`. Override the model with `CODEX_AGY_MODEL` or config `"model"`; supported values are `Gemini 3.5 Flash (High)`, `Gemini 3.1 Pro (High)`, `Claude Sonnet 4.6 (Thinking)`, and `Claude Opus 4.6 (Thinking)`. If `agy` is not on `PATH`, set `CODEX_AGY_CMD` or the config file's `"command"` to the CLI path, for example `~/.local/bin/agy`.

Grok launches through `grok --prompt-file ... --output-format streaming-json` with `--permission-mode bypassPermissions` by default. Configure it with `~/.codex/grok_cli.json` or environment variables such as `CODEX_GROK_CMD`, `CODEX_GROK_CONFIG`, `CODEX_GROK_MODEL`, `CODEX_GROK_EFFORT`, and `CODEX_GROK_PERMISSION_MODE`.

If `agy` reports `E... not logged into Antigravity`, the wrapper prints the matching `W...` and `E...` log lines and relaunches `agy` up to 5 times by default. If the skill command still exits with a login failure after those internal retries, rerun the same command with the same brief and context files until reaching 10 total skill-command attempts before treating the advisor as unavailable.

This skill has been smoke-tested with Antigravity CLI `agy` version `1.0.7`. After upgrading `agy`, re-run the tests and a small advisory smoke test because flags, log wording, or transcript layout may change.

Gemini CLI advisory skills have been removed from the Codex runtime because Gemini CLI is no longer supported. Migrate any old `$gemini-error-analysis` workflow to `$advisor-error-analysis`.

`--context-file` paths are priority starting hints only. The selected advisor runs from the selected workspace root and may inspect any other workspace-local files or directories it decides are relevant.

When one failure spans multiple projects, repeat `--project-root` for each target project root so the advisor receives the correct project scope, runs from their common workspace ancestor, and receives the other existing roots through provider-specific mechanisms when supported.

## Read The Output Correctly

- Expect likely causes, code logic errors, environmental issues, most useful checks, recovery options, and confidence.
- Prefer discriminating checks that separate causes quickly.
- Validate any claim against the actual code, logs, and environment before acting on it.
- If the advisor is unavailable, times out, or returns noise, continue with local debugging and mention the unavailable advisory pass only if it affects confidence.

## Guardrails

- Do not ask the advisor to edit files or output patches.
- Keep logs pruned. Paste only the smallest high-signal failure excerpt.
- Do not use this skill to outsource ordinary debugging. Codex should inspect locally first.
- Avoid broad refactor prompts. Ask for likely root causes and the next checks that best separate them.

## Resources

- `scripts/run_advisor_error_analysis.py` wraps the shared advisory runner with provider routing, project-root execution, Antigravity or Grok transport selection, workspace-local path filtering, and debugging instructions.
- [references/error-brief-template.md](references/error-brief-template.md) provides a compact template for diagnostic briefs.
