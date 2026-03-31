# Agent Skills

This is a public repository of reusable local-agent skills organized by runtime.

## Gemini Advisory Skills (Auto-Trigger)

The following Gemini advisory skills should be used automatically without explicit user invocation when the triggering conditions are met.

### gemini-review

**Trigger:** After completing non-trivial code changes, before delivering the final answer.

- Skip for trivial edits, formatting-only changes, or when the user only asked for analysis.
- Run once per finished change set, not on every intermediate step.
- Use `--mode structural` for changes touching shared modules, public interfaces, cross-module boundaries, or architecture-level code.
- Set `--project-root` to the specific project subdirectory being reviewed to prevent Gemini from browsing sibling directories and misattributing code.

### gemini-error-analysis

**Trigger:** When the same non-trivial failure persists across two consecutive implementation attempts, or when a build/test/runtime failure remains ambiguous after local inspection.

- Skip for obvious syntax errors or single-step fixes.
- Run once per failure cluster.

### gemini-design-checkpoint

**Trigger:** Before locking in a major technical decision that is expensive to reverse (architecture, protocols, migrations, security boundaries).

- Skip for routine implementation, small refactors, or low-risk questions.
- Run once per decision point.

### pitfall-notebook

**Trigger:**
- **Read:** At the start of non-trivial implementation or review work, if `.claude-pitfalls.md` exists in the project root.
- **Write:** After a non-trivial error, regression, or blocker is successfully fixed. Record the pitfall to the specific project's notebook (not a global one) to keep entries scoped and manageable.

## Pitfall Notebooks

Each sub-project should maintain its own pitfall notebook (`.claude-pitfalls.md` or `.codex-pitfalls.md`) at its project root. Do not use a single global notebook — keep pitfalls scoped to the project where they occurred.

When a significant error is discovered and fixed, record it using the pitfall-notebook skill with the correct `--notebook-file` path for that project.

## Gemini Advisory Best Practices

- Always set `--project-root` to the specific subdirectory being reviewed, not the workspace root, to prevent Gemini from browsing unrelated sibling directories.
- Always verify Gemini findings against the actual code (grep, read) before acting on them. Gemini can hallucinate or misattribute code from other directories.
- Add explicit scoping instructions in the review brief (e.g., "Only review files under X. Do NOT inspect Y.").
- Default model is `gemini-2.5-pro` with 1-hour timeout.
