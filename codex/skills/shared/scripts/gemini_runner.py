#!/usr/bin/env python3
"""Shared Gemini CLI advisory runner used by Codex Gemini skills."""
from __future__ import annotations

import argparse
import errno
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path


DEFAULT_TIMEOUT_SECONDS = 1200
MAX_OUTPUT_CHARS = 12000
DEFAULT_GEMINI_MODEL = "pro"
GEMINI_MODEL_ENV_VAR = "CODEX_GEMINI_MODEL"
DEFAULT_GEMINI_FLAGS = ("--approval-mode", "yolo")
GEMINI_SANDBOX_ENV_VAR = "GEMINI_SANDBOX"
GEMINI_SANDBOX_DISABLED_VALUE = "false"
GEMINI_OUTPUT_FORMAT = "json"
LANE_SESSION_STATE_FILE = "codex-lane-sessions.json"
INLINE_PROMPT_TOO_LARGE_MESSAGE = (
    "Gemini inline prompt is too large for this platform's command-line limit. "
    "Reduce the brief size or switch to a non-argv prompt delivery path."
)
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
        "updatedAt": datetime.utcnow().isoformat() + "Z",
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
# Gemini CLI non-interactive invocation
# ---------------------------------------------------------------------------


def configured_gemini_model() -> str:
    model = os.environ.get(GEMINI_MODEL_ENV_VAR, DEFAULT_GEMINI_MODEL).strip()
    return model or DEFAULT_GEMINI_MODEL


def _gemini_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("COLORTERM", "truecolor")
    env[GEMINI_SANDBOX_ENV_VAR] = GEMINI_SANDBOX_DISABLED_VALUE
    return env


def _noninteractive_command(gemini: str, prompt: str, session_id: str) -> list[str]:
    safe_prompt = prompt if not prompt.startswith("-") else "\n" + prompt
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
    # In a headless subprocess, a positional query routes to the official
    # non-interactive code path without relying on -p/--prompt.
    command.append(safe_prompt)
    return command


def _combined_result_output(result: subprocess.CompletedProcess[str]) -> str:
    combined = "\n".join(
        part for part in (result.stdout, result.stderr) if part
    ).strip()
    return combined[:MAX_OUTPUT_CHARS]


def _extract_json_payload(raw_text: str) -> dict[str, object] | None:
    stripped = raw_text.strip()
    if not stripped:
        return None

    candidates = [stripped]
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
        if isinstance(candidate, dict):
            payload = candidate
        else:
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
        if isinstance(payload, dict) and any(
            key in payload for key in ("session_id", "response", "error", "stats")
        ):
            return payload
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
            raise OSError(errno.E2BIG, INLINE_PROMPT_TOO_LARGE_MESSAGE) from exc
        raise


def _should_retry_resume(command: list[str], combined_output: str) -> bool:
    return "--resume" in command and any(
        marker in combined_output for marker in RESUME_FALLBACK_MARKERS
    )


def run_gemini(
    prompt: str, timeout_seconds: int, project_root: Path, *, lane: str
) -> subprocess.CompletedProcess[str]:
    """Invoke Gemini CLI in headless mode and parse the official JSON output."""
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

        combined_output = (
            error_text or _combined_result_output(result)
        ).strip()
        if _should_retry_resume(command, combined_output.lower()):
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
        result = run_gemini(prompt, args.timeout_seconds, project_root, lane=lane)
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
