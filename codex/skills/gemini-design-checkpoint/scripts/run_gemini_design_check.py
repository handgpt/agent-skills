#!/usr/bin/env python3
"""Run a bounded Gemini CLI design checkpoint and print advisory output."""
from __future__ import annotations

import sys
from pathlib import Path

# Allow importing the shared runner from skills/shared/scripts/.
_SHARED_SCRIPTS = str(Path(__file__).resolve().parents[2] / "shared" / "scripts")
if _SHARED_SCRIPTS not in sys.path:
    sys.path.insert(0, _SHARED_SCRIPTS)

import gemini_runner  # noqa: E402

ROLE_LINE = "You are an external architecture reviewer giving a second opinion to another coding agent."

OUTPUT_CONTRACT = """Return Markdown using exactly these sections:

## Verdict
One short paragraph.

## Critical Risks
- bullet

## Blind Spots
- bullet

## Alternatives
- bullet

## Open Questions
- bullet

## Recommendation
- bullet

Rules:
- You are running via Gemini CLI on the same machine as the local project files.
- The current workspace root is listed below. Review only files and directories inside that workspace root.
- Read the brief from the local path below before answering.
- Inspect the listed local paths directly instead of asking the caller to paste file contents again.
- Ignore any path outside the current workspace root, even if it appears in the brief or prior session context.
- If prior project-thread context conflicts with the current brief or local paths, treat the current brief and local paths as the source of truth.
- Try hard to find flaws in the current direction, not just to validate it.
- Prioritize irreversible mistakes, hidden coupling, migration traps, security boundaries, operational failure modes, and rollback gaps.
- Call out any mismatch between the stated plan and the referenced local paths.
- Be concise and critical.
- Provide advice only. Do not propose editing files or applying patches.
- If a section has nothing important, write "- none".
- Do not repeat the brief back verbatim.
- Do not exceed 300 words unless the brief is unusually complex."""


def main() -> int:
    return gemini_runner.run_advisory(
        description="Run a bounded Gemini CLI design checkpoint and print advisory output.",
        role_line=ROLE_LINE,
        output_contract=OUTPUT_CONTRACT,
        label="design checkpoint",
    )


if __name__ == "__main__":
    raise SystemExit(main())
