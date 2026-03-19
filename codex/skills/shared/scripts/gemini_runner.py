#!/usr/bin/env python3
"""Shared Gemini CLI advisory runner used by Codex Gemini skills."""
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


DEFAULT_TIMEOUT_SECONDS = 1200
MAX_OUTPUT_CHARS = 12000
MAX_PTY_OUTPUT_CHARS = 16000
DEFAULT_GEMINI_MODEL = "pro"
GEMINI_MODEL_ENV_VAR = "CODEX_GEMINI_MODEL"
DEFAULT_GEMINI_FLAGS = ("--approval-mode", "yolo")
GEMINI_SANDBOX_ENV_VAR = "GEMINI_SANDBOX"
GEMINI_SANDBOX_DISABLED_VALUE = "false"
GEMINI_OUTPUT_FORMAT = "json"
GEMINI_RUN_MODE_ENV_VAR = "CODEX_GEMINI_RUN_MODE"
DEFAULT_GEMINI_RUN_MODE = "interactive"
VALID_GEMINI_RUN_MODES = ("interactive", "headless")
LANE_SESSION_STATE_FILE = "codex-lane-sessions.json"
GEMINI_PROJECTS_FILE = "projects.json"
GEMINI_TMP_DIRNAME = "tmp"
INLINE_PROMPT_TOO_LARGE_MESSAGE = (
    "Gemini inline prompt is too large for this platform's command-line limit. "
    "Reduce the brief size or switch to a non-argv prompt delivery path."
)
INTERACTIVE_STABILITY_SECONDS = 2.0
INTERACTIVE_POLL_SECONDS = 1.0
INTERACTIVE_SHUTDOWN_GRACE_SECONDS = 3.0
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


def describe_paths(raw_paths: list[str], project_root: Path) -> list[str]:
    resolved_project_root = project_root.resolve()
    described: list[str] = []
    seen: set[Path] = set()
    for raw_path in raw_paths:
        path = _workspace_path(raw_path, resolved_project_root)
        if path is None:
            continue
        resolved_path = path.resolve()
        if not _is_within(resolved_path, resolved_project_root):
            continue
        if not resolved_path.exists():
            _append_context_entry(
                described, seen, path, "missing", resolved_project_root
            )
            continue
        kind = "directory" if resolved_path.is_dir() else "file"
        _append_context_entry(described, seen, path, kind, resolved_project_root)
    return described


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


def _lane_state_key(project_root: Path, lane: str) -> str:
    return f"{project_root.resolve()}::{lane}"


def _remember_lane_session(project_root: Path, lane: str, session_id: str) -> None:
    if not lane or not session_id:
        return
    payload = _load_lane_state()
    payload[_lane_state_key(project_root, lane)] = {
        "lane": lane,
        "projectRoot": str(project_root.resolve()),
        "sessionId": session_id,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    _save_lane_state(payload)


def _saved_lane_session_id(project_root: Path, lane: str) -> str:
    if not lane:
        return ""
    payload = _load_lane_state()
    entry = payload.get(_lane_state_key(project_root, lane))
    if not isinstance(entry, dict):
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
    role_line: str,
    output_contract: str,
) -> str:
    """Assemble the full prompt from a role line, output contract, and paths."""
    sections = [
        role_line,
        "You are running inside Gemini CLI on the same machine as the codebase.",
        "Use the workspace root below as your filesystem boundary. You may inspect any local file or directory inside that workspace root if it helps you answer well.",
        output_contract,
        "## Current Workspace Root",
        f"- {_tilde_path(project_root)}",
        "## Inlined Brief",
        brief_text.strip() or "- The brief file was empty.",
    ]
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
    prompt: str, timeout_seconds: int, project_root: Path, *, lane: str
) -> subprocess.CompletedProcess[str]:
    gemini = shutil.which("gemini")
    if not gemini:
        raise FileNotFoundError("gemini executable not found in PATH")

    session_id = _saved_lane_session_id(project_root, lane)
    commands = [_noninteractive_command(gemini, prompt, session_id)]
    if session_id:
        commands.append(_noninteractive_command(gemini, prompt, ""))

    last_result: subprocess.CompletedProcess[str] | None = None
    for command in commands:
        result = _run_noninteractive_attempt(command, timeout_seconds, project_root)
        last_result = result

        resolved_session_id, response_text, error_text = _parse_cli_result(result)
        if resolved_session_id:
            _remember_lane_session(project_root, lane, resolved_session_id)

        if result.returncode == 0 and response_text:
            return subprocess.CompletedProcess(command, 0, response_text, "")

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


def _project_short_id(project_root: Path) -> str:
    return str(_load_project_registry().get(_normalize_project_path(project_root), "")).strip()


def _project_chats_dir(project_root: Path) -> Path | None:
    short_id = _project_short_id(project_root)
    if not short_id:
        return None
    return Path.home() / ".gemini" / GEMINI_TMP_DIRNAME / short_id / "chats"


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
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _latest_session_file_for_id(project_root: Path, session_id: str) -> Path | None:
    chats_dir = _project_chats_dir(project_root)
    if not chats_dir or not chats_dir.is_dir():
        return None

    matches: list[tuple[tuple[float, str], Path]] = []
    for path in chats_dir.glob("session-*.json"):
        conversation = _load_conversation(path)
        if not conversation:
            continue
        if str(conversation.get("sessionId", "")).strip() != session_id:
            continue
        matches.append((_conversation_sort_key(path, conversation), path))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def _latest_chat_file_since(project_root: Path, start_epoch: float) -> Path | None:
    chats_dir = _project_chats_dir(project_root)
    if not chats_dir or not chats_dir.is_dir():
        return None

    candidates = [
        path for path in chats_dir.glob("session-*.json") if path.stat().st_mtime >= start_epoch
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


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


def _session_is_complete(conversation: dict[str, object]) -> bool:
    messages = _conversation_messages(conversation)
    if not messages:
        return False
    last_message = messages[-1]
    return (
        str(last_message.get("type", "")).strip() == "gemini"
        and not _message_has_active_tool_calls(last_message)
    )


def _saved_reusable_lane_session_id(project_root: Path, lane: str) -> str:
    session_id = _saved_lane_session_id(project_root, lane)
    if not session_id:
        return ""
    session_file = _latest_session_file_for_id(project_root, session_id)
    if not session_file:
        return ""
    conversation = _load_conversation(session_file)
    if not conversation or not _session_is_complete(conversation):
        return ""
    return session_id


def _refreshed_resumed_target(
    project_root: Path,
    resumed_session_id: str,
    target_file: Path | None,
    baseline_file: Path | None,
    baseline_messages: int,
) -> tuple[Path | None, int]:
    if not resumed_session_id:
        return (target_file, baseline_messages)
    candidate = _latest_session_file_for_id(project_root, resumed_session_id)
    if candidate is None or candidate == target_file:
        return (target_file, baseline_messages)
    if candidate == baseline_file:
        return (candidate, baseline_messages)
    return (candidate, 0)


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

    last_user_index = -1
    for index, message in enumerate(new_messages):
        if str(message.get("type", "")).strip() == "user":
            last_user_index = index
    if last_user_index == -1:
        return None

    trailing_messages = new_messages[last_user_index + 1 :]
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
    baseline_file: Path | None = None
    baseline_messages = 0
    if resumed_session_id:
        baseline_file = _latest_session_file_for_id(project_root, resumed_session_id)
        if baseline_file:
            conversation = _load_conversation(baseline_file)
            baseline_messages = len(_conversation_messages(conversation or {}))

    process, master_fd = _launch_interactive_process(command, project_root)
    captured_output = ""
    start_monotonic = time.monotonic()
    start_epoch = time.time()
    target_file = baseline_file
    last_change = start_monotonic
    last_mtime: float | None = baseline_file.stat().st_mtime if baseline_file else None
    resolved_session_id = resumed_session_id
    outcome: tuple[str, str] | None = None

    try:
        while True:
            captured_output = _drain_pty_output(master_fd, captured_output)

            if resumed_session_id:
                candidate, candidate_baseline_messages = _refreshed_resumed_target(
                    project_root,
                    resumed_session_id,
                    target_file,
                    baseline_file,
                    baseline_messages,
                )
                if candidate is not None and candidate != target_file:
                    target_file = candidate
                    baseline_messages = candidate_baseline_messages
                    last_mtime = candidate.stat().st_mtime
                    last_change = time.monotonic()
            elif target_file is None:
                candidate = _latest_chat_file_since(project_root, start_epoch)
                if candidate is not None:
                    target_file = candidate
                    baseline_messages = 0
                    last_mtime = candidate.stat().st_mtime
                    last_change = time.monotonic()

            conversation: dict[str, object] | None = None
            if target_file and target_file.exists():
                current_mtime = target_file.stat().st_mtime
                if last_mtime is None or current_mtime != last_mtime:
                    last_mtime = current_mtime
                    last_change = time.monotonic()
                conversation = _load_conversation(target_file)
                if conversation:
                    resolved_session_id = str(
                        conversation.get("sessionId", resolved_session_id)
                    ).strip()
                    messages = _conversation_messages(conversation)
                    if len(messages) >= baseline_messages:
                        outcome = _interactive_outcome(messages[baseline_messages:])

            now = time.monotonic()
            if outcome and now - last_change >= INTERACTIVE_STABILITY_SECONDS:
                status, text = outcome
                _close_interactive_process(process, master_fd)
                if status == "success":
                    return (
                        subprocess.CompletedProcess(command, 0, text, ""),
                        resolved_session_id,
                    )
                return (
                    subprocess.CompletedProcess(command, 1, "", text[:MAX_OUTPUT_CHARS]),
                    resolved_session_id,
                )

            if process.poll() is not None:
                captured_output = _drain_pty_output(master_fd, captured_output)
                if conversation is None and target_file and target_file.exists():
                    conversation = _load_conversation(target_file)
                    if conversation:
                        resolved_session_id = str(
                            conversation.get("sessionId", resolved_session_id)
                        ).strip()
                        messages = _conversation_messages(conversation)
                        if len(messages) >= baseline_messages:
                            outcome = _interactive_outcome(messages[baseline_messages:])
                _close_interactive_process(process, master_fd)
                if outcome and outcome[0] == "success":
                    return (
                        subprocess.CompletedProcess(command, 0, outcome[1], ""),
                        resolved_session_id,
                    )
                stderr = captured_output.strip()[:MAX_OUTPUT_CHARS]
                if outcome and outcome[0] == "error":
                    stderr = outcome[1][:MAX_OUTPUT_CHARS]
                if not stderr:
                    stderr = "Gemini interactive run exited without a recorded final response."
                return (
                    subprocess.CompletedProcess(
                        command,
                        process.returncode or 1,
                        "",
                        stderr,
                    ),
                    resolved_session_id,
                )

            if now - start_monotonic >= timeout_seconds:
                _close_interactive_process(process, master_fd)
                raise subprocess.TimeoutExpired(command, timeout_seconds, output=captured_output)

            time.sleep(INTERACTIVE_POLL_SECONDS)
    except Exception:
        try:
            _close_interactive_process(process, master_fd)
        except Exception:
            pass
        raise


def _run_interactive(
    prompt: str, timeout_seconds: int, project_root: Path, *, lane: str
) -> subprocess.CompletedProcess[str]:
    gemini = shutil.which("gemini")
    if not gemini:
        raise FileNotFoundError("gemini executable not found in PATH")

    session_id = _saved_reusable_lane_session_id(project_root, lane)
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
            _remember_lane_session(project_root, lane, resolved_session_id)
        combined_output = _combined_result_output(result)
        if result.returncode == 0 and result.stdout.strip():
            return result
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
    runner_mode: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke Gemini CLI via the configured runner mode."""
    mode = configured_run_mode(runner_mode)
    if mode == "headless":
        return _run_headless(prompt, timeout_seconds, project_root, lane=lane)
    return _run_interactive(prompt, timeout_seconds, project_root, lane=lane)


# ---------------------------------------------------------------------------
# Shared argument parser
# ---------------------------------------------------------------------------


def make_arg_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--brief-file", required=True, help="Markdown or text file with the brief."
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

    project_root = detect_project_root()
    context_entries = describe_paths(args.context_file, project_root)

    resolved_output_contract = (
        output_contract_builder(args) if output_contract_builder else output_contract
    )
    assert resolved_output_contract is not None

    brief_text = brief_path.read_text(encoding="utf-8")
    prompt = build_prompt(
        project_root,
        brief_text,
        context_entries,
        role_line=role_line,
        output_contract=resolved_output_contract,
    )

    try:
        result = run_gemini(
            prompt,
            args.timeout_seconds,
            project_root,
            lane=lane,
            runner_mode=args.runner_mode,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except subprocess.TimeoutExpired:
        print(
            f"Gemini {label} timed out after {args.timeout_seconds} seconds.",
            file=sys.stderr,
        )
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
