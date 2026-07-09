# Review Brief Template

Use this template when preparing an external advisor review pass.

```md
# Change Summary

Short description of what changed and why.

## Risk Areas

- What could regress?
- What is most likely to be wrong?
- Is there dead code, stale compatibility logic, duplication, or obvious implementation bloat worth questioning?
- For non-code artifacts, what claims, audience assumptions, structure, evidence, or wording should be challenged?

## Artifact Type / Review Focus

- code, article, doc, spec, prompt, or general

## Files Changed

- /absolute/path/to/file1
- /absolute/path/to/file2
- /absolute/path/to/changed-directory

## Relevant Modules Or Directories

- Optional. Add sibling modules, shared packages, or architecture touchpoints when this is an important checkpoint and the advisor should do a broader structural review.

## Diff Stat

Paste a compact diff stat or a short summary.

## Selected Diff Or Excerpts

Optional. Paste only the few hunks or snippets that matter most when local path inspection alone may miss the issue.

## Known Gaps

- Untested branch
- Assumption not yet validated
- Cleanup or simplification not attempted yet
- Structural review context may still be incomplete
```

Keep the brief targeted. The advisor should review a representative change set or artifact through local paths, not a whole repository dump pasted into the prompt. The shared runner expands those explicit paths to nearby module directories automatically, so you usually do not need to list every sibling file by hand.
