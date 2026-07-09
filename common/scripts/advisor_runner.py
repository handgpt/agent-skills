#!/usr/bin/env python3
"""Provider-routed advisory runner used by agent advisory skills."""
from __future__ import annotations

import argparse
import errno
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import advisory_common
import agy_runner
import grok_runner


MAX_OUTPUT_CHARS = 12000
DEFAULT_PROVIDER = "agy"


@dataclass(frozen=True)
class AdvisorPlatformConfig:
    name: str
    env_prefix: str
    home_env_var: str
    default_config_path: str
    agy_platform: agy_runner.AgyPlatformConfig
    enable_output_file: bool = False


CODEX_ADVISOR_PLATFORM = AdvisorPlatformConfig(
    name="Codex",
    env_prefix="CODEX",
    home_env_var="CODEX_HOME",
    default_config_path="~/.codex/advisor_cli.json",
    agy_platform=agy_runner.CODEX_AGY_PLATFORM,
)
CLAUDE_CODE_ADVISOR_PLATFORM = AdvisorPlatformConfig(
    name="Claude Code",
    env_prefix="CLAUDE",
    home_env_var="CLAUDE_HOME",
    default_config_path="~/.claude/advisor_cli.json",
    agy_platform=agy_runner.CLAUDE_CODE_AGY_PLATFORM,
    enable_output_file=True,
)

_PLATFORM = CODEX_ADVISOR_PLATFORM
DEFAULT_CONFIG_PATH = _PLATFORM.default_config_path
ADVISOR_HOME_ENV_VAR = _PLATFORM.home_env_var
ADVISOR_CONFIG_ENV_VAR = f"{_PLATFORM.env_prefix}_ADVISOR_CONFIG"
ADVISOR_PROVIDER_ENV_VAR = f"{_PLATFORM.env_prefix}_ADVISOR_PROVIDER"
ENABLE_OUTPUT_FILE_ARGUMENT = _PLATFORM.enable_output_file


def configure_platform(config: AdvisorPlatformConfig) -> None:
    """Configure platform-specific defaults for the current runner process."""
    global _PLATFORM
    global DEFAULT_CONFIG_PATH, ADVISOR_HOME_ENV_VAR, ADVISOR_CONFIG_ENV_VAR
    global ADVISOR_PROVIDER_ENV_VAR, ENABLE_OUTPUT_FILE_ARGUMENT

    _PLATFORM = config
    DEFAULT_CONFIG_PATH = config.default_config_path
    ADVISOR_HOME_ENV_VAR = config.home_env_var
    ADVISOR_CONFIG_ENV_VAR = f"{config.env_prefix}_ADVISOR_CONFIG"
    ADVISOR_PROVIDER_ENV_VAR = f"{config.env_prefix}_ADVISOR_PROVIDER"
    ENABLE_OUTPUT_FILE_ARGUMENT = config.enable_output_file
    agy_runner.configure_platform(config.agy_platform)


def _config_path(config_path: str | Path | None = None) -> Path:
    raw = str(config_path or os.getenv(ADVISOR_CONFIG_ENV_VAR, "")).strip()
    if not raw:
        platform_home = os.getenv(ADVISOR_HOME_ENV_VAR, "").strip()
        raw = str(Path(platform_home) / "advisor_cli.json") if platform_home else DEFAULT_CONFIG_PATH
    return Path(os.path.expandvars(os.path.expanduser(raw))).resolve()


def _load_config(config_path: str | Path | None = None) -> dict[str, object]:
    path = _config_path(config_path)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        print(f"[Advisor config] ignored unreadable config: {advisory_common._tilde_path(path)}", file=sys.stderr)
        return {}
    return payload if isinstance(payload, dict) else {}


def _config_text(
    config: dict[str, object],
    key: str,
    env_name: str = "",
    default: str = "",
) -> str:
    if env_name:
        raw_env = os.getenv(env_name, "").strip()
        if raw_env:
            return raw_env
    value = config.get(key)
    if value is None:
        return default
    return str(value).strip()


def normalize_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower().replace("_", "-")
    if normalized in {"", "agy", "antigravity", "antigravity-cli"}:
        return "agy"
    if normalized in {"grok", "grok-cli", "grok-build", "grokbuild"}:
        return "grok"
    raise ValueError(f"Unsupported advisor provider: {provider!r}. Allowed values: agy, grok")


def _provider_label(provider: str) -> str:
    return "Antigravity CLI" if provider == "agy" else "Grok CLI"


def _provider_config_path(config: dict[str, object], provider: str) -> str:
    nested_key = f"{provider}_config"
    raw = _config_text(config, nested_key)
    return raw


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
        help="Optional local file or directory the advisor should treat as a high-priority starting point.",
    )
    parser.add_argument(
        "--provider",
        default="",
        help="Advisor provider override for this run. Supported values: agy, grok.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=agy_runner.DEFAULT_TIMEOUT_SECONDS,
        help=f"End-to-end advisory timeout in seconds. Default: {agy_runner.DEFAULT_TIMEOUT_SECONDS}.",
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
    """Run a routed external advisory pass end-to-end and return an exit code."""
    if (output_contract is None) == (output_contract_builder is None):
        raise ValueError("Provide exactly one of output_contract or output_contract_builder.")

    parser = make_arg_parser(description)
    if configure_parser is not None:
        configure_parser(parser)
    args = parser.parse_args(argv)

    output_handle = None
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    original_agy_progress_stream = agy_runner._PROGRESS_STREAM
    original_grok_progress_stream = grok_runner._PROGRESS_STREAM
    output_file = str(getattr(args, "output_file", "") or "").strip()
    if output_file:
        output_path = Path(output_file).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_handle = open(output_path, "w", encoding="utf-8", buffering=1)  # noqa: SIM115
        agy_runner._PROGRESS_STREAM = original_stderr
        grok_runner._PROGRESS_STREAM = original_stderr
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
        agy_runner._PROGRESS_STREAM = original_agy_progress_stream
        grok_runner._PROGRESS_STREAM = original_grok_progress_stream
        if output_handle is not None:
            output_handle.close()


def _run_provider(
    *,
    provider: str,
    prompt: str,
    timeout_seconds: int,
    project_root: Path,
    project_roots: tuple[Path, ...],
    output_normalizer: Callable[[str], str],
    output_validator: Callable[[str], str],
    config: dict[str, object],
) -> subprocess.CompletedProcess[str]:
    if provider == "agy":
        return agy_runner.run_agy(
            prompt,
            timeout_seconds,
            project_root,
            add_dirs=_project_add_dirs(project_root, project_roots),
            output_normalizer=output_normalizer,
            output_validator=output_validator,
            config_path=_provider_config_path(config, "agy") or None,
        )
    if provider == "grok":
        return grok_runner.run_grok(
            prompt,
            timeout_seconds,
            project_root,
            output_normalizer=output_normalizer,
            output_validator=output_validator,
            config_path=_provider_config_path(config, "grok") or None,
            env_prefix=_PLATFORM.env_prefix,
        )
    raise ValueError(f"Unsupported advisor provider: {provider!r}. Allowed values: agy, grok")


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

    config = _load_config()
    provider = normalize_provider(
        str(getattr(args, "provider", "") or "")
        or _config_text(config, "provider", ADVISOR_PROVIDER_ENV_VAR, DEFAULT_PROVIDER)
    )
    provider_label = _provider_label(provider)

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
        runner_name=provider_label,
    )
    output_normalizer = advisory_common.build_output_normalizer(resolved_output_contract)
    output_validator = advisory_common.build_output_validator(resolved_output_contract)

    try:
        result = _run_provider(
            provider=provider,
            prompt=prompt,
            timeout_seconds=args.timeout_seconds,
            project_root=project_root,
            project_roots=project_roots,
            output_normalizer=output_normalizer,
            output_validator=output_validator,
            config=config,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except subprocess.TimeoutExpired as exc:
        print(
            f"{provider_label} {label} timed out after {args.timeout_seconds} seconds total wait.",
            file=sys.stderr,
        )
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
                f"{provider_label} inline prompt is too large for this platform's command-line limit. "
                "Reduce the brief size.",
                file=sys.stderr,
            )
            return 5
        print(f"{provider_label} {label} failed to start: {exc}", file=sys.stderr)
        return 5

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if result.returncode != 0 or not stdout:
        print(f"{provider_label} {label} failed with exit code {result.returncode}.", file=sys.stderr)
        if stderr:
            print(stderr[:MAX_OUTPUT_CHARS], file=sys.stderr)
        if stdout:
            print(stdout[:MAX_OUTPUT_CHARS], file=sys.stderr)
        return 5

    print(stdout[:MAX_OUTPUT_CHARS])
    return 0
