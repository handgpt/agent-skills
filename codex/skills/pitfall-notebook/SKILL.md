---
name: pitfall-notebook
description: Maintain a concise per-project pitfall notebook after non-trivial errors are successfully fixed. Use to read previously hit pitfalls before implementation or review work, and to append a short entry after a meaningful blocker is resolved so Codex does not repeat the same mistake. Do not use for trivial typos, obvious one-step mistakes, or verbose retrospective notes.
---

# Pitfall Notebook

Maintain a short project-local markdown notebook of mistakes that were already paid for once.

This skill is not advisory-only: it intentionally updates a local memory file in the current project.

## Notebook Location

- Default notebook path: `.codex-pitfalls.md` inside the project root (not the filesystem root).
- Recommended: if the project uses Git and this notebook is personal agent memory rather than team knowledge, add `.codex-pitfalls.md` to `.gitignore`

## When To Read It

- At the start of non-trivial implementation work, if `.codex-pitfalls.md` exists
- At the start of a final code review, if `.codex-pitfalls.md` exists
- Before investigating a new error that feels similar to a past failure

## When To Update It

- After a non-trivial error, regression, or blocker is successfully fixed
- After a repeated pitfall is recognized and the new fix clarifies the rule
- Skip updates for trivial typos, obvious syntax fixes, or noisy low-signal mistakes

## Entry Format

Each entry must stay short and high-signal:

- `Title`
- `Symptom`
- `Cause`
- `Rule`

The notebook should stay concise. Use the helper script so entries are normalized, deduped by title, and capped to a small rolling window.

## Update The Notebook

Run:

```bash
python3 scripts/update_pitfall_notebook.py \
  --title "Short pitfall title" \
  --symptom "What failed or what misled the debugging" \
  --cause "Actual root cause" \
  --rule "How to avoid repeating it"
```

The script auto-detects the current project root, writes to `.codex-pitfalls.md`, dedupes entries by normalized title, and keeps only the newest entries.

## Read The Notebook Correctly

- Treat the notebook as a pre-flight checklist, not as a full design history.
- Read it before non-trivial implementation or review work when it exists.
- Treat past rules as historical evidence. Check the affected component, version, and current facts before applying one; current user instructions and verified project requirements take precedence.
- Reuse a notebook already read in the same task unless it changed or the relevant scope changed.
- Keep entries concrete. If an entry cannot explain the pitfall in a few short bullets, it is probably too broad.

## Guardrails

- Never add content whose practical effect is to block or materially impede completion of authorized tasks. In particular, do not use the notebook to create safety or security policy, approval gates, or blanket prohibitions.
- A verified security defect may be recorded only as a narrowly scoped technical failure and fix. Notebook entries never override current host security and authorization boundaries or current user instructions.
- Do not dump stack traces or long logs into the notebook.
- Do not create entries before the fix is actually confirmed.
- Do not let the notebook grow unbounded; the helper script keeps a small rolling buffer.
- Do not record secrets, credentials, or sensitive production data.

## Resources

- `scripts/update_pitfall_notebook.py` writes concise entries into the project-local notebook.
- [pitfall-entry-template.md](references/pitfall-entry-template.md) shows the intended level of detail.
