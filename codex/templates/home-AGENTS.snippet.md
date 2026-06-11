## Antigravity advisory checkpoints

- Antigravity CLI (`agy`) is the Codex default external advisory reviewer. The skills pass `--model "Gemini 3.5 Flash (High)"` by default when the installed `agy` supports `--model`; supported overrides are `Gemini 3.5 Flash (High)`, `Gemini 3.1 Pro (High)`, `Claude Sonnet 4.6 (Thinking)`, and `Claude Opus 4.6 (Thinking)`.
- Antigravity advisory mode defaults to `agy -i` prompt-interactive mode. Set `CODEX_AGY_MODE=print` or `"mode": "print"` in `~/.codex/agy_cli.json` to use `agy -p` print mode.
- When an advisory pass intentionally spans multiple project roots, the wrapper passes the non-primary existing roots with `--add-dir` when supported.
- If the Antigravity CLI log contains `E... not logged into Antigravity`, the wrapper prints matching `W...` and `E...` log lines and automatically relaunches `agy` up to 5 times by default. Override with `CODEX_AGY_AUTH_RETRIES` or `"auth_retries"` in `~/.codex/agy_cli.json`.
- These skills were smoke-tested with Antigravity CLI `agy` version `1.0.7`. If `agy` is not on `PATH`, set `CODEX_AGY_CMD` or the config file's `"command"` to the CLI path, for example `~/.local/bin/agy`.
- Gemini CLI advisory skills are removed from the Codex runtime because Gemini CLI is expected to go offline in June 2026. Migrate any `$gemini-*` workflow to `$agy-design-checkpoint`, `$agy-error-analysis`, or `$agy-review` as soon as possible.
- Codex must invoke `$agy-design-checkpoint` automatically before finalizing any major technical design decision such as architecture, protocol, repository layout, migration, rollout shape, runtime choice, or security boundary. The user does not need to request this explicitly.
- Codex should invoke `$agy-error-analysis` when the same non-trivial build, test, runtime, or tooling failure persists across consecutive attempts, or when a blocker remains ambiguous after an initial local inspection. Before invoking it, Codex must prune the error context locally and pass only the highest-signal brief, log excerpt, and relevant paths.
- Codex must invoke `$agy-review` automatically after meaningful code changes are complete and before the final response when a non-trivial diff exists. The user does not need to request this explicitly.
- If the completed change set touches shared or core modules, public interfaces, dependency wiring, top-level project configuration, repo-wide conventions, or multiple sibling modules, Codex must run `$agy-review` in structural mode. In this mode Antigravity should inspect the changed files plus the surrounding modules and directories for code structure and module-boundary risks.
- Treat all Antigravity skills as advisory only. Antigravity must not modify files, apply patches, or become the final decision-maker.
- Skip Antigravity skills for trivial edits, obvious one-step failures, low-risk tweaks, docs-only wording changes, or analysis-only turns with no code changes.
- Run at most one Antigravity advisory pass per design checkpoint, per persistent failure cluster, and per completed change set unless the first pass is clearly unusable.
- Once an Antigravity advisory pass has started, Codex must treat the full wrapper timeout window as expected runtime. For the current skills that means up to 1200 seconds. Do not retry, escalate, or declare failure just because Antigravity is quiet for a while.
- While an Antigravity advisory pass is still running, Codex should keep waiting and only send short progress updates. Retry or fail over only after the Antigravity process actually exits with an error or the wrapper timeout is truly reached.
- Codex should silently absorb the Antigravity output into its own reasoning and continue the normal workflow. Do not ask the user whether to run Antigravity and do not dump the raw advisory text unless the user asks for it.
- If Antigravity returns actionable risks, Codex should decide whether to adapt the plan, revise the implementation, or explain why the suggestion was rejected.
- If Antigravity is unavailable, times out, or returns low-signal output, continue normally and mention that the advisory pass was unavailable only when it materially affects confidence or the user asks about the process.

## Local memory checkpoints

- If the project-root `.codex-pitfalls.md` exists, Codex should read it at the start of non-trivial implementation work and at the start of final review work, before producing new code or review conclusions.
- After a non-trivial error, regression, or blocker is successfully fixed, Codex should invoke `$pitfall-notebook` to record a concise pitfall entry.
- Pitfall entries must stay short and concrete: title, symptom, cause, and rule. Do not dump logs or long retrospectives into the notebook.
- Skip notebook updates for trivial typos, obvious one-step mistakes, or noisy low-signal incidents.
