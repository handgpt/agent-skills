#!/usr/bin/env python3
"""Run a bounded Gemini CLI error-analysis pass and print advisory output."""
from __future__ import annotations

import sys
from pathlib import Path

# Allow importing the shared runner from skills/shared/scripts/.
_SHARED_SCRIPTS = str(Path(__file__).resolve().parents[2] / "shared" / "scripts")
if _SHARED_SCRIPTS not in sys.path:
    sys.path.insert(0, _SHARED_SCRIPTS)

import gemini_runner  # noqa: E402

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
- You are running via Gemini CLI on the same machine as the local project files.
- The current workspace root is listed below. Analyze only files and directories inside that workspace root.
- Read the inlined diagnostic brief below before answering.
- Inspect the listed local paths directly instead of asking the caller to paste file contents again.
- Ignore any path outside the current workspace root, even if it appears in the brief or prior session context.
- If prior project-thread context conflicts with the current brief or local paths, treat the current brief and local paths as the source of truth.
- Focus on likely causes, the fastest high-signal checks, and clear separation between code logic errors and environmental issues.
- If the evidence is weak or incomplete, say so explicitly instead of pretending to know the root cause.
- Prefer small, discriminating next checks over broad refactor suggestions.
- Provide advice only. Do not propose editing files or applying patches.
- Prefer to start with `## Likely Causes`, but if the formatting drifts slightly, still return a concise on-task advisory instead of meta commentary.
- Avoid preambles, tool notes, and self-commentary before the main diagnostic content.
- Do not narrate your inspection process, say that you are reviewing or inspecting files, or describe a plan you are about to execute.
- Do not ask what to do next, and do not describe which tools you intend to use.
- If a section has nothing important, write "- none".
- Keep the response concise and specific.
- Do not exceed 300 words unless the failure is unusually complex."""


def main() -> int:
    return gemini_runner.run_advisory(
        description="Run a bounded Gemini CLI error-analysis pass and print advisory output.",
        role_line=ROLE_LINE,
        output_contract=OUTPUT_CONTRACT,
        label="error analysis",
        lane="error",
    )


if __name__ == "__main__":
    raise SystemExit(main())
