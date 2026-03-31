#!/usr/bin/env python3
"""Run a bounded Codex CLI review pass and print advisory output."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_SHARED_SCRIPTS = str(Path(__file__).resolve().parents[2] / "shared" / "scripts")
if _SHARED_SCRIPTS not in sys.path:
    sys.path.insert(0, _SHARED_SCRIPTS)

import codex_runner  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded Codex CLI review pass and print advisory output."
    )
    parser.add_argument(
        "--project-root", default=None,
        help="Project root directory. Defaults to git top-level or cwd.",
    )
    parser.add_argument(
        "--base", default="",
        help="Review changes against the given base branch.",
    )
    parser.add_argument(
        "--commit", default="",
        help="Review the changes introduced by a specific commit SHA.",
    )
    parser.add_argument(
        "--uncommitted", action="store_true",
        help="Review staged, unstaged, and untracked changes.",
    )
    parser.add_argument(
        "--prompt", default="",
        help="Custom review instructions to append.",
    )
    parser.add_argument(
        "--timeout-seconds", type=int, default=codex_runner.DEFAULT_TIMEOUT_SECONDS,
        help=f"Review timeout in seconds. Default: {codex_runner.DEFAULT_TIMEOUT_SECONDS}.",
    )
    args = parser.parse_args(argv)

    if args.project_root:
        project_root = Path(args.project_root).expanduser().resolve()
    else:
        project_root = codex_runner.detect_project_root()

    review_prompt = args.prompt or ""

    # Build enhanced review prompt with structural focus
    if not review_prompt:
        review_prompt = (
            "Focus on bugs, regressions, risky assumptions, missing tests, "
            "dead code, duplicated logic, over-complicated implementations, "
            "and code that is safe to simplify. "
            "Prioritize correctness and behavioral risk. "
            "Be concise and specific. Provide advice only."
        )

    print(f"[Codex review] Starting review...", file=sys.stderr, flush=True)
    print(f"[Codex review] Model: {codex_runner.configured_codex_model()}", file=sys.stderr, flush=True)
    print(f"[Codex review] Project root: {codex_runner._tilde_path(project_root)}", file=sys.stderr, flush=True)

    try:
        result = codex_runner.run_codex_review(
            project_root=project_root,
            custom_prompt=review_prompt,
            base_branch=args.base,
            commit_sha=args.commit,
            uncommitted=args.uncommitted,
            timeout_seconds=args.timeout_seconds,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except subprocess.TimeoutExpired:
        print(
            f"Codex review timed out after {args.timeout_seconds} seconds.",
            file=sys.stderr,
        )
        return 4

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if result.returncode != 0 or not stdout:
        print(f"Codex review failed with exit code {result.returncode}.", file=sys.stderr)
        if stderr:
            print(stderr[:codex_runner.MAX_OUTPUT_CHARS], file=sys.stderr)
        if stdout:
            print(stdout[:codex_runner.MAX_OUTPUT_CHARS], file=sys.stderr)
        return 5

    print(stdout[:codex_runner.MAX_OUTPUT_CHARS])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
