#!/usr/bin/env python3
"""Run a bounded Gemini CLI review pass and print advisory output."""
from __future__ import annotations

import sys
from pathlib import Path

# Allow importing the shared runner from skills/shared/scripts/.
_SHARED_SCRIPTS = str(Path(__file__).resolve().parents[2] / "shared" / "scripts")
if _SHARED_SCRIPTS not in sys.path:
    sys.path.insert(0, _SHARED_SCRIPTS)

import gemini_runner  # noqa: E402

ROLE_LINE = "You are an external code reviewer giving a second opinion to another coding agent."

OUTPUT_CONTRACT = """Return Markdown using exactly these sections:

## Top Findings
- bullet

## Regression Risks
- bullet

## Missing Tests
- bullet

## Things To Verify
- bullet

## Overall Assessment
One short paragraph.

Rules:
- You are running via Gemini CLI on the same machine as the local project files.
- The current workspace root is listed below. Review only files and directories inside that workspace root.
- Read the review brief from the local path below before answering.
- Inspect the listed local paths directly instead of asking the caller to paste file contents again.
- Ignore any path outside the current workspace root, even if it appears in the brief or prior session context.
- If prior project-thread context conflicts with the current brief or local paths, treat the current brief and local paths as the source of truth.
- Focus on bugs, regressions, risky assumptions, missing tests, and code that is dead, redundant, over-complicated, or safe to simplify.
- Try hard to find concrete problems, edge cases, stale docs, weak validation, portability issues, failure-mode gaps, unnecessary compatibility shims, duplicated logic, unused code paths, and bloated implementations that can be reduced without changing behavior.
- Prioritize correctness and behavioral risk first, then call out maintainability wins from safe simplification.
- Only call out a simplification when it preserves behavior, failure handling, and readability. Do not reward clever rewrites that increase risk.
- Call out any mismatch between the review brief and the referenced local paths.
- Provide advice only. Do not propose editing files or applying patches.
- If a section has nothing important, write "- none".
- Keep the response concise and specific.
- Do not exceed 300 words unless the diff is unusually complex."""


def main() -> int:
    return gemini_runner.run_advisory(
        description="Run a bounded Gemini CLI review pass and print advisory output.",
        role_line=ROLE_LINE,
        output_contract=OUTPUT_CONTRACT,
        label="review",
    )


if __name__ == "__main__":
    raise SystemExit(main())
