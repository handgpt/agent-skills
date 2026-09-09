## Advisory checkpoints

- Use `$advisor-design-checkpoint` before finalizing major architecture, protocol, migration, runtime, rollout, or security-boundary decisions. Skip routine implementation choices.
- Use `$advisor-error-analysis` after local inspection when a non-trivial failure persists or its cause remains ambiguous. Pass a pruned brief and relevant paths.
- Use `$advisor-review` for explicit review requests, even without a diff. Automatically review completed high-risk changes to core/shared modules, public interfaces, dependencies, security, or cross-module behavior; use structural mode for those changes. Ordinary local edits need appropriate validation, with advisory review only for unresolved material risk.
- Run one pass per decision, failure cluster, or completed change set. The advisor reports only; verify its findings and retain responsibility for the result. Do not invoke nested advisors.
- The runner owns retries and timeouts. Do not repeat the same failed wrapper without new evidence or an external-state change. Allow the configured wait budget; silence alone is not failure. If unavailable, continue authorized work and identify material verification limits.
- Keep provider configuration and operational details in the skills' shared runtime guide rather than duplicating them here.

## Project pitfalls

- Read an existing project-local `.codex-pitfalls.md` before non-trivial implementation or review. Reuse it during the task unless it changed or the relevant scope changed.
- Treat historical rules as evidence: verify version, component, and current applicability. Current user instructions and verified project requirements prevail over stale memory.
- After a non-trivial error is confirmed fixed, use `$pitfall-notebook` to record a short title, symptom, cause, and rule. Skip trivial mistakes and never record secrets.
