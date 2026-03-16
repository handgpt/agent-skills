# Error Brief Template

Use this template when preparing a Gemini error-analysis pass.

```md
# Failure Summary

Short summary of the blocker and when it occurs.

## What Was Attempted

- Attempt 1
- Attempt 2

## Exact Error Signature

- Test name, command, exception class, or log signature

## Pruned Log Excerpt

Paste only the smallest high-signal excerpt that still shows the failure.

## Suspect Paths

- /absolute/path/to/source/file
- /absolute/path/to/config/file
- /absolute/path/to/log/or-output-file

## Environment Notes

- OS, toolchain, dependency, network, or filesystem facts that may matter

## Known Unknowns

- What still is not explained
- What may be environmental rather than code-level
```

Keep the brief compact. Gemini should see the real failure signature and the few most relevant files, not a full raw dump of the workspace. The shared runner expands those explicit suspect paths to nearby module directories automatically, so you usually do not need to enumerate every adjacent source file yourself.
