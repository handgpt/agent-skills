#!/usr/bin/env python3
"""Shared Gemini CLI advisory runner used by Claude Code Gemini skills."""
from __future__ import annotations

import argparse
import errno
import json
import os
import pty
import select
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


DEFAULT_TIMEOUT_SECONDS = 3600
MAX_OUTPUT_CHARS = 12000
MAX_PTY_OUTPUT_CHARS = 16000
DEFAULT_GEMINI_MODEL = "gemini-2.5-pro"
GEMINI_MODEL_ENV_VAR = "CLAUDE_GEMINI_MODEL"
DEFAULT_GEMINI_FLAGS = ("--approval-mode", "yolo")
GEMINI_SANDBOX_ENV_VAR = "GEMINI_SANDBOX"
GEMINI_SANDBOX_DISABLED_VALUE = "false"
GEMINI_OUTPUT_FORMAT = "json"
GEMINI_RUN_MODE_ENV_VAR = "CLAUDE_GEMINI_RUN_MODE"
DEFAULT_GEMINI_RUN_MODE = "interactive"
VALID_GEMINI_RUN_MODES = ("interactive", "headless")
GEMINI_SESSION_TTL_ENV_VAR = "CLAUDE_GEMINI_SESSION_TTL_SECONDS"
DEFAULT_SESSION_REUSE_TTL_SECONDS = 6 * 60 * 60
LANE_SESSION_STATE_FILE = "claude-lane-sessions.json"
GEMINI_PROJECTS_FILE = "projects.json"
GEMINI_TMP_DIRNAME = "tmp"
GEMINI_HISTORY_DIRNAME = "history"
PROJECT_ROOT_MARKER_FILE = ".project_root"
INLINE_PROMPT_TOO_LARGE_MESSAGE = (
    "Gemini inline prompt is too large for this platform's command-line limit. "
    "Reduce the brief size or switch to a non-argv prompt delivery path."
)
INTERACTIVE_STABILITY_SECONDS = 2.0
INTERACTIVE_POLL_SECONDS = 1.0
INTERACTIVE_SHUTDOWN_GRACE_SECONDS = 3.0
JSON_READ_RETRY_COUNT = 3
JSON_READ_RETRY_DELAY_SECONDS = 0.05
RESUME_FALLBACK_MARKERS = (
    "unknown option",
    "unexpected argument",
    "unknown argument",
    "unknown flag",
    "invalid session",
    "session not found",
    "could not find session",
    "error resuming session",
)
INTERACTIVE_ERROR_MARKERS = (
    "429",
    "too many requests",
    "resource_exhausted",
    "api error",
    "error resuming session",
    "session not found",
    "invalid session",
    "unavailable",
)
TERMINAL_TOOL_STATUSES = {"success", "error", "cancelled"}
THOUGHT_PROGRESS_PREFIX = "[Gemini thought]"
WAIT_PROGRESS_PREFIX = "[Gemini wait]"
MAX_THOUGHT_TEXT_CHARS = 400
EXIT_RESUME_PROGRESS_NOTE = (
    "[Gemini thought] Gemini exited before a final reply was recorded; "
    "resuming the same session and continuing to wait."
)
RUN_MARKER_PREFIX = "cadv-"
META_CHATTER_MARKERS = (
    "what would you like",
    "would you like me to",
    "do you want me to",
    "please tell me",
    "let me know if you'd like",
    "let me know if you would like",
    "i will begin",
    "i'll begin",
    "i will start by",
    "i'll start by",
    "i will inspect",
    "i'll inspect",
    "i will search",
    "i'll search",
    "i will look",
    "i'll look",
    "i have begun",
    "i've begun",
    "i am currently reviewing",
    "i'm currently reviewing",
    "i am going to",
    "i'm going to",
    "i will now",
    "i'll now",
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


def detect_workspace_root() -> Path:
    """Prefer the nearest CLAUDE.md-scoped workspace root, then fall back to project root."""
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "CLAUDE.md").is_file() or (candidate / "AGENTS.md").is_file():
            return candidate
    return detect_project_root()


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


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


def _uses_home_shorthand(path: Path) -> bool:
    try:
        path.resolve().relative_to(Path.home().resolve())
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


def _display_workspace_path(path: Path, project_root: Path) -> str:
    if _uses_home_shorthand(project_root):
        try:
            relative_path = path.resolve().relative_to(project_root.resolve())
            return "." if str(relative_path) == "." else relative_path.as_posix()
        except ValueError:
            pass
    return _tilde_path(path)


def _append_context_entry(
    described: list[str],
    seen: set[Path],
    path: Path,
    kind: str,
    project_root: Path,
) -> None:
    if path in seen:
        return
    seen.add(path)
    described.append(f"- {_display_workspace_path(path, project_root)} [{kind}]")


def _is_within_any(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(_is_within(path, root) for root in roots)


def _allowed_project_roots(
    project_root: Path, project_roots: tuple[Path, ...] | None = None
) -> tuple[Path, ...]:
    if project_roots:
        normalized_roots: list[Path] = []
        seen: set[Path] = set()
        for root in project_roots:
            resolved_root = root.resolve()
            if resolved_root in seen:
                continue
            seen.add(resolved_root)
            normalized_roots.append(resolved_root)
        if normalized_roots:
            return tuple(normalized_roots)
    return (project_root.resolve(),)


def _detect_git_root_for_path(path: Path) -> Path | None:
    git = shutil.which("git")
    if not git:
        return None
    start_dir = path if path.is_dir() else path.parent
    try:
        result = subprocess.run(
            [git, "-C", str(start_dir), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            input="",
            check=False,
        )
    except Exception:
        return None
    root = result.stdout.strip()
    if result.returncode != 0 or not root:
        return None
    return Path(root).resolve()


def _normalize_multi_project_roots(
    raw_project_roots: list[str],
    raw_paths: list[str],
    default_project_root: Path,
    workspace_boundary: Path,
) -> tuple[Path, ...]:
    resolved_workspace_boundary = workspace_boundary.resolve()
    roots: list[Path] = []
    seen: set[Path] = set()

    def add_root(candidate: Path | None) -> None:
        if candidate is None:
            return
        resolved_candidate = candidate.resolve()
        if not _is_within(resolved_candidate, resolved_workspace_boundary):
            return
        if resolved_candidate in seen:
            return
        seen.add(resolved_candidate)
        roots.append(resolved_candidate)

    for raw_root in raw_project_roots:
        path = Path(raw_root.strip()).expanduser()
        if not path.is_absolute():
            path = (resolved_workspace_boundary / path).absolute()
        if path.exists() and path.is_file():
            path = path.parent
        add_root(path if path.exists() else None)

    if not roots:
        for raw_path in raw_paths:
            path = Path(raw_path.strip()).expanduser()
            if not path.is_absolute():
                path = (resolved_workspace_boundary / path).absolute()
            add_root(_detect_git_root_for_path(path))

    if not roots:
        add_root(default_project_root.resolve())
    return tuple(roots) if roots else (default_project_root.resolve(),)


def _multi_project_workspace_root(
    project_roots: tuple[Path, ...], default_project_root: Path, workspace_boundary: Path
) -> Path:
    if not project_roots:
        return default_project_root.resolve()
    resolved_workspace_boundary = workspace_boundary.resolve()
    common_root = Path(os.path.commonpath([str(path) for path in project_roots]))
    if _is_within(common_root, resolved_workspace_boundary):
        return common_root
    return (
        resolved_workspace_boundary
        if _is_within(resolved_workspace_boundary, common_root)
        else default_project_root.resolve()
    )


def _project_roots_in_scope(
    project_root: Path, project_roots: tuple[Path, ...] | None = None
) -> tuple[Path, ...]:
    allowed_roots = _allowed_project_roots(project_root, project_roots)
    in_scope_roots: list[Path] = []
    seen: set[Path] = set()
    for root in allowed_roots:
        if not _is_within(root, project_root.resolve()) and root != project_root.resolve():
            continue
        if root in seen:
            continue
        seen.add(root)
        in_scope_roots.append(root)
    return tuple(in_scope_roots) if in_scope_roots else (project_root.resolve(),)


def _context_paths(
    raw_paths: list[str],
    project_root: Path,
    project_roots: tuple[Path, ...] | None = None,
) -> list[Path]:
    resolved_project_root = project_root.resolve()
    allowed_roots = _project_roots_in_scope(resolved_project_root, project_roots)
    context_paths: list[Path] = []
    seen: set[Path] = set()
    for raw_path in raw_paths:
        path = _workspace_path(raw_path, resolved_project_root)
        if path is None:
            continue
        resolved_path = path.resolve()
        if not _is_within(resolved_path, resolved_project_root):
            continue
        if not _is_within_any(resolved_path, allowed_roots):
            continue
        if resolved_path in seen:
            continue
        seen.add(resolved_path)
        context_paths.append(path)
    return context_paths


def describe_paths(
    raw_paths: list[str],
    project_root: Path,
    project_roots: tuple[Path, ...] | None = None,
) -> list[str]:
    described: list[str] = []
    seen: set[Path] = set()
    resolved_project_root = project_root.resolve()
    for path in _context_paths(raw_paths, project_root, project_roots):
        if not path.exists():
            _append_context_entry(described, seen, path, "missing", resolved_project_root)
            continue
        kind = "directory" if path.is_dir() else "file"
        _append_context_entry(described, seen, path, kind, resolved_project_root)
    return described


def _focus_scope_root(
    raw_paths: list[str],
    project_root: Path,
    project_roots: tuple[Path, ...] | None = None,
) -> Path:
    resolved_project_root = project_root.resolve()
    scope_candidates: list[Path] = []
    for path in _context_paths(raw_paths, resolved_project_root, project_roots):
        resolved_path = path.resolve()
        candidate = resolved_path if path.is_dir() else resolved_path.parent
        if not _is_within(candidate, resolved_project_root):
            continue
        scope_candidates.append(candidate)
    if not scope_candidates:
        return resolved_project_root
    common = Path(os.path.commonpath([str(path) for path in scope_candidates]))
    return common if _is_within(common, resolved_project_root) else resolved_project_root


# ---------------------------------------------------------------------------
# Lane session helpers
# ---------------------------------------------------------------------------


def _lane_state_path() -> Path:
    return Path.home() / ".gemini" / LANE_SESSION_STATE_FILE


def _load_lane_state() -> dict[str, object]:
    state_path = _lane_state_path()
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_lane_state(payload: dict[str, object]) -> None:
    state_path = _lane_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def configured_session_reuse_ttl_seconds() -> int:
    raw_value = os.environ.get(GEMINI_SESSION_TTL_ENV_VAR, "").strip()
    if not raw_value:
        return DEFAULT_SESSION_REUSE_TTL_SECONDS
    try:
        ttl_seconds = int(raw_value)
    except ValueError:
        return DEFAULT_SESSION_REUSE_TTL_SECONDS
    return max(0, ttl_seconds)


def _scope_key(project_root: Path, scope_root: Path | None = None) -> str:
    resolved_project_root = project_root.resolve()
    resolved_scope_root = (scope_root or resolved_project_root).resolve()
    if not _is_within(resolved_scope_root, resolved_project_root):
        resolved_scope_root = resolved_project_root
    try:
        relative_path = resolved_scope_root.relative_to(resolved_project_root)
    except ValueError:
        return "."
    return "." if str(relative_path) == "." else relative_path.as_posix()


def _project_set_key(
    project_root: Path, project_roots: tuple[Path, ...] | None = None
) -> str:
    normalized_roots = _project_roots_in_scope(project_root, project_roots)
    relative_roots: list[str] = []
    for root in normalized_roots:
        try:
            relative_path = root.relative_to(project_root.resolve())
        except ValueError:
            continue
        relative_roots.append("." if str(relative_path) == "." else relative_path.as_posix())
    if not relative_roots:
        return "."
    return "|".join(sorted(relative_roots))


def _lane_state_key(
    project_root: Path,
    lane: str,
    scope_root: Path | None = None,
    project_roots: tuple[Path, ...] | None = None,
) -> str:
    return (
        f"{project_root.resolve()}::{lane}::projects="
        f"{_project_set_key(project_root, project_roots)}::scope="
        f"{_scope_key(project_root, scope_root)}"
    )


def _legacy_lane_state_key(project_root: Path, lane: str) -> str:
    return f"{project_root.resolve()}::{lane}"


def _remember_lane_session(
    project_root: Path,
    lane: str,
    session_id: str,
    scope_root: Path | None = None,
    project_roots: tuple[Path, ...] | None = None,
) -> None:
    if not lane or not session_id:
        return
    resolved_scope_root = project_root.resolve()
    if scope_root is not None:
        candidate_scope_root = scope_root.resolve()
        if _is_within(candidate_scope_root, resolved_scope_root):
            resolved_scope_root = candidate_scope_root
    payload = _load_lane_state()
    normalized_project_roots = _project_roots_in_scope(project_root, project_roots)
    payload[_lane_state_key(project_root, lane, resolved_scope_root, normalized_project_roots)] = {
        "lane": lane,
        "projectRoot": str(project_root.resolve()),
        "projectRoots": [str(root) for root in normalized_project_roots],
        "scopeRoot": str(resolved_scope_root),
        "sessionId": session_id,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    _save_lane_state(payload)


def _saved_lane_session_id(
    project_root: Path,
    lane: str,
    scope_root: Path | None = None,
    project_roots: tuple[Path, ...] | None = None,
) -> str:
    if not lane:
        return ""
    payload = _load_lane_state()
    entry = payload.get(_lane_state_key(project_root, lane, scope_root, project_roots))
    if (
        not isinstance(entry, dict)
        and _scope_key(project_root, scope_root) == "."
        and _project_set_key(project_root, project_roots) == "."
    ):
        entry = payload.get(_legacy_lane_state_key(project_root, lane))
    if not isinstance(entry, dict):
        return ""
    ttl_seconds = configured_session_reuse_ttl_seconds()
    if ttl_seconds <= 0:
        return ""
    raw_updated_at = entry.get("updatedAt")
    updated_at = _parse_iso_timestamp(raw_updated_at)
    if raw_updated_at in (None, ""):
        return str(entry.get("sessionId", "")).strip()
    if updated_at is None:
        return ""
    if (datetime.now(timezone.utc) - updated_at).total_seconds() > ttl_seconds:
        return ""
    return str(entry.get("sessionId", "")).strip()


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_prompt(
    project_root: Path,
    brief_text: str,
    context_entries: list[str],
    *,
    lane: str,
    focus_root: Path,
    project_roots: tuple[Path, ...] | None = None,
    run_marker: str = "",
    role_line: str,
    output_contract: str,
) -> str:
    """Assemble the full prompt from a role line, output contract, and paths."""
    resolved_project_root = project_root.resolve()
    resolved_focus_root = focus_root.resolve()
    normalized_project_roots = _project_roots_in_scope(
        resolved_project_root, project_roots
    )
    project_scope_key = _project_set_key(resolved_project_root, normalized_project_roots)
    if not _is_within(resolved_focus_root, resolved_project_root):
        resolved_focus_root = resolved_project_root
    sections = [
        role_line,
        "You are running inside Gemini CLI on the same machine as the codebase.",
        (
            "Use the workspace root below as your filesystem boundary. "
            "You may inspect any local file or directory inside that workspace root "
            "if it helps you answer well."
        ),
        (
            "This advisory is only for the projects and directories listed below. "
            "Ignore prior session context about any other project unless it is "
            "explicitly listed in the current projects-in-scope section."
        ),
        (
            "Treat this as a fresh single-turn advisory. Ignore unfinished work, "
            "tool chatter, reminders, draft content, and follow-up questions from "
            "earlier turns in this session."
        ),
        (
            "Return only the final Markdown answer for the current task. Do not add "
            "a preamble, do not describe which tools you might use, and do not ask "
            "what to do next."
        ),
        output_contract,
        "## Projects In Scope",
    ]
    for scoped_root in normalized_project_roots:
        sections.append(
            f"- {scoped_root.name}: {_display_workspace_path(scoped_root, resolved_project_root)}"
        )
    sections.extend(
        [
        "## Current Advisory Target",
        f"- Project Name: {resolved_project_root.name}",
        f"- Advisory Lane: {lane}",
        f"- Project Scope Key: {project_scope_key}",
        f"- Target Directory: {_display_workspace_path(resolved_focus_root, resolved_project_root)}",
        f"- Workspace Root: {_tilde_path(resolved_project_root)}",
        f"- Run Marker: {run_marker or f'{RUN_MARKER_PREFIX}none'}",
        "## Inlined Brief",
        brief_text.strip() or "- The brief file was empty.",
        ]
    )
    if context_entries:
        sections.append("## Priority Paths To Start From")
        sections.extend(context_entries)
        sections.append(
            "Treat those paths as starting points, not as an exhaustive file list. Decide for yourself which other workspace-local files or directories you should inspect."
        )
    else:
        sections.append(
            "No priority paths were supplied. Explore the workspace root as needed, but stay inside it."
        )
    return "\n\n".join(sections).strip() + "\n"


# ---------------------------------------------------------------------------
# Generic Gemini CLI configuration
# ---------------------------------------------------------------------------


def configured_gemini_model() -> str:
    model = os.environ.get(GEMINI_MODEL_ENV_VAR, DEFAULT_GEMINI_MODEL).strip()
    return model or DEFAULT_GEMINI_MODEL


def configured_run_mode(explicit_mode: str | None = None) -> str:
    candidate = (
        explicit_mode or os.environ.get(GEMINI_RUN_MODE_ENV_VAR, DEFAULT_GEMINI_RUN_MODE)
    ).strip()
    if candidate not in VALID_GEMINI_RUN_MODES:
        return DEFAULT_GEMINI_RUN_MODE
    return candidate


def _gemini_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("COLORTERM", "truecolor")
    env[GEMINI_SANDBOX_ENV_VAR] = GEMINI_SANDBOX_DISABLED_VALUE
    return env


def _safe_prompt_argument(prompt: str) -> str:
    return prompt if not prompt.startswith("-") else "\n" + prompt


def _combined_result_output(result: subprocess.CompletedProcess[str]) -> str:
    combined = "\n".join(
        part for part in (result.stdout, result.stderr) if part
    ).strip()
    return combined[:MAX_OUTPUT_CHARS]


def _raise_e2big(exc: OSError) -> OSError:
    return OSError(errno.E2BIG, INLINE_PROMPT_TOO_LARGE_MESSAGE)


def _trim_output_tail(current: str, addition: str) -> str:
    if not addition:
        return current
    combined = current + addition
    if len(combined) <= MAX_PTY_OUTPUT_CHARS:
        return combined
    return combined[-MAX_PTY_OUTPUT_CHARS:]


def _should_retry_resume(command: list[str], combined_output: str) -> bool:
    lowered = combined_output.lower()
    return "--resume" in command and any(
        marker in lowered for marker in RESUME_FALLBACK_MARKERS
    )


# ---------------------------------------------------------------------------
# Gemini CLI headless non-interactive invocation
# ---------------------------------------------------------------------------


def _noninteractive_command(gemini: str, prompt: str, session_id: str) -> list[str]:
    command = [
        gemini,
        *DEFAULT_GEMINI_FLAGS,
        "--model",
        configured_gemini_model(),
        "--output-format",
        GEMINI_OUTPUT_FORMAT,
    ]
    if session_id:
        command.extend(["--resume", session_id])
    command.append(_safe_prompt_argument(prompt))
    return command


def _extract_json_payload(raw_text: str) -> dict[str, object] | None:
    stripped = raw_text.strip()
    if not stripped:
        return None

    candidates: list[dict[str, object]] = []
    decoder = json.JSONDecoder()
    for start_index, character in enumerate(stripped):
        if character != "{":
            continue
        try:
            payload, end_index = decoder.raw_decode(stripped[start_index:])
        except json.JSONDecodeError:
            continue
        trailing = stripped[start_index + end_index :].strip()
        if isinstance(payload, dict) and not trailing:
            candidates.append(payload)

    for candidate in candidates:
        if any(
            key in candidate for key in ("session_id", "response", "error", "stats")
        ):
            return candidate
    return None


def _format_json_error(error_payload: object) -> str:
    if isinstance(error_payload, str):
        return error_payload.strip()
    if not isinstance(error_payload, dict):
        return ""

    parts: list[str] = []
    error_type = str(error_payload.get("type", "")).strip()
    message = str(error_payload.get("message", "")).strip()
    code = str(error_payload.get("code", "")).strip()
    if error_type:
        parts.append(error_type)
    if code:
        parts.append(code)
    if message:
        parts.append(message)
    if parts:
        return ": ".join(parts)
    return json.dumps(error_payload, ensure_ascii=False)


def _parse_cli_result(
    result: subprocess.CompletedProcess[str],
) -> tuple[str, str, str]:
    payload = _extract_json_payload(result.stdout)
    if payload is None:
        return ("", "", "")

    session_id = str(payload.get("session_id", "")).strip()
    response = payload.get("response")
    error = payload.get("error")
    response_text = response.strip() if isinstance(response, str) else ""
    error_text = _format_json_error(error)
    return (session_id, response_text, error_text)


def _expected_markdown_headings(output_contract: str) -> tuple[str, ...]:
    headings: list[str] = []
    for line in output_contract.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            headings.append(stripped)
    return tuple(headings)


def _strip_outer_markdown_fence(output_text: str) -> str:
    lines = output_text.strip().splitlines()
    if len(lines) < 3:
        return output_text.strip()
    first_line = lines[0].strip()
    last_line = lines[-1].strip()
    if not first_line.startswith("```") or last_line != "```":
        return output_text.strip()
    return "\n".join(lines[1:-1]).strip()


def _looks_like_meta_chatter(output_text: str) -> bool:
    lowered = output_text.strip().lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in META_CHATTER_MARKERS)


def _normalize_advisory_output(
    output_text: str, expected_headings: tuple[str, ...] = ()
) -> str:
    stripped_output = _strip_outer_markdown_fence(output_text)
    if not stripped_output:
        return ""

    lines = stripped_output.splitlines()
    if expected_headings:
        expected_heading_set = {heading.casefold() for heading in expected_headings}
        first_expected_heading_index = next(
            (
                index
                for index, line in enumerate(lines)
                if line.strip().casefold() in expected_heading_set
            ),
            None,
        )
        if first_expected_heading_index not in (None, 0):
            prefix = "\n".join(lines[:first_expected_heading_index]).strip()
            if prefix and _looks_like_meta_chatter(prefix):
                lines = lines[first_expected_heading_index:]

    if len(lines) > 1:
        trailing_tail = "\n".join(lines[-3:]).strip()
        if trailing_tail and _looks_like_meta_chatter(trailing_tail):
            trimmed_lines = lines[:]
            for index in range(max(0, len(lines) - 3), len(lines)):
                if _looks_like_meta_chatter("\n".join(lines[index:]).strip()):
                    trimmed_lines = lines[:index]
                    break
            lines = trimmed_lines

    return "\n".join(lines).strip()


def build_output_normalizer(output_contract: str) -> Callable[[str], str]:
    expected_headings = _expected_markdown_headings(output_contract)

    def normalize(output_text: str) -> str:
        return _normalize_advisory_output(output_text, expected_headings)

    return normalize


def build_output_validator(output_contract: str) -> Callable[[str], str]:
    expected_headings = _expected_markdown_headings(output_contract)
    normalize_output = build_output_normalizer(output_contract)

    def validate(output_text: str) -> str:
        stripped_output = normalize_output(output_text)
        if not stripped_output:
            return "Gemini returned empty output."

        nonempty_lines = [
            line.strip() for line in stripped_output.splitlines() if line.strip()
        ]
        if not nonempty_lines:
            return "Gemini returned empty output."

        if _looks_like_meta_chatter(stripped_output):
            return "Gemini returned meta chatter instead of a final advisory."

        if expected_headings:
            actual_headings = {
                line.strip().casefold()
                for line in stripped_output.splitlines()
                if line.strip().startswith("## ")
            }
            if actual_headings and not any(
                heading.casefold() in actual_headings for heading in expected_headings
            ):
                return (
                    "Gemini output used headings from the wrong advisory shape "
                    "and appears to belong to a different task."
                )
        return ""

    return validate


def _run_noninteractive_attempt(
    command: list[str], timeout_seconds: int, project_root: Path
) -> subprocess.CompletedProcess[str]:
    env = _gemini_environment()
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(project_root),
            env=env,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except OSError as exc:
        if exc.errno == errno.E2BIG:
            raise _raise_e2big(exc) from exc
        raise


def _run_headless(
    prompt: str,
    timeout_seconds: int,
    project_root: Path,
    *,
    lane: str,
    scope_root: Path,
    project_roots: tuple[Path, ...] | None = None,
    output_normalizer: Callable[[str], str] | None = None,
    output_validator: Callable[[str], str] | None = None,
) -> subprocess.CompletedProcess[str]:
    gemini = shutil.which("gemini")
    if not gemini:
        raise FileNotFoundError("gemini executable not found in PATH")

    session_id = _saved_lane_session_id(
        project_root, lane, scope_root, project_roots
    )
    commands = [_noninteractive_command(gemini, prompt, session_id)]
    if session_id:
        commands.append(_noninteractive_command(gemini, prompt, ""))

    last_result: subprocess.CompletedProcess[str] | None = None
    for command in commands:
        result = _run_noninteractive_attempt(command, timeout_seconds, project_root)
        last_result = result

        resolved_session_id, response_text, error_text = _parse_cli_result(result)
        if resolved_session_id:
            _remember_lane_session(
                project_root,
                lane,
                resolved_session_id,
                scope_root,
                project_roots,
            )

        if result.returncode == 0:
            normalized_response = (
                output_normalizer(response_text)
                if output_normalizer
                else response_text.strip()
            )
            validation_error = (
                output_validator(normalized_response) if output_validator else ""
            )
            if validation_error:
                if "--resume" in command:
                    continue
                return subprocess.CompletedProcess(command, 1, "", validation_error)
            if normalized_response:
                return subprocess.CompletedProcess(
                    command, 0, normalized_response, ""
                )

        combined_output = (error_text or _combined_result_output(result)).strip()
        if _should_retry_resume(command, combined_output):
            continue

        return subprocess.CompletedProcess(
            command,
            result.returncode or 1,
            response_text,
            combined_output,
        )

    assert last_result is not None
    return last_result


# ---------------------------------------------------------------------------
# Gemini CLI interactive invocation
# ---------------------------------------------------------------------------


def _interactive_command(gemini: str, prompt: str, session_id: str) -> list[str]:
    command = [
        gemini,
        *DEFAULT_GEMINI_FLAGS,
        "--model",
        configured_gemini_model(),
    ]
    if session_id:
        command.extend(["--resume", session_id])
    command.extend(["-i", _safe_prompt_argument(prompt)])
    return command


def _project_registry_path() -> Path:
    return Path.home() / ".gemini" / GEMINI_PROJECTS_FILE


def _project_registry_base_dirs() -> tuple[Path, ...]:
    gemini_dir = Path.home() / ".gemini"
    return (
        gemini_dir / GEMINI_TMP_DIRNAME,
        gemini_dir / GEMINI_HISTORY_DIRNAME,
    )


def _load_project_registry() -> dict[str, str]:
    try:
        payload = json.loads(_project_registry_path().read_text(encoding="utf-8"))
    except Exception:
        return {}
    projects = payload.get("projects") if isinstance(payload, dict) else None
    return projects if isinstance(projects, dict) else {}


def _normalize_project_path(project_root: Path) -> str:
    normalized = str(project_root.resolve())
    if os.name == "nt":
        normalized = normalized.lower()
    return normalized


def _verify_slug_ownership(slug: str, normalized_project_root: str) -> bool:
    for base_dir in _project_registry_base_dirs():
        marker_path = base_dir / slug / PROJECT_ROOT_MARKER_FILE
        if not marker_path.is_file():
            continue
        try:
            owner = _normalize_project_path(
                Path(marker_path.read_text(encoding="utf-8").strip())
            )
        except Exception:
            return False
        if owner != normalized_project_root:
            return False
    return True


def _find_slug_by_marker(normalized_project_root: str) -> str:
    for base_dir in _project_registry_base_dirs():
        if not base_dir.is_dir():
            continue
        try:
            candidates = sorted(base_dir.iterdir(), key=lambda path: path.name)
        except Exception:
            continue
        for candidate in candidates:
            marker_path = candidate / PROJECT_ROOT_MARKER_FILE
            if not marker_path.is_file():
                continue
            try:
                owner = _normalize_project_path(Path(marker_path.read_text(encoding="utf-8").strip()))
            except Exception:
                continue
            if owner == normalized_project_root:
                return candidate.name
    return ""


def _project_short_id(project_root: Path) -> str:
    normalized_project_root = _normalize_project_path(project_root)
    registry_slug = str(
        _load_project_registry().get(normalized_project_root, "")
    ).strip()
    if registry_slug and _verify_slug_ownership(registry_slug, normalized_project_root):
        return registry_slug
    return _find_slug_by_marker(normalized_project_root)


def _project_chats_dir(project_root: Path) -> Path | None:
    short_id = _project_short_id(project_root)
    if not short_id:
        return None
    return Path.home() / ".gemini" / GEMINI_TMP_DIRNAME / short_id / "chats"


def _session_file_glob(session_id: str) -> str:
    short_id = session_id.strip()[:8]
    if short_id:
        return f"session-*-{short_id}.json"
    return "session-*.json"


def _parse_iso_timestamp(raw_value: object) -> datetime | None:
    if not isinstance(raw_value, str):
        return None
    text = raw_value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _conversation_sort_key(path: Path, conversation: dict[str, object]) -> tuple[float, str]:
    for field in ("lastUpdated", "startTime"):
        parsed = _parse_iso_timestamp(conversation.get(field))
        if parsed is not None:
            return (parsed.timestamp(), path.name)
    return (path.stat().st_mtime, path.name)


def _load_conversation(path: Path) -> dict[str, object] | None:
    payload = _load_json_file(path)
    return payload if isinstance(payload, dict) else None


def _load_json_file(path: Path) -> dict[str, object] | None:
    for attempt in range(JSON_READ_RETRY_COUNT):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            if attempt + 1 >= JSON_READ_RETRY_COUNT:
                return None
            time.sleep(JSON_READ_RETRY_DELAY_SECONDS)
            continue
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None
    return None


def _is_subagent_conversation(conversation: dict[str, object]) -> bool:
    return str(conversation.get("kind", "")).strip() == "subagent"


def _session_conversations_for_id(
    project_root: Path, session_id: str
) -> list[tuple[tuple[float, str], Path, dict[str, object]]]:
    chats_dir = _project_chats_dir(project_root)
    if not chats_dir or not chats_dir.is_dir():
        return []

    matches: list[tuple[tuple[float, str], Path, dict[str, object]]] = []
    for path in chats_dir.glob(_session_file_glob(session_id)):
        conversation = _load_conversation(path)
        if not conversation:
            continue
        if _is_subagent_conversation(conversation):
            continue
        if str(conversation.get("sessionId", "")).strip() != session_id:
            continue
        matches.append((_conversation_sort_key(path, conversation), path, conversation))
    matches.sort(key=lambda item: item[0])
    return matches


def _conversation_messages(conversation: dict[str, object]) -> list[dict[str, object]]:
    messages = conversation.get("messages")
    if not isinstance(messages, list):
        return []
    return [message for message in messages if isinstance(message, dict)]


def _extract_text_from_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [_extract_text_from_content(item) for item in content]
        return "".join(part for part in parts if part)
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"]
        if isinstance(content.get("response"), dict):
            return _extract_text_from_content(content["response"])
        if isinstance(content.get("output"), str):
            return content["output"]
    return ""


def _message_text(message: dict[str, object]) -> str:
    text = _extract_text_from_content(message.get("content"))
    if text:
        return text
    return _extract_text_from_content(message.get("displayContent"))


def _message_identity(message: dict[str, object]) -> str:
    message_id = str(message.get("id", "")).strip()
    if message_id:
        return f"id:{message_id}"
    tool_call_ids: list[str] = []
    tool_calls = message.get("toolCalls")
    if isinstance(tool_calls, list):
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            tool_call_ids.append(str(tool_call.get("id", "")).strip())
    fallback = {
        "timestamp": str(message.get("timestamp", "")).strip(),
        "type": str(message.get("type", "")).strip(),
        "text": _message_text(message).strip(),
        "toolCallIds": tool_call_ids,
    }
    return "fallback:" + json.dumps(fallback, ensure_ascii=False, sort_keys=True)


def _message_timestamp_sort_value(message: dict[str, object]) -> float:
    parsed = _parse_iso_timestamp(message.get("timestamp"))
    if parsed is None:
        return float("inf")
    return parsed.timestamp()


def _message_thoughts(message: dict[str, object]) -> list[dict[str, object]]:
    thoughts = message.get("thoughts")
    if not isinstance(thoughts, list):
        return []
    return [thought for thought in thoughts if isinstance(thought, dict)]


def _thought_signature(thought: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(thought.get("timestamp", "")).strip(),
        str(thought.get("subject", "")).strip(),
        str(thought.get("description", "")).strip(),
    )


def _thought_text(thought: dict[str, object]) -> str:
    subject = str(thought.get("subject", "")).strip()
    description = str(thought.get("description", "")).strip()
    if subject and description:
        return f"{subject}: {description}"
    return subject or description


def _tool_call_signature(tool_call: dict[str, object]) -> tuple[str, str, str, int]:
    result_text = _extract_text_from_content(tool_call.get("result")).strip()
    return (
        str(tool_call.get("id", "")).strip(),
        str(tool_call.get("name", "")).strip(),
        str(tool_call.get("status", "")).strip().lower(),
        len(result_text),
    )


def _message_progress_signature(
    message: dict[str, object],
) -> tuple[
    str,
    str,
    str,
    tuple[tuple[str, str, str], ...],
    tuple[tuple[str, str, str, int], ...],
]:
    tool_calls = message.get("toolCalls")
    tool_signatures: list[tuple[str, str, str, int]] = []
    if isinstance(tool_calls, list):
        for tool_call in tool_calls:
            if isinstance(tool_call, dict):
                tool_signatures.append(_tool_call_signature(tool_call))
    return (
        _message_identity(message),
        str(message.get("type", "")).strip(),
        _message_text(message).strip(),
        tuple(_thought_signature(thought) for thought in _message_thoughts(message)),
        tuple(tool_signatures),
    )


def _latest_turn_messages(new_messages: list[dict[str, object]]) -> list[dict[str, object]]:
    last_user_index = -1
    for index, message in enumerate(new_messages):
        if str(message.get("type", "")).strip() == "user":
            last_user_index = index
    if last_user_index == -1:
        return []
    return new_messages[last_user_index + 1 :]


def _latest_turn_thought_entries(
    new_messages: list[dict[str, object]],
) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for message in _latest_turn_messages(new_messages):
        message_key = _message_identity(message)
        for index, thought in enumerate(_message_thoughts(message)):
            thought_key = (
                f"{message_key}|{index}|"
                f"{thought.get('timestamp', '')}|{thought.get('subject', '')}|"
                f"{thought.get('description', '')}"
            )
            thought_text = _thought_text(thought).strip()
            entries.append((thought_key, thought_text))
    return entries


def _emit_new_thought_progress(
    new_messages: list[dict[str, object]], seen_thought_keys: set[str]
) -> set[str]:
    updated_keys = set(seen_thought_keys)
    for thought_key, thought_text in _latest_turn_thought_entries(new_messages):
        if thought_key in updated_keys:
            continue
        updated_keys.add(thought_key)
        if thought_text:
            print(
                f"{THOUGHT_PROGRESS_PREFIX} {thought_text[:MAX_THOUGHT_TEXT_CHARS]}",
                file=sys.stderr,
                flush=True,
            )
    return updated_keys


def _emit_wait_progress(
    now: float,
    start_monotonic: float,
    timeout_seconds: int,
    last_percent: int,
) -> int:
    if timeout_seconds <= 0:
        percent = 100
        elapsed_seconds = 0
    else:
        elapsed_seconds = max(0, int(now - start_monotonic))
        percent = min(100, int(((now - start_monotonic) / timeout_seconds) * 100))
    if percent <= last_percent:
        return last_percent
    print(
        f"{WAIT_PROGRESS_PREFIX} {percent}% ({elapsed_seconds}s/{timeout_seconds}s)",
        file=sys.stderr,
        flush=True,
    )
    return percent


def _latest_turn_has_thoughts(new_messages: list[dict[str, object]]) -> bool:
    return bool(_latest_turn_thought_entries(new_messages))


def _merged_session_messages(project_root: Path, session_id: str) -> list[dict[str, object]]:
    conversations = _session_conversations_for_id(project_root, session_id)
    merged_messages: dict[str, dict[str, object]] = {}
    ordering: dict[str, tuple[float, float, str, int, str]] = {}

    for conversation_sort_key, _path, conversation in conversations:
        conversation_time = conversation_sort_key[0]
        conversation_name = conversation_sort_key[1]
        for index, message in enumerate(_conversation_messages(conversation)):
            key = _message_identity(message)
            merged_messages[key] = message
            ordering[key] = (
                _message_timestamp_sort_value(message),
                conversation_time,
                conversation_name,
                index,
                key,
            )

    ordered_keys = sorted(ordering, key=lambda key: ordering[key])
    return [merged_messages[key] for key in ordered_keys]


def _message_has_active_tool_calls(message: dict[str, object]) -> bool:
    if str(message.get("type", "")).strip() != "gemini":
        return False
    tool_calls = message.get("toolCalls")
    if not isinstance(tool_calls, list):
        return False
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        status = str(tool_call.get("status", "")).strip().lower()
        if status and status not in TERMINAL_TOOL_STATUSES:
            return True
    return False


def _saved_reusable_lane_session_id(
    project_root: Path,
    lane: str,
    scope_root: Path | None = None,
    project_roots: tuple[Path, ...] | None = None,
    output_normalizer: Callable[[str], str] | None = None,
    output_validator: Callable[[str], str] | None = None,
) -> str:
    session_id = _saved_lane_session_id(
        project_root, lane, scope_root, project_roots
    )
    if not session_id:
        return ""
    messages = _merged_session_messages(project_root, session_id)
    if not messages:
        return ""
    outcome = _interactive_outcome(messages)
    if not outcome or outcome[0] != "success":
        return ""
    normalized_output = (
        output_normalizer(outcome[1]) if output_normalizer else outcome[1].strip()
    )
    if not normalized_output:
        return ""
    if output_validator and output_validator(normalized_output):
        return ""
    return session_id


def _normalized_prompt_text(text: str) -> str:
    return text.strip()


def _prompt_run_marker(prompt: str) -> str:
    marker_prefix = "- Run Marker:"
    for line in prompt.splitlines():
        stripped = line.strip()
        if stripped.startswith(marker_prefix):
            return stripped[len(marker_prefix) :].strip()
    return ""


def _prompt_variants(prompt: str) -> set[str]:
    variants = {
        _normalized_prompt_text(prompt),
        _normalized_prompt_text(_safe_prompt_argument(prompt)),
    }
    return {variant for variant in variants if variant}


def _conversation_matches_prompt(conversation: dict[str, object], prompt: str) -> bool:
    prompt_variants = _prompt_variants(prompt)
    prompt_run_marker = _prompt_run_marker(prompt)
    if not prompt_variants:
        return False
    for message in _conversation_messages(conversation):
        if str(message.get("type", "")).strip() != "user":
            continue
        message_text = _normalized_prompt_text(_message_text(message))
        if prompt_run_marker and prompt_run_marker in message_text:
            return True
        if message_text in prompt_variants:
            return True
    return False


def _latest_fresh_chat_file_since(
    project_root: Path, start_epoch: float, prompt: str
) -> Path | None:
    chats_dir = _project_chats_dir(project_root)
    if not chats_dir or not chats_dir.is_dir():
        return None

    matched: list[tuple[tuple[float, str], Path]] = []
    start_cutoff = start_epoch - 5.0
    for path in chats_dir.glob("session-*.json"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < start_cutoff:
            continue
        conversation = _load_conversation(path)
        if not conversation:
            continue
        if _is_subagent_conversation(conversation):
            continue
        parsed_start = _parse_iso_timestamp(conversation.get("startTime"))
        if parsed_start is not None and parsed_start.timestamp() < start_cutoff:
            continue
        if not _conversation_matches_prompt(conversation, prompt):
            continue
        matched.append((_conversation_sort_key(path, conversation), path))
    if not matched:
        return None
    matched.sort(key=lambda item: item[0], reverse=True)
    return matched[0][1]


def _launch_interactive_process(
    command: list[str], project_root: Path
) -> tuple[subprocess.Popen[bytes], int]:
    master_fd, slave_fd = pty.openpty()
    env = _gemini_environment()
    try:
        process = subprocess.Popen(
            command,
            cwd=str(project_root),
            env=env,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        os.close(master_fd)
        os.close(slave_fd)
        if exc.errno == errno.E2BIG:
            raise _raise_e2big(exc) from exc
        raise
    os.close(slave_fd)
    os.set_blocking(master_fd, False)
    return process, master_fd


def _drain_pty_output(master_fd: int, current_output: str) -> str:
    updated = current_output
    while True:
        try:
            ready, _, _ = select.select([master_fd], [], [], 0)
        except OSError:
            return updated
        if not ready:
            return updated
        try:
            chunk = os.read(master_fd, 4096)
        except BlockingIOError:
            return updated
        except OSError:
            return updated
        if not chunk:
            return updated
        updated = _trim_output_tail(updated, chunk.decode("utf-8", errors="replace"))


def _message_looks_like_error(message: dict[str, object]) -> bool:
    text = _message_text(message).strip().lower()
    if not text:
        return False
    return any(marker in text for marker in INTERACTIVE_ERROR_MARKERS)


def _interactive_outcome(
    new_messages: list[dict[str, object]],
) -> tuple[str, str] | None:
    if not new_messages:
        return None

    trailing_messages = _latest_turn_messages(new_messages)
    if not trailing_messages:
        return None
    for message in trailing_messages:
        if _message_has_active_tool_calls(message):
            return None

    for message in reversed(trailing_messages):
        message_type = str(message.get("type", "")).strip()
        if message_type in {"error", "warning", "info"} and _message_looks_like_error(
            message
        ):
            text = _message_text(message).strip()
            return ("error", text or message_type)
        if message_type == "gemini":
            text = _message_text(message).strip()
            if text:
                return ("success", text)
            if _message_has_active_tool_calls(message):
                return None
    return None


def _interactive_state_summary(new_messages: list[dict[str, object]]) -> str:
    if not new_messages:
        return "No new session messages were recorded yet."

    trailing_messages = _latest_turn_messages(new_messages)
    if not trailing_messages and not any(
        str(message.get("type", "")).strip() == "user" for message in new_messages
    ):
        return "The latest merged session state does not contain a new user turn yet."
    if not trailing_messages:
        return "The latest turn only recorded the user message; Gemini has not recorded a reply yet."

    if any(_message_has_active_tool_calls(message) for message in trailing_messages):
        return "The latest turn still has active Gemini tool calls."

    for message in reversed(trailing_messages):
        message_type = str(message.get("type", "")).strip()
        if message_type in {"error", "warning", "info"} and _message_looks_like_error(
            message
        ):
            text = _message_text(message).strip()
            return f"The latest turn recorded an error marker: {text or message_type}."
        if message_type == "gemini":
            text = _message_text(message).strip()
            if text:
                return "The latest turn already has a non-empty Gemini reply."

    thought_entries = _latest_turn_thought_entries(new_messages)
    if thought_entries:
        return (
            f"The latest turn recorded {len(thought_entries)} Gemini thought(s) "
            "but no final reply yet."
        )

    return "The latest turn only recorded empty Gemini intermediate messages so far."


def _interactive_diagnostics(
    captured_output: str, new_messages: list[dict[str, object]]
) -> str:
    sections = [_interactive_state_summary(new_messages)]
    thought_entries = _latest_turn_thought_entries(new_messages)
    if thought_entries:
        recent_thoughts = "\n".join(
            f"- {thought_text[:MAX_THOUGHT_TEXT_CHARS] or '(empty thought)'}"
            for _, thought_text in thought_entries[-3:]
        )
        sections.append(f"Latest thoughts:\n{recent_thoughts}")
    output_tail = captured_output.strip()
    if output_tail:
        sections.append(f"PTY tail:\n{output_tail[:MAX_OUTPUT_CHARS]}")
    return "\n".join(section for section in sections if section)


def _close_interactive_process(process: subprocess.Popen[bytes], master_fd: int) -> None:
    deadline = time.monotonic() + INTERACTIVE_SHUTDOWN_GRACE_SECONDS
    for _ in range(2):
        if process.poll() is not None:
            break
        try:
            os.write(master_fd, b"\x04")
        except OSError:
            break
        time.sleep(0.2)
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
    try:
        os.close(master_fd)
    except OSError:
        pass


def _run_interactive_attempt(
    command: list[str],
    timeout_seconds: int,
    project_root: Path,
    *,
    resumed_session_id: str,
) -> tuple[subprocess.CompletedProcess[str], str]:
    baseline_message_keys: set[str] = set()
    if resumed_session_id:
        baseline_message_keys = {
            _message_identity(message)
            for message in _merged_session_messages(project_root, resumed_session_id)
        }
    start_monotonic = time.monotonic()
    start_epoch = time.time()
    last_progress = start_monotonic
    resolved_session_id = resumed_session_id
    outcome: tuple[str, str] | None = None
    last_progress_signature: tuple[object, ...] = ()
    seen_thought_keys: set[str] = set()
    last_wait_percent = -1
    new_messages: list[dict[str, object]] = []
    current_command = list(command)
    last_wait_percent = _emit_wait_progress(
        start_monotonic, start_monotonic, timeout_seconds, last_wait_percent
    )

    while True:
        process, master_fd = _launch_interactive_process(current_command, project_root)
        captured_output = ""
        process_closed = False

        try:
            while True:
                captured_output = _drain_pty_output(master_fd, captured_output)

                if not resolved_session_id:
                    candidate = _latest_fresh_chat_file_since(
                        project_root, start_epoch, prompt=current_command[-1]
                    )
                    if candidate is not None:
                        conversation = _load_conversation(candidate)
                        if conversation:
                            resolved_session_id = str(
                                conversation.get("sessionId", "")
                            ).strip()
                            if resolved_session_id:
                                last_progress = time.monotonic()

                merged_messages: list[dict[str, object]] = []
                if resolved_session_id:
                    merged_messages = _merged_session_messages(
                        project_root, resolved_session_id
                    )
                    current_progress_signature = tuple(
                        _message_progress_signature(message)
                        for message in merged_messages
                    )
                    if current_progress_signature != last_progress_signature:
                        last_progress_signature = current_progress_signature
                        last_progress = time.monotonic()
                    new_messages = [
                        message
                        for message in merged_messages
                        if _message_identity(message) not in baseline_message_keys
                    ]
                    seen_thought_keys = _emit_new_thought_progress(
                        new_messages, seen_thought_keys
                    )
                    outcome = _interactive_outcome(new_messages)
                else:
                    outcome = None

                now = time.monotonic()
                last_wait_percent = _emit_wait_progress(
                    now, start_monotonic, timeout_seconds, last_wait_percent
                )
                if outcome and now - last_progress >= INTERACTIVE_STABILITY_SECONDS:
                    status, text = outcome
                    _close_interactive_process(process, master_fd)
                    process_closed = True
                    if status == "success":
                        return (
                            subprocess.CompletedProcess(
                                current_command, 0, text, ""
                            ),
                            resolved_session_id,
                        )
                    return (
                        subprocess.CompletedProcess(
                            current_command, 1, "", text[:MAX_OUTPUT_CHARS]
                        ),
                        resolved_session_id,
                    )

                if process.poll() is not None:
                    captured_output = _drain_pty_output(master_fd, captured_output)
                    if resolved_session_id:
                        merged_messages = _merged_session_messages(
                            project_root, resolved_session_id
                        )
                        current_progress_signature = tuple(
                            _message_progress_signature(message)
                            for message in merged_messages
                        )
                        if current_progress_signature != last_progress_signature:
                            last_progress_signature = current_progress_signature
                            last_progress = time.monotonic()
                        new_messages = [
                            message
                            for message in merged_messages
                            if _message_identity(message) not in baseline_message_keys
                        ]
                        seen_thought_keys = _emit_new_thought_progress(
                            new_messages, seen_thought_keys
                        )
                        outcome = _interactive_outcome(new_messages)

                    should_resume_incomplete = (
                        bool(resolved_session_id)
                        and outcome is None
                        and _latest_turn_has_thoughts(new_messages)
                        and now - start_monotonic < timeout_seconds
                    )

                    _close_interactive_process(process, master_fd)
                    process_closed = True
                    if outcome and outcome[0] == "success":
                        return (
                            subprocess.CompletedProcess(
                                current_command, 0, outcome[1], ""
                            ),
                            resolved_session_id,
                        )
                    if should_resume_incomplete:
                        print(EXIT_RESUME_PROGRESS_NOTE, file=sys.stderr, flush=True)
                        current_command = _interactive_command(
                            current_command[0],
                            current_command[-1],
                            resolved_session_id,
                        )
                        time.sleep(INTERACTIVE_POLL_SECONDS)
                        break
                    stderr = _interactive_diagnostics(
                        captured_output, new_messages
                    )[:MAX_OUTPUT_CHARS]
                    if outcome and outcome[0] == "error":
                        stderr = outcome[1][:MAX_OUTPUT_CHARS]
                    return (
                        subprocess.CompletedProcess(
                            current_command,
                            process.returncode or 1,
                            "",
                            stderr,
                        ),
                        resolved_session_id,
                    )

                if now - start_monotonic >= timeout_seconds:
                    _close_interactive_process(process, master_fd)
                    process_closed = True
                    raise subprocess.TimeoutExpired(
                        current_command,
                        timeout_seconds,
                        output=_interactive_diagnostics(captured_output, new_messages),
                    )

                time.sleep(INTERACTIVE_POLL_SECONDS)
        except Exception:
            if not process_closed:
                try:
                    _close_interactive_process(process, master_fd)
                except Exception:
                    pass
            raise


def _run_interactive(
    prompt: str,
    timeout_seconds: int,
    project_root: Path,
    *,
    lane: str,
    scope_root: Path,
    project_roots: tuple[Path, ...] | None = None,
    output_normalizer: Callable[[str], str] | None = None,
    output_validator: Callable[[str], str] | None = None,
) -> subprocess.CompletedProcess[str]:
    gemini = shutil.which("gemini")
    if not gemini:
        raise FileNotFoundError("gemini executable not found in PATH")

    session_id = _saved_reusable_lane_session_id(
        project_root,
        lane,
        scope_root,
        project_roots,
        output_normalizer,
        output_validator,
    )
    commands = [_interactive_command(gemini, prompt, session_id)]
    if session_id:
        commands.append(_interactive_command(gemini, prompt, ""))

    last_result: subprocess.CompletedProcess[str] | None = None
    for command in commands:
        resumed_session_id = session_id if "--resume" in command else ""
        result, resolved_session_id = _run_interactive_attempt(
            command,
            timeout_seconds,
            project_root,
            resumed_session_id=resumed_session_id,
        )
        last_result = result
        if resolved_session_id:
            _remember_lane_session(
                project_root,
                lane,
                resolved_session_id,
                scope_root,
                project_roots,
            )
        combined_output = _combined_result_output(result)
        if result.returncode == 0:
            normalized_stdout = (
                output_normalizer(result.stdout)
                if output_normalizer
                else result.stdout.strip()
            )
            validation_error = (
                output_validator(normalized_stdout) if output_validator else ""
            )
            if validation_error:
                if "--resume" in command:
                    continue
                return subprocess.CompletedProcess(command, 1, "", validation_error)
            if normalized_stdout:
                return subprocess.CompletedProcess(command, 0, normalized_stdout, "")
        if _should_retry_resume(command, combined_output):
            continue
        return result

    assert last_result is not None
    return last_result


def run_gemini(
    prompt: str,
    timeout_seconds: int,
    project_root: Path,
    *,
    lane: str,
    scope_root: Path,
    project_roots: tuple[Path, ...] | None = None,
    runner_mode: str | None = None,
    output_normalizer: Callable[[str], str] | None = None,
    output_validator: Callable[[str], str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke Gemini CLI via the configured runner mode."""
    mode = configured_run_mode(runner_mode)
    if mode == "headless":
        return _run_headless(
            prompt,
            timeout_seconds,
            project_root,
            lane=lane,
            scope_root=scope_root,
            project_roots=project_roots,
            output_normalizer=output_normalizer,
            output_validator=output_validator,
        )
    return _run_interactive(
        prompt,
        timeout_seconds,
        project_root,
        lane=lane,
        scope_root=scope_root,
        project_roots=project_roots,
        output_normalizer=output_normalizer,
        output_validator=output_validator,
    )


# ---------------------------------------------------------------------------
# Shared argument parser
# ---------------------------------------------------------------------------


def make_arg_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--brief-file", required=True, help="Markdown or text file with the brief."
    )
    parser.add_argument(
        "--project-root",
        action="append",
        default=[],
        help=(
            "Optional project root directory. Repeat this flag to intentionally scope "
            "one advisory pass across multiple projects under the current workspace."
        ),
    )
    parser.add_argument(
        "--context-file",
        action="append",
        default=[],
        help="Optional local file or directory Gemini should treat as a high-priority starting point.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"End-to-end advisory timeout in seconds. Default: {DEFAULT_TIMEOUT_SECONDS}.",
    )
    parser.add_argument(
        "--runner-mode",
        choices=VALID_GEMINI_RUN_MODES,
        default=None,
        help=(
            "Gemini runner mode. Defaults to the interactive runner unless "
            f"{GEMINI_RUN_MODE_ENV_VAR} overrides it."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Generic advisory entry point
# ---------------------------------------------------------------------------


def run_advisory(
    *,
    description: str,
    role_line: str,
    label: str,
    lane: str,
    output_contract: str | None = None,
    output_contract_builder: Callable[[argparse.Namespace], str] | None = None,
    configure_parser: Callable[[argparse.ArgumentParser], None] | None = None,
    argv: list[str] | None = None,
) -> int:
    """Run a Gemini advisory pass end-to-end and return an exit code."""
    if (output_contract is None) == (output_contract_builder is None):
        raise ValueError(
            "Provide exactly one of output_contract or output_contract_builder."
        )

    parser = make_arg_parser(description)
    if configure_parser is not None:
        configure_parser(parser)
    args = parser.parse_args(argv)

    brief_path = Path(args.brief_file).expanduser().resolve()
    if not brief_path.is_file():
        print(f"Brief file not found: {_tilde_path(brief_path)}", file=sys.stderr)
        return 2

    default_project_root = detect_project_root()
    workspace_boundary = detect_workspace_root()
    project_roots = _normalize_multi_project_roots(
        args.project_root, args.context_file, default_project_root, workspace_boundary
    )
    project_root = _multi_project_workspace_root(
        project_roots, default_project_root, workspace_boundary
    )
    focus_root = _focus_scope_root(args.context_file, project_root, project_roots)
    context_entries = describe_paths(args.context_file, project_root, project_roots)
    run_marker = f"{RUN_MARKER_PREFIX}{uuid4().hex[:10]}"

    resolved_output_contract = (
        output_contract_builder(args) if output_contract_builder else output_contract
    )
    assert resolved_output_contract is not None
    output_normalizer = build_output_normalizer(resolved_output_contract)
    output_validator = build_output_validator(resolved_output_contract)

    brief_text = brief_path.read_text(encoding="utf-8")
    prompt = build_prompt(
        project_root,
        brief_text,
        context_entries,
        lane=lane,
        focus_root=focus_root,
        project_roots=project_roots,
        run_marker=run_marker,
        role_line=role_line,
        output_contract=resolved_output_contract,
    )

    try:
        result = run_gemini(
            prompt,
            args.timeout_seconds,
            project_root,
            lane=lane,
            scope_root=focus_root,
            project_roots=project_roots,
            runner_mode=args.runner_mode,
            output_normalizer=output_normalizer,
            output_validator=output_validator,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except subprocess.TimeoutExpired as exc:
        print(
            (
                f"Gemini {label} timed out after "
                f"{args.timeout_seconds} seconds total wait."
            ),
            file=sys.stderr,
        )
        timeout_output = str(getattr(exc, "output", "")).strip()
        if timeout_output:
            print(timeout_output[:MAX_OUTPUT_CHARS], file=sys.stderr)
        return 4
    except OSError as exc:
        if exc.errno == errno.E2BIG:
            print(str(exc), file=sys.stderr)
            return 5
        raise

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if result.returncode != 0 or not stdout:
        print(
            f"Gemini {label} failed with exit code {result.returncode}.",
            file=sys.stderr,
        )
        if stderr:
            print(stderr[:MAX_OUTPUT_CHARS], file=sys.stderr)
        if stdout:
            print(stdout[:MAX_OUTPUT_CHARS], file=sys.stderr)
        return 5

    print(stdout[:MAX_OUTPUT_CHARS])
    return 0
