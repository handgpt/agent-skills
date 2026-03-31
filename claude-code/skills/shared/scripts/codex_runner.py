#!/usr/bin/env python3
"""Shared Codex CLI advisory runner used by Claude Code Codex skills."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 3600
MAX_OUTPUT_CHARS = 12000
DEFAULT_CODEX_MODEL = "gpt-5.4"
CODEX_MODEL_ENV_VAR = "CLAUDE_CODEX_MODEL"
CODEX_SANDBOX_MODE = "read-only"


# ---------------------------------------------------------------------------
# Project root detection
# ---------------------------------------------------------------------------


def detect_project_root() -> Path:
    """Walk up from cwd to find the Git top-level, or fall back to cwd."""
    cwd = Path.cwd().resolve()
    git = shutil.which("git")
    if not git:
        return cwd
    try:
        result = subprocess.run(
            [git, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(cwd),
            input="",
            check=False,
        )
    except Exception:
        return cwd
    root = result.stdout.strip()
    return Path(root).resolve() if result.returncode == 0 and root else cwd


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _tilde_path(path: Path) -> str:
    try:
        relative_path = path.resolve().relative_to(Path.home().resolve())
    except ValueError:
        return str(path)
    if str(relative_path) == ".":
        return "~"
    return f"~/{relative_path.as_posix()}"


# ---------------------------------------------------------------------------
# Codex CLI configuration
# ---------------------------------------------------------------------------


def configured_codex_model() -> str:
    model = os.environ.get(CODEX_MODEL_ENV_VAR, DEFAULT_CODEX_MODEL).strip()
    return model or DEFAULT_CODEX_MODEL


# ---------------------------------------------------------------------------
# Codex CLI review invocation
# ---------------------------------------------------------------------------


def run_codex_review(
    *,
    project_root: Path,
    custom_prompt: str = "",
    base_branch: str = "",
    commit_sha: str = "",
    uncommitted: bool = False,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run `codex review` and return the result."""
    codex = shutil.which("codex")
    if not codex:
        raise FileNotFoundError("codex executable not found in PATH")

    command: list[str] = [
        codex, "review",
        "-c", f'model="{configured_codex_model()}"',
    ]

    if base_branch:
        command.extend(["--base", base_branch])
    if commit_sha:
        command.extend(["--commit", commit_sha])
    if uncommitted:
        command.append("--uncommitted")
    if custom_prompt:
        command.append(custom_prompt)

    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(project_root),
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise


# ---------------------------------------------------------------------------
# Codex CLI exec invocation (for error-analysis and design-checkpoint)
# ---------------------------------------------------------------------------


def run_codex_exec(
    *,
    project_root: Path,
    prompt: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    output_file: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `codex exec` in read-only sandbox and return the result."""
    codex = shutil.which("codex")
    if not codex:
        raise FileNotFoundError("codex executable not found in PATH")

    command: list[str] = [
        codex, "exec",
        "-m", configured_codex_model(),
        "-s", CODEX_SANDBOX_MODE,
    ]

    if output_file:
        command.extend(["-o", output_file])

    command.append(prompt)

    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(project_root),
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_advisory_prompt(
    *,
    role_line: str,
    output_contract: str,
    brief_text: str,
    context_paths: list[str],
    project_root: Path,
) -> str:
    """Assemble a full advisory prompt for codex exec."""
    resolved_root = project_root.resolve()
    sections = [
        role_line,
        "You are running via Codex CLI on the same machine as the codebase.",
        (
            "Use the project root below as your filesystem boundary. "
            "You may inspect any local file or directory inside that project root "
            "if it helps you answer well."
        ),
        (
            "Return only the final Markdown answer. Do not add preambles, "
            "do not describe which tools you might use, and do not ask what to do next."
        ),
        "Provide advice only. Do not edit files or apply patches.",
        output_contract,
        f"## Project Root\n\n{_tilde_path(resolved_root)}",
        f"## Brief\n\n{brief_text.strip() or '(empty brief)'}",
    ]

    if context_paths:
        path_entries: list[str] = []
        for raw_path in context_paths:
            path = Path(raw_path).expanduser()
            if not path.is_absolute():
                path = (resolved_root / path).absolute()
            if not _is_within(path.resolve(), resolved_root):
                continue
            kind = "directory" if path.is_dir() else ("file" if path.exists() else "missing")
            try:
                rel = path.resolve().relative_to(resolved_root)
                display = str(rel)
            except ValueError:
                display = str(path)
            path_entries.append(f"- {display} [{kind}]")
        if path_entries:
            sections.append("## Priority Paths\n\n" + "\n".join(path_entries))

    return "\n\n".join(sections).strip() + "\n"


# ---------------------------------------------------------------------------
# Shared argument parser
# ---------------------------------------------------------------------------


def make_arg_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--brief-file", required=True,
        help="Markdown or text file with the advisory brief.",
    )
    parser.add_argument(
        "--project-root", default=None,
        help="Project root directory. Defaults to git top-level or cwd.",
    )
    parser.add_argument(
        "--context-file", action="append", default=[],
        help="Optional local file or directory Codex should treat as a priority starting point.",
    )
    parser.add_argument(
        "--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS,
        help=f"End-to-end advisory timeout in seconds. Default: {DEFAULT_TIMEOUT_SECONDS}.",
    )
    return parser


# ---------------------------------------------------------------------------
# Generic advisory entry point (for error-analysis and design-checkpoint)
# ---------------------------------------------------------------------------


def run_advisory(
    *,
    description: str,
    role_line: str,
    label: str,
    output_contract: str,
    configure_parser=None,
    argv: list[str] | None = None,
) -> int:
    """Run a Codex advisory pass end-to-end and return an exit code."""
    parser = make_arg_parser(description)
    if configure_parser is not None:
        configure_parser(parser)
    args = parser.parse_args(argv)

    brief_path = Path(args.brief_file).expanduser().resolve()
    if not brief_path.is_file():
        print(f"Brief file not found: {_tilde_path(brief_path)}", file=sys.stderr)
        return 2

    if args.project_root:
        project_root = Path(args.project_root).expanduser().resolve()
    else:
        project_root = detect_project_root()

    brief_text = brief_path.read_text(encoding="utf-8")
    prompt = build_advisory_prompt(
        role_line=role_line,
        output_contract=output_contract,
        brief_text=brief_text,
        context_paths=args.context_file,
        project_root=project_root,
    )

    print(f"[Codex {label}] Starting advisory pass...", file=sys.stderr, flush=True)
    print(f"[Codex {label}] Model: {configured_codex_model()}", file=sys.stderr, flush=True)
    print(f"[Codex {label}] Project root: {_tilde_path(project_root)}", file=sys.stderr, flush=True)

    try:
        result = run_codex_exec(
            project_root=project_root,
            prompt=prompt,
            timeout_seconds=args.timeout_seconds,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except subprocess.TimeoutExpired:
        print(
            f"Codex {label} timed out after {args.timeout_seconds} seconds.",
            file=sys.stderr,
        )
        return 4

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if result.returncode != 0 or not stdout:
        print(
            f"Codex {label} failed with exit code {result.returncode}.",
            file=sys.stderr,
        )
        if stderr:
            print(stderr[:MAX_OUTPUT_CHARS], file=sys.stderr)
        if stdout:
            print(stdout[:MAX_OUTPUT_CHARS], file=sys.stderr)
        return 5

    print(stdout[:MAX_OUTPUT_CHARS])
    return 0
