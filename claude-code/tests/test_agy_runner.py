from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = ROOT / "skills" / "shared" / "scripts"
if str(SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPTS))

import agy_runner


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


if __name__ == "__main__":
    unittest.main()
