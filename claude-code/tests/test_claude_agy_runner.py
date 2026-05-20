from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = ROOT / "skills" / "shared" / "scripts"


def _load_runner_module() -> object:
    shared_path = str(SHARED_SCRIPTS)
    previous_path = list(sys.path)
    previous_advisory_common = sys.modules.get("advisory_common")
    if shared_path in sys.path:
        sys.path.remove(shared_path)
    sys.path.insert(0, shared_path)
    sys.modules.pop("advisory_common", None)
    try:
        spec = importlib.util.spec_from_file_location(
            "claude_code_agy_runner_under_test",
            SHARED_SCRIPTS / "agy_runner.py",
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not load Claude Code agy_runner test module")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = previous_path
        if previous_advisory_common is None:
            sys.modules.pop("advisory_common", None)
        else:
            sys.modules["advisory_common"] = previous_advisory_common


agy_runner = _load_runner_module()


class ClaudeAgyRunnerTests(unittest.TestCase):
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

    def test_output_file_excludes_progress_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            brief_path = root / "brief.md"
            output_path = root / "review.md"
            brief_path.write_text("brief", encoding="utf-8")

            def fake_inner(**_kwargs: object) -> int:
                agy_runner._emit_progress("[Antigravity step]", "progress")
                agy_runner._emit_wait_progress(10, 0, 100, -1)
                print("final advisory")
                return 0

            progress = io.StringIO()
            with (
                patch.object(agy_runner, "_run_advisory_inner", side_effect=fake_inner),
                contextlib.redirect_stderr(progress),
            ):
                exit_code = agy_runner.run_advisory(
                    description="review",
                    role_line="role",
                    label="review",
                    lane="review",
                    output_contract="contract",
                    argv=[
                        "--brief-file",
                        str(brief_path),
                        "--output-file",
                        str(output_path),
                    ],
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "final advisory\n")
            self.assertIn("[Antigravity step] progress", progress.getvalue())
            self.assertIn("[Antigravity wait] 10% (10s/100s)", progress.getvalue())

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
    def test_launch_interactive_cleans_up_when_set_blocking_fails(self) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.terminated = False
                self.waited = False

            def poll(self) -> int | None:
                return 0 if self.terminated else None

            def terminate(self) -> None:
                self.terminated = True

            def wait(self, timeout: float | None = None) -> int:
                self.waited = True
                raise RuntimeError("wait failed")

            def kill(self) -> None:
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
            _load_runner_module()
            self.assertIs(sys.modules["advisory_common"], sentinel)
        finally:
            if previous is None:
                sys.modules.pop("advisory_common", None)
            else:
                sys.modules["advisory_common"] = previous


if __name__ == "__main__":
    unittest.main()
