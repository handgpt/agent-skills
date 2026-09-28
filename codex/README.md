# Codex Skills

Reusable provider-routed advisor and project-pitfall skills. Antigravity is the
default advisor; Grok is optional. Source lives in `codex/skills`, shared transport
code in `common/scripts`, and deployed copies in `$CODEX_HOME/skills` (normally
`~/.codex/skills`). Do not maintain edits only in deployed copies.

## Skills and checkpoints

- `advisor-design-checkpoint`: major architecture, migration, runtime, rollout,
  protocol, or security decisions; skip routine implementation choices.
- `advisor-error-analysis`: a persistent or ambiguous non-trivial failure after
  local inspection, using a pruned diagnostic brief.
- `advisor-review`: explicit audits of existing code or artifacts, even without
  a diff, and automatic review of completed high-risk changes. Use structural
  mode for core/shared modules, public interfaces, dependencies, security, and
  cross-module behavior. Ordinary local edits need appropriate tests; external
  review is optional unless material uncertainty remains.
- `pitfall-notebook`: short project-local records of confirmed fixes. Check
  current applicability before reusing historical rules.

Advisors are instructed to inspect and report, not modify files. These instructions
are not an OS sandbox. Specify the permitted scope and validate the findings.
Each pass runs once per decision, failure cluster, or completed change set.

For artifacts use `--focus article|doc|spec|prompt|general`; with `--mode structural`,
review focuses on organization and evidence instead of code module boundaries.

## Install and upgrade

From this repository root:

```bash
./codex/scripts/install.sh
```

To also install global advisor/pitfall rules in `$CODEX_HOME/AGENTS.md`:

```bash
./codex/scripts/install.sh --install-global-agents
```

The old `--install-home-agents` flag is an alias for this migration. Only balanced
managed advisor/legacy marker blocks are removed from `~/AGENTS.md`; unmarked
user text is preserved. Malformed markers or symlinked instruction files stop the
migration before deployment. Old managed skills and changed instruction files are
backed up under `$CODEX_HOME/backups/advisor-install-*`. Unrelated skills and
provider/model configuration are preserved. Repeating installation is supported.

To additionally opt into bounded delegation, proportional verification, and
artifact-writing preferences:

```bash
./codex/scripts/install.sh --install-global-agents --install-workflow-preferences
```

These preferences live in their own managed global block. They retain required
final rendering and tests while avoiding endless subjective polishing. Vendor
plugin caches are not edited. Existing project-local instructions can override
global guidance; remove obsolete local copies of this package's policy when
migrating. `templates/workspace-AGENTS.md` is an example for such a workspace;
the installer does not replace project instructions automatically.

Restart Codex and start a new task to load the updated instruction chain.

## Provider configuration

Read the [shared runtime guide](skills/shared/references/advisor-runtime.md) when
running an advisor. Provider selection: `--provider agy|grok`,
`CODEX_ADVISOR_PROVIDER`, or `provider` in `$CODEX_HOME/advisor_cli.json`.

Antigravity options in `$CODEX_HOME/agy_cli.json`:

```json
{
  "mode": "interactive",
  "command": "agy",
  "auth_retries": 5
}
```

`model` may override the runner default. Supported model values are maintained in
`common/scripts/agy_runner.py`; unsupported values produce an actionable error.
Environment overrides: `CODEX_AGY_MODE`, `CODEX_AGY_CMD`, `CODEX_AGY_CONFIG`,
`CODEX_AGY_MODEL`, `CODEX_AGY_PRINT_TIMEOUT`, `CODEX_AGY_AUTH_RETRIES`, and
`CODEX_AGY_DANGEROUSLY_SKIP_PERMISSIONS`. Existing permission settings are preserved.

When agy reports `not logged into Antigravity`, the runner automatically
relaunches it up to 5 times by default. Set `auth_retries` or
`CODEX_AGY_AUTH_RETRIES` to change the retry count, including `0` to disable it.
All retries share one execution deadline, normally 1200 seconds;
short bounded process cleanup may follow. Help probing is separately bounded to
15 seconds and deducted from that budget. A custom print timeout cannot extend
the wrapper's execution budget. Never add an outer loop of wrapper invocations.
Claude Code's default retry count remains unchanged by this Codex migration.

Grok configuration in `$CODEX_HOME/grok_cli.json` supports `command`, `model`,
`output_format`, `permission_mode`, `no_memory`, and `verbatim`. Existing Grok
transport behavior is unchanged. Use `CODEX_GROK_CONFIG` for another config path.

## Validation and evidence

```bash
python3 -m unittest discover -s codex/tests
```

Transport tests cover authentication, deadlines, and transcript recovery. Installer
tests cover backups, preservation, idempotency, and malformed markers. A real
advisory pass verifies the selected provider beyond mocked transport tests.
See [instruction maintenance evidence](references/instruction-maintenance.md)
for official guidance, scoped community observations, and their limitations.
