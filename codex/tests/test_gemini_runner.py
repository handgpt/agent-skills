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


def _write_projects_registry(home: Path, project_root: Path, short_id: str) -> None:
    registry_path = home / ".gemini" / gemini_runner.GEMINI_PROJECTS_FILE
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps({"projects": {str(project_root.resolve()): short_id}}),
        encoding="utf-8",
    )


def _write_session_file(
    home: Path,
    short_id: str,
    filename: str,
    payload: dict[str, object],
    *,
    mtime: float | None = None,
) -> Path:
    chats_dir = home / ".gemini" / gemini_runner.GEMINI_TMP_DIRNAME / short_id / "chats"
    chats_dir.mkdir(parents=True, exist_ok=True)
    path = chats_dir / filename
    path.write_text(json.dumps(payload), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


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

    def test_interactive_command_defaults_to_pro_alias(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            command = gemini_runner._interactive_command(
                "gemini", 'line 1\nline "2"', "session-2"
            )

        self.assertIn("--model", command)
        self.assertIn("pro", command)
        self.assertIn("--approval-mode", command)
        self.assertIn("yolo", command)
        self.assertIn("--resume", command)
        self.assertIn("session-2", command)
        self.assertIn("-i", command)
        self.assertNotIn("--output-format", command)
        self.assertEqual(command[-1], 'line 1\nline "2"')

    def test_safe_prompt_argument_prefixes_hyphen_led_prompt(self) -> None:
        self.assertEqual(gemini_runner._safe_prompt_argument("- risky"), "\n- risky")

    def test_configured_run_mode_defaults_to_interactive(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(gemini_runner.configured_run_mode(), "interactive")

    def test_configured_run_mode_respects_override(self) -> None:
        with mock.patch.dict(
            os.environ, {gemini_runner.GEMINI_RUN_MODE_ENV_VAR: "headless"}, clear=True
        ):
            self.assertEqual(gemini_runner.configured_run_mode(), "headless")
            self.assertEqual(gemini_runner.configured_run_mode("interactive"), "interactive")

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
                [str(inside_dir), str(missing_inside), str(outside_dir)],
                project_root,
            )

            self.assertEqual(
                entries,
                [f"- {inside_dir} [directory]", f"- {missing_inside} [missing]"],
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

            self.assertEqual(entries, ["- skills [directory]", "- missing.txt [missing]"])

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

    def test_parse_cli_result_reads_response_and_error(self) -> None:
        success = gemini_runner._parse_cli_result(
            mock.Mock(stdout='{"session_id":"s1","response":"done"}', stderr="")
        )
        failure = gemini_runner._parse_cli_result(
            mock.Mock(
                stdout='{"session_id":"s1","error":{"type":"ApiError","code":"429","message":"Too Many Requests"}}',
                stderr="",
            )
        )

        self.assertEqual(success, ("s1", "done", ""))
        self.assertEqual(failure, ("s1", "", "ApiError: 429: Too Many Requests"))

    def test_project_short_id_reads_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            _write_projects_registry(home, project_root, "proj-1")

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                self.assertEqual(gemini_runner._project_short_id(project_root), "proj-1")

    def test_project_short_id_falls_back_to_marker_when_registry_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            wrong_owner = home / "other-workspace"
            wrong_owner.mkdir()
            _write_projects_registry(home, project_root, "proj-1")
            marker_dir = home / ".gemini" / gemini_runner.GEMINI_TMP_DIRNAME / "proj-1"
            marker_dir.mkdir(parents=True, exist_ok=True)
            (marker_dir / gemini_runner.PROJECT_ROOT_MARKER_FILE).write_text(
                str(wrong_owner.resolve()),
                encoding="utf-8",
            )
            recovered_dir = (
                home / ".gemini" / gemini_runner.GEMINI_HISTORY_DIRNAME / "workspace"
            )
            recovered_dir.mkdir(parents=True, exist_ok=True)
            (recovered_dir / gemini_runner.PROJECT_ROOT_MARKER_FILE).write_text(
                str(project_root.resolve()),
                encoding="utf-8",
            )

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                self.assertEqual(
                    gemini_runner._project_short_id(project_root), "workspace"
                )

    def test_latest_session_file_for_id_prefers_newest_matching_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            _write_projects_registry(home, project_root, "proj-1")
            older = {
                "sessionId": "session-a",
                "lastUpdated": "2026-03-20T01:00:00Z",
                "startTime": "2026-03-20T00:59:00Z",
                "messages": [],
            }
            newer = {
                "sessionId": "session-a",
                "lastUpdated": "2026-03-20T02:00:00Z",
                "startTime": "2026-03-20T01:59:00Z",
                "messages": [],
            }
            older_path = _write_session_file(
                home, "proj-1", "session-old.json", older, mtime=1.0
            )
            newer_path = _write_session_file(
                home, "proj-1", "session-new.json", newer, mtime=2.0
            )

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                selected = gemini_runner._latest_session_file_for_id(
                    project_root, "session-a"
                )

            self.assertEqual(selected, newer_path)
            self.assertNotEqual(selected, older_path)

    def test_latest_session_file_for_id_ignores_subagent_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            _write_projects_registry(home, project_root, "proj-1")
            _write_session_file(
                home,
                "proj-1",
                "session-subagent.json",
                {
                    "sessionId": "session-a",
                    "kind": "subagent",
                    "lastUpdated": "2026-03-20T03:00:00Z",
                    "startTime": "2026-03-20T03:00:00Z",
                    "messages": [
                        {"type": "user", "content": "prompt"},
                        {"type": "gemini", "content": "subagent"},
                    ],
                },
                mtime=3.0,
            )
            main_path = _write_session_file(
                home,
                "proj-1",
                "session-main.json",
                {
                    "sessionId": "session-a",
                    "kind": "main",
                    "lastUpdated": "2026-03-20T02:00:00Z",
                    "startTime": "2026-03-20T02:00:00Z",
                    "messages": [
                        {"type": "user", "content": "prompt"},
                        {"type": "gemini", "content": "main"},
                    ],
                },
                mtime=2.0,
            )

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                selected = gemini_runner._latest_session_file_for_id(
                    project_root, "session-a"
                )

            self.assertEqual(selected, main_path)

    def test_saved_reusable_lane_session_id_requires_complete_gemini_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            _write_projects_registry(home, project_root, "proj-1")
            _write_session_file(
                home,
                "proj-1",
                "session-finished.json",
                {
                    "sessionId": "session-ok",
                    "lastUpdated": "2026-03-20T02:00:00Z",
                    "startTime": "2026-03-20T01:59:00Z",
                    "messages": [
                        {"type": "user", "content": "prompt"},
                        {"type": "gemini", "content": "done"},
                    ],
                },
            )
            _write_session_file(
                home,
                "proj-1",
                "session-open.json",
                {
                    "sessionId": "session-open",
                    "lastUpdated": "2026-03-20T03:00:00Z",
                    "startTime": "2026-03-20T02:59:00Z",
                    "messages": [
                        {"type": "user", "content": "prompt"},
                        {"type": "gemini", "content": "", "toolCalls": [{"status": "executing"}]},
                    ],
                },
            )

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                gemini_runner._remember_lane_session(project_root, "review", "session-ok")
                reusable = gemini_runner._saved_reusable_lane_session_id(
                    project_root, "review"
                )
                gemini_runner._remember_lane_session(project_root, "review", "session-open")
                not_reusable = gemini_runner._saved_reusable_lane_session_id(
                    project_root, "review"
                )

            self.assertEqual(reusable, "session-ok")
            self.assertEqual(not_reusable, "")

    def test_saved_reusable_lane_session_id_rejects_new_user_turn_in_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            _write_projects_registry(home, project_root, "proj-1")
            _write_session_file(
                home,
                "proj-1",
                "session-old.json",
                {
                    "sessionId": "session-a",
                    "lastUpdated": "2026-03-20T02:00:00Z",
                    "startTime": "2026-03-20T01:00:00Z",
                    "messages": [
                        {
                            "id": "u1",
                            "timestamp": "2026-03-20T01:00:00Z",
                            "type": "user",
                            "content": "old prompt",
                        },
                        {
                            "id": "g1",
                            "timestamp": "2026-03-20T01:01:00Z",
                            "type": "gemini",
                            "content": "old answer",
                        },
                    ],
                },
                mtime=2.0,
            )
            _write_session_file(
                home,
                "proj-1",
                "session-new.json",
                {
                    "sessionId": "session-a",
                    "lastUpdated": "2026-03-20T03:00:00Z",
                    "startTime": "2026-03-20T03:00:00Z",
                    "messages": [
                        {
                            "id": "u2",
                            "timestamp": "2026-03-20T03:00:00Z",
                            "type": "user",
                            "content": "new prompt",
                        }
                    ],
                },
                mtime=3.0,
            )

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                gemini_runner._remember_lane_session(project_root, "review", "session-a")
                reusable = gemini_runner._saved_reusable_lane_session_id(
                    project_root, "review"
                )

            self.assertEqual(reusable, "")

    def test_session_is_complete_rejects_empty_gemini_tail_without_text(self) -> None:
        conversation = {
            "messages": [
                {"type": "user", "content": "prompt"},
                {"type": "gemini", "content": ""},
            ]
        }

        self.assertFalse(gemini_runner._session_is_complete(conversation))

    def test_merged_session_messages_combines_multiple_files_for_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            _write_projects_registry(home, project_root, "proj-1")
            _write_session_file(
                home,
                "proj-1",
                "session-old.json",
                {
                    "sessionId": "session-a",
                    "lastUpdated": "2026-03-20T02:00:00Z",
                    "startTime": "2026-03-20T01:00:00Z",
                    "messages": [
                        {
                            "id": "u1",
                            "timestamp": "2026-03-20T01:00:00Z",
                            "type": "user",
                            "content": "old prompt",
                        },
                        {
                            "id": "g1",
                            "timestamp": "2026-03-20T01:01:00Z",
                            "type": "gemini",
                            "content": "old answer",
                        },
                    ],
                },
                mtime=2.0,
            )
            _write_session_file(
                home,
                "proj-1",
                "session-new.json",
                {
                    "sessionId": "session-a",
                    "lastUpdated": "2026-03-20T03:00:00Z",
                    "startTime": "2026-03-20T03:00:00Z",
                    "messages": [
                        {
                            "id": "u2",
                            "timestamp": "2026-03-20T03:00:00Z",
                            "type": "user",
                            "content": "new prompt",
                        }
                    ],
                },
                mtime=3.0,
            )

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                messages = gemini_runner._merged_session_messages(
                    project_root, "session-a"
                )

            self.assertEqual([message["id"] for message in messages], ["u1", "g1", "u2"])

    def test_merged_session_messages_keeps_latest_version_of_same_message_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            _write_projects_registry(home, project_root, "proj-1")
            _write_session_file(
                home,
                "proj-1",
                "session-old.json",
                {
                    "sessionId": "session-a",
                    "lastUpdated": "2026-03-20T02:00:00Z",
                    "startTime": "2026-03-20T01:00:00Z",
                    "messages": [
                        {
                            "id": "g1",
                            "timestamp": "2026-03-20T01:01:00Z",
                            "type": "gemini",
                            "content": "",
                        }
                    ],
                },
                mtime=2.0,
            )
            _write_session_file(
                home,
                "proj-1",
                "session-new.json",
                {
                    "sessionId": "session-a",
                    "lastUpdated": "2026-03-20T03:00:00Z",
                    "startTime": "2026-03-20T03:00:00Z",
                    "messages": [
                        {
                            "id": "g1",
                            "timestamp": "2026-03-20T01:01:00Z",
                            "type": "gemini",
                            "content": "final answer",
                        }
                    ],
                },
                mtime=3.0,
            )

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                messages = gemini_runner._merged_session_messages(
                    project_root, "session-a"
                )

            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]["content"], "final answer")

    def test_interactive_outcome_returns_success_after_final_gemini_message(self) -> None:
        outcome = gemini_runner._interactive_outcome(
            [
                {"type": "user", "content": "prompt"},
                {"type": "gemini", "content": "", "toolCalls": [{"status": "success"}]},
                {"type": "gemini", "content": "final answer"},
            ]
        )

        self.assertEqual(outcome, ("success", "final answer"))

    def test_interactive_outcome_waits_while_tool_call_is_active(self) -> None:
        outcome = gemini_runner._interactive_outcome(
            [
                {"type": "user", "content": "prompt"},
                {"type": "gemini", "content": "", "toolCalls": [{"status": "executing"}]},
            ]
        )

        self.assertIsNone(outcome)

    def test_interactive_outcome_detects_error_markers(self) -> None:
        outcome = gemini_runner._interactive_outcome(
            [
                {"type": "user", "content": "prompt"},
                {"type": "error", "content": "429 Too Many Requests"},
            ]
        )

        self.assertEqual(outcome, ("error", "429 Too Many Requests"))

    def test_latest_fresh_chat_file_since_prefers_prompt_matching_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            _write_projects_registry(home, project_root, "proj-1")
            start_epoch = 100.0
            unrelated_path = _write_session_file(
                home,
                "proj-1",
                "session-unrelated.json",
                {
                    "sessionId": "session-other",
                    "lastUpdated": "2026-03-20T03:00:00Z",
                    "startTime": "2026-03-20T03:00:00Z",
                    "messages": [
                        {"type": "user", "content": "different prompt"},
                        {"type": "gemini", "content": "done"},
                    ],
                },
                mtime=130.0,
            )
            matching_path = _write_session_file(
                home,
                "proj-1",
                "session-matching.json",
                {
                    "sessionId": "session-target",
                    "lastUpdated": "2026-03-20T02:00:00Z",
                    "startTime": "2026-03-20T02:00:00Z",
                    "messages": [
                        {"type": "user", "content": 'line 1\nline "2"'},
                        {"type": "gemini", "content": "done"},
                    ],
                },
                mtime=120.0,
            )

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                selected = gemini_runner._latest_fresh_chat_file_since(
                    project_root,
                    start_epoch,
                    'line 1\nline "2"',
                )

            self.assertEqual(selected, matching_path)
            self.assertNotEqual(selected, unrelated_path)

    def test_latest_fresh_chat_file_since_ignores_subagent_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            _write_projects_registry(home, project_root, "proj-1")
            start_epoch = 100.0
            _write_session_file(
                home,
                "proj-1",
                "session-subagent.json",
                {
                    "sessionId": "session-a",
                    "kind": "subagent",
                    "lastUpdated": "2026-03-20T03:00:00Z",
                    "startTime": "2026-03-20T03:00:00Z",
                    "messages": [
                        {"type": "user", "content": "prompt"},
                        {"type": "gemini", "content": "subagent"},
                    ],
                },
                mtime=130.0,
            )
            main_path = _write_session_file(
                home,
                "proj-1",
                "session-main.json",
                {
                    "sessionId": "session-b",
                    "kind": "main",
                    "lastUpdated": "2026-03-20T02:00:00Z",
                    "startTime": "2026-03-20T02:00:00Z",
                    "messages": [
                        {"type": "user", "content": "prompt"},
                        {"type": "gemini", "content": "main"},
                    ],
                },
                mtime=120.0,
            )

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                selected = gemini_runner._latest_fresh_chat_file_since(
                    project_root,
                    start_epoch,
                    "prompt",
                )

            self.assertEqual(selected, main_path)

    def test_run_gemini_dispatches_by_runner_mode(self) -> None:
        project_root = Path("/workspace")
        headless = subprocess.CompletedProcess(["gemini"], 0, "headless", "")
        interactive = subprocess.CompletedProcess(["gemini"], 0, "interactive", "")

        with mock.patch(
            "gemini_runner._run_headless", return_value=headless
        ) as headless_mock, mock.patch(
            "gemini_runner._run_interactive", return_value=interactive
        ) as interactive_mock:
            result_interactive = gemini_runner.run_gemini(
                "prompt", 30, project_root, lane="review", runner_mode="interactive"
            )
            result_headless = gemini_runner.run_gemini(
                "prompt", 30, project_root, lane="review", runner_mode="headless"
            )

        self.assertEqual(result_interactive.stdout, "interactive")
        self.assertEqual(result_headless.stdout, "headless")
        interactive_mock.assert_called_once()
        headless_mock.assert_called_once()

    def test_run_gemini_retries_without_resume_on_invalid_saved_session_headless(
        self,
    ) -> None:
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
            result = gemini_runner._run_headless(
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

    def test_run_advisory_accepts_parser_extension_output_contract_builder_and_runner_mode(
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
            ) as run_gemini_mock:
                exit_code = gemini_runner.run_advisory(
                    description="review",
                    role_line="role",
                    label="review",
                    lane="review",
                    configure_parser=configure_parser,
                    output_contract_builder=lambda args: f"MODE={args.mode}",
                    argv=[
                        "--brief-file",
                        str(brief_path),
                        "--mode",
                        "structural",
                        "--runner-mode",
                        "headless",
                    ],
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(run_gemini_mock.call_args.kwargs["runner_mode"], "headless")

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
