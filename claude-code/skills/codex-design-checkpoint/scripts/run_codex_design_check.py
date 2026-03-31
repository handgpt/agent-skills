#!/usr/bin/env python3
"""Run a bounded Codex CLI design checkpoint and print advisory output."""
from __future__ import annotations

import sys
from pathlib import Path

_SHARED_SCRIPTS = str(Path(__file__).resolve().parents[2] / "shared" / "scripts")
if _SHARED_SCRIPTS not in sys.path:
    sys.path.insert(0, _SHARED_SCRIPTS)

import codex_runner  # noqa: E402

ROLE_LINE = "You are an external architecture reviewer giving a second opinion to another coding agent."

OUTPUT_CONTRACT = """Return concise Markdown. Prefer these sections when practical:

## Verdict
One short paragraph.

## Best-Practice Alignment
- bullet

## System-Level Risks
- bullet

## Module-Level Risks
- bullet

## Alternatives
- bullet

## Open Questions
- bullet

## Recommendation
- bullet

## Sources & Verification
For every best-practice claim or recommendation above, list:
- The practice or claim
- Source: official doc URL, community reference, or "unverified (training knowledge only)"
- Whether the source is official guidance or community convention
If no verification was possible for a claim, explicitly mark it as unverified.

Rules:
- Explicitly judge whether the preferred direction follows current best practices; if it deviates, say whether the deviation is justified.
- For EVERY best-practice claim you make, verify it against official documentation or community sources. Do not rely solely on training knowledge. If you cannot verify, explicitly state "unverified".
- Check both the overall architecture and the module-level design.
- When the topic depends on external frameworks, APIs, infrastructure, or standards, consult official documentation and community experience before concluding.
- Seek disconfirming evidence, not just supporting evidence, from official docs and community practice before endorsing the preferred direction.
- Distinguish official guidance from community practice when they differ, and say which one drives your recommendation.
- Try hard to find flaws in the current direction, not just to validate it.
- Prioritize irreversible mistakes, hidden coupling, migration traps, security boundaries, operational failure modes, and rollback gaps.
- Be concise and critical.
- Provide advice only. Do not edit files or apply patches.
- The "## Sources & Verification" section is MANDATORY. Every recommendation in Verdict, Best-Practice Alignment, and Recommendation sections must have a corresponding entry in Sources & Verification.
- If a section has nothing important, write "- none".
- If evidence from official docs or community practice is weak or conflicting, say so explicitly.
- Do not exceed 400 words unless the brief is unusually complex."""


def main() -> int:
    return codex_runner.run_advisory(
        description="Run a bounded Codex CLI design checkpoint and print advisory output.",
        role_line=ROLE_LINE,
        output_contract=OUTPUT_CONTRACT,
        label="design checkpoint",
    )


if __name__ == "__main__":
    raise SystemExit(main())
