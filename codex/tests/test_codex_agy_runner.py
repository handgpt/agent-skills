from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import textwrap
import time
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import sys


ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = ROOT.parent / "common" / "scripts"


def _load_runner_module() -> tuple[object, object]:
    shared_path = str(SHARED_SCRIPTS)
    previous_path = list(sys.path)
    previous_advisory_common = sys.modules.get("advisory_common")
    if shared_path in sys.path:
        sys.path.remove(shared_path)
    sys.path.insert(0, shared_path)
    sys.modules.pop("advisory_common", None)
    try:
        spec = importlib.util.spec_from_file_location(
            "codex_agy_runner_under_test",
            SHARED_SCRIPTS / "agy_runner.py",
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not load Codex agy_runner test module")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module.configure_platform(module.CODEX_AGY_PLATFORM)
        advisory_module = sys.modules["advisory_common"]
        return module, advisory_module
    finally:
        sys.path[:] = previous_path
        if previous_advisory_common is None:
            sys.modules.pop("advisory_common", None)
        else:
            sys.modules["advisory_common"] = previous_advisory_common


agy_runner, advisory_common = _load_runner_module()


class AgyRunnerTests(unittest.TestCase):
    def test_build_command_adds_default_model_and_workspace_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            extra_dir = root / "extra"
            extra_dir.mkdir()
            help_text = "\n".join(
                [
                    "--add-dir",
                    "--dangerously-skip-permissions",
                    "--log-file",
                    "--model",
                    "--print",
                    "--print-timeout",
                ]
            )
            command = agy_runner._build_command(
                ["agy", "--model", "old-model", "-p", "old prompt"],
                help_text=help_text,
                prompt='line 1\nline "2"',
                print_timeout="1200s",
                log_file=str(root / "agy.log"),
                model=agy_runner.DEFAULT_AGY_MODEL,
                add_dirs=(extra_dir,),
            )

        self.assertIn("-p", command)
        self.assertIn("--print-timeout", command)
        self.assertIn("1200s", command)
        self.assertEqual(command[command.index("--model") + 1], "Gemini 3.5 Flash (High)")
        self.assertEqual(command[command.index("--add-dir") + 1], str(extra_dir.resolve()))
        self.assertIn("--dangerously-skip-permissions", command)
        self.assertIn("--log-file", command)
        self.assertNotIn("old-model", command)
        self.assertEqual(command[-1], 'line 1\nline "2"')

    def test_build_command_uses_interactive_mode_without_print_timeout(self) -> None:
        command = agy_runner._build_command(
            ["agy", "--print", "old prompt"],
            help_text="--print-timeout\n--dangerously-skip-permissions\n--log-file\n-i, --prompt-interactive",
            prompt="prompt",
            mode="interactive",
            print_timeout="1200s",
            log_file="/tmp/agy.log",
            model=agy_runner.DEFAULT_AGY_MODEL,
        )

        self.assertIn("-i", command)
        self.assertNotIn("-p", command)
        self.assertNotIn("--print", command)
        self.assertNotIn("--print-timeout", command)
        self.assertEqual(command[-1], "prompt")

    def test_build_command_drops_unsupported_managed_flags(self) -> None:
        command = agy_runner._build_command(
            [
                "agy",
                "--dangerously-skip-permissions",
                "--print-timeout",
                "10s",
                "--add-dir",
                "/tmp/old-extra",
            ],
            help_text="--log-file\n-i, --prompt-interactive",
            prompt="prompt",
            mode="interactive",
            print_timeout="1200s",
            log_file="/tmp/agy.log",
            model=agy_runner.DEFAULT_AGY_MODEL,
        )

        self.assertNotIn("--dangerously-skip-permissions", command)
        self.assertNotIn("--print-timeout", command)
        self.assertNotIn("10s", command)
        self.assertNotIn("--add-dir", command)
        self.assertNotIn("/tmp/old-extra", command)
        self.assertIn("-i", command)

    def test_probe_help_uses_full_base_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            fake_cli = root / "fake_cli.py"
            fake_cli.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import sys

                    if sys.argv[1:] == ["run", "agy", "--help"]:
                        print("--model\\n--add-dir")
                    else:
                        print("wrong command")
                    """
                ),
                encoding="utf-8",
            )
            fake_cli.chmod(0o755)

            help_text = agy_runner._probe_help([sys.executable, str(fake_cli), "run", "agy"], root, {})

        self.assertIn("--model", help_text)
        self.assertIn("--add-dir", help_text)
        self.assertNotIn("wrong command", help_text)

    def test_default_mode_is_interactive(self) -> None:
        self.assertEqual(agy_runner.DEFAULT_MODE, "interactive")

    def test_mode_can_be_loaded_from_config_or_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "agy_cli.json"
            config_path.write_text(
                json.dumps({"mode": "interactive", "command": "~/.local/bin/agy"}),
                encoding="utf-8",
            )

            config = agy_runner._load_config(config_path)
            self.assertEqual(agy_runner._normalize_mode(agy_runner._config_text(config, "mode")), "interactive")
            self.assertEqual(agy_runner._base_command(config=config)[0], ["~/.local/bin/agy"])

            with patch.dict(os.environ, {"CODEX_AGY_MODE": "print"}):
                self.assertEqual(
                    agy_runner._normalize_mode(
                        agy_runner._config_text(config, "mode", agy_runner.AGY_MODE_ENV_VAR)
                    ),
                    "print",
                )

    def test_configured_model_rejects_unsupported_values(self) -> None:
        with patch.dict(os.environ, {"CODEX_AGY_MODEL": "Gemini 3.5 Flash (Low)"}):
            with self.assertRaisesRegex(ValueError, "Unsupported Antigravity model"):
                agy_runner._configured_agy_model({})

    def test_configure_platform_refreshes_derived_globals(self) -> None:
        try:
            agy_runner.configure_platform(agy_runner.CLAUDE_CODE_AGY_PLATFORM)
            self.assertEqual(agy_runner.DEFAULT_MODE, "print")
            self.assertEqual(agy_runner.DEFAULT_CONFIG_PATH, "~/.claude/agy_cli.json")
            self.assertEqual(agy_runner.AGY_CMD_ENV_VAR, "CLAUDE_AGY_CMD")
            self.assertEqual(agy_runner.AGY_MODEL_ENV_VAR, "CLAUDE_AGY_MODEL")
            self.assertTrue(agy_runner.ENABLE_OUTPUT_FILE_ARGUMENT)
            self.assertTrue(
                any(action.dest == "output_file" for action in agy_runner.make_arg_parser("test")._actions)
            )

            agy_runner.configure_platform(agy_runner.CODEX_AGY_PLATFORM)
            self.assertEqual(agy_runner.DEFAULT_MODE, "interactive")
            self.assertEqual(agy_runner.DEFAULT_CONFIG_PATH, "~/.codex/agy_cli.json")
            self.assertEqual(agy_runner.AGY_CMD_ENV_VAR, "CODEX_AGY_CMD")
            self.assertEqual(agy_runner.AGY_MODEL_ENV_VAR, "CODEX_AGY_MODEL")
            self.assertFalse(agy_runner.ENABLE_OUTPUT_FILE_ARGUMENT)
            self.assertFalse(
                any(action.dest == "output_file" for action in agy_runner.make_arg_parser("test")._actions)
            )
        finally:
            agy_runner.configure_platform(agy_runner.CODEX_AGY_PLATFORM)

    def test_project_add_dirs_excludes_primary_root_and_missing_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project_a = root / "a"
            project_b = root / "b"
            missing = root / "missing"
            project_a.mkdir()
            project_b.mkdir()

            self.assertEqual(
                agy_runner._project_add_dirs(root, (project_a, project_b, missing, project_a)),
                (project_a.resolve(), project_b.resolve()),
            )

    def test_run_print_returns_terminal_log_failure_after_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            fake_agy = root / "fake_agy.py"
            fake_agy.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import pathlib
                    import sys

                    args = sys.argv[1:]
                    log_path = pathlib.Path(args[args.index("--log-file") + 1])
                    log_path.write_text(
                        "Created conversation 33333333-3333-3333-3333-333333333333\\n"
                        "agent executor error: RESOURCE_EXHAUSTED: Individual quota reached\\n",
                        encoding="utf-8",
                    )
                    """
                ),
                encoding="utf-8",
            )
            fake_agy.chmod(0o755)
            log_path = root / "agy.log"

            result = agy_runner._run_print(
                [str(fake_agy), "--log-file", str(log_path), "-p", "prompt"],
                cwd=root,
                env=os.environ.copy(),
                timeout_seconds=5,
                start_dt=datetime.now(),
                start_epoch=time.time(),
                prompt_text="prompt",
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("RESOURCE_EXHAUSTED", result.stderr)

    def test_latest_model_text_reads_last_done_model_record(self) -> None:
        records = [
            {"source": "MODEL", "status": "STREAMING", "content": "draft"},
            {"source": "USER", "status": "DONE", "content": "prompt"},
            {"source": "MODEL", "status": "DONE", "content": "final"},
        ]

        self.assertEqual(agy_runner._latest_model_text(records), "final")

    def test_latest_run_model_text_ignores_tool_planner_records(self) -> None:
        start_epoch = datetime(2026, 5, 20, 0, 0, tzinfo=timezone.utc).timestamp()
        records = [
            {
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "status": "DONE",
                "created_at": "2026-05-20T00:00:01Z",
                "content": "prompt",
            },
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "tool_calls": [{"name": "view_file"}],
                "created_at": "2026-05-20T00:00:02Z",
                "content": "I will inspect files",
            },
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "created_at": "2026-05-20T00:00:03Z",
                "content": "final review",
            },
        ]

        self.assertEqual(
            agy_runner._latest_run_model_text(records, "prompt", start_epoch),
            "final review",
        )

    def test_latest_run_model_text_allows_reasonable_server_clock_skew(self) -> None:
        start_epoch = datetime(2026, 5, 20, 0, 5, tzinfo=timezone.utc).timestamp()
        records = [
            {
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "status": "DONE",
                "created_at": "2026-05-20T00:01:00Z",
                "content": "same prompt",
            },
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "created_at": "2026-05-20T00:01:10Z",
                "content": "current final",
            },
        ]

        self.assertEqual(
            agy_runner._latest_run_model_text(records, "same prompt", start_epoch),
            "current final",
        )

    def test_latest_run_model_text_rejects_recent_duplicate_when_transcript_is_stale(self) -> None:
        start_epoch = datetime(2026, 5, 20, 0, 5, tzinfo=timezone.utc).timestamp()
        records = [
            {
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "status": "DONE",
                "created_at": "2026-05-20T00:04:00Z",
                "content": "same prompt",
            },
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "created_at": "2026-05-20T00:04:20Z",
                "content": "previous final",
            },
        ]

        self.assertEqual(
            agy_runner._latest_run_model_text(
                records,
                "same prompt",
                start_epoch,
                transcript_epoch=start_epoch - 30,
            ),
            "",
        )

    def test_latest_run_model_text_ignores_records_before_current_run_baseline(self) -> None:
        start_epoch = datetime(2026, 5, 20, 0, 5, tzinfo=timezone.utc).timestamp()
        records = [
            {
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "status": "DONE",
                "created_at": "2026-05-20T00:04:00Z",
                "content": "same prompt",
            },
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "created_at": "2026-05-20T00:04:20Z",
                "content": "previous final",
            },
        ]

        self.assertEqual(
            agy_runner._latest_run_model_text(
                records,
                "same prompt",
                start_epoch,
                transcript_epoch=start_epoch,
                min_record_index=len(records),
            ),
            "",
        )

    def test_latest_run_model_text_rejects_stale_duplicate_prompt(self) -> None:
        start_epoch = datetime(2026, 5, 20, 0, 10, tzinfo=timezone.utc).timestamp()
        records = [
            {
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "status": "DONE",
                "created_at": "2026-05-19T23:50:00Z",
                "content": "same prompt",
            },
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "created_at": "2026-05-19T23:50:10Z",
                "content": "stale final",
            },
        ]

        self.assertEqual(
            agy_runner._latest_run_model_text(records, "same prompt", start_epoch),
            "",
        )

    def test_record_epoch_treats_naive_iso_timestamp_as_utc(self) -> None:
        self.assertEqual(
            agy_runner._record_epoch({"created_at": "2026-05-20T00:00:00"}),
            datetime(2026, 5, 20, 0, 0, tzinfo=timezone.utc).timestamp(),
        )

    def test_record_epoch_honors_explicit_timezone_offset(self) -> None:
        self.assertEqual(
            agy_runner._record_epoch({"created_at": "2026-05-20T08:00:00+08:00"}),
            datetime(2026, 5, 20, 0, 0, tzinfo=timezone.utc).timestamp(),
        )

    @unittest.skipIf(agy_runner.pty is None, "Requires POSIX PTY support")
    def test_run_interactive_reads_transcript_and_requests_quit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            fake_agy = root / "fake_agy.py"
            fake_agy.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import json
                    import os
                    import pathlib
                    import select
                    import sys
                    import time

                    args = sys.argv[1:]
                    log_path = pathlib.Path(args[args.index("--log-file") + 1])
                    prompt = args[-1]
                    conversation_id = "11111111-1111-1111-1111-111111111111"
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    log_path.write_text(f"Created conversation {conversation_id}\\n", encoding="utf-8")

                    transcript_path = (
                        pathlib.Path(os.environ["HOME"])
                        / ".gemini"
                        / "antigravity-cli"
                        / "brain"
                        / conversation_id
                        / ".system_generated"
                        / "logs"
                        / "transcript.jsonl"
                    )
                    transcript_path.parent.mkdir(parents=True, exist_ok=True)
                    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    records = [
                        {
                            "step_index": 0,
                            "source": "USER_EXPLICIT",
                            "type": "USER_INPUT",
                            "status": "DONE",
                            "created_at": now,
                            "content": prompt,
                        },
                        {
                            "step_index": 1,
                            "source": "MODEL",
                            "type": "PLANNER_RESPONSE",
                            "status": "DONE",
                            "created_at": now,
                            "content": "final review",
                        },
                    ]
                    transcript_path.write_text(
                        "\\n".join(json.dumps(record) for record in records) + "\\n",
                        encoding="utf-8",
                    )
                    deadline = time.time() + 3
                    while time.time() < deadline:
                        ready, _, _ = select.select([sys.stdin], [], [], 0.1)
                        if ready and "/quit" in sys.stdin.readline():
                            break
                    """
                ),
                encoding="utf-8",
            )
            fake_agy.chmod(0o755)
            log_path = root / "agy.log"
            prompt = "prompt"
            env = os.environ.copy()
            env["HOME"] = str(root)
            start_dt = datetime.now()
            start_epoch = time.time()

            with patch.dict(os.environ, {"HOME": str(root)}):
                result = agy_runner._run_interactive(
                    [str(fake_agy), "--log-file", str(log_path), "-i", prompt],
                    cwd=root,
                    env=env,
                    timeout_seconds=5,
                    start_dt=start_dt,
                    start_epoch=start_epoch,
                    prompt_text=prompt,
                )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "final review")

    @unittest.skipIf(agy_runner.pty is None, "Requires POSIX PTY support")
    def test_run_interactive_returns_terminal_log_failure_without_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            fake_agy = root / "fake_agy.py"
            fake_agy.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import pathlib
                    import select
                    import sys
                    import time

                    args = sys.argv[1:]
                    log_path = pathlib.Path(args[args.index("--log-file") + 1])
                    conversation_id = "22222222-2222-2222-2222-222222222222"
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    log_path.write_text(f"Created conversation {conversation_id}\\n", encoding="utf-8")
                    time.sleep(0.2)
                    with log_path.open("a", encoding="utf-8") as handle:
                        handle.write("agent executor error: RESOURCE_EXHAUSTED: Individual quota reached\\n")
                    deadline = time.time() + 5
                    while time.time() < deadline:
                        ready, _, _ = select.select([sys.stdin], [], [], 0.1)
                        if ready and "/quit" in sys.stdin.readline():
                            break
                    """
                ),
                encoding="utf-8",
            )
            fake_agy.chmod(0o755)
            log_path = root / "agy.log"
            env = os.environ.copy()
            env["HOME"] = str(root)

            started = time.monotonic()
            with (
                patch.dict(os.environ, {"HOME": str(root)}),
                patch.object(agy_runner, "AGY_POLL_SECONDS", 0.05),
                patch.object(agy_runner, "AGY_SHUTDOWN_GRACE_SECONDS", 0.1),
            ):
                result = agy_runner._run_interactive(
                    [str(fake_agy), "--log-file", str(log_path), "-i", "prompt"],
                    cwd=root,
                    env=env,
                    timeout_seconds=5,
                    start_dt=datetime.now(),
                    start_epoch=time.time(),
                    prompt_text="prompt",
                )

        self.assertEqual(result.returncode, 1)
        self.assertIn("RESOURCE_EXHAUSTED", result.stderr)
        self.assertLess(time.monotonic() - started, 2)

    def test_interactive_mode_reports_non_posix_platform(self) -> None:
        cwd = Path.cwd()
        with patch.object(agy_runner.os, "name", "nt"):
            result = agy_runner._run_interactive(
                ["agy", "-i", "prompt"],
                cwd=cwd,
                env=os.environ.copy(),
                timeout_seconds=1,
                start_dt=datetime.now(),
                start_epoch=time.time(),
                prompt_text="prompt",
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("POSIX PTY", result.stderr)

    @unittest.skipIf(agy_runner.pty is None, "Requires POSIX PTY support")
    def test_launch_interactive_cleans_up_when_set_blocking_fails(self) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.terminated = False
                self.waited = False
                self.killed = False

            def poll(self) -> int | None:
                return 0 if self.terminated else None

            def terminate(self) -> None:
                self.terminated = True

            def wait(self, timeout: float | None = None) -> int:
                self.waited = True
                raise RuntimeError("wait failed")

            def kill(self) -> None:
                self.killed = True
                self.terminated = True

        master_fd, slave_fd = os.pipe()
        fake_process = FakeProcess()

        with (
            patch.object(agy_runner.pty, "openpty", return_value=(master_fd, slave_fd)),
            patch.object(agy_runner.subprocess, "Popen", return_value=fake_process),
            patch.object(agy_runner.os, "set_blocking", side_effect=OSError("boom")),
        ):
            with self.assertRaises(OSError):
                agy_runner._launch_interactive(["agy", "-i", "prompt"], Path.cwd(), os.environ.copy())

        self.assertTrue(fake_process.terminated)
        self.assertTrue(fake_process.waited)
        for fd in (master_fd, slave_fd):
            with self.assertRaises(OSError):
                os.fstat(fd)

    @unittest.skipIf(agy_runner.pty is None, "Requires POSIX PTY support")
    def test_interactive_start_state_closes_launch_when_log_setup_fails(self) -> None:
        class ExitedProcess:
            def poll(self) -> int:
                return 0

        master_fd, slave_fd = os.pipe()
        os.close(slave_fd)

        with (
            patch.object(agy_runner, "_launch_interactive", return_value=(ExitedProcess(), master_fd)),
            patch.object(agy_runner, "_interactive_log_path", side_effect=OSError("boom")),
        ):
            with self.assertRaises(OSError):
                agy_runner._build_interactive_start_state(
                    ["agy", "-i", "prompt"],
                    cwd=Path.cwd(),
                    env=os.environ.copy(),
                    start_dt=datetime.now(),
                )

        with self.assertRaises(OSError):
            os.fstat(master_fd)

    def test_close_interactive_closes_fd_when_poll_is_interrupted(self) -> None:
        class InterruptingProcess:
            def poll(self) -> int | None:
                raise KeyboardInterrupt()

        master_fd, slave_fd = os.pipe()
        os.close(slave_fd)

        agy_runner._close_interactive(InterruptingProcess(), master_fd)

        with self.assertRaises(OSError):
            os.fstat(master_fd)

    def test_loader_restores_advisory_common_module_cache(self) -> None:
        sentinel = types.ModuleType("advisory_common")
        previous = sys.modules.get("advisory_common")
        sys.modules["advisory_common"] = sentinel
        try:
            _module, loaded_common = _load_runner_module()
            self.assertIs(sys.modules["advisory_common"], sentinel)
            self.assertIsNot(loaded_common, sentinel)
        finally:
            if previous is None:
                sys.modules.pop("advisory_common", None)
            else:
                sys.modules["advisory_common"] = previous

    def test_auth_failure_detection_requires_no_transcript_state(self) -> None:
        self.assertTrue(
            agy_runner._is_auth_failure(
                "Authentication required. Error: authentication timed out.",
                "",
                [],
            )
        )
        self.assertFalse(
            agy_runner._is_auth_failure(
                "Authentication required.",
                "conversation-id",
                [],
            )
        )

    def test_log_auth_failure_reads_antigravity_login_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "agy.log"
            log_path.write_text(
                "Failed to get OAuth token: error getting token source: "
                "You are not logged into Antigravity.",
                encoding="utf-8",
            )

            self.assertIn("not logged", agy_runner._log_auth_failure(log_path))

    def test_log_terminal_failure_ignores_transient_login_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "agy.log"
            log_path.write_text(
                "Failed to get OAuth token: error getting token source: "
                "You are not logged into Antigravity.",
                encoding="utf-8",
            )
            self.assertEqual(agy_runner._log_terminal_failure(log_path), "")

            log_path.write_text(
                "agent executor error: RESOURCE_EXHAUSTED: Individual quota reached",
                encoding="utf-8",
            )
            self.assertIn("RESOURCE_EXHAUSTED", agy_runner._log_terminal_failure(log_path))

    def test_load_transcript_salvages_prior_records_before_partial_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "transcript.jsonl"
            path.write_text(
                json.dumps({"source": "MODEL", "status": "DONE", "content": "ok"})
                + "\n"
                + '{"source": "MODEL", "status"',
                encoding="utf-8",
            )

            records = agy_runner._load_transcript(path)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["content"], "ok")

    def test_shared_prompt_can_name_antigravity_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            prompt = advisory_common.build_prompt(
                project_root,
                "brief",
                [],
                lane="review",
                focus_root=project_root,
                role_line="role",
                output_contract="contract",
                runner_name="Antigravity CLI",
            )

        self.assertIn("inside Antigravity CLI", prompt)
        self.assertNotIn("inside Gemini CLI", prompt)


if __name__ == "__main__":
    unittest.main()
