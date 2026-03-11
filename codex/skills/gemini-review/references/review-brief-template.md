# Review Brief Template

Use this template when preparing a Gemini review pass.

```md
# Change Summary

Short description of what changed and why.

## Risk Areas

- What could regress?
- What is most likely to be wrong?
- Is there dead code, stale compatibility logic, duplication, or obvious implementation bloat worth questioning?

## Files Changed

- /absolute/path/to/file1
- /absolute/path/to/file2
- /absolute/path/to/changed-directory

## Diff Stat

Paste a compact diff stat or a short summary.

## Selected Diff Or Excerpts

Optional. Paste only the few hunks or snippets that matter most when local path inspection alone may miss the issue.

## Known Gaps

- Untested branch
- Assumption not yet validated
- Cleanup or simplification not attempted yet
```

Keep the brief targeted. Gemini should review a representative change set through local paths, not a whole repository dump pasted into the prompt.
