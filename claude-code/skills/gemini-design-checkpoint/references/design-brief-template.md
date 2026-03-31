# Design Brief Template

Use this template when preparing a Gemini design checkpoint.

```md
# Decision

One-sentence description of the design choice under consideration.

## Goal

- What outcome matters most?

## Constraints

- Technical limits
- Business limits
- Time, compatibility, security, or operational constraints

## Options Considered

1. Option A
2. Option B
3. Option C

## Current Preferred Direction

- State the choice you are leaning toward and why.
- If this direction intentionally deviates from a default best practice, state the constraint or operating tradeoff that is supposed to justify that deviation.

## Known Risks

- Risk 1
- Risk 2

## Relevant Official Docs

- https://official-doc.example/path

## Relevant Community References

- https://community-post.example/path

## Relevant Paths

- /absolute/path/to/spec-or-doc
- /absolute/path/to/design-file
```

Keep the brief compact. Prefer summaries plus absolute local paths over whole-file pastes. If you already know the official docs or community references that matter, include them here so Gemini can weigh them against the local design context and look for disconfirming evidence instead of only confirming the preferred direction. The shared runner expands those explicit local paths to nearby module directories automatically, so you usually only need to name the core design docs and source touchpoints.
