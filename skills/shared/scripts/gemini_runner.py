#!/usr/bin/env python3
"""Shared Gemini CLI advisory runner used by both design-checkpoint and review skills."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


DEFAULT_TIMEOUT_SECONDS = 1200
MAX_OUTPUT_CHARS = 12000
MAX_STAGED_BRIEFS = 20
STAGED_BRIEF_TTL_SECONDS = 7 * 24 * 60 * 60
DEFAULT_GEMINI_FLAGS = ("--sandbox=none",)
PROMPT_FALLBACK_MARKERS = ("unknown option", "unexpected argument", "unknown argument")
RESUME_FALLBACK_MARKERS = (
    "unknown option",
    "unexpected argument",
    "unknown argument",
    "unknown flag",
    "invalid session",
    "session not found",
    "could not find session",
)


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

def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "context"


def _path_digest(path: Path) -> str:
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _workspace_path(raw_path: str, project_root: Path) -> Path | None:
    cleaned = raw_path.strip()
    if not cleaned:
        return None
    path = Path(cleaned).expanduser()
    return path if path.is_absolute() else (project_root / path).absolute()


# ---------------------------------------------------------------------------
# Gemini project / session helpers
# ---------------------------------------------------------------------------

def _gemini_projects() -> dict[str, str]:
    projects_path = Path.home() / ".gemini" / "projects.json"
    try:
        payload = json.loads(projects_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    projects = payload.get("projects")
    return projects if isinstance(projects, dict) else {}


def _project_alias(project_root: Path) -> str:
    return str(_gemini_projects().get(str(project_root), "")).strip()


def _parse_gemini_timestamp(raw_value: object) -> float | None:
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00") if text.endswith("Z") else text
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return None


def _session_sort_key(chat_path: Path, payload: dict[str, object]) -> tuple[int, float, float, str]:
    last_updated = _parse_gemini_timestamp(payload.get("lastUpdated"))
    start_time = _parse_gemini_timestamp(payload.get("startTime"))
    timestamp = last_updated if last_updated is not None else start_time
    has_timestamp = 1 if timestamp is not None else 0
    try:
        modified_time = chat_path.stat().st_mtime
    except OSError:
        modified_time = 0.0
    return (has_timestamp, timestamp or 0.0, modified_time, chat_path.name)


def latest_project_session_id(project_root: Path) -> str:
    """Return the most-recently-updated Gemini session ID for *project_root*."""
    project_alias = _project_alias(project_root)
    if not project_alias:
        return ""

    chats_dir = Path.home() / ".gemini" / "tmp" / project_alias / "chats"
    if not chats_dir.is_dir():
        return ""

    best_key: tuple[int, float, float, str] | None = None
    latest_session_id = ""
    for chat_path in sorted(chats_dir.glob("session-*.json")):
        try:
            payload = json.loads(chat_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        session_id = str(payload.get("sessionId", "")).strip()
        if not session_id:
            continue
        ordering_key = _session_sort_key(chat_path, payload)
        if best_key is None or ordering_key >= best_key:
            best_key = ordering_key
            latest_session_id = session_id
    return latest_session_id


# ---------------------------------------------------------------------------
# Bridge directory & brief staging
# ---------------------------------------------------------------------------

def bridge_root_for_project(project_root: Path) -> Path:
    root = project_root / ".codex-gemini-advisories"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_staged_briefs(briefs_dir: Path, current_brief: Path) -> None:
    now = time.time()
    tracked_files: list[tuple[Path, float]] = []
    for path in briefs_dir.iterdir():
        if not path.is_file():
            continue
        try:
            tracked_files.append((path, path.stat().st_mtime))
        except FileNotFoundError:
            continue
    tracked_files.sort(key=lambda item: item[1], reverse=True)
    keep_recent = {path for path, _ in tracked_files[:MAX_STAGED_BRIEFS]}
    for path, modified_time in tracked_files:
        if path == current_brief:
            continue
        age_seconds = now - modified_time
        if age_seconds > STAGED_BRIEF_TTL_SECONDS or path not in keep_recent:
            path.unlink(missing_ok=True)


def stage_brief_file(brief_path: Path, bridge_root: Path) -> Path:
    briefs_dir = bridge_root / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    suffix = brief_path.suffix or ".md"
    staged_name = f"{_safe_name(brief_path.stem)}-{_path_digest(brief_path)}{suffix}"
    staged_path = briefs_dir / staged_name
    shutil.copy2(brief_path, staged_path)
    _cleanup_staged_briefs(briefs_dir, staged_path)
    return staged_path


def describe_paths(raw_paths: list[str], project_root: Path, bridge_root: Path) -> list[str]:
    resolved_project_root = project_root.resolve()
    resolved_bridge_root = bridge_root.resolve()
    described: list[str] = []
    for raw_path in raw_paths:
        path = _workspace_path(raw_path, resolved_project_root)
        if path is None:
            continue
        resolved_path = path.resolve()
        if _is_within(resolved_path, resolved_bridge_root) or not _is_within(resolved_path, resolved_project_root):
            continue
        if not resolved_path.exists():
            described.append(f"- {path} [missing]")
            continue
        kind = "directory" if resolved_path.is_dir() else "file"
        described.append(f"- {path} [{kind}]")
    return described


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def build_prompt(
    project_root: Path,
    brief_path: Path,
    context_entries: list[str],
    *,
    role_line: str,
    output_contract: str,
) -> str:
    """Assemble the full prompt from a role line, output contract, and paths."""
    sections = [
        role_line,
        "Use the local filesystem paths provided below as your primary context source.",
        output_contract,
        "## Current Workspace Root",
        f"- {project_root}",
        "## Required Local Brief",
        f"- {brief_path}",
    ]
    if context_entries:
        sections.append("## Local Paths To Inspect")
        sections.extend(context_entries)
    return "\n\n".join(sections).strip() + "\n"


# ---------------------------------------------------------------------------
# Gemini CLI invocation with fallbacks
# ---------------------------------------------------------------------------

def _should_fallback_resume(command: list[str], combined_output: str) -> bool:
    return "--resume" in command and any(marker in combined_output for marker in RESUME_FALLBACK_MARKERS)


def _should_fallback_prompt(command: list[str], combined_output: str) -> bool:
    return "-p" in command and any(marker in combined_output for marker in PROMPT_FALLBACK_MARKERS)


def _should_retry_command(command: list[str], combined_output: str) -> bool:
    return _should_fallback_resume(command, combined_output) or _should_fallback_prompt(command, combined_output)


def _candidate_commands(gemini: str, prompt: str, session_id: str) -> list[list[str]]:
    prompt_variants = [["-p", prompt], [prompt]]
    commands: list[list[str]] = []
    if session_id:
        commands.extend(
            [ [gemini, *DEFAULT_GEMINI_FLAGS, "--resume", session_id, *variant] for variant in prompt_variants ]
        )
    commands.extend([[gemini, *DEFAULT_GEMINI_FLAGS, *variant] for variant in prompt_variants])
    return commands


def run_gemini(prompt: str, timeout_seconds: int, project_root: Path) -> subprocess.CompletedProcess[str]:
    """Invoke ``gemini`` CLI with session-resume and flag fallbacks."""
    gemini = shutil.which("gemini")
    if not gemini:
        raise FileNotFoundError("gemini executable not found in PATH")

    env = os.environ.copy()
    env.setdefault("NO_COLOR", "1")
    env.setdefault("TERM", "dumb")

    session_id = latest_project_session_id(project_root)
    commands = _candidate_commands(gemini, prompt, session_id)

    last_result: subprocess.CompletedProcess[str] | None = None
    for command in commands:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            cwd=str(project_root),
            input="",
            check=False,
        )
        last_result = result
        combined = f"{result.stdout}\n{result.stderr}".lower()
        if result.returncode == 0 and result.stdout.strip():
            return result
        if _should_retry_command(command, combined):
            continue
        break

    assert last_result is not None
    return last_result


# ---------------------------------------------------------------------------
# Shared argument parser
# ---------------------------------------------------------------------------

def make_arg_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--brief-file", required=True, help="Markdown or text file with the brief.")
    parser.add_argument(
        "--context-file",
        action="append",
        default=[],
        help="Optional local file or directory Gemini should inspect directly. Repeat as needed.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Subprocess timeout in seconds. Default: {DEFAULT_TIMEOUT_SECONDS}.",
    )
    return parser


# ---------------------------------------------------------------------------
# Generic advisory entry point
# ---------------------------------------------------------------------------

def run_advisory(
    *,
    description: str,
    role_line: str,
    output_contract: str,
    label: str,
    argv: list[str] | None = None,
) -> int:
    """Run a Gemini advisory pass end-to-end and return an exit code.

    Parameters
    ----------
    description : str
        One-line parser description shown in ``--help``.
    role_line : str
        First line of the assembled prompt (sets the reviewer role).
    output_contract : str
        The Markdown template + rules Gemini must follow in its response.
    label : str
        Human label used in error messages, e.g. ``"design checkpoint"`` or ``"review"``.
    argv : list[str] | None
        Override for ``sys.argv[1:]``; mainly useful for testing.
    """
    parser = make_arg_parser(description)
    args = parser.parse_args(argv)

    brief_path = Path(args.brief_file).expanduser().resolve()
    if not brief_path.is_file():
        print(f"Brief file not found: {brief_path}", file=sys.stderr)
        return 2

    project_root = detect_project_root()
    bridge_root = bridge_root_for_project(project_root)
    staged_brief = stage_brief_file(brief_path, bridge_root)
    context_entries = describe_paths(args.context_file, project_root, bridge_root)

    prompt = build_prompt(
        project_root,
        staged_brief,
        context_entries,
        role_line=role_line,
        output_contract=output_contract,
    )

    try:
        result = run_gemini(prompt, args.timeout_seconds, project_root)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except subprocess.TimeoutExpired:
        print(f"Gemini {label} timed out after {args.timeout_seconds} seconds.", file=sys.stderr)
        return 4

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if result.returncode != 0 or not stdout:
        print(f"Gemini {label} failed with exit code {result.returncode}.", file=sys.stderr)
        if stderr:
            print(stderr[:MAX_OUTPUT_CHARS], file=sys.stderr)
        if stdout:
            print(stdout[:MAX_OUTPUT_CHARS], file=sys.stderr)
        return 5

    print(stdout[:MAX_OUTPUT_CHARS])
    return 0
