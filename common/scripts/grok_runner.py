#!/usr/bin/env python3
"""Shared Grok CLI transport for advisory skills."""
from __future__ import annotations

import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote


DEFAULT_GROK_CMD = "grok"
DEFAULT_CONFIG_BASENAME = "grok_cli.json"
DEFAULT_OUTPUT_FORMAT = "streaming-json"
DEFAULT_PERMISSION_MODE = "bypassPermissions"
DEFAULT_POST_OUTPUT_GRACE_SECONDS = 12.0
GROK_BACKGROUND_STALL_RETURN_CODE = 125
GROK_PROGRESS_INTERVAL_SECONDS = 12.0
GROK_PROGRESS_TEXT_LIMIT = 500
MAX_DIAGNOSTIC_CHARS = 12000
ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
OUTPUT_EVENT_TYPES = {"text", "output_text", "assistant_message", "message"}
END_EVENT_TYPE = "end"
ENV_ASSIGN_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
_PROGRESS_STREAM = None


def _emit_progress(label: str, value: object = "") -> None:
    text = str(value or "")
    if len(text) > GROK_PROGRESS_TEXT_LIMIT:
        text = text[:GROK_PROGRESS_TEXT_LIMIT] + "..."
    print(f"{label} {text}".rstrip(), file=_PROGRESS_STREAM or sys.stderr, flush=True)


def _strip_ansi(text: str) -> str:
    return ANSI_PATTERN.sub("", str(text or ""))


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
    for idx, token in enumerate(tokens):
        if not _looks_like_env_assignment(token):
            break
        name, value = token.split("=", 1)
        env_overrides[name] = value
        command_start = idx + 1

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
    return shutil.which(expanded) or ""


def _default_config_path(env_prefix: str) -> Path:
    prefix = env_prefix.upper()
    home_env = f"{prefix}_HOME"
    platform_home = os.getenv(home_env, "").strip()
    if platform_home:
        return (Path(platform_home).expanduser() / DEFAULT_CONFIG_BASENAME).resolve()
    if prefix == "CLAUDE":
        return (Path.home() / ".claude" / DEFAULT_CONFIG_BASENAME).resolve()
    return (Path.home() / ".codex" / DEFAULT_CONFIG_BASENAME).resolve()


def _load_config(config_path: str | Path | None = None, *, env_prefix: str = "CODEX") -> dict[str, Any]:
    prefix = env_prefix.upper()
    raw = str(config_path or os.getenv(f"{prefix}_GROK_CONFIG", "")).strip()
    path = (
        Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
        if raw
        else _default_config_path(prefix)
    )
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _emit_progress("[Grok config]", f"ignored unreadable config: {path}")
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


def _config_float(config: dict[str, Any], key: str, env_name: str, default: float) -> float:
    raw_env = os.getenv(env_name, "").strip() if env_name else ""
    value: object = raw_env if raw_env else config.get(key, default)
    try:
        return max(0.0, float(str(value).strip()))
    except (TypeError, ValueError):
        return max(0.0, float(default))


def _probe_help(args: list[str], cwd: Path, env_overrides: dict[str, str]) -> str:
    if not args:
        return ""
    try:
        env = os.environ.copy()
        env.update(env_overrides)
        proc = subprocess.run(
            [*args, "--help"],
            text=True,
            capture_output=True,
            cwd=str(cwd),
            env=env,
            timeout=10,
            input="",
            check=False,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    help_text = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    return help_text if "--" in help_text else ""


def _has_flag(args: list[str], *flags: str) -> bool:
    flag_set = set(flags)
    for token in args:
        if token in flag_set:
            return True
        for flag in flag_set:
            if token.startswith(flag + "="):
                return True
    return False


def _find_option(args: list[str], flag: str, *aliases: str) -> tuple[int, str, bool] | None:
    for idx, token in enumerate(args):
        for option in (flag, *aliases):
            if token == option:
                return idx, option, False
            if token.startswith(option + "="):
                return idx, option, True
    return None


def _flag_supported(help_text: str, flag: str, *aliases: str) -> bool:
    if not help_text:
        return True
    return flag in help_text or any(alias in help_text for alias in aliases)


def _append_option(args: list[str], help_text: str, flag: str, value: str, *aliases: str) -> bool:
    if not value or not _flag_supported(help_text, flag, *aliases):
        return False
    existing = _find_option(args, flag, *aliases)
    if existing is not None:
        idx, existing_flag, inline_value = existing
        if inline_value:
            args[idx] = f"{existing_flag}={value}"
        elif idx + 1 < len(args) and not args[idx + 1].startswith("-"):
            args[idx + 1] = value
        else:
            args.insert(idx + 1, value)
        return True
    args.extend([flag, value])
    return True


def _append_switch(args: list[str], help_text: str, flag: str, *aliases: str) -> bool:
    if not _flag_supported(help_text, flag, *aliases):
        return False
    if not _has_flag(args, flag, *aliases):
        args.append(flag)
    return True


def _parse_json_line(line: str) -> dict[str, Any] | None:
    stripped = _strip_ansi(line).strip()
    if not stripped.startswith("{"):
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _event_text(event: dict[str, Any]) -> str:
    data = event.get("data")
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for key in ("text", "content", "delta"):
            value = data.get(key)
            if isinstance(value, str):
                return value
    for key in ("text", "content", "delta"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    return ""


def _is_end_event(event: dict[str, Any]) -> bool:
    return str(event.get("type") or "").strip().lower() == END_EVENT_TYPE


def _extract_end_event(stdout: str) -> dict[str, Any]:
    end_event: dict[str, Any] = {}
    for line in str(stdout or "").splitlines():
        event = _parse_json_line(line)
        if event is not None and _is_end_event(event):
            end_event = event
    return end_event


def _is_streaming_json_format(output_format: str) -> bool:
    return str(output_format or "").strip().lower() == "streaming-json"


def _extract_stream_text(stdout: str, *, allow_fallback: bool = True) -> str:
    text_parts: list[str] = []
    fallback_lines: list[str] = []
    for line in str(stdout or "").splitlines():
        event = _parse_json_line(line)
        if event is not None:
            event_type = str(event.get("type") or "").strip().lower()
            if event_type in OUTPUT_EVENT_TYPES:
                text_parts.append(_event_text(event))
            continue
        cleaned = _strip_ansi(line).strip()
        if cleaned:
            fallback_lines.append(cleaned)
    text = "".join(text_parts).strip()
    if text:
        return text
    if not allow_fallback:
        return ""
    return "\n".join(fallback_lines).strip()


def _session_updates_path(project_root: Path, session_id: str, env: dict[str, str]) -> Path:
    raw_home = str(env.get("GROK_HOME") or "").strip()
    if raw_home:
        grok_home = Path(raw_home).expanduser()
    else:
        home = Path(str(env.get("HOME") or Path.home())).expanduser()
        grok_home = home / ".grok"
    encoded_cwd = quote(str(project_root.resolve()), safe="")
    return grok_home / "sessions" / encoded_cwd / session_id / "updates.jsonl"


def _turn_completed_signature(line: str) -> str:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return ""
    if not isinstance(event, dict):
        return ""
    params = event.get("params")
    update = params.get("update") if isinstance(params, dict) else None
    if not isinstance(update, dict) or update.get("sessionUpdate") != "turn_completed":
        return ""
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class _SessionCompletionProbe:
    """Watch only updates appended after this runner invocation starts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._offset = 0
        self._identity: tuple[int, int] | None = None
        self._known_completions: set[str] = set()
        self._partial = ""
        try:
            stat = path.stat()
        except OSError:
            return
        self._offset = stat.st_size
        self._identity = (stat.st_dev, stat.st_ino)
        try:
            existing = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        self._known_completions = {
            signature
            for line in existing.splitlines()
            if (signature := _turn_completed_signature(line))
        }

    def poll(self) -> bool:
        try:
            stat = self.path.stat()
        except OSError:
            return False

        identity = (stat.st_dev, stat.st_ino)
        if self._identity is None:
            self._identity = identity
        elif identity != self._identity or stat.st_size < self._offset:
            self._identity = identity
            self._partial = ""
            try:
                replaced = self.path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return False
            self._offset = stat.st_size
            current_completions = {
                signature
                for line in replaced.splitlines()
                if (signature := _turn_completed_signature(line))
            }
            new_completion = bool(current_completions - self._known_completions)
            self._known_completions = current_completions
            return new_completion

        if stat.st_size <= self._offset:
            return False

        try:
            with self.path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(self._offset)
                appended = handle.read()
                self._offset = handle.tell()
        except OSError:
            return False

        lines = (self._partial + appended).splitlines(keepends=True)
        self._partial = ""
        if lines and not lines[-1].endswith(("\n", "\r")):
            self._partial = lines.pop()

        for line in lines:
            if _turn_completed_signature(line):
                return True
        return False


def _tail_diagnostics(stdout: str, stderr: str) -> str:
    return "\n".join(part for part in (_strip_ansi(stdout).strip(), _strip_ansi(stderr).strip()) if part)[
        -MAX_DIAGNOSTIC_CHARS:
    ].strip()


def _reader_thread(stream: Any, source: str, output: queue.Queue[tuple[str, str]]) -> None:
    try:
        for line in stream:
            output.put((source, line))
    finally:
        output.put((source, ""))


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _stream_process(
    args: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    env: dict[str, str],
    post_output_grace_seconds: float,
    session_completion_probe: Callable[[], bool] | None = None,
) -> tuple[subprocess.CompletedProcess[str], bool, int, bool]:
    process = subprocess.Popen(
        args,
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    output: queue.Queue[tuple[str, str]] = queue.Queue()
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_thread = threading.Thread(target=_reader_thread, args=(process.stdout, "stdout", output), daemon=True)
    stderr_thread = threading.Thread(target=_reader_thread, args=(process.stderr, "stderr", output), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    start_mono = time.monotonic()
    last_progress = start_mono
    last_stdout_activity = start_mono
    completion_event_seen = False
    session_completion_seen = False
    output_text_seen = False
    stdout_done = False
    stderr_done = False
    terminated_after_output = False

    while True:
        now = time.monotonic()
        if now - start_mono > timeout_seconds:
            _terminate_process(process)
            raise subprocess.TimeoutExpired(args, timeout_seconds, output="".join(stdout_parts), stderr="".join(stderr_parts))

        try:
            source, line = output.get(timeout=0.1)
        except queue.Empty:
            source = ""
            line = ""

        now = time.monotonic()
        if source:
            if line == "":
                if source == "stdout":
                    stdout_done = True
                elif source == "stderr":
                    stderr_done = True
            elif source == "stdout":
                stdout_parts.append(line)
                last_stdout_activity = now
                event = _parse_json_line(line)
                if event is None:
                    output_text_seen = output_text_seen or bool(_strip_ansi(line).strip())
                else:
                    event_type = str(event.get("type") or "").strip().lower()
                    if event_type in OUTPUT_EVENT_TYPES and _event_text(event).strip():
                        output_text_seen = True
                    if _is_end_event(event):
                        completion_event_seen = True
            elif source == "stderr":
                stderr_parts.append(line)

        if not session_completion_seen and session_completion_probe is not None:
            try:
                session_completion_seen = bool(session_completion_probe())
            except OSError:
                session_completion_seen = False

        if now - last_progress >= GROK_PROGRESS_INTERVAL_SECONDS:
            current_text = _extract_stream_text("".join(stdout_parts))
            _emit_progress(
                "[Grok wait]",
                (
                    f"{int(now - start_mono)}s/{timeout_seconds}s "
                    f"output_chars={len(current_text)} stderr_chars={sum(len(part) for part in stderr_parts)}"
                ),
            )
            last_progress = now

        if (
            (completion_event_seen or (session_completion_seen and output_text_seen))
            and post_output_grace_seconds > 0
            and now - last_stdout_activity >= post_output_grace_seconds
            and process.poll() is None
        ):
            terminated_after_output = True
            _emit_progress(
                "[Grok background]",
                (
                    f"terminating cleanup {now - last_stdout_activity:.1f}s after "
                    f"{'stream end' if completion_event_seen else 'session completion'}"
                ),
            )
            _terminate_process(process)

        if process.poll() is not None and stdout_done and stderr_done:
            break

    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)
    for stream in (process.stdout, process.stderr):
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass
    process_returncode = int(process.returncode or 0)
    return (
        subprocess.CompletedProcess(
            args=args,
            returncode=GROK_BACKGROUND_STALL_RETURN_CODE if terminated_after_output else process_returncode,
            stdout="".join(stdout_parts),
            stderr="".join(stderr_parts),
        ),
        terminated_after_output,
        process_returncode,
        session_completion_seen,
    )


def _write_prompt_file(prompt_text: str) -> Path:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix="agent-skills-grok-", suffix=".txt", delete=False)
    with handle:
        handle.write(prompt_text)
    return Path(handle.name)


def _build_command(
    base_args: list[str],
    *,
    help_text: str,
    prompt_file: Path,
    launch_dir: Path,
    model: str,
    effort: str,
    session: str,
    new_session_id: str,
    output_format: str,
    permission_mode: str,
    sandbox: str,
    always_approve: bool,
    no_memory: bool,
    verbatim: bool,
) -> tuple[list[str], bool, str]:
    args = list(base_args)
    _append_option(args, help_text, "--cwd", str(launch_dir))
    _append_option(args, help_text, "--model", model, "-m")
    _append_option(args, help_text, "--reasoning-effort", effort, "--effort")
    if permission_mode and not _append_option(args, help_text, "--permission-mode", permission_mode):
        _emit_progress("[Grok config]", "ignoring unsupported --permission-mode")
    _append_option(args, help_text, "--sandbox", sandbox)
    if always_approve and not _append_switch(args, help_text, "--always-approve"):
        _emit_progress("[Grok config]", "ignoring unsupported --always-approve")
    if no_memory:
        _append_switch(args, help_text, "--no-memory")
    if verbatim:
        _append_switch(args, help_text, "--verbatim")
    if not _append_option(args, help_text, "--output-format", output_format):
        raise RuntimeError("Grok CLI does not support required option: --output-format")

    resume_used = False
    session_id = new_session_id
    if session:
        if not _append_option(args, help_text, "--resume", session, "-r"):
            raise RuntimeError("Grok CLI does not support required option: --resume")
        resume_used = True
        session_id = session
    else:
        if not _append_option(args, help_text, "--session-id", new_session_id, "-s"):
            raise RuntimeError("Grok CLI does not support required option: --session-id")

    if not _append_option(args, help_text, "--prompt-file", str(prompt_file)):
        raise RuntimeError("Grok CLI does not support required option: --prompt-file")
    return args, resume_used, session_id


def run_grok(
    prompt: str,
    timeout_seconds: int,
    project_root: Path,
    *,
    output_normalizer: Callable[[str], str] | None = None,
    output_validator: Callable[[str], str] | None = None,
    config_path: str | Path | None = None,
    env_prefix: str = "CODEX",
) -> subprocess.CompletedProcess[str]:
    prompt_text = str(prompt or "")
    if not prompt_text.strip():
        raise ValueError("prompt is required")
    project_root = Path(project_root).resolve()

    prefix = env_prefix.upper()
    config = _load_config(config_path, env_prefix=env_prefix)
    command_env = f"{prefix}_GROK_CMD"
    config_env = f"{prefix}_GROK_CONFIG"
    output_format_env = f"{prefix}_GROK_OUTPUT_FORMAT"
    permission_env = f"{prefix}_GROK_PERMISSION_MODE"
    sandbox_env = f"{prefix}_GROK_SANDBOX"
    post_output_grace_env = f"{prefix}_GROK_POST_OUTPUT_GRACE"
    model_env = f"{prefix}_GROK_MODEL"
    effort_env = f"{prefix}_GROK_EFFORT"

    selected_model = _config_text(config, "model", model_env)
    selected_effort = _config_text(config, "effort", effort_env)
    output_format = _config_text(config, "output_format", output_format_env, DEFAULT_OUTPUT_FORMAT) or DEFAULT_OUTPUT_FORMAT
    permission_mode = _config_text(config, "permission_mode", permission_env, DEFAULT_PERMISSION_MODE)
    sandbox = _config_text(config, "sandbox", sandbox_env, "")
    always_approve = _config_bool(config, "always_approve", f"{prefix}_GROK_ALWAYS_APPROVE", True)
    no_memory = _config_bool(config, "no_memory", f"{prefix}_GROK_NO_MEMORY", True)
    verbatim = _config_bool(config, "verbatim", f"{prefix}_GROK_VERBATIM", True)
    post_output_grace = _config_float(
        config,
        "post_output_grace_seconds",
        post_output_grace_env,
        DEFAULT_POST_OUTPUT_GRACE_SECONDS,
    )

    raw_command = str(os.getenv(command_env, "") or config.get("command") or DEFAULT_GROK_CMD)
    base_args, env_overrides = _split_cli_command(raw_command, [DEFAULT_GROK_CMD])
    resolved_exe = _resolve_executable(base_args[0])
    if not resolved_exe:
        raise FileNotFoundError(
            f"grok executable not found. {command_env}={os.getenv(command_env, '')!r}, "
            f"{config_env}={os.getenv(config_env, '')!r}, "
            f"binary={base_args[0]!r}, PATH={os.getenv('PATH', '')!r}."
        )
    base_args[0] = resolved_exe
    help_text = _probe_help(base_args, project_root, env_overrides)
    prompt_file: Path | None = None
    try:
        prompt_file = _write_prompt_file(prompt_text)
        command, _resume_used, session_id = _build_command(
            base_args,
            help_text=help_text,
            prompt_file=prompt_file,
            launch_dir=project_root,
            model=selected_model,
            effort=selected_effort,
            session=_config_text(config, "session", f"{prefix}_GROK_SESSION"),
            new_session_id=str(uuid.uuid4()),
            output_format=output_format,
            permission_mode=permission_mode,
            sandbox=sandbox,
            always_approve=always_approve,
            no_memory=no_memory,
            verbatim=verbatim,
        )

        child_env = os.environ.copy()
        child_env.update(env_overrides)
        session_completion_probe = _SessionCompletionProbe(
            _session_updates_path(project_root, session_id, child_env)
        )
        _emit_progress("[Grok mode]", "headless")
        _emit_progress("[Grok cwd]", project_root)
        _emit_progress("[Grok session]", session_id)
        proc, terminated_after_output, process_returncode, session_completion_seen = _stream_process(
            command,
            cwd=project_root,
            timeout_seconds=timeout_seconds,
            env=child_env,
            post_output_grace_seconds=post_output_grace,
            session_completion_probe=session_completion_probe.poll,
        )
    finally:
        if prompt_file is not None:
            prompt_file.unlink(missing_ok=True)

    streaming_json = _is_streaming_json_format(output_format)
    output_text = _extract_stream_text(proc.stdout, allow_fallback=not streaming_json).strip()
    end_event = _extract_end_event(proc.stdout)
    completion_signal_seen = bool(end_event) or session_completion_seen
    diagnostics = _tail_diagnostics(proc.stdout, proc.stderr)
    cleanup_after_completion = bool(terminated_after_output and completion_signal_seen)
    missing_completion_signal = bool(
        streaming_json and int(proc.returncode) == 0 and output_text and not completion_signal_seen
    )
    effective_returncode = 0 if cleanup_after_completion else int(proc.returncode)
    if missing_completion_signal or (effective_returncode == 0 and not output_text):
        effective_returncode = 1
    text = output_text if output_text else diagnostics

    normalized_stdout = output_normalizer(text) if output_normalizer else text
    validation_error = output_validator(normalized_stdout) if output_validator and normalized_stdout else ""
    if validation_error:
        return subprocess.CompletedProcess(command, 1, "", validation_error)
    if effective_returncode == 0 and normalized_stdout:
        return subprocess.CompletedProcess(command, 0, normalized_stdout, proc.stderr)

    if missing_completion_signal:
        diagnostics = "\n".join(
            part
            for part in (
                diagnostics,
                "Grok CLI did not emit a streaming-json or session-file completion signal.",
            )
            if part
        )
    if terminated_after_output and not cleanup_after_completion:
        diagnostics = "\n".join(part for part in (diagnostics, f"Grok CLI stalled; process_returncode={process_returncode}.") if part)
    return subprocess.CompletedProcess(command, effective_returncode, text, diagnostics)
