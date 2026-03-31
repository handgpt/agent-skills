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

Rules:
- Explicitly judge whether the preferred direction follows current best practices; if it deviates, say whether the deviation is justified.
- Check both the overall architecture and the module-level design.
- When the topic depends on external frameworks, APIs, infrastructure, or standards, consult official documentation and community experience before concluding.
- Seek disconfirming evidence, not just supporting evidence.
- Try hard to find flaws in the current direction, not just to validate it.
- Prioritize irreversible mistakes, hidden coupling, migration traps, security boundaries, operational failure modes, and rollback gaps.
- Be concise and critical.
- Provide advice only. Do not edit files or apply patches.
- If a section has nothing important, write "- none".
- Do not exceed 300 words unless the brief is unusually complex."""


def main() -> int:
    return codex_runner.run_advisory(
        description="Run a bounded Codex CLI design checkpoint and print advisory output.",
        role_line=ROLE_LINE,
        output_contract=OUTPUT_CONTRACT,
        label="design checkpoint",
    )


if __name__ == "__main__":
    raise SystemExit(main())
