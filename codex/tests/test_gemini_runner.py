from __future__ import annotations

import argparse
import errno
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = ROOT / "skills" / "shared" / "scripts"
if str(SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPTS))

import gemini_runner


class GeminiRunnerTests(unittest.TestCase):
    def test_noninteractive_command_defaults_to_pro_alias(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            command = gemini_runner._noninteractive_command(
                "gemini", "prompt", "session-1"
            )

        self.assertIn("--model", command)
        self.assertIn("pro", command)
        self.assertIn("--approval-mode", command)
        self.assertIn("yolo", command)
        self.assertIn("--output-format", command)
        self.assertIn("json", command)
        self.assertIn("--resume", command)
        self.assertIn("session-1", command)
        self.assertEqual(command[-1], "prompt")
        self.assertNotIn("-i", command)

    def test_noninteractive_command_respects_model_override_env(self) -> None:
        with mock.patch.dict(
            os.environ, {gemini_runner.GEMINI_MODEL_ENV_VAR: "gemini-2.5-pro"}, clear=True
        ):
            command = gemini_runner._noninteractive_command("gemini", "prompt", "")

        self.assertIn("--model", command)
        self.assertIn("gemini-2.5-pro", command)
        self.assertNotIn("--resume", command)

    def test_gemini_environment_disables_sandbox_for_full_access(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            env = gemini_runner._gemini_environment()

        self.assertEqual(env[gemini_runner.GEMINI_SANDBOX_ENV_VAR], "false")
        self.assertEqual(env["TERM"], "xterm-256color")
        self.assertEqual(env["COLORTERM"], "truecolor")

    def test_run_noninteractive_attempt_rewrites_e2big_with_actionable_message(
        self,
    ) -> None:
        project_root = Path(__file__).resolve().parent

        with mock.patch("gemini_runner.subprocess.run") as run_mock:
            run_mock.side_effect = OSError(errno.E2BIG, "Argument list too long")
            with self.assertRaises(OSError) as exc_info:
                gemini_runner._run_noninteractive_attempt(
                    ["gemini", "prompt"], 30, project_root
                )

        self.assertEqual(exc_info.exception.errno, errno.E2BIG)
        self.assertIn("Reduce the brief size", str(exc_info.exception))

    def test_lane_session_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                gemini_runner._remember_lane_session(project_root, "review", "session-1")
                self.assertEqual(
                    gemini_runner._saved_lane_session_id(project_root, "review"),
                    "session-1",
                )

    def test_describe_paths_filters_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "workspace"
            project_root.mkdir()
            inside_dir = project_root / "skills"
            inside_dir.mkdir()
            missing_inside = project_root / "missing.txt"
            outside_dir = Path(tmp_dir) / "outside"
            outside_dir.mkdir()

            entries = gemini_runner.describe_paths(
                [
                    str(inside_dir),
                    str(missing_inside),
                    str(outside_dir),
                ],
                project_root,
            )

            self.assertEqual(
                entries,
                [
                    f"- {inside_dir} [directory]",
                    f"- {missing_inside} [missing]",
                ],
            )

    def test_describe_paths_uses_workspace_relative_paths_under_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            inside_dir = project_root / "skills"
            missing_inside = project_root / "missing.txt"
            inside_dir.mkdir(parents=True)

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                entries = gemini_runner.describe_paths(
                    [str(inside_dir), str(missing_inside)],
                    project_root,
                )

            self.assertEqual(
                entries,
                [
                    "- skills [directory]",
                    "- missing.txt [missing]",
                ],
            )

    def test_describe_paths_ignores_blank_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "workspace"
            project_root.mkdir()

            entries = gemini_runner.describe_paths(["", "   "], project_root)

            self.assertEqual(entries, [])

    def test_describe_paths_keeps_only_explicit_context_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "workspace"
            feature_dir = project_root / "src" / "feature"
            feature_dir.mkdir(parents=True)
            target_file = feature_dir / "service.py"
            target_file.write_text("print('ok')\n", encoding="utf-8")

            entries = gemini_runner.describe_paths([str(target_file)], project_root)

            self.assertEqual(entries, [f"- {target_file} [file]"])

    def test_describe_paths_skips_symlink_to_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project_root = root / "workspace"
            project_root.mkdir()
            outside_file = root / "outside.txt"
            outside_file.write_text("outside", encoding="utf-8")
            linked_outside = project_root / "linked-outside.txt"
            linked_outside.symlink_to(outside_file)

            entries = gemini_runner.describe_paths([str(linked_outside)], project_root)

            self.assertEqual(entries, [])

    def test_extract_json_payload_accepts_wrapped_stdout(self) -> None:
        payload = gemini_runner._extract_json_payload(
            "banner line\n{\n  \"session_id\": \"s1\",\n  \"response\": \"ok\"\n}\n"
        )

        self.assertEqual(payload, {"session_id": "s1", "response": "ok"})

    def test_extract_json_payload_skips_earlier_non_payload_braces(self) -> None:
        payload = gemini_runner._extract_json_payload(
            'warning: saw placeholder {ignored}\n{"session_id":"s1","response":"ok"}\n'
        )

        self.assertEqual(payload, {"session_id": "s1", "response": "ok"})

    def test_parse_cli_result_reads_response_and_error(self) -> None:
        success = gemini_runner._parse_cli_result(
            mock.Mock(
                stdout='{"session_id":"s1","response":"done"}',
                stderr="",
            )
        )
        failure = gemini_runner._parse_cli_result(
            mock.Mock(
                stdout='{"session_id":"s1","error":{"type":"ApiError","code":"429","message":"Too Many Requests"}}',
                stderr="",
            )
        )

        self.assertEqual(success, ("s1", "done", ""))
        self.assertEqual(failure, ("s1", "", "ApiError: 429: Too Many Requests"))

    def test_resume_retry_marker_detection(self) -> None:
        self.assertTrue(
            gemini_runner._should_retry_resume(
                ["gemini", "--resume", "session"],
                "error: invalid session",
            )
        )
        self.assertFalse(
            gemini_runner._should_retry_resume(
                ["gemini", "--resume", "session"],
                "all good",
            )
        )
        self.assertFalse(
            gemini_runner._should_retry_resume(
                ["gemini"],
                "invalid session",
            )
        )

    def test_run_gemini_retries_without_resume_on_invalid_saved_session(self) -> None:
        project_root = Path("/workspace")
        invalid = subprocess.CompletedProcess(
            ["gemini"],
            1,
            '{"session_id":"old-session","error":{"message":"invalid session"}}',
            "",
        )
        success = subprocess.CompletedProcess(
            ["gemini"],
            0,
            '{"session_id":"new-session","response":"final answer"}',
            "",
        )

        with mock.patch("gemini_runner.shutil.which", return_value="/usr/bin/gemini"), mock.patch(
            "gemini_runner._saved_lane_session_id", return_value="old-session"
        ), mock.patch(
            "gemini_runner._run_noninteractive_attempt", side_effect=[invalid, success]
        ) as run_mock, mock.patch("gemini_runner._remember_lane_session") as remember_mock:
            result = gemini_runner.run_gemini(
                "prompt",
                30,
                project_root,
                lane="review",
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "final answer")
        self.assertEqual(run_mock.call_count, 2)
        remember_mock.assert_any_call(project_root, "review", "new-session")

    def test_build_prompt_hides_home_path_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                prompt = gemini_runner.build_prompt(
                    project_root,
                    '# Review Brief\n\nQuote: "hello"',
                    ["- codex/skills/shared/scripts/gemini_runner.py [file]"],
                    role_line="role",
                    output_contract="contract",
                )

            self.assertIn("- ~/workspace", prompt)
            self.assertIn("## Inlined Brief", prompt)
            self.assertIn('Quote: "hello"', prompt)
            self.assertNotIn(str(home), prompt)

    def test_noninteractive_command_preserves_quotes_and_newlines(self) -> None:
        prompt = 'line 1\nline "2"\nline 3'

        command = gemini_runner._noninteractive_command("gemini", prompt, "")

        self.assertEqual(command[-1], prompt)

    def test_noninteractive_command_prefixes_hyphen_led_prompts(self) -> None:
        command = gemini_runner._noninteractive_command("gemini", "- risky", "")

        self.assertEqual(command[-1], "\n- risky")

    def test_run_advisory_accepts_parser_extension_and_output_contract_builder(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            brief_path = project_root / "brief.md"
            brief_path.write_text("brief", encoding="utf-8")

            def configure_parser(parser: argparse.ArgumentParser) -> None:
                parser.add_argument(
                    "--mode", choices=("standard", "structural"), default="standard"
                )

            def build_prompt(
                project_root: Path,
                brief_text: str,
                context_entries: list[str],
                *,
                role_line: str,
                output_contract: str,
            ) -> str:
                self.assertEqual(brief_text, "brief")
                self.assertEqual(output_contract, "MODE=structural")
                return "assembled prompt"

            with mock.patch(
                "gemini_runner.detect_project_root", return_value=project_root
            ), mock.patch(
                "gemini_runner.describe_paths", return_value=[]
            ), mock.patch(
                "gemini_runner.build_prompt", side_effect=build_prompt
            ), mock.patch(
                "gemini_runner.run_gemini",
                return_value=mock.Mock(returncode=0, stdout="ok", stderr=""),
            ):
                exit_code = gemini_runner.run_advisory(
                    description="review",
                    role_line="role",
                    label="review",
                    lane="review",
                    configure_parser=configure_parser,
                    output_contract_builder=lambda args: f"MODE={args.mode}",
                    argv=["--brief-file", str(brief_path), "--mode", "structural"],
                )

            self.assertEqual(exit_code, 0)

    def test_run_advisory_returns_code_5_for_e2big(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            brief_path = project_root / "brief.md"
            brief_path.write_text("brief", encoding="utf-8")
            error = OSError(errno.E2BIG, gemini_runner.INLINE_PROMPT_TOO_LARGE_MESSAGE)

            with mock.patch(
                "gemini_runner.detect_project_root", return_value=project_root
            ), mock.patch(
                "gemini_runner.describe_paths", return_value=[]
            ), mock.patch(
                "gemini_runner.run_gemini", side_effect=error
            ), mock.patch(
                "sys.stderr", new_callable=io.StringIO
            ) as stderr:
                exit_code = gemini_runner.run_advisory(
                    description="review",
                    role_line="role",
                    label="review",
                    lane="review",
                    output_contract="contract",
                    argv=["--brief-file", str(brief_path)],
                )

            self.assertEqual(exit_code, 5)
            self.assertIn("Reduce the brief size", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
