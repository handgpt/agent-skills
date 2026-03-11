## Gemini advisory checkpoints

- Codex must invoke `$gemini-design-checkpoint` automatically before finalizing any major technical design decision such as architecture, protocol, repository layout, migration, rollout shape, runtime choice, or security boundary. The user does not need to request this explicitly.
- Codex must invoke `$gemini-review` automatically after meaningful code changes are complete and before the final response when a non-trivial diff exists. The user does not need to request this explicitly.
- Treat both skills as advisory only. Gemini must not modify files, apply patches, or become the final decision-maker.
- Skip both skills for trivial edits, low-risk tweaks, docs-only wording changes, or analysis-only turns with no code changes.
- Run at most one Gemini advisory pass per design checkpoint and one Gemini advisory pass per completed change set unless the first pass is clearly unusable.
- Once a Gemini advisory pass has started, Codex must treat the full wrapper timeout window as expected runtime. For the current skills that means up to 1200 seconds. Do not retry, escalate, or declare failure just because Gemini is quiet for a while.
- While a Gemini advisory pass is still running, Codex should keep waiting and only send short progress updates. Retry or fail over only after the Gemini process actually exits with an error or the wrapper timeout is truly reached.
- Codex should silently absorb the Gemini output into its own reasoning and continue the normal workflow. Do not ask the user whether to run Gemini and do not dump the raw advisory text unless the user asks for it.
- If Gemini returns actionable risks, Codex should decide whether to adapt the plan, revise the implementation, or explain why the suggestion was rejected.
- If Gemini is unavailable, times out, or returns low-signal output, continue normally and mention that the advisory pass was unavailable only when it materially affects confidence or the user asks about the process.
