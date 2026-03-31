#!/usr/bin/env python3
"""Run a bounded Codex CLI error-analysis pass and print advisory output."""
from __future__ import annotations

import sys
from pathlib import Path

_SHARED_SCRIPTS = str(Path(__file__).resolve().parents[2] / "shared" / "scripts")
if _SHARED_SCRIPTS not in sys.path:
    sys.path.insert(0, _SHARED_SCRIPTS)

import codex_runner  # noqa: E402

ROLE_LINE = "You are an external debugging analyst giving a second opinion to another coding agent."

OUTPUT_CONTRACT = """Return concise Markdown. Prefer these sections when practical:

## Likely Causes
- bullet

## Code Logic Errors
- bullet

## Environmental Issues
- bullet

## Most Useful Checks
- bullet

## Recovery Options
- bullet

## Confidence
One short paragraph.

Rules:
- Focus on likely causes, the fastest high-signal checks, and clear separation between code logic errors and environmental issues.
- If the evidence is weak or incomplete, say so explicitly instead of pretending to know the root cause.
- Prefer small, discriminating next checks over broad refactor suggestions.
- Provide advice only. Do not edit files or apply patches.
- If a section has nothing important, write "- none".
- Keep the response concise and specific.
- Do not exceed 300 words unless the failure is unusually complex."""


def main() -> int:
    return codex_runner.run_advisory(
        description="Run a bounded Codex CLI error-analysis pass and print advisory output.",
        role_line=ROLE_LINE,
        output_contract=OUTPUT_CONTRACT,
        label="error analysis",
    )


if __name__ == "__main__":
    raise SystemExit(main())
