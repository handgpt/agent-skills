#!/usr/bin/env python3
"""Shared Antigravity CLI advisory runner used by Codex Antigravity skills."""
from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import advisory_common


DEFAULT_TIMEOUT_SECONDS = 1200
MAX_OUTPUT_CHARS = 12000
MAX_PROGRESS_TEXT_CHARS = 500
DEFAULT_AGY_CMD = "agy"
AGY_CMD_ENV_VAR = "CODEX_AGY_CMD"
AGY_PRINT_TIMEOUT_ENV_VAR = "CODEX_AGY_PRINT_TIMEOUT"
AGY_POLL_SECONDS = 1.0
AGY_SHUTDOWN_GRACE_SECONDS = 3.0
AGY_WAIT_PROGRESS_PREFIX = "[Antigravity wait]"
UUID_TEXT = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
CONVERSATION_PATTERNS = (
    re.compile(rf"Created conversation\s+({UUID_TEXT})"),
    re.compile(rf"Streaming conversation\s+({UUID_TEXT})"),
    re.compile(rf"conversation=({UUID_TEXT})"),
    re.compile(rf"Forwarding user message to conversation\s+({UUID_TEXT})"),
    re.compile(rf"Sending user message to conversation\s+({UUID_TEXT})"),
    re.compile(rf"--conversation=?\s*({UUID_TEXT})"),
)


def _emit_progress(prefix: str, message: object) -> None:
    text = _clean_progress_text(message)
    if text:
        print(f"{prefix} {text}", file=sys.stderr, flush=True)


def _clean_progress_text(value: object, *, limit: int = MAX_PROGRESS_TEXT_CHARS) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except Exception:
            text = str(value)
    text = re.sub(r"\s+", " ", text.replace("\r", "\n")).strip()
    if limit > 0 and len(text) > limit:
        return f"{text[:limit].rstrip()}..."
    return text


def _safe_prompt_argument(prompt: str) -> str:
    return prompt if not prompt.startswith("-") else "\n" + prompt


def _duration_text(timeout_seconds: int) -> str:
    return f"{max(1, int(timeout_seconds))}s"


def _split_cli_command(raw_command: str, fallback_args: list[str]) -> tuple[list[str], dict[str, str]]:
    text = str(raw_command or "").strip()
    if not text:
        return list(fallback_args), {}
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()

    env_overrides: dict[str, str] = {}
    command_start = 0
    for index, token in enumerate(tokens):
        if "=" not in token:
            break
        name, value = token.split("=", 1)
        if not name or not all(ch.isalnum() or ch == "_" for ch in name) or name[0].isdigit():
            break
        env_overrides[name] = value
        command_start = index + 1

    command = tokens[command_start:]
    return (command or list(fallback_args)), env_overrides


def _resolve_executable(binary: str) -> str:
    token = str(binary or "").strip()
    if not token:
        return ""
    expanded = os.path.expandvars(os.path.expanduser(token))
    candidate = Path(expanded)
    if ("/" in expanded or "\\" in expanded) and candidate.is_file():
        return str(candidate)
    resolved = shutil.which(expanded)
    if resolved:
        return resolved
    if expanded == DEFAULT_AGY_CMD:
        local_candidate = Path.home() / ".local" / "bin" / DEFAULT_AGY_CMD
        if local_candidate.is_file():
            return str(local_candidate)
    return ""


def _base_command(command: str | None = None) -> tuple[list[str], dict[str, str]]:
    raw_command = str(command or os.getenv(AGY_CMD_ENV_VAR, "") or DEFAULT_AGY_CMD)
    return _split_cli_command(raw_command, [DEFAULT_AGY_CMD])


def _agy_environment(env_overrides: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(env_overrides)
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("COLORTERM", "truecolor")
    return env


def _probe_help(args: list[str], cwd: Path, env_overrides: dict[str, str]) -> str:
    if not args:
        return ""
    try:
        env = _agy_environment(env_overrides)
        proc = subprocess.run(
            [args[0], "--help"],
            text=True,
            capture_output=True,
            cwd=str(cwd),
            timeout=15,
            env=env,
            check=False,
        )
    except Exception:
        return ""
    return f"{proc.stdout}\n{proc.stderr}"


def _has_flag(args: list[str], *flags: str) -> bool:
    return any(token == flag or token.startswith(f"{flag}=") for token in args for flag in flags)


def _flag_value(args: list[str], *flags: str) -> str:
    for index, token in enumerate(args):
        for flag in flags:
            if token == flag and index + 1 < len(args):
                return str(args[index + 1]).strip()
            prefix = f"{flag}="
            if token.startswith(prefix):
                return token[len(prefix) :].strip()
    return ""


def _drop_mode_prompt_flags(args: list[str]) -> list[str]:
    prompt_flags = {"--print", "-p", "--prompt", "--prompt-interactive", "-i"}
    updated: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token in prompt_flags:
            index += 2 if index + 1 < len(args) and not str(args[index + 1]).startswith("-") else 1
            continue
        if any(token.startswith(f"{flag}=") for flag in prompt_flags):
            index += 1
            continue
        updated.append(token)
        index += 1
    return updated


def _drop_value_flags(args: list[str], flags: set[str]) -> list[str]:
    updated: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token in flags:
            index += 2 if index + 1 < len(args) and not str(args[index + 1]).startswith("-") else 1
            continue
        if any(token.startswith(f"{flag}=") for flag in flags):
            index += 1
            continue
        updated.append(token)
        index += 1
    return updated


def _agy_log_dir() -> Path:
    return Path.home() / ".gemini" / "antigravity-cli" / "log"


def _agy_brain_dir() -> Path:
    return Path.home() / ".gemini" / "antigravity-cli" / "brain"


def _agy_log_file(start_dt: datetime) -> Path:
    path = _agy_log_dir() / f"cli-{start_dt.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4()}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _conversation_id_from_log(log_path: Path | None) -> str:
    if not log_path or not log_path.is_file():
        return ""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return ""
    discovered: list[str] = []
    for line in lines:
        for pattern in CONVERSATION_PATTERNS:
            match = pattern.search(line)
            if match:
                discovered.append(match.group(1))
    return discovered[0] if discovered else ""


def _transcript_path(conversation_id: str) -> Path | None:
    if not conversation_id:
        return None
    return _agy_brain_dir() / conversation_id / ".system_generated" / "logs" / "transcript.jsonl"


def _load_transcript(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.is_file():
        return []
    for attempt in range(3):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            if attempt < 2:
                time.sleep(0.05)
                continue
            return []
        records: list[dict[str, Any]] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                break
            if isinstance(obj, dict):
                records.append(obj)
        return records
    return []


def _latest_model_text(records: list[dict[str, Any]]) -> str:
    for record in reversed(records):
        if str(record.get("source", "")).strip() != "MODEL":
            continue
        if str(record.get("status", "")).strip() != "DONE":
            continue
        text = str(record.get("content") or "").strip()
        if text:
            return text
    return ""


def _is_auth_failure(text: str, conversation_id: str, records: list[dict[str, Any]]) -> bool:
    if conversation_id or records:
        return False
    normalized = str(text or "").lower()
    return "authentication required" in normalized or "authentication timed out" in normalized


def _step_progress(record: dict[str, Any]) -> str:
    step_index = record.get("step_index", "?")
    source = str(record.get("source", "")).strip()
    step_type = str(record.get("type", "")).strip()
    status = str(record.get("status", "")).strip()
    content = _clean_progress_text(record.get("content"), limit=160)
    parts = [f"#{step_index}", source, step_type, status]
    tool_calls = record.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        tool_names = [
            str(tool_call.get("name") or "").strip()
            for tool_call in tool_calls[:4]
            if isinstance(tool_call, dict)
        ]
        if any(tool_names):
            parts.append(f"tools={','.join(name for name in tool_names if name)}")
    if content:
        parts.append(f"content={content}")
    return " ".join(part for part in parts if part)


def _emit_transcript_progress(
    records: list[dict[str, Any]], seen_steps: set[tuple[Any, str]]
) -> set[tuple[Any, str]]:
    updated = set(seen_steps)
    for record in records:
        key = (record.get("step_index"), str(record.get("status", "")))
        if key in updated:
            continue
        updated.add(key)
        _emit_progress("[Antigravity step]", _step_progress(record))
    return updated


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
        f"{AGY_WAIT_PROGRESS_PREFIX} {percent}% ({elapsed_seconds}s/{timeout_seconds}s)",
        file=sys.stderr,
        flush=True,
    )
    return percent


def _build_command(
    base_args: list[str],
    *,
    help_text: str,
    prompt: str,
    print_timeout: str,
    log_file: str,
    dangerously_skip_permissions: bool = True,
) -> list[str]:
    args = _drop_mode_prompt_flags(base_args)
    args = _drop_value_flags(args, {"--model", "-m"})
    if dangerously_skip_permissions and "--dangerously-skip-permissions" in help_text and not _has_flag(
        args, "--dangerously-skip-permissions"
    ):
        args.append("--dangerously-skip-permissions")
    if log_file:
        args = _drop_value_flags(args, {"--log-file"})
        args.extend(["--log-file", log_file])
    if print_timeout and "--print-timeout" in help_text and not _has_flag(args, "--print-timeout"):
        args.extend(["--print-timeout", print_timeout])
    if not _has_flag(args, "--print", "-p", "--prompt"):
        args.append("-p")
    args.append(_safe_prompt_argument(prompt))
    return args


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=AGY_SHUTDOWN_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1)


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _run_print(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
    start_dt: datetime,
) -> subprocess.CompletedProcess[str]:
    stdout_file = tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False)
    stderr_file = tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False)
    stdout_path = Path(stdout_file.name)
    stderr_path = Path(stderr_file.name)
    stdout_file.close()
    stderr_file.close()

    start_monotonic = time.monotonic()
    log_path = Path(os.path.expandvars(os.path.expanduser(_flag_value(args, "--log-file")))).resolve()
    conversation_id = ""
    transcript: Path | None = None
    records: list[dict[str, Any]] = []
    seen_steps: set[tuple[Any, str]] = set()
    last_wait_percent = -1

    _emit_progress("[Antigravity mode]", "print")
    _emit_progress("[Antigravity cwd]", cwd)
    _emit_progress("[Antigravity log]", f"start={start_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    _emit_progress("[Antigravity log]", log_path)

    process: subprocess.Popen[str] | None = None
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
            "w", encoding="utf-8"
        ) as stderr_handle:
            process = subprocess.Popen(
                args,
                text=True,
                cwd=str(cwd),
                env=env,
                stdout=stdout_handle,
                stderr=stderr_handle,
            )

            while process.poll() is None:
                if not conversation_id:
                    conversation_id = _conversation_id_from_log(log_path)
                    if conversation_id:
                        transcript = _transcript_path(conversation_id)
                        _emit_progress("[Antigravity conversation]", conversation_id)
                        _emit_progress("[Antigravity transcript]", transcript)
                if transcript:
                    records = _load_transcript(transcript)
                    seen_steps = _emit_transcript_progress(records, seen_steps)
                last_wait_percent = _emit_wait_progress(
                    time.monotonic(), start_monotonic, timeout_seconds, last_wait_percent
                )
                if time.monotonic() - start_monotonic >= timeout_seconds:
                    _terminate_process(process)
                    stdout_handle.flush()
                    stderr_handle.flush()
                    stdout_text = _read_text_file(stdout_path)
                    stderr_text = _read_text_file(stderr_path)
                    raise subprocess.TimeoutExpired(
                        args,
                        timeout_seconds,
                        output=stdout_text,
                        stderr=stderr_text,
                    )
                time.sleep(AGY_POLL_SECONDS)
            returncode = process.wait()

            stdout_handle.flush()
            stderr_handle.flush()

        if not conversation_id:
            conversation_id = _conversation_id_from_log(log_path)
        if conversation_id and transcript is None:
            transcript = _transcript_path(conversation_id)
        if transcript:
            records = _load_transcript(transcript)
            _emit_transcript_progress(records, seen_steps)

        stdout_text = _read_text_file(stdout_path)
        stderr_text = _read_text_file(stderr_path)

        transcript_text = _latest_model_text(records)
        combined_diagnostics = "\n".join(part for part in (stdout_text, stderr_text) if part)
        effective_returncode = returncode or (
            1 if _is_auth_failure(combined_diagnostics, conversation_id, records) else 0
        )
        text = stdout_text.strip() or transcript_text or stderr_text.strip()
        return subprocess.CompletedProcess(args, effective_returncode, text, stderr_text.strip())
    finally:
        if process is not None and process.poll() is None:
            _terminate_process(process)
        stdout_path.unlink(missing_ok=True)
        stderr_path.unlink(missing_ok=True)


def run_agy(
    prompt: str,
    timeout_seconds: int,
    project_root: Path,
    *,
    output_normalizer: Callable[[str], str] | None = None,
    output_validator: Callable[[str], str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke Antigravity CLI through `agy -p` print mode."""
    prompt_text = str(prompt or "")
    if not prompt_text.strip():
        raise ValueError("prompt is required")

    base_args, env_overrides = _base_command()
    resolved_exe = _resolve_executable(base_args[0])
    if not resolved_exe:
        raise FileNotFoundError(
            f"agy executable not found. {AGY_CMD_ENV_VAR}={os.getenv(AGY_CMD_ENV_VAR, '')!r}, "
            f"binary={base_args[0]!r}, PATH={os.getenv('PATH', '')!r}"
        )
    base_args[0] = resolved_exe

    help_text = _probe_help(base_args, project_root, env_overrides)
    start_dt = datetime.now()
    log_file = str(_agy_log_file(start_dt))
    print_timeout = os.getenv(AGY_PRINT_TIMEOUT_ENV_VAR, "").strip() or _duration_text(timeout_seconds)
    command = _build_command(
        base_args,
        help_text=help_text,
        prompt=prompt_text,
        print_timeout=print_timeout,
        log_file=log_file,
        dangerously_skip_permissions=True,
    )

    result = _run_print(
        command,
        cwd=project_root,
        env=_agy_environment(env_overrides),
        timeout_seconds=timeout_seconds,
        start_dt=start_dt,
    )
    if result.returncode == 0:
        normalized_stdout = (
            output_normalizer(result.stdout)
            if output_normalizer
            else result.stdout.strip()
        )
        validation_error = output_validator(normalized_stdout) if output_validator else ""
        if validation_error:
            return subprocess.CompletedProcess(command, 1, "", validation_error.replace("Gemini", "Antigravity"))
        if normalized_stdout:
            return subprocess.CompletedProcess(command, 0, normalized_stdout, result.stderr)
    return result


def make_arg_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--brief-file", required=True, help="Markdown or text file with the brief.")
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
        help="Optional local file or directory Antigravity should treat as a high-priority starting point.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"End-to-end advisory timeout in seconds. Default: {DEFAULT_TIMEOUT_SECONDS}.",
    )
    return parser


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
    """Run an Antigravity CLI advisory pass end-to-end and return an exit code."""
    if (output_contract is None) == (output_contract_builder is None):
        raise ValueError("Provide exactly one of output_contract or output_contract_builder.")

    parser = make_arg_parser(description)
    if configure_parser is not None:
        configure_parser(parser)
    args = parser.parse_args(argv)

    brief_path = Path(args.brief_file).expanduser().resolve()
    if not brief_path.is_file():
        print(f"Brief file not found: {advisory_common._tilde_path(brief_path)}", file=sys.stderr)
        return 2

    default_project_root = advisory_common.detect_project_root()
    workspace_boundary = advisory_common.detect_workspace_root()
    project_roots = advisory_common._normalize_multi_project_roots(
        args.project_root, args.context_file, default_project_root, workspace_boundary
    )
    project_root = advisory_common._multi_project_workspace_root(
        project_roots, default_project_root, workspace_boundary
    )
    focus_root = advisory_common._focus_scope_root(args.context_file, project_root, project_roots)
    context_entries = advisory_common.describe_paths(args.context_file, project_root, project_roots)
    resolved_output_contract = (
        output_contract_builder(args) if output_contract_builder else output_contract
    )
    assert resolved_output_contract is not None

    brief_text = brief_path.read_text(encoding="utf-8")
    prompt = advisory_common.build_prompt(
        project_root,
        brief_text,
        context_entries,
        lane=lane,
        focus_root=focus_root,
        project_roots=project_roots,
        role_line=role_line,
        output_contract=resolved_output_contract,
        runner_name="Antigravity CLI",
    )
    output_normalizer = advisory_common.build_output_normalizer(resolved_output_contract)
    output_validator = advisory_common.build_output_validator(resolved_output_contract)

    try:
        result = run_agy(
            prompt,
            args.timeout_seconds,
            project_root,
            output_normalizer=output_normalizer,
            output_validator=output_validator,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except subprocess.TimeoutExpired as exc:
        print(f"Antigravity {label} timed out after {args.timeout_seconds} seconds total wait.", file=sys.stderr)
        timeout_output = str(getattr(exc, "output", "") or getattr(exc, "stderr", "")).strip()
        if timeout_output:
            print(timeout_output[:MAX_OUTPUT_CHARS], file=sys.stderr)
        return 4
    except OSError as exc:
        if exc.errno == errno.E2BIG:
            print(
                "Antigravity inline prompt is too large for this platform's command-line limit. "
                "Reduce the brief size.",
                file=sys.stderr,
            )
            return 5
        raise

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if result.returncode != 0 or not stdout:
        print(f"Antigravity {label} failed with exit code {result.returncode}.", file=sys.stderr)
        if stderr:
            print(stderr[:MAX_OUTPUT_CHARS], file=sys.stderr)
        if stdout:
            print(stdout[:MAX_OUTPUT_CHARS], file=sys.stderr)
        return 5

    print(stdout[:MAX_OUTPUT_CHARS])
    return 0
