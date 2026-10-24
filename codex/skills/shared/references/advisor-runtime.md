# Advisor runtime

Use the selected skill's wrapper once with a compact brief and relevant paths.
The advisor must only inspect and report: no edits, patches, nested advisors, or
unrequested external actions. Validate its findings against current evidence.

## Scope and configuration

Pass the smallest relevant `--project-root`; repeat it for an intentionally
multi-project review. State permitted directories and exclusions in the brief.
`--context-file` entries are priority starting hints, not a filesystem sandbox.
The runner executes at the common workspace ancestor, so restrict inspection to
named projects and their relevant dependencies. Do not inspect unrelated personal
files or credentials. Out-of-workspace context paths are skipped.

Antigravity (`agy`) is the default. Use `--provider agy|grok`,
`CODEX_ADVISOR_PROVIDER`, or the `provider` field in `$CODEX_HOME/advisor_cli.json`
(default home: `~/.codex`). Keep existing provider/model preferences.

Provider options belong in `$CODEX_HOME/agy_cli.json` or `grok_cli.json`.
Antigravity defaults to interactive `agy -i`; `CODEX_AGY_MODE=print` selects `agy -p`.
Print mode requires CLI support for `--output-format stream-json`. The runner uses
the terminal result event, then bounds CLI shutdown; a completed result does not
wait for the entire execution timeout just because the CLI stays alive.
Use `CODEX_AGY_CMD` / `CODEX_AGY_MODEL` or config `command` / `model` to override.
The runner maintains supported model names and validates them; do not copy the
model list into every skill. Grok uses `grok --prompt-file` with streaming JSON;
its configuration remains independent. See the installed runner's `--help` for
wrapper arguments and the source repository's Codex README for provider options.

## Failure handling and waiting

- The runner owns retries. Never multiply attempts by repeatedly executing the
  same failed wrapper command without new evidence or an external-state change.
- On `not logged into Antigravity`, the runner relaunches agy up to 5 times by
  default. `CODEX_AGY_AUTH_RETRIES` or config `auth_retries` changes the count;
  `0` disables retries. All attempts share one execution budget. A persistent
  failure after those attempts still requires authentication to be restored.
- Correct an invalid argument or missing brief locally before retrying. Do not
  treat configuration mistakes as successful or unavailable reviews.
- Rate limits, unavailable providers, and timeouts do not imply findings. Report
  the limitation when material and continue authorized work with local validation.
- While running, allow the configured execution budget (1200 seconds by default).
  Silence alone is not failure. Continue independent work and provide progress
  according to the host. Do not launch a second advisor while the first runs.
- Never change credentials, permissions, provider, or model to evade a failure
  without authorization. Exit status alone is insufficient: check that the output
  is substantive, relevant advisory text rather than a login or transport error.
