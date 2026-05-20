from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys


ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = ROOT / "skills" / "shared" / "scripts"
if str(SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPTS))

import agy_runner
import gemini_runner


class AgyRunnerTests(unittest.TestCase):
    def test_build_command_uses_print_mode_without_model_flag(self) -> None:
        command = agy_runner._build_command(
            ["agy", "--model", "old-model", "-p", "old prompt"],
            help_text="--print-timeout\n--dangerously-skip-permissions\n--log-file\n-p, --print",
            prompt='line 1\nline "2"',
            print_timeout="1200s",
            log_file="/tmp/agy.log",
        )

        self.assertIn("-p", command)
        self.assertIn("--print-timeout", command)
        self.assertIn("1200s", command)
        self.assertIn("--dangerously-skip-permissions", command)
        self.assertIn("--log-file", command)
        self.assertIn("/tmp/agy.log", command)
        self.assertNotIn("--model", command)
        self.assertNotIn("old-model", command)
        self.assertEqual(command[-1], 'line 1\nline "2"')

    def test_latest_model_text_reads_last_done_model_record(self) -> None:
        records = [
            {"source": "MODEL", "status": "STREAMING", "content": "draft"},
            {"source": "USER", "status": "DONE", "content": "prompt"},
            {"source": "MODEL", "status": "DONE", "content": "final"},
        ]

        self.assertEqual(agy_runner._latest_model_text(records), "final")

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
            prompt = gemini_runner.build_prompt(
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
