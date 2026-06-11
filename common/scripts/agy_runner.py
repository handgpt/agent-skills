#!/usr/bin/env python3
"""Shared Antigravity CLI advisory runner used by agent advisory skills."""
from __future__ import annotations

import argparse
import errno
import json
import os
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import advisory_common

try:
    import pty
except ImportError:  # pragma: no cover - platform dependent
    pty = None  # type: ignore[assignment]


DEFAULT_TIMEOUT_SECONDS = 1200
DEFAULT_AGY_MODEL = "Gemini 3.5 Flash (High)"
SUPPORTED_AGY_MODELS = (
    "Gemini 3.5 Flash (High)",
    "Gemini 3.1 Pro (High)",
    "Claude Sonnet 4.6 (Thinking)",
    "Claude Opus 4.6 (Thinking)",
)
MAX_OUTPUT_CHARS = 12000
MAX_PROGRESS_TEXT_CHARS = 500
DEFAULT_AGY_CMD = "agy"
AGY_POLL_SECONDS = 1.0
AGY_SHUTDOWN_GRACE_SECONDS = 3.0
TURN_START_SKEW_SECONDS = 300.0
TRANSCRIPT_MTIME_SKEW_SECONDS = 2.0
AGY_WAIT_PROGRESS_PREFIX = "[Antigravity wait]"
ENV_ASSIGN_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
UUID_TEXT = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
CONVERSATION_PATTERNS = (
    re.compile(rf"Created conversation\s+({UUID_TEXT})"),
    re.compile(rf"Streaming conversation\s+({UUID_TEXT})"),
    re.compile(rf"conversation=({UUID_TEXT})"),
    re.compile(rf"Forwarding user message to conversation\s+({UUID_TEXT})"),
    re.compile(rf"Sending user message to conversation\s+({UUID_TEXT})"),
    re.compile(rf"--conversation=?\s*({UUID_TEXT})"),
)
AUTH_FAILURE_MARKERS = (
    "you are not logged into antigravity",
    "failed to get oauth token",
    "authentication required",
    "authentication timed out",
)
TERMINAL_LOG_FAILURE_MARKERS = (
    "auth timed out",
    "authentication timed out",
    "invalid_grant",
    "malformed auth code",
    "resource_exhausted",
    "individual quota reached",
    "user location is not supported",
    "failed_precondition",
)
_PROGRESS_STREAM = None


@dataclass(frozen=True)
class AgyPlatformConfig:
    name: str
    env_prefix: str
    home_env_var: str
    default_mode: str
    default_config_path: str
    enable_output_file: bool = False


CODEX_AGY_PLATFORM = AgyPlatformConfig(
    name="Codex",
    env_prefix="CODEX",
    home_env_var="CODEX_HOME",
    default_mode="interactive",
    default_config_path="~/.codex/agy_cli.json",
)
CLAUDE_CODE_AGY_PLATFORM = AgyPlatformConfig(
    name="Claude Code",
    env_prefix="CLAUDE",
    home_env_var="CLAUDE_HOME",
    default_mode="print",
    default_config_path="~/.claude/agy_cli.json",
    enable_output_file=True,
)

_PLATFORM = CODEX_AGY_PLATFORM
DEFAULT_MODE = _PLATFORM.default_mode
DEFAULT_CONFIG_PATH = _PLATFORM.default_config_path
AGY_HOME_ENV_VAR = _PLATFORM.home_env_var
AGY_CMD_ENV_VAR = f"{_PLATFORM.env_prefix}_AGY_CMD"
AGY_MODE_ENV_VAR = f"{_PLATFORM.env_prefix}_AGY_MODE"
AGY_CONFIG_ENV_VAR = f"{_PLATFORM.env_prefix}_AGY_CONFIG"
AGY_MODEL_ENV_VAR = f"{_PLATFORM.env_prefix}_AGY_MODEL"
AGY_PRINT_TIMEOUT_ENV_VAR = f"{_PLATFORM.env_prefix}_AGY_PRINT_TIMEOUT"
AGY_DANGEROUS_SKIP_ENV_VAR = f"{_PLATFORM.env_prefix}_AGY_DANGEROUSLY_SKIP_PERMISSIONS"
ENABLE_OUTPUT_FILE_ARGUMENT = _PLATFORM.enable_output_file


def configure_platform(config: AgyPlatformConfig) -> None:
    """Configure platform-specific defaults for the current runner process."""
    global _PLATFORM
    global DEFAULT_MODE, DEFAULT_CONFIG_PATH, AGY_HOME_ENV_VAR
    global AGY_CMD_ENV_VAR, AGY_MODE_ENV_VAR, AGY_CONFIG_ENV_VAR, AGY_MODEL_ENV_VAR
    global AGY_PRINT_TIMEOUT_ENV_VAR, AGY_DANGEROUS_SKIP_ENV_VAR, ENABLE_OUTPUT_FILE_ARGUMENT

    _PLATFORM = config
    DEFAULT_MODE = config.default_mode
    DEFAULT_CONFIG_PATH = config.default_config_path
    AGY_HOME_ENV_VAR = config.home_env_var
    AGY_CMD_ENV_VAR = f"{config.env_prefix}_AGY_CMD"
    AGY_MODE_ENV_VAR = f"{config.env_prefix}_AGY_MODE"
    AGY_CONFIG_ENV_VAR = f"{config.env_prefix}_AGY_CONFIG"
    AGY_MODEL_ENV_VAR = f"{config.env_prefix}_AGY_MODEL"
    AGY_PRINT_TIMEOUT_ENV_VAR = f"{config.env_prefix}_AGY_PRINT_TIMEOUT"
    AGY_DANGEROUS_SKIP_ENV_VAR = f"{config.env_prefix}_AGY_DANGEROUSLY_SKIP_PERMISSIONS"
    ENABLE_OUTPUT_FILE_ARGUMENT = config.enable_output_file


def _emit_progress(prefix: str, message: object) -> None:
    text = _clean_progress_text(message)
    if text:
        print(f"{prefix} {text}", file=_PROGRESS_STREAM or sys.stderr, flush=True)


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


def _config_path(config_path: str | Path | None = None) -> Path:
    raw = str(config_path or os.getenv(AGY_CONFIG_ENV_VAR, "")).strip()
    if not raw:
        platform_home = os.getenv(AGY_HOME_ENV_VAR, "").strip()
        raw = str(Path(platform_home) / "agy_cli.json") if platform_home else DEFAULT_CONFIG_PATH
    return Path(os.path.expandvars(os.path.expanduser(raw))).resolve()


def _load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = _config_path(config_path)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _emit_progress("[Antigravity config]", f"ignored unreadable config: {path}")
        return {}
    return payload if isinstance(payload, dict) else {}


def _config_text(config: dict[str, Any], key: str, env_name: str = "", default: str = "") -> str:
    if env_name:
        raw_env = os.getenv(env_name, "").strip()
        if raw_env:
            return raw_env
    value = config.get(key)
    if value is None:
        return default
    return str(value).strip()


def _config_bool(config: dict[str, Any], key: str, env_name: str, default: bool) -> bool:
    raw_env = os.getenv(env_name, "").strip() if env_name else ""
    value: object = raw_env if raw_env else config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _normalize_mode(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized in {"", "p", "print"}:
        return "print"
    if normalized in {"i", "interactive", "prompt-interactive"}:
        return "interactive"
    raise ValueError(f"Unsupported Antigravity mode: {mode!r}. Allowed values: print, interactive")


def _looks_like_env_assignment(token: str) -> bool:
    if "=" not in token:
        return False
    name, _value = token.split("=", 1)
    return bool(name) and all(ch in ENV_ASSIGN_CHARS for ch in name) and not name[0].isdigit()


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
        if not _looks_like_env_assignment(token):
            break
        name, value = token.split("=", 1)
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


def _base_command(
    command: str | None = None, config: dict[str, Any] | None = None
) -> tuple[list[str], dict[str, str]]:
    raw_command = str(
        command
        or os.getenv(AGY_CMD_ENV_VAR, "")
        or _config_text(config or {}, "command")
        or DEFAULT_AGY_CMD
    )
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
            [*args, "--help"],
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


def _flag_values(args: list[str], *flags: str) -> list[str]:
    values: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        matched = False
        for flag in flags:
            if token == flag:
                if index + 1 < len(args):
                    values.append(str(args[index + 1]).strip())
                    index += 2
                else:
                    index += 1
                matched = True
                break
            prefix = f"{flag}="
            if token.startswith(prefix):
                values.append(token[len(prefix) :].strip())
                index += 1
                matched = True
                break
        if not matched:
            index += 1
    return [value for value in values if value]


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


def _drop_bool_flags(args: list[str], flags: set[str]) -> list[str]:
    return [
        token
        for token in args
        if token not in flags and not any(token.startswith(f"{flag}=") for flag in flags)
    ]


def _configured_agy_model(config: dict[str, Any]) -> str:
    model = _config_text(config, "model", AGY_MODEL_ENV_VAR, DEFAULT_AGY_MODEL)
    if not model:
        return DEFAULT_AGY_MODEL
    if model not in SUPPORTED_AGY_MODELS:
        supported = ", ".join(SUPPORTED_AGY_MODELS)
        raise ValueError(f"Unsupported Antigravity model: {model!r}. Supported models: {supported}")
    return model


def _append_add_dirs(args: list[str], help_text: str, add_dirs: tuple[Path, ...]) -> list[str]:
    if "--add-dir" not in help_text or not add_dirs:
        return args
    updated = list(args)
    existing = set(_flag_values(updated, "--add-dir"))
    for path in add_dirs:
        value = str(path.expanduser().resolve())
        if value in existing:
            continue
        updated.extend(["--add-dir", value])
        existing.add(value)
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


def _log_auth_failure(log_path: Path | None) -> str:
    if not log_path or not log_path.is_file():
        return ""
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")[-MAX_OUTPUT_CHARS:]
    except Exception:
        return ""
    normalized = text.lower()
    return text.strip() if any(marker in normalized for marker in AUTH_FAILURE_MARKERS) else ""


def _log_terminal_failure(log_path: Path | None) -> str:
    if not log_path or not log_path.is_file():
        return ""
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")[-MAX_OUTPUT_CHARS:]
    except Exception:
        return ""
    normalized = text.lower()
    return text.strip() if any(marker in normalized for marker in TERMINAL_LOG_FAILURE_MARKERS) else ""


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


def _path_mtime_epoch(path: Path | None) -> float:
    if not path:
        return 0.0
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _transcript_touched_for_run(path: Path | None, start_epoch: float) -> bool:
    if start_epoch <= 0:
        return True
    transcript_epoch = _path_mtime_epoch(path)
    if transcript_epoch <= 0:
        return False
    return transcript_epoch + TRANSCRIPT_MTIME_SKEW_SECONDS >= start_epoch


def _record_epoch(record: dict[str, Any]) -> float:
    raw = str(record.get("created_at") or "").strip()
    if not raw:
        return 0.0
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _is_user_input_record(record: dict[str, Any]) -> bool:
    return (
        str(record.get("source", "")).strip() == "USER_EXPLICIT"
        and str(record.get("type", "")).strip() == "USER_INPUT"
        and str(record.get("status", "")).strip() == "DONE"
    )


def _turn_start_index(records: list[dict[str, Any]], prompt: str, start_epoch: float) -> int:
    return _turn_start_index_after(records, prompt, start_epoch, 0)


def _turn_start_index_after(
    records: list[dict[str, Any]],
    prompt: str,
    start_epoch: float,
    min_record_index: int,
) -> int:
    prompt_text = str(prompt or "").strip()
    lower_bound = max(0, min(int(min_record_index or 0), len(records)))
    if start_epoch > 0:
        threshold = max(0.0, start_epoch - TURN_START_SKEW_SECONDS)
        recent_user_index = -1
        for index in range(len(records) - 1, lower_bound - 1, -1):
            record = records[index]
            if not _is_user_input_record(record):
                continue
            record_epoch = _record_epoch(record)
            if record_epoch > 0 and record_epoch < threshold:
                continue
            if recent_user_index < 0:
                recent_user_index = index
            if prompt_text and prompt_text in str(record.get("content") or ""):
                return index + 1
        if recent_user_index >= 0:
            return recent_user_index + 1
        return len(records) if records else 0

    for index in range(len(records) - 1, lower_bound - 1, -1):
        record = records[index]
        if _is_user_input_record(record) and prompt_text and prompt_text in str(record.get("content") or ""):
            return index + 1
    return 0


def _latest_model_text(records: list[dict[str, Any]], turn_start_index: int = 0) -> str:
    start_index = max(0, min(int(turn_start_index or 0), len(records)))
    for record in reversed(records[start_index:]):
        if str(record.get("source", "")).strip() != "MODEL":
            continue
        if str(record.get("status", "")).strip() != "DONE":
            continue
        if str(record.get("type", "")).strip() not in {"", "PLANNER_RESPONSE"}:
            continue
        if record.get("tool_calls"):
            continue
        text = str(record.get("content") or "").strip()
        if text:
            return text
    return ""


def _latest_run_model_text(
    records: list[dict[str, Any]],
    prompt: str,
    start_epoch: float,
    transcript_epoch: float = 0.0,
    min_record_index: int = 0,
) -> str:
    if (
        start_epoch > 0
        and transcript_epoch > 0
        and transcript_epoch + TRANSCRIPT_MTIME_SKEW_SECONDS < start_epoch
    ):
        return ""
    return _latest_model_text(
        records,
        _turn_start_index_after(records, prompt, start_epoch, min_record_index),
    )


def _is_auth_failure(text: str, conversation_id: str, records: list[dict[str, Any]]) -> bool:
    if conversation_id or records:
        return False
    normalized = str(text or "").lower()
    return any(marker in normalized for marker in AUTH_FAILURE_MARKERS)


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
        file=_PROGRESS_STREAM or sys.stderr,
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
    model: str,
    add_dirs: tuple[Path, ...] = (),
    mode: str = "print",
    dangerously_skip_permissions: bool = True,
) -> list[str]:
    args = _drop_mode_prompt_flags(base_args)
    args = _drop_value_flags(args, {"--model", "-m"})
    if model and "--model" in help_text:
        args.extend(["--model", model])
    if "--add-dir" in help_text:
        args = _append_add_dirs(args, help_text, add_dirs)
    else:
        args = _drop_value_flags(args, {"--add-dir"})
    if dangerously_skip_permissions and "--dangerously-skip-permissions" in help_text:
        if not _has_flag(args, "--dangerously-skip-permissions"):
            args.append("--dangerously-skip-permissions")
    else:
        args = _drop_bool_flags(args, {"--dangerously-skip-permissions"})
    if log_file:
        args = _drop_value_flags(args, {"--log-file"})
        args.extend(["--log-file", log_file])

    if mode == "print":
        if "--print-timeout" in help_text:
            if print_timeout and not _has_flag(args, "--print-timeout"):
                args.extend(["--print-timeout", print_timeout])
        else:
            args = _drop_value_flags(args, {"--print-timeout"})
        if not _has_flag(args, "--print", "-p", "--prompt"):
            args.append("-p")
    else:
        args = _drop_value_flags(args, {"--print-timeout"})
        if not _has_flag(args, "--prompt-interactive", "-i"):
            args.append("-i")
    args.append(_safe_prompt_argument(prompt))
    return args


def _terminate_process(process: subprocess.Popen[Any]) -> None:
    try:
        if process.poll() is not None:
            return
    except Exception:
        pass
    try:
        process.terminate()
    except Exception:
        pass
    try:
        process.wait(timeout=AGY_SHUTDOWN_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except Exception:
            pass
        try:
            process.wait(timeout=1)
        except Exception:
            pass
    except Exception:
        pass


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _launch_interactive(
    args: list[str], cwd: Path, env: dict[str, str]
) -> tuple[subprocess.Popen[bytes], int]:
    if pty is None:
        raise OSError("Antigravity interactive mode requires POSIX PTY support.")
    master_fd, slave_fd = pty.openpty()
    process: subprocess.Popen[bytes] | None = None
    slave_closed = False
    try:
        process = subprocess.Popen(
            args,
            cwd=str(cwd),
            env=env,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave_fd)
        slave_closed = True
        os.set_blocking(master_fd, False)
        return process, master_fd
    except BaseException:
        if process is not None:
            try:
                _terminate_process(process)
            except Exception:
                pass
        if not slave_closed:
            try:
                os.close(slave_fd)
            except OSError:
                pass
        try:
            os.close(master_fd)
        except OSError:
            pass
        raise


def _interactive_log_path(args: list[str]) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(_flag_value(args, "--log-file")))).resolve()


def _build_interactive_start_state(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    start_dt: datetime,
) -> tuple[subprocess.Popen[bytes], int, Path]:
    process, master_fd = _launch_interactive(args, cwd, env)
    try:
        log_path = _interactive_log_path(args)
        _emit_progress("[Antigravity mode]", "interactive")
        _emit_progress("[Antigravity cwd]", cwd)
        _emit_progress("[Antigravity log]", f"start={start_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        _emit_progress("[Antigravity log]", log_path)
        return process, master_fd, log_path
    except BaseException:
        _close_interactive(process, master_fd)
        raise


def _drain_pty(master_fd: int, current_output: str) -> str:
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
        updated = (updated + chunk.decode("utf-8", errors="replace"))[-MAX_OUTPUT_CHARS:]


def _request_interactive_exit(master_fd: int) -> bool:
    try:
        os.write(master_fd, b"/quit\r\n")
        return True
    except OSError:
        return False


def _close_interactive(process: subprocess.Popen[bytes], master_fd: int) -> None:
    try:
        deadline = time.monotonic() + AGY_SHUTDOWN_GRACE_SECONDS
        while time.monotonic() < deadline:
            try:
                if process.poll() is not None:
                    break
            except BaseException:
                break
            if not _request_interactive_exit(master_fd):
                break
            time.sleep(0.2)
        try:
            process_running = process.poll() is None
        except BaseException:
            process_running = False
        if process_running:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except BaseException:
                try:
                    process.terminate()
                except BaseException:
                    pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except BaseException:
                    pass
                try:
                    process.wait(timeout=1)
                except BaseException:
                    pass
            except BaseException:
                pass
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass


def _run_print(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
    start_dt: datetime,
    start_epoch: float,
    prompt_text: str,
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
    transcript_start_index = 0
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
                        if transcript and not _transcript_touched_for_run(transcript, start_epoch):
                            transcript_start_index = len(_load_transcript(transcript))
                if transcript and _transcript_touched_for_run(transcript, start_epoch):
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
        if transcript and _transcript_touched_for_run(transcript, start_epoch):
            records = _load_transcript(transcript)
            _emit_transcript_progress(records, seen_steps)

        stdout_text = _read_text_file(stdout_path)
        stderr_text = _read_text_file(stderr_path)

        transcript_text = _latest_run_model_text(
            records,
            prompt_text,
            start_epoch,
            _path_mtime_epoch(transcript),
            transcript_start_index,
        )
        terminal_failure_text = _log_terminal_failure(log_path)
        auth_failure_text = _log_auth_failure(log_path) if not conversation_id else ""
        combined_diagnostics = "\n".join(
            part for part in (stdout_text, stderr_text, terminal_failure_text, auth_failure_text) if part
        )
        effective_returncode = returncode or (
            1 if terminal_failure_text or _is_auth_failure(combined_diagnostics, conversation_id, records) else 0
        )
        text = (
            stdout_text.strip()
            or transcript_text
            or stderr_text.strip()
            or terminal_failure_text.strip()
            or auth_failure_text.strip()
        )
        stderr = "\n".join(
            part for part in (stderr_text.strip(), terminal_failure_text.strip(), auth_failure_text.strip()) if part
        )
        return subprocess.CompletedProcess(args, effective_returncode, text, stderr)
    finally:
        if process is not None and process.poll() is None:
            _terminate_process(process)
        stdout_path.unlink(missing_ok=True)
        stderr_path.unlink(missing_ok=True)


def _run_interactive(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
    start_dt: datetime,
    start_epoch: float,
    prompt_text: str,
) -> subprocess.CompletedProcess[str]:
    if os.name != "posix" or pty is None:
        return subprocess.CompletedProcess(
            args,
            1,
            "",
            "Antigravity interactive mode requires POSIX PTY support; use print mode on this platform.",
        )
    process: subprocess.Popen[bytes] | None = None
    master_fd: int | None = None
    interactive_closed = False
    captured_output = ""
    start_monotonic = time.monotonic()
    log_path: Path | None = None
    conversation_id = ""
    transcript: Path | None = None
    records: list[dict[str, Any]] = []
    latest_text = ""
    exit_requested = False
    seen_steps: set[tuple[Any, str]] = set()
    transcript_start_index = 0
    last_wait_percent = -1

    try:
        process, master_fd, log_path = _build_interactive_start_state(
            args,
            cwd=cwd,
            env=env,
            start_dt=start_dt,
        )
        while True:
            captured_output = _drain_pty(master_fd, captured_output)

            if not conversation_id:
                conversation_id = _conversation_id_from_log(log_path)
                if conversation_id:
                    transcript = _transcript_path(conversation_id)
                    _emit_progress("[Antigravity conversation]", conversation_id)
                    _emit_progress("[Antigravity transcript]", transcript)
                    if transcript and not _transcript_touched_for_run(transcript, start_epoch):
                        transcript_start_index = len(_load_transcript(transcript))
                elif time.monotonic() - start_monotonic >= 5:
                    terminal_failure_text = _log_terminal_failure(log_path)
                    if terminal_failure_text:
                        _close_interactive(process, master_fd)
                        interactive_closed = True
                        return subprocess.CompletedProcess(
                            args,
                            1,
                            "",
                            "\n".join(part for part in (captured_output.strip(), terminal_failure_text) if part),
                        )

            if transcript:
                if _transcript_touched_for_run(transcript, start_epoch):
                    records = _load_transcript(transcript)
                    seen_steps = _emit_transcript_progress(records, seen_steps)
                    latest_text = (
                        _latest_run_model_text(
                            records,
                            prompt_text,
                            start_epoch,
                            _path_mtime_epoch(transcript),
                            transcript_start_index,
                        )
                        or latest_text
                    )
                if latest_text and not exit_requested:
                    if _request_interactive_exit(master_fd):
                        exit_requested = True
                        _emit_progress("[Antigravity exit]", "requested /quit after transcript output")
                elif not latest_text:
                    terminal_failure_text = _log_terminal_failure(log_path)
                    if terminal_failure_text:
                        _close_interactive(process, master_fd)
                        interactive_closed = True
                        return subprocess.CompletedProcess(
                            args,
                            1,
                            "",
                            "\n".join(part for part in (captured_output.strip(), terminal_failure_text) if part),
                        )

            if process.poll() is not None:
                captured_output = _drain_pty(master_fd, captured_output)
                if not conversation_id:
                    conversation_id = _conversation_id_from_log(log_path)
                if conversation_id and transcript is None:
                    transcript = _transcript_path(conversation_id)
                if transcript and _transcript_touched_for_run(transcript, start_epoch):
                    records = _load_transcript(transcript)
                    _emit_transcript_progress(records, seen_steps)
                    latest_text = (
                        _latest_run_model_text(
                            records,
                            prompt_text,
                            start_epoch,
                            _path_mtime_epoch(transcript),
                            transcript_start_index,
                        )
                        or latest_text
                    )

                returncode = process.returncode or 0
                terminal_failure_text = _log_terminal_failure(log_path)
                diagnostics = "\n".join(part for part in (captured_output.strip(), terminal_failure_text) if part)
                effective_returncode = returncode or (
                    1 if terminal_failure_text or _is_auth_failure(diagnostics, conversation_id, records) else 0
                )
                text = latest_text or captured_output.strip()
                _close_interactive(process, master_fd)
                interactive_closed = True
                return subprocess.CompletedProcess(args, effective_returncode, text, diagnostics)

            last_wait_percent = _emit_wait_progress(
                time.monotonic(), start_monotonic, timeout_seconds, last_wait_percent
            )
            if time.monotonic() - start_monotonic >= timeout_seconds:
                captured_output = _drain_pty(master_fd, captured_output)
                _close_interactive(process, master_fd)
                interactive_closed = True
                raise subprocess.TimeoutExpired(
                    args,
                    timeout_seconds,
                    output=captured_output,
                    stderr=latest_text,
                )
            time.sleep(AGY_POLL_SECONDS)
    except BaseException:
        if not interactive_closed and process is not None and master_fd is not None:
            _close_interactive(process, master_fd)
        raise


def run_agy(
    prompt: str,
    timeout_seconds: int,
    project_root: Path,
    *,
    add_dirs: tuple[Path, ...] = (),
    output_normalizer: Callable[[str], str] | None = None,
    output_validator: Callable[[str], str] | None = None,
    mode: str = "",
    config_path: str | Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke Antigravity CLI through configured print or interactive prompt mode."""
    prompt_text = str(prompt or "")
    if not prompt_text.strip():
        raise ValueError("prompt is required")

    config = _load_config(config_path)
    selected_mode = _normalize_mode(mode or _config_text(config, "mode", AGY_MODE_ENV_VAR, DEFAULT_MODE))
    model = _configured_agy_model(config)
    dangerously_skip_permissions = _config_bool(
        config, "dangerously_skip_permissions", AGY_DANGEROUS_SKIP_ENV_VAR, True
    )

    base_args, env_overrides = _base_command(config=config)
    resolved_exe = _resolve_executable(base_args[0])
    if not resolved_exe:
        raise FileNotFoundError(
            f"agy executable not found. {AGY_CMD_ENV_VAR}={os.getenv(AGY_CMD_ENV_VAR, '')!r}, "
            f"{AGY_CONFIG_ENV_VAR}={os.getenv(AGY_CONFIG_ENV_VAR, '')!r}, "
            f"config={_config_path(config_path)}, binary={base_args[0]!r}, "
            f"PATH={os.getenv('PATH', '')!r}. Set {AGY_CMD_ENV_VAR} or the config file's "
            "`command` field to the absolute Antigravity CLI path."
        )
    base_args[0] = resolved_exe

    help_text = _probe_help(base_args, project_root, env_overrides)
    start_dt = datetime.now()
    start_epoch = time.time()
    log_file = str(_agy_log_file(start_dt))
    print_timeout = _config_text(
        config, "print_timeout", AGY_PRINT_TIMEOUT_ENV_VAR, _duration_text(timeout_seconds)
    )
    command = _build_command(
        base_args,
        help_text=help_text,
        prompt=prompt_text,
        print_timeout=print_timeout,
        log_file=log_file,
        model=model,
        add_dirs=add_dirs,
        mode=selected_mode,
        dangerously_skip_permissions=dangerously_skip_permissions,
    )

    if selected_mode == "print":
        result = _run_print(
            command,
            cwd=project_root,
            env=_agy_environment(env_overrides),
            timeout_seconds=timeout_seconds,
            start_dt=start_dt,
            start_epoch=start_epoch,
            prompt_text=prompt_text,
        )
    else:
        result = _run_interactive(
            command,
            cwd=project_root,
            env=_agy_environment(env_overrides),
            timeout_seconds=timeout_seconds,
            start_dt=start_dt,
            start_epoch=start_epoch,
            prompt_text=prompt_text,
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
    if ENABLE_OUTPUT_FILE_ARGUMENT:
        parser.add_argument(
            "--output-file",
            default=None,
            help="Write all output (stdout and stderr) to this file instead of the console.",
        )
    return parser


def _project_add_dirs(project_root: Path, project_roots: tuple[Path, ...]) -> tuple[Path, ...]:
    resolved_project_root = project_root.resolve()
    add_dirs: list[Path] = []
    seen: set[Path] = set()
    for root in project_roots:
        resolved_root = root.resolve()
        if resolved_root == resolved_project_root or resolved_root in seen:
            continue
        if not resolved_root.exists() or not resolved_root.is_dir():
            continue
        seen.add(resolved_root)
        add_dirs.append(resolved_root)
    return tuple(add_dirs)


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
    global _PROGRESS_STREAM
    if (output_contract is None) == (output_contract_builder is None):
        raise ValueError("Provide exactly one of output_contract or output_contract_builder.")

    parser = make_arg_parser(description)
    if configure_parser is not None:
        configure_parser(parser)
    args = parser.parse_args(argv)

    output_handle = None
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    original_progress_stream = _PROGRESS_STREAM
    output_file = str(getattr(args, "output_file", "") or "").strip()
    if output_file:
        output_path = Path(output_file).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_handle = open(output_path, "w", encoding="utf-8", buffering=1)  # noqa: SIM115
        _PROGRESS_STREAM = original_stderr
        sys.stdout = output_handle
        sys.stderr = output_handle
    try:
        return _run_advisory_inner(
            args=args,
            role_line=role_line,
            label=label,
            lane=lane,
            output_contract=output_contract,
            output_contract_builder=output_contract_builder,
        )
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        _PROGRESS_STREAM = original_progress_stream
        if output_handle is not None:
            output_handle.close()


def _run_advisory_inner(
    *,
    args: argparse.Namespace,
    role_line: str,
    label: str,
    lane: str,
    output_contract: str | None = None,
    output_contract_builder: Callable[[argparse.Namespace], str] | None = None,
) -> int:
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
            add_dirs=_project_add_dirs(project_root, project_roots),
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
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:
        if exc.errno == errno.E2BIG:
            print(
                "Antigravity inline prompt is too large for this platform's command-line limit. "
                "Reduce the brief size.",
                file=sys.stderr,
            )
            return 5
        print(f"Antigravity {label} failed to start: {exc}", file=sys.stderr)
        return 5

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
