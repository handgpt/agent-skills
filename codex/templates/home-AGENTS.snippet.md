## Advisor checkpoints

- External advisory skills are provider-routed through `$advisor-design-checkpoint`, `$advisor-error-analysis`, and `$advisor-review`. The default provider is Antigravity CLI (`agy`); set `CODEX_ADVISOR_PROVIDER=grok`, pass `--provider grok`, or set `"provider": "grok"` in `~/.codex/advisor_cli.json` to use Grok CLI.
- Antigravity remains the default provider. The skills pass `--model "Gemini 3.7 Flash (High)"` by default when the installed `agy` supports `--model`; supported overrides are `Gemini 3.7 Flash (High)`, `Gemini 3.5 Flash (High)`, `Gemini 3.1 Pro (High)`, `Claude Sonnet 4.6 (Thinking)`, and `Claude Opus 4.6 (Thinking)`.
- Antigravity advisory mode defaults to `agy -i` prompt-interactive mode. Set `CODEX_AGY_MODE=print` or `"mode": "print"` in `~/.codex/agy_cli.json` to use `agy -p` print mode.
- Grok provider uses `grok --prompt-file ... --output-format streaming-json` with `--permission-mode bypassPermissions` by default. Configure it with `~/.codex/grok_cli.json` or `CODEX_GROK_CMD`, `CODEX_GROK_CONFIG`, `CODEX_GROK_MODEL`, `CODEX_GROK_EFFORT`, and `CODEX_GROK_PERMISSION_MODE`.
- When an advisory pass intentionally spans multiple project roots, the wrapper runs from the common workspace ancestor and lists every project explicitly in the prompt. Providers may receive additional project roots through provider-specific mechanisms when supported.
- If the Antigravity CLI log contains `E... not logged into Antigravity`, the wrapper prints matching `W...` and `E...` log lines and automatically relaunches `agy` up to 5 times by default. Override with `CODEX_AGY_AUTH_RETRIES` or `"auth_retries"` in `~/.codex/agy_cli.json`. If a skill command still exits with a login failure after those internal retries, Codex should rerun the same skill command until reaching 10 total skill-command attempts before treating the advisor as unavailable.
- These skills were smoke-tested with Antigravity CLI `agy` version `1.1.13`. If `agy` is not on `PATH`, set `CODEX_AGY_CMD` or the config file's `"command"` to the CLI path, for example `~/.local/bin/agy`.
- Gemini CLI advisory skills are removed from the Codex runtime because Gemini CLI is no longer supported. Migrate any `$gemini-*` workflow to `$advisor-design-checkpoint`, `$advisor-error-analysis`, or `$advisor-review`.
- Codex must invoke `$advisor-design-checkpoint` automatically before finalizing any major technical design decision such as architecture, protocol, repository layout, migration, rollout shape, runtime choice, or security boundary. The user does not need to request this explicitly.
- Codex should invoke `$advisor-error-analysis` when the same non-trivial build, test, runtime, or tooling failure persists across consecutive attempts, or when a blocker remains ambiguous after an initial local inspection. Before invoking it, Codex must prune the error context locally and pass only the highest-signal brief, log excerpt, and relevant paths.
- Codex must invoke `$advisor-review` automatically after meaningful code changes are complete and before the final response when a non-trivial diff exists. The user does not need to request this explicitly.
- Codex may invoke `$advisor-review` with an artifact focus such as `--focus article`, `--focus doc`, `--focus spec`, or `--focus prompt` when reviewing finished non-code artifacts.
- If the completed change set touches shared or core modules, public interfaces, dependency wiring, top-level project configuration, repo-wide conventions, or multiple sibling modules, Codex must run `$advisor-review` in structural mode. In this mode the advisor should inspect the changed files plus the surrounding modules and directories for code structure and module-boundary risks.
- Treat all advisor skills as advisory only. The advisor must not modify files, apply patches, or become the final decision-maker.
- Skip advisor skills for trivial edits, obvious one-step failures, low-risk tweaks, docs-only wording changes, or analysis-only turns with no substantive change.
- Run at most one advisor pass per design checkpoint, per persistent failure cluster, and per completed change set unless the first pass is clearly unusable.
- Once an advisor pass has started, Codex must treat the full wrapper timeout window as expected runtime. For the current skills that means up to 1200 seconds. Do not retry, escalate, or declare failure just because the advisor is quiet for a while.
- While an advisor pass is still running, Codex should keep waiting and only send short progress updates. Retry or fail over only after the advisor process actually exits with an error or the wrapper timeout is truly reached.
- Codex should silently absorb the advisor output into its own reasoning and continue the normal workflow. Do not ask the user whether to run the advisor and do not dump the raw advisory text unless the user asks for it.
- If the advisor returns actionable risks, Codex should decide whether to adapt the plan, revise the implementation, or explain why the suggestion was rejected.
- If the advisor is unavailable, times out, or returns low-signal output, continue normally and mention that the advisory pass was unavailable only when it materially affects confidence or the user asks about the process.

## Local memory checkpoints

- If the project-root `.codex-pitfalls.md` exists, Codex should read it at the start of non-trivial implementation work and at the start of final review work, before producing new code or review conclusions.
- After a non-trivial error, regression, or blocker is successfully fixed, Codex should invoke `$pitfall-notebook` to record a concise pitfall entry.
- Pitfall entries must stay short and concrete: title, symptom, cause, and rule. Do not dump logs or long retrospectives into the notebook.
- Skip notebook updates for trivial typos, obvious one-step mistakes, or noisy low-signal incidents.
