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
- You are running via Gemini CLI on the same machine as the local project files.
- The current workspace root is listed below. Review only files and directories inside that workspace root.
- Read the inlined brief below before answering.
- Inspect the listed local paths directly instead of asking the caller to paste file contents again.
- Ignore any path outside the current workspace root, even if it appears in the brief or prior session context.
- If prior project-thread context conflicts with the current brief or local paths, treat the current brief and local paths as the source of truth.
- Explicitly judge whether the preferred direction follows current best practices; if it deviates, say whether the deviation is justified.
- Treat a deviation from default best practice as justified only when the stated constraints or operating model clearly outweigh the normal best-practice tradeoffs.
- Check both the overall architecture and the module-level design. A design is not "best practice" if individual modules look fine but the overall composition, boundaries, or ownership model are poor.
- When the topic depends on external frameworks, APIs, infrastructure, or standards, consult official documentation and community experience before concluding.
- Seek disconfirming evidence, not just supporting evidence, from official docs and community practice before endorsing the preferred direction.
- Distinguish official guidance from community practice when they differ, and say which one drives your recommendation.
- Try hard to find flaws in the current direction, not just to validate it.
- Prioritize irreversible mistakes, hidden coupling, migration traps, security boundaries, operational failure modes, and rollback gaps.
- Prioritize whole-system fit before local module polish.
- Call out any mismatch between the stated plan and the referenced local paths.
- Be concise and critical.
- Provide advice only. Do not propose editing files or applying patches.
- Prefer to start with `## Verdict`, but if the formatting drifts slightly, still return a concise on-task advisory instead of meta commentary.
- Avoid preambles, tool notes, and self-commentary before the main advisory content.
- Do not narrate your inspection process, say that you are reviewing or inspecting files, or describe a plan you are about to execute.
- Do not ask what to do next, and do not describe which tools you intend to use.
- If a section has nothing important, write "- none".
- Do not repeat the brief back verbatim.
- If evidence from official docs or community practice is weak or conflicting, say so explicitly.
- Do not exceed 300 words unless the brief is unusually complex."""


def main() -> int:
    return gemini_runner.run_advisory(
        description="Run a bounded Gemini CLI design checkpoint and print advisory output.",
        role_line=ROLE_LINE,
        output_contract=OUTPUT_CONTRACT,
        label="design checkpoint",
        lane="design",
    )


if __name__ == "__main__":
    raise SystemExit(main())
