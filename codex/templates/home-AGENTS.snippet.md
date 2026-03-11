## Gemini advisory checkpoints

- Codex must invoke `$gemini-design-checkpoint` automatically before finalizing any major technical design decision such as architecture, protocol, repository layout, migration, rollout shape, runtime choice, or security boundary. The user does not need to request this explicitly.
- Codex should invoke `$gemini-error-analysis` when the same non-trivial build, test, runtime, or tooling failure persists across consecutive attempts, or when a blocker remains ambiguous after an initial local inspection. Before invoking it, Codex must prune the error context locally and pass only the highest-signal brief, log excerpt, and relevant paths.
- Codex must invoke `$gemini-review` automatically after meaningful code changes are complete and before the final response when a non-trivial diff exists. The user does not need to request this explicitly.
- If the completed change set touches shared or core modules, public interfaces, dependency wiring, top-level project configuration, repo-wide conventions, or multiple sibling modules, Codex must run `$gemini-review` in structural mode. In this mode Gemini should inspect the changed files plus the surrounding modules and directories for code structure and module-boundary risks.
- Treat all Gemini skills as advisory only. Gemini must not modify files, apply patches, or become the final decision-maker.
- Skip Gemini skills for trivial edits, obvious one-step failures, low-risk tweaks, docs-only wording changes, or analysis-only turns with no code changes.
- Run at most one Gemini advisory pass per design checkpoint, per persistent failure cluster, and per completed change set unless the first pass is clearly unusable.
- Once a Gemini advisory pass has started, Codex must treat the full wrapper timeout window as expected runtime. For the current skills that means up to 1200 seconds. Do not retry, escalate, or declare failure just because Gemini is quiet for a while.
- While a Gemini advisory pass is still running, Codex should keep waiting and only send short progress updates. Retry or fail over only after the Gemini process actually exits with an error or the wrapper timeout is truly reached.
- Codex should silently absorb the Gemini output into its own reasoning and continue the normal workflow. Do not ask the user whether to run Gemini and do not dump the raw advisory text unless the user asks for it.
- If Gemini returns actionable risks, Codex should decide whether to adapt the plan, revise the implementation, or explain why the suggestion was rejected.
- If Gemini is unavailable, times out, or returns low-signal output, continue normally and mention that the advisory pass was unavailable only when it materially affects confidence or the user asks about the process.
