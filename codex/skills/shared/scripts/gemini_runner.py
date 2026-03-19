#!/usr/bin/env python3
"""Shared Gemini CLI advisory runner used by Codex Gemini skills."""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import select
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


DEFAULT_TIMEOUT_SECONDS = 1200
MAX_OUTPUT_CHARS = 12000
MAX_STAGED_BRIEFS = 20
STAGED_BRIEF_TTL_SECONDS = 7 * 24 * 60 * 60
DEFAULT_GEMINI_MODEL = "pro"
GEMINI_MODEL_ENV_VAR = "CODEX_GEMINI_MODEL"
DEFAULT_GEMINI_FLAGS = ("--approval-mode", "yolo")
GEMINI_SANDBOX_ENV_VAR = "GEMINI_SANDBOX"
GEMINI_SANDBOX_DISABLED_VALUE = "false"
RESUME_FALLBACK_MARKERS = (
    "unknown option",
    "unexpected argument",
    "unknown argument",
    "unknown flag",
    "invalid session",
    "session not found",
    "could not find session",
)
PTY_POLL_INTERVAL_SECONDS = 0.2
EXIT_GRACE_SECONDS = 5
RESPONSE_STABILITY_SECONDS = 3.0
RUN_MARKER_PREFIX = "cadv"
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
ERROR_TEXT_MARKERS = (
    "429",
    "api error",
    "quota",
    "rate limit",
    "rate-limit",
    "rate_limited",
    "resource_exhausted",
    "too many requests",
)


@dataclass
class RunObservation:
    submitted: bool
    response: str | None = None
    error: str | None = None
    last_updated: float = 0.0


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


def _append_context_entry(described: list[str], seen: set[Path], path: Path, kind: str, project_root: Path) -> None:
    if path in seen:
        return
    seen.add(path)
    described.append(f"- {_display_workspace_path(path, project_root)} [{kind}]")


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


def _chat_activity_timestamp(chat_path: Path, payload: dict[str, object]) -> float:
    parsed_last_updated = _parse_gemini_timestamp(payload.get("lastUpdated"))
    if parsed_last_updated is not None:
        return parsed_last_updated
    parsed_start_time = _parse_gemini_timestamp(payload.get("startTime"))
    if parsed_start_time is not None:
        return parsed_start_time
    try:
        return chat_path.stat().st_mtime
    except OSError:
        return 0.0


def _all_chat_files() -> list[Path]:
    chats_root = Path.home() / ".gemini" / "tmp"
    if not chats_root.is_dir():
        return []
    return sorted(chats_root.glob("*/chats/session-*.json"))


def _read_chat_payload(chat_path: Path) -> dict[str, object] | None:
    try:
        return json.loads(chat_path.read_text(encoding="utf-8"))
    except Exception:
        return None


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
        payload = _read_chat_payload(chat_path)
        if not payload:
            continue
        session_id = str(payload.get("sessionId", "")).strip()
        if not session_id:
            continue
        ordering_key = _session_sort_key(chat_path, payload)
        if best_key is None or ordering_key >= best_key:
            best_key = ordering_key
            latest_session_id = session_id
    return latest_session_id


def _find_chat_by_session_id(session_id: str) -> Path | None:
    if not session_id:
        return None
    for chat_path in _all_chat_files():
        payload = _read_chat_payload(chat_path)
        if payload and str(payload.get("sessionId", "")).strip() == session_id:
            return chat_path
    return None


def _project_chat_files(project_root: Path) -> list[Path]:
    project_alias = _project_alias(project_root)
    if project_alias:
        chats_dir = Path.home() / ".gemini" / "tmp" / project_alias / "chats"
        if chats_dir.is_dir():
            return sorted(chats_dir.glob("session-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return sorted(_all_chat_files(), key=lambda path: path.stat().st_mtime, reverse=True)


def _message_text(message: object) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        parts: list[str] = []
        for item in message:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    if isinstance(message, dict):
        text = message.get("text")
        return text if isinstance(text, str) else ""
    return ""


def _message_error_text(message: object) -> str | None:
    if not isinstance(message, dict):
        return None

    message_type = str(message.get("type", "")).strip().lower()
    content_text = _message_text(message.get("content")).strip()
    serialized = json.dumps(message, ensure_ascii=False, sort_keys=True)
    lower_serialized = serialized.lower()

    if message_type == "error":
        return content_text or serialized

    tool_calls = message.get("toolCalls")
    if isinstance(tool_calls, list):
        for tool_call in tool_calls:
            if isinstance(tool_call, dict) and str(tool_call.get("status", "")).strip().lower() == "error":
                return content_text or serialized

    if any(marker in lower_serialized for marker in ERROR_TEXT_MARKERS):
        return content_text or serialized
    return None


def _find_run_observation_in_payload(payload: dict[str, object], run_marker: str, chat_path: Path) -> RunObservation:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return RunObservation(False)

    marker_index: int | None = None
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        if message.get("type") != "user":
            continue
        if run_marker in _message_text(message.get("content")):
            marker_index = index

    if marker_index is None:
        return RunObservation(False)

    latest_response: str | None = None
    latest_error: str | None = None
    for message in messages[marker_index + 1 :]:
        if not isinstance(message, dict):
            continue
        if message.get("type") != "gemini":
            message_error = _message_error_text(message)
            if message_error:
                latest_error = message_error
            continue

        response = _message_text(message.get("content")).strip()
        if response:
            latest_response = response

        message_error = _message_error_text(message)
        if message_error:
            latest_error = message_error

    return RunObservation(
        True,
        response=latest_response,
        error=None if latest_response else latest_error,
        last_updated=_chat_activity_timestamp(chat_path, payload),
    )


def _find_run_observation(run_marker: str, session_id: str, project_root: Path) -> RunObservation:
    chat_paths: list[Path]
    if session_id:
        chat_path = _find_chat_by_session_id(session_id)
        chat_paths = [chat_path] if chat_path else _project_chat_files(project_root)
    else:
        chat_paths = _project_chat_files(project_root)

    for chat_path in chat_paths:
        if chat_path is None:
            continue
        payload = _read_chat_payload(chat_path)
        if not payload:
            continue
        observation = _find_run_observation_in_payload(payload, run_marker, chat_path)
        if observation.submitted:
            return observation
    return RunObservation(False)


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


def stage_instruction_text(instruction_text: str, bridge_root: Path) -> Path:
    bridge_root.mkdir(parents=True, exist_ok=True)
    staged_path = bridge_root / "i.md"
    staged_path.write_text(instruction_text, encoding="utf-8")
    return staged_path


def describe_paths(raw_paths: list[str], project_root: Path, bridge_root: Path) -> list[str]:
    resolved_project_root = project_root.resolve()
    resolved_bridge_root = bridge_root.resolve()
    described: list[str] = []
    seen: set[Path] = set()
    for raw_path in raw_paths:
        path = _workspace_path(raw_path, resolved_project_root)
        if path is None:
            continue
        resolved_path = path.resolve()
        if _is_within(resolved_path, resolved_bridge_root) or not _is_within(resolved_path, resolved_project_root):
            continue
        if not resolved_path.exists():
            _append_context_entry(described, seen, path, "missing", resolved_project_root)
            continue
        kind = "directory" if resolved_path.is_dir() else "file"
        _append_context_entry(described, seen, path, kind, resolved_project_root)
    return described


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _make_run_marker() -> str:
    return f"{RUN_MARKER_PREFIX}-{uuid.uuid4().hex[:8]}"


def build_prompt(
    project_root: Path,
    brief_path: Path,
    context_entries: list[str],
    *,
    role_line: str,
    output_contract: str,
    run_marker: str,
) -> str:
    """Assemble the full prompt from a role line, output contract, and paths."""
    sections = [
        role_line,
        "You are running inside Gemini CLI on the same machine as the codebase.",
        "Use the workspace root below as your filesystem boundary. You may inspect any local file or directory inside that workspace root if it helps you answer well.",
        output_contract,
        "## Current Workspace Root",
        f"- {_tilde_path(project_root)}",
        "## Required Local Brief",
        f"- {_display_workspace_path(brief_path, project_root)}",
    ]
    if context_entries:
        sections.append("## Priority Paths To Start From")
        sections.extend(context_entries)
        sections.append(
            "Treat those paths as starting points, not as an exhaustive file list. Decide for yourself which other workspace-local files or directories you should inspect."
        )
    else:
        sections.append("No priority paths were supplied. Explore the workspace root as needed, but stay inside it.")
    sections.extend(
        [
            "## Advisory Run Marker",
            f"- Internal correlation marker for the caller only. Do not repeat it in your answer: {run_marker}",
        ]
    )
    return "\n\n".join(sections).strip() + "\n"


def build_submission_message(project_root: Path, instruction_path: Path, run_marker: str) -> str:
    try:
        instruction_ref = instruction_path.relative_to(project_root)
    except ValueError:
        instruction_ref = instruction_path
    return (
        f"@{instruction_ref.as_posix()}\n\n"
        "Follow the attached instruction file exactly. "
        f"Ref {run_marker}. "
        "Do not repeat the ref."
    )


# ---------------------------------------------------------------------------
# Gemini CLI interactive invocation
# ---------------------------------------------------------------------------

def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def _trim_output(text: str) -> str:
    return text[-MAX_OUTPUT_CHARS:]


def _combined_result_output(result: subprocess.CompletedProcess[str]) -> str:
    combined = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    return combined[:MAX_OUTPUT_CHARS]


def _drain_process_output(process: subprocess.Popen[bytes], timeout_seconds: float) -> str:
    if process.stdout is None:
        return ""
    chunks: list[str] = []
    deadline = time.monotonic() + timeout_seconds
    stdout_fd = process.stdout.fileno()
    while True:
        remaining = deadline - time.monotonic()
        if remaining < 0:
            remaining = 0
        ready, _, _ = select.select([stdout_fd], [], [], remaining)
        if not ready:
            break
        try:
            data = os.read(stdout_fd, 4096)
        except OSError as exc:
            if exc.errno == errno.EIO:
                break
            raise
        if not data:
            break
        chunks.append(data.decode("utf-8", errors="replace"))
        deadline = time.monotonic()
    return "".join(chunks)


def _gemini_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("COLORTERM", "truecolor")
    env[GEMINI_SANDBOX_ENV_VAR] = GEMINI_SANDBOX_DISABLED_VALUE
    return env


def _write_all(process: subprocess.Popen[bytes], text: str) -> None:
    if process.stdin is None:
        return
    data = text.encode("utf-8")
    process.stdin.write(data)
    process.stdin.flush()


def _interactive_command(gemini: str, prompt: str, session_id: str) -> list[str]:
    command = [gemini, *DEFAULT_GEMINI_FLAGS, "--model", configured_gemini_model()]
    if session_id:
        command.extend(["--resume", session_id])
    command.extend(["-i", prompt])
    return command


def _start_gemini_process(command: list[str], project_root: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    script = shutil.which("script")
    if not script:
        raise FileNotFoundError("script executable not found in PATH")
    wrapped_command = [script, "-q", "/dev/null", *command]
    return subprocess.Popen(
        wrapped_command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(project_root),
        env=env,
        bufsize=0,
    )


def _graceful_shutdown(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        _write_all(process, "\x04\x04")
    except OSError:
        pass
    deadline = time.monotonic() + EXIT_GRACE_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return
        _drain_process_output(process, PTY_POLL_INTERVAL_SECONDS)
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _should_retry_resume(command: list[str], combined_output: str) -> bool:
    return "--resume" in command and any(marker in combined_output for marker in RESUME_FALLBACK_MARKERS)


def configured_gemini_model() -> str:
    model = os.environ.get(GEMINI_MODEL_ENV_VAR, DEFAULT_GEMINI_MODEL).strip()
    return model or DEFAULT_GEMINI_MODEL


def _run_interactive_attempt(
    *,
    command: list[str],
    timeout_seconds: int,
    project_root: Path,
    run_marker: str,
    session_id: str,
) -> subprocess.CompletedProcess[str]:
    env = _gemini_environment()
    process = _start_gemini_process(command, project_root, env)
    deadline = time.monotonic() + timeout_seconds
    clean_output = ""
    last_observed_update = 0.0
    last_change_time = time.monotonic()
    try:
        while time.monotonic() < deadline:
            clean_output = _trim_output(clean_output + _strip_ansi(_drain_process_output(process, PTY_POLL_INTERVAL_SECONDS)))
            observation = _find_run_observation(run_marker, session_id, project_root)

            if observation.submitted and observation.last_updated > last_observed_update:
                last_observed_update = observation.last_updated
                last_change_time = time.monotonic()

            if observation.response and time.monotonic() - last_change_time >= RESPONSE_STABILITY_SECONDS:
                _graceful_shutdown(process)
                return subprocess.CompletedProcess(command, 0, observation.response, "")

            if observation.error and time.monotonic() - last_change_time >= RESPONSE_STABILITY_SECONDS:
                _graceful_shutdown(process)
                return subprocess.CompletedProcess(command, 1, "", observation.error)

            if process.poll() is not None:
                clean_output = _trim_output(clean_output + _strip_ansi(_drain_process_output(process, 0)))
                observation = _find_run_observation(run_marker, session_id, project_root)
                if observation.response:
                    return subprocess.CompletedProcess(command, 0, observation.response, "")
                if observation.error:
                    return subprocess.CompletedProcess(command, 1, "", observation.error)
                return subprocess.CompletedProcess(command, process.returncode or 1, "", clean_output.strip())

        raise subprocess.TimeoutExpired(command, timeout_seconds)
    finally:
        try:
            _graceful_shutdown(process)
        finally:
            try:
                if process.stdin is not None:
                    process.stdin.close()
                if process.stdout is not None:
                    process.stdout.close()
            except OSError:
                pass


def run_gemini(prompt: str, timeout_seconds: int, project_root: Path, *, run_marker: str) -> subprocess.CompletedProcess[str]:
    """Invoke ``gemini`` CLI with ``-i`` and recover the final answer from session JSON."""
    gemini = shutil.which("gemini")
    if not gemini:
        raise FileNotFoundError("gemini executable not found in PATH")

    session_id = latest_project_session_id(project_root)
    commands = [_interactive_command(gemini, prompt, session_id)]
    if session_id:
        commands.append(_interactive_command(gemini, prompt, ""))

    last_result: subprocess.CompletedProcess[str] | None = None
    for command in commands:
        active_session_id = session_id if "--resume" in command else ""
        result = _run_interactive_attempt(
            command=command,
            timeout_seconds=timeout_seconds,
            project_root=project_root,
            run_marker=run_marker,
            session_id=active_session_id,
        )
        last_result = result
        if result.returncode == 0 and result.stdout.strip():
            return result
        if "--resume" in command and _should_retry_resume(command, _combined_result_output(result).lower()):
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
        help="Optional local file or directory Gemini should treat as a high-priority starting point.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"End-to-end advisory timeout in seconds. Default: {DEFAULT_TIMEOUT_SECONDS}.",
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
    output_contract: str | None = None,
    output_contract_builder: Callable[[argparse.Namespace], str] | None = None,
    configure_parser: Callable[[argparse.ArgumentParser], None] | None = None,
    argv: list[str] | None = None,
) -> int:
    """Run a Gemini advisory pass end-to-end and return an exit code."""
    if (output_contract is None) == (output_contract_builder is None):
        raise ValueError("Provide exactly one of output_contract or output_contract_builder.")

    parser = make_arg_parser(description)
    if configure_parser is not None:
        configure_parser(parser)
    args = parser.parse_args(argv)

    brief_path = Path(args.brief_file).expanduser().resolve()
    if not brief_path.is_file():
        print(f"Brief file not found: {_tilde_path(brief_path)}", file=sys.stderr)
        return 2

    project_root = detect_project_root()
    bridge_root = bridge_root_for_project(project_root)
    staged_brief = stage_brief_file(brief_path, bridge_root)
    context_entries = describe_paths(args.context_file, project_root, bridge_root)
    run_marker = _make_run_marker()

    resolved_output_contract = output_contract_builder(args) if output_contract_builder else output_contract
    assert resolved_output_contract is not None

    prompt = build_prompt(
        project_root,
        staged_brief,
        context_entries,
        role_line=role_line,
        output_contract=resolved_output_contract,
        run_marker=run_marker,
    )
    submission_message = build_submission_message(
        project_root,
        stage_instruction_text(prompt, bridge_root),
        run_marker,
    )

    try:
        result = run_gemini(submission_message, args.timeout_seconds, project_root, run_marker=run_marker)
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
