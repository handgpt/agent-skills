#!/usr/bin/env python3
"""Run a bounded Gemini CLI review pass and print advisory output."""
from __future__ import annotations

import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path

# Allow importing the shared runner from skills/shared/scripts/.
_SHARED_SCRIPTS = str(Path(__file__).resolve().parents[2] / "shared" / "scripts")
if _SHARED_SCRIPTS not in sys.path:
    sys.path.insert(0, _SHARED_SCRIPTS)

import gemini_runner  # noqa: E402

ROLE_LINE = "You are an external code reviewer giving a second opinion to another coding agent."

STANDARD_OUTPUT_CONTRACT = """Return concise Markdown. Prefer these sections when practical:

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
- Read the inlined review brief below before answering.
- Inspect the listed local paths directly instead of asking the caller to paste file contents again.
- Ignore any path outside the current workspace root, even if it appears in the brief or prior session context.
- If prior project-thread context conflicts with the current brief or local paths, treat the current brief and local paths as the source of truth.
- Focus on bugs, regressions, risky assumptions, missing tests, and code that is dead, redundant, over-complicated, or safe to simplify.
- Try hard to find concrete problems, edge cases, stale docs, weak validation, portability issues, failure-mode gaps, unnecessary compatibility shims, duplicated logic, unused code paths, and bloated implementations that can be reduced without changing behavior.
- Prioritize correctness and behavioral risk first, then call out maintainability wins from safe simplification.
- Only call out a simplification when it preserves behavior, failure handling, and readability. Do not reward clever rewrites that increase risk.
- Call out any mismatch between the review brief and the referenced local paths.
- Provide advice only. Do not propose editing files or applying patches.
- Prefer to start with `## Top Findings`, but if the formatting drifts slightly, still return a concise on-task advisory instead of meta commentary.
- Avoid preambles, tool notes, and self-commentary before the main review content.
- Do not narrate your inspection process, say that you are reviewing or inspecting files, or describe a plan you are about to execute.
- Do not ask what to do next, and do not describe which tools you intend to use.
- If a section has nothing important, write "- none".
- Keep the response concise and specific.
- Do not exceed 300 words unless the diff is unusually complex."""

STRUCTURAL_OUTPUT_CONTRACT = """Return concise Markdown. Prefer these sections when practical:

## Top Findings
- bullet

## Structural & Architectural Risks
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
- Read the inlined review brief below before answering.
- Inspect the listed local paths directly instead of asking the caller to paste file contents again.
- Ignore any path outside the current workspace root, even if it appears in the brief or prior session context.
- If prior project-thread context conflicts with the current brief or local paths, treat the current brief and local paths as the source of truth.
- This is structural mode. Review the changed files first, then zoom out to the surrounding modules, sibling directories, ownership boundaries, interface contracts, dependency direction, and architecture touchpoints that matter for those changes.
- Focus on structural risks that are concrete and relevant: bad module boundaries, hidden coupling, unstable interfaces, misplaced responsibilities, dependency inversion problems, cross-module leakage, and repo-level design drift.
- Still look for bugs, regressions, risky assumptions, missing tests, and code that is dead, redundant, over-complicated, or safe to simplify.
- Prioritize correctness and structural risk first. Only call out simplification opportunities when they preserve behavior, failure handling, and readability.
- If the provided context is too narrow for a confident structural conclusion, say so instead of inventing architecture issues.
- Call out any mismatch between the review brief and the referenced local paths.
- Provide advice only. Do not propose editing files or applying patches.
- Prefer to start with `## Top Findings`, but if the formatting drifts slightly, still return a concise on-task advisory instead of meta commentary.
- Avoid preambles, tool notes, and self-commentary before the main review content.
- Do not narrate your inspection process, say that you are reviewing or inspecting files, or describe a plan you are about to execute.
- Do not ask what to do next, and do not describe which tools you intend to use.
- If a section has nothing important, write "- none".
- Keep the response concise and specific.
- Do not exceed 400 words unless the review is unusually complex."""


def configure_parser(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--mode",
        choices=("standard", "structural"),
        default="standard",
        help="Review mode. Use structural for important checkpoints that need broader module and architecture review.",
    )


def build_output_contract(args: Namespace) -> str:
    return STRUCTURAL_OUTPUT_CONTRACT if args.mode == "structural" else STANDARD_OUTPUT_CONTRACT


def main() -> int:
    return gemini_runner.run_advisory(
        description="Run a bounded Gemini CLI review pass and print advisory output.",
        role_line=ROLE_LINE,
        label="review",
        lane="review",
        output_contract_builder=build_output_contract,
        configure_parser=configure_parser,
    )


if __name__ == "__main__":
    raise SystemExit(main())
