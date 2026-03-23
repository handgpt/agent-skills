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
from datetime import datetime, timezone
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


def _session_filename(label: str, session_id: str) -> str:
    return f"session-{label}-{session_id[:8]}.json"


class GeminiRunnerTests(unittest.TestCase):
    def test_detect_workspace_root_prefers_nearest_agents_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_root = Path(tmp_dir) / "workspace"
            nested_root = workspace_root / "ios" / "app"
            nested_root.mkdir(parents=True)
            (workspace_root / "AGENTS.md").write_text("workspace", encoding="utf-8")

            with mock.patch("gemini_runner.Path.cwd", return_value=nested_root):
                self.assertEqual(
                    gemini_runner.detect_workspace_root(), workspace_root.resolve()
                )

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

    def test_lane_session_state_isolated_by_scope_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            scope_a = project_root / "ios"
            scope_b = project_root / "android"
            scope_a.mkdir(parents=True)
            scope_b.mkdir(parents=True)

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                gemini_runner._remember_lane_session(
                    project_root, "review", "session-ios", scope_root=scope_a
                )
                self.assertEqual(
                    gemini_runner._saved_lane_session_id(
                        project_root, "review", scope_root=scope_a
                    ),
                    "session-ios",
                )
                self.assertEqual(
                    gemini_runner._saved_lane_session_id(
                        project_root, "review", scope_root=scope_b
                    ),
                    "",
                )

    def test_lane_session_state_isolated_by_project_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            workspace_root = home / "workspace"
            ios_root = workspace_root / "ios"
            server_root = workspace_root / "server"
            android_root = workspace_root / "android"
            ios_root.mkdir(parents=True)
            server_root.mkdir(parents=True)
            android_root.mkdir(parents=True)

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                gemini_runner._remember_lane_session(
                    workspace_root,
                    "review",
                    "session-ios-server",
                    scope_root=workspace_root,
                    project_roots=(ios_root, server_root),
                )
                self.assertEqual(
                    gemini_runner._saved_lane_session_id(
                        workspace_root,
                        "review",
                        scope_root=workspace_root,
                        project_roots=(ios_root, server_root),
                    ),
                    "session-ios-server",
                )
                self.assertEqual(
                    gemini_runner._saved_lane_session_id(
                        workspace_root,
                        "review",
                        scope_root=workspace_root,
                        project_roots=(ios_root, android_root),
                    ),
                    "",
                )

    def test_saved_lane_session_id_rejects_stale_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            lane_state_path = home / ".gemini" / gemini_runner.LANE_SESSION_STATE_FILE
            lane_state_path.parent.mkdir(parents=True, exist_ok=True)
            stale_payload = {
                f"{project_root.resolve()}::review::projects=.::scope=.": {
                    "lane": "review",
                    "projectRoot": str(project_root.resolve()),
                    "scopeRoot": str(project_root.resolve()),
                    "sessionId": "stale-session",
                    "updatedAt": "2026-03-20T00:00:00+00:00",
                }
            }
            lane_state_path.write_text(
                json.dumps(stale_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            fake_now = datetime(2026, 3, 23, 0, 0, 0, tzinfo=timezone.utc)

            with mock.patch.object(gemini_runner.Path, "home", return_value=home), mock.patch(
                "gemini_runner.configured_session_reuse_ttl_seconds", return_value=3600
            ), mock.patch.object(gemini_runner, "datetime", wraps=datetime) as datetime_mock:
                datetime_mock.now.return_value = fake_now
                self.assertEqual(
                    gemini_runner._saved_lane_session_id(project_root, "review"),
                    "",
                )

    def test_saved_lane_session_id_root_scope_reads_legacy_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            legacy_payload = {
                f"{project_root.resolve()}::review": {
                    "lane": "review",
                    "projectRoot": str(project_root.resolve()),
                    "sessionId": "legacy-session",
                    "updatedAt": "2026-03-23T00:00:00+00:00",
                }
            }
            lane_state_path = home / ".gemini" / gemini_runner.LANE_SESSION_STATE_FILE
            lane_state_path.parent.mkdir(parents=True, exist_ok=True)
            lane_state_path.write_text(
                json.dumps(legacy_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(gemini_runner.Path, "home", return_value=home), mock.patch(
                "gemini_runner.configured_session_reuse_ttl_seconds", return_value=999999
            ):
                self.assertEqual(
                    gemini_runner._saved_lane_session_id(project_root, "review"),
                    "legacy-session",
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

    def test_focus_scope_root_prefers_common_context_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "workspace"
            ios_dir = project_root / "ios"
            ios_dir.mkdir(parents=True)
            file_a = ios_dir / "a.swift"
            file_b = ios_dir / "b.swift"
            file_a.write_text("a", encoding="utf-8")
            file_b.write_text("b", encoding="utf-8")

            focus_root = gemini_runner._focus_scope_root(
                [str(file_a), str(file_b)], project_root
            )

            self.assertEqual(focus_root, ios_dir.resolve())

    def test_focus_scope_root_bubbles_to_workspace_for_sibling_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "workspace"
            ios_dir = project_root / "ios"
            android_dir = project_root / "android"
            ios_dir.mkdir(parents=True)
            android_dir.mkdir(parents=True)
            file_a = ios_dir / "a.swift"
            file_b = android_dir / "b.kt"
            file_a.write_text("a", encoding="utf-8")
            file_b.write_text("b", encoding="utf-8")

            focus_root = gemini_runner._focus_scope_root(
                [str(file_a), str(file_b)], project_root
            )

            self.assertEqual(focus_root, project_root.resolve())

    def test_normalize_multi_project_roots_prefers_explicit_roots_within_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_root = Path(tmp_dir) / "workspace"
            ios_root = workspace_root / "ios"
            server_root = workspace_root / "server"
            ios_root.mkdir(parents=True)
            server_root.mkdir(parents=True)

            roots = gemini_runner._normalize_multi_project_roots(
                [str(ios_root), str(server_root)],
                [],
                workspace_root,
                workspace_root,
            )

            self.assertEqual(roots, (ios_root.resolve(), server_root.resolve()))

    def test_normalize_multi_project_roots_rejects_roots_outside_workspace_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_root = Path(tmp_dir) / "workspace"
            ios_root = workspace_root / "ios"
            outside_root = Path(tmp_dir) / "outside"
            ios_root.mkdir(parents=True)
            outside_root.mkdir(parents=True)

            roots = gemini_runner._normalize_multi_project_roots(
                [str(ios_root), str(outside_root)],
                [],
                workspace_root,
                workspace_root,
            )

            self.assertEqual(roots, (ios_root.resolve(),))

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

    def test_output_validator_rejects_preamble_before_first_heading(self) -> None:
        validator = gemini_runner.build_output_validator(
            "## Top Findings\n- bullet\n\n## Overall Assessment\nOne short paragraph."
        )

        self.assertIn(
            "did not start with the required first heading",
            validator("Here is the review.\n\n## Top Findings\n- ok\n\n## Overall Assessment\nDone."),
        )

    def test_output_validator_accepts_matching_headings(self) -> None:
        validator = gemini_runner.build_output_validator(
            "## Likely Causes\n- bullet\n\n## Confidence\nOne short paragraph."
        )

        self.assertEqual(
            validator("## Likely Causes\n- one\n\n## Confidence\nHigh."),
            "",
        )

    def test_output_validator_accepts_outer_markdown_code_fence(self) -> None:
        validator = gemini_runner.build_output_validator(
            "## Top Findings\n- bullet\n\n## Overall Assessment\nOne short paragraph."
        )

        self.assertEqual(
            validator(
                "```markdown\n## Top Findings\n- ok\n\n## Overall Assessment\nGood.\n```"
            ),
            "",
        )

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

    def test_session_file_glob_targets_session_short_id(self) -> None:
        self.assertEqual(
            gemini_runner._session_file_glob("12345678-aaaa-bbbb-cccc-ddddeeeeffff"),
            "session-*-12345678.json",
        )
        self.assertEqual(gemini_runner._session_file_glob(""), "session-*.json")

    def test_session_conversations_for_id_sorts_by_conversation_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            _write_projects_registry(home, project_root, "proj-1")
            older_path = _write_session_file(
                home,
                "proj-1",
                _session_filename("old", "session-a"),
                {
                    "sessionId": "session-a",
                    "lastUpdated": "2026-03-20T01:00:00Z",
                    "startTime": "2026-03-20T00:59:00Z",
                    "messages": [],
                },
                mtime=1.0,
            )
            newer_path = _write_session_file(
                home,
                "proj-1",
                _session_filename("new", "session-a"),
                {
                    "sessionId": "session-a",
                    "lastUpdated": "2026-03-20T02:00:00Z",
                    "startTime": "2026-03-20T01:59:00Z",
                    "messages": [],
                },
                mtime=2.0,
            )

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                conversations = gemini_runner._session_conversations_for_id(
                    project_root, "session-a"
                )

            self.assertEqual([item[1] for item in conversations], [older_path, newer_path])

    def test_load_conversation_retries_partial_json_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "session.json"
            path.write_text("{}", encoding="utf-8")

            with mock.patch.object(
                Path,
                "read_text",
                side_effect=['{"sessionId"', '{"sessionId":"session-a","messages":[]}'],
            ), mock.patch("gemini_runner.time.sleep") as sleep_mock:
                conversation = gemini_runner._load_conversation(path)

            self.assertEqual(conversation, {"sessionId": "session-a", "messages": []})
            sleep_mock.assert_called_once_with(
                gemini_runner.JSON_READ_RETRY_DELAY_SECONDS
            )

    def test_session_conversations_for_id_ignores_subagent_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            _write_projects_registry(home, project_root, "proj-1")
            _write_session_file(
                home,
                "proj-1",
                _session_filename("subagent", "session-a"),
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
                _session_filename("main", "session-a"),
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
                conversations = gemini_runner._session_conversations_for_id(
                    project_root, "session-a"
                )

            self.assertEqual([item[1] for item in conversations], [main_path])

    def test_saved_reusable_lane_session_id_requires_complete_gemini_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            _write_projects_registry(home, project_root, "proj-1")
            _write_session_file(
                home,
                "proj-1",
                _session_filename("finished", "session-ok"),
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
                _session_filename("open", "session-open"),
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

    def test_saved_reusable_lane_session_id_rejects_invalid_contract_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            _write_projects_registry(home, project_root, "proj-1")
            _write_session_file(
                home,
                "proj-1",
                _session_filename("bad", "session-bad"),
                {
                    "sessionId": "session-bad",
                    "lastUpdated": "2026-03-23T03:00:00Z",
                    "startTime": "2026-03-23T02:59:00Z",
                    "messages": [
                        {"type": "user", "content": "prompt"},
                        {
                            "type": "gemini",
                            "content": "I will inspect the files now.",
                        },
                    ],
                },
            )

            validator = gemini_runner.build_output_validator(
                "## Likely Causes\n- bullet\n\n## Confidence\nOne short paragraph."
            )

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                gemini_runner._remember_lane_session(project_root, "error", "session-bad")
                reusable = gemini_runner._saved_reusable_lane_session_id(
                    project_root, "error", output_validator=validator
                )

            self.assertEqual(reusable, "")

    def test_saved_reusable_lane_session_id_rejects_new_user_turn_in_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            _write_projects_registry(home, project_root, "proj-1")
            _write_session_file(
                home,
                "proj-1",
                _session_filename("old", "session-a"),
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
                _session_filename("new", "session-a"),
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

    def test_merged_session_messages_combines_multiple_files_for_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            _write_projects_registry(home, project_root, "proj-1")
            _write_session_file(
                home,
                "proj-1",
                _session_filename("old", "session-a"),
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
                _session_filename("new", "session-a"),
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
                _session_filename("old", "session-a"),
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
                _session_filename("new", "session-a"),
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

    def test_interactive_state_summary_reports_user_only_turn(self) -> None:
        summary = gemini_runner._interactive_state_summary(
            [{"type": "user", "content": "prompt"}]
        )

        self.assertIn("only recorded the user message", summary)

    def test_interactive_state_summary_reports_empty_gemini_intermediate_turn(self) -> None:
        summary = gemini_runner._interactive_state_summary(
            [
                {"type": "user", "content": "prompt"},
                {"type": "gemini", "content": ""},
                {"type": "gemini", "content": ""},
            ]
        )

        self.assertIn("empty Gemini intermediate messages", summary)

    def test_interactive_state_summary_reports_recorded_thoughts(self) -> None:
        summary = gemini_runner._interactive_state_summary(
            [
                {"type": "user", "content": "prompt"},
                {
                    "type": "gemini",
                    "content": "",
                    "thoughts": [
                        {
                            "timestamp": "2026-03-20T01:00:00Z",
                            "subject": "Planning",
                            "description": "Inspecting session state.",
                        }
                    ],
                },
            ]
        )

        self.assertIn("recorded 1 Gemini thought", summary)

    def test_emit_new_thought_progress_dedupes_incremental_updates(self) -> None:
        new_messages = [
            {"type": "user", "content": "prompt"},
            {
                "id": "g1",
                "type": "gemini",
                "content": "",
                "thoughts": [
                    {
                        "timestamp": "2026-03-20T01:00:00Z",
                        "subject": "Planning",
                        "description": "Inspecting session state.",
                    }
                ],
            },
        ]

        with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            seen = gemini_runner._emit_new_thought_progress(new_messages, set())
            seen = gemini_runner._emit_new_thought_progress(new_messages, seen)

        self.assertEqual(len(seen), 1)
        self.assertEqual(stderr.getvalue().count(gemini_runner.THOUGHT_PROGRESS_PREFIX), 1)

    def test_emit_wait_progress_dedupes_percent_changes(self) -> None:
        with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            last_percent = -1
            last_percent = gemini_runner._emit_wait_progress(0.0, 0.0, 100, last_percent)
            last_percent = gemini_runner._emit_wait_progress(0.4, 0.0, 100, last_percent)
            last_percent = gemini_runner._emit_wait_progress(1.0, 0.0, 100, last_percent)

        self.assertEqual(last_percent, 1)
        self.assertEqual(stderr.getvalue().count(gemini_runner.WAIT_PROGRESS_PREFIX), 2)
        self.assertIn("0% (0s/100s)", stderr.getvalue())
        self.assertIn("1% (1s/100s)", stderr.getvalue())

    def test_run_interactive_attempt_uses_total_timeout_despite_thought_progress(self) -> None:
        project_root = Path("/workspace")
        prompt = "prompt"
        command = ["gemini", "-i", prompt]
        process = mock.Mock()
        process.poll.return_value = None
        monotonic_values = (index / 10 for index in range(30))

        with mock.patch(
            "gemini_runner._launch_interactive_process", return_value=(process, 11)
        ), mock.patch(
            "gemini_runner._drain_pty_output", side_effect=lambda fd, output: output
        ), mock.patch(
            "gemini_runner._close_interactive_process"
        ) as close_mock, mock.patch(
            "gemini_runner.time.monotonic", side_effect=monotonic_values
        ), mock.patch(
            "gemini_runner.time.time", return_value=100.0
        ), mock.patch(
            "gemini_runner.time.sleep"
        ), mock.patch(
            "gemini_runner._merged_session_messages",
            side_effect=(
                [
                    [],
                    [
                        {"type": "user", "content": prompt},
                        {"id": "g1", "type": "gemini", "content": ""},
                    ],
                ]
                + [
                    [
                        {"type": "user", "content": prompt},
                        {
                            "id": "g1",
                            "type": "gemini",
                            "content": "",
                            "thoughts": [
                                {
                                    "timestamp": "2026-03-20T01:00:00Z",
                                    "subject": "Planning",
                                    "description": "Still working.",
                                }
                            ],
                        },
                    ]
                ]
                * 20
            ),
        ), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ) as stderr:
            with self.assertRaises(subprocess.TimeoutExpired):
                gemini_runner._run_interactive_attempt(
                    command,
                    1,
                    project_root,
                    resumed_session_id="session-a",
                )

        self.assertIn(gemini_runner.THOUGHT_PROGRESS_PREFIX, stderr.getvalue())
        self.assertIn(gemini_runner.WAIT_PROGRESS_PREFIX, stderr.getvalue())
        self.assertIn("100% (1s/1s)", stderr.getvalue())
        close_mock.assert_called_once()

    def test_run_interactive_attempt_restarts_after_exit_with_thoughts(self) -> None:
        project_root = Path("/workspace")
        prompt = "prompt"
        command = ["gemini", "-i", prompt]
        process_one = mock.Mock()
        process_one.poll.side_effect = [None, 0]
        process_one.returncode = 0
        process_two = mock.Mock()
        process_two.poll.side_effect = [None]
        process_two.returncode = 0

        monotonic_values = (index / 10 for index in range(100))

        with mock.patch(
            "gemini_runner._launch_interactive_process",
            side_effect=[(process_one, 11), (process_two, 12)],
        ), mock.patch(
            "gemini_runner._drain_pty_output", side_effect=lambda fd, output: output
        ), mock.patch(
            "gemini_runner._close_interactive_process"
        ) as close_mock, mock.patch(
            "gemini_runner.time.monotonic", side_effect=monotonic_values
        ), mock.patch(
            "gemini_runner.time.time", return_value=100.0
        ), mock.patch(
            "gemini_runner.time.sleep"
        ), mock.patch(
            "gemini_runner._merged_session_messages",
            side_effect=[
                [],
                [
                    {"type": "user", "content": prompt},
                    {
                        "id": "g1",
                        "type": "gemini",
                        "content": "",
                    },
                ],
                [
                    {"type": "user", "content": prompt},
                    {
                        "id": "g1",
                        "type": "gemini",
                        "content": "",
                        "thoughts": [
                            {
                                "timestamp": "2026-03-20T01:00:00Z",
                                "subject": "Planning",
                                "description": "Still working.",
                            }
                        ],
                    },
                ],
                [
                    {"type": "user", "content": prompt},
                    {
                        "id": "g1",
                        "type": "gemini",
                        "content": "",
                        "thoughts": [
                            {
                                "timestamp": "2026-03-20T01:00:00Z",
                                "subject": "Planning",
                                "description": "Still working.",
                            }
                        ],
                    },
                ],
                [
                    {"type": "user", "content": prompt},
                    {
                        "id": "g1",
                        "type": "gemini",
                        "content": "",
                        "thoughts": [
                            {
                                "timestamp": "2026-03-20T01:00:00Z",
                                "subject": "Planning",
                                "description": "Still working.",
                            }
                        ],
                    },
                ],
                [
                    {"type": "user", "content": prompt},
                    {
                        "id": "g1",
                        "type": "gemini",
                        "content": "done",
                        "thoughts": [
                            {
                                "timestamp": "2026-03-20T01:00:00Z",
                                "subject": "Planning",
                                "description": "Still working.",
                            }
                        ],
                    },
                ],
            ],
        ), mock.patch.object(
            gemini_runner, "INTERACTIVE_STABILITY_SECONDS", 0.0
        ), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ) as stderr:
            result, resolved_session_id = gemini_runner._run_interactive_attempt(
                command,
                1200,
                project_root,
                resumed_session_id="session-a",
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "done")
        self.assertEqual(resolved_session_id, "session-a")
        self.assertIn(gemini_runner.EXIT_RESUME_PROGRESS_NOTE, stderr.getvalue())
        self.assertEqual(close_mock.call_count, 2)

    def test_run_interactive_attempt_bounds_resume_loop_by_total_timeout(self) -> None:
        project_root = Path("/workspace")
        prompt = "prompt"
        command = ["gemini", "-i", prompt]
        processes = [mock.Mock(returncode=0) for _ in range(3)]
        for process in processes:
            process.poll.side_effect = [0]

        thought_only_messages = [
            {"type": "user", "content": prompt},
            {
                "id": "g1",
                "type": "gemini",
                "content": "",
                "thoughts": [
                    {
                        "timestamp": "2026-03-20T01:00:00Z",
                        "subject": "Planning",
                        "description": "Still working.",
                    }
                ],
            },
        ]

        with mock.patch(
            "gemini_runner._launch_interactive_process",
            side_effect=[(processes[0], 11), (processes[1], 12), (processes[2], 13)],
        ), mock.patch(
            "gemini_runner._drain_pty_output", side_effect=lambda fd, output: output
        ), mock.patch(
            "gemini_runner._close_interactive_process"
        ) as close_mock, mock.patch(
            "gemini_runner.time.monotonic", side_effect=[0.0, 0.2, 0.7, 1.2]
        ), mock.patch(
            "gemini_runner.time.time", return_value=100.0
        ), mock.patch(
            "gemini_runner.time.sleep"
        ), mock.patch(
            "gemini_runner._merged_session_messages",
            side_effect=[[]] + [thought_only_messages] * 6,
        ), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ) as stderr:
            result, resolved_session_id = gemini_runner._run_interactive_attempt(
                command,
                1,
                project_root,
                resumed_session_id="session-a",
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(resolved_session_id, "session-a")
        self.assertIn(gemini_runner.EXIT_RESUME_PROGRESS_NOTE, stderr.getvalue())
        self.assertIn("100% (1s/1s)", stderr.getvalue())
        self.assertGreaterEqual(close_mock.call_count, 2)

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

    def test_conversation_matches_prompt_prefers_run_marker(self) -> None:
        conversation = {
            "messages": [
                {
                    "type": "user",
                    "content": "header\n- Run Marker: cadv-abc123\nfooter",
                }
            ]
        }

        self.assertTrue(
            gemini_runner._conversation_matches_prompt(
                conversation,
                "header changed\n- Run Marker: cadv-abc123\nfooter changed",
            )
        )

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
                "prompt",
                30,
                project_root,
                lane="review",
                scope_root=project_root,
                runner_mode="interactive",
            )
            result_headless = gemini_runner.run_gemini(
                "prompt",
                30,
                project_root,
                lane="review",
                scope_root=project_root,
                runner_mode="headless",
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
                scope_root=project_root,
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "final answer")
        self.assertEqual(run_mock.call_count, 2)
        remember_mock.assert_any_call(
            project_root, "review", "new-session", project_root, None
        )

    def test_run_headless_retries_fresh_session_when_reused_output_violates_contract(
        self,
    ) -> None:
        project_root = Path("/workspace")
        invalid = subprocess.CompletedProcess(
            ["gemini"],
            0,
            '{"session_id":"old-session","response":"I will inspect the files now."}',
            "",
        )
        success = subprocess.CompletedProcess(
            ["gemini"],
            0,
            '{"session_id":"new-session","response":"## Top Findings\\n- ok\\n\\n## Overall Assessment\\nGood."}',
            "",
        )
        validator = gemini_runner.build_output_validator(
            "## Top Findings\n- bullet\n\n## Overall Assessment\nOne short paragraph."
        )

        with mock.patch("gemini_runner.shutil.which", return_value="/usr/bin/gemini"), mock.patch(
            "gemini_runner._saved_lane_session_id", return_value="old-session"
        ), mock.patch(
            "gemini_runner._run_noninteractive_attempt", side_effect=[invalid, success]
        ) as run_mock:
            result = gemini_runner._run_headless(
                "prompt",
                30,
                project_root,
                lane="review",
                scope_root=project_root,
                output_validator=validator,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("## Top Findings", result.stdout)
        self.assertEqual(run_mock.call_count, 2)

    def test_run_headless_retries_fresh_session_when_reused_output_is_empty(
        self,
    ) -> None:
        project_root = Path("/workspace")
        empty = subprocess.CompletedProcess(
            ["gemini"],
            0,
            '{"session_id":"old-session","response":""}',
            "",
        )
        success = subprocess.CompletedProcess(
            ["gemini"],
            0,
            '{"session_id":"new-session","response":"## Top Findings\\n- ok\\n\\n## Overall Assessment\\nGood."}',
            "",
        )
        validator = gemini_runner.build_output_validator(
            "## Top Findings\n- bullet\n\n## Overall Assessment\nOne short paragraph."
        )

        with mock.patch("gemini_runner.shutil.which", return_value="/usr/bin/gemini"), mock.patch(
            "gemini_runner._saved_lane_session_id", return_value="old-session"
        ), mock.patch(
            "gemini_runner._run_noninteractive_attempt", side_effect=[empty, success]
        ) as run_mock:
            result = gemini_runner._run_headless(
                "prompt",
                30,
                project_root,
                lane="review",
                scope_root=project_root,
                output_validator=validator,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("## Top Findings", result.stdout)
        self.assertEqual(run_mock.call_count, 2)

    def test_run_interactive_retries_fresh_session_when_reused_output_is_invalid(self) -> None:
        project_root = Path("/workspace")
        invalid = subprocess.CompletedProcess(["gemini"], 0, "I will inspect files.", "")
        success = subprocess.CompletedProcess(
            ["gemini"], 0, "## Top Findings\n- ok\n\n## Overall Assessment\nGood.", ""
        )
        validator = gemini_runner.build_output_validator(
            "## Top Findings\n- bullet\n\n## Overall Assessment\nOne short paragraph."
        )

        with mock.patch("gemini_runner.shutil.which", return_value="/usr/bin/gemini"), mock.patch(
            "gemini_runner._saved_reusable_lane_session_id", return_value="old-session"
        ), mock.patch(
            "gemini_runner._run_interactive_attempt",
            side_effect=[(invalid, "old-session"), (success, "new-session")],
        ) as attempt_mock:
            result = gemini_runner._run_interactive(
                "prompt",
                30,
                project_root,
                lane="review",
                scope_root=project_root,
                output_validator=validator,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("## Top Findings", result.stdout)
        self.assertEqual(attempt_mock.call_count, 2)

    def test_build_prompt_hides_home_path_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                prompt = gemini_runner.build_prompt(
                    project_root,
                    '# Review Brief\n\nQuote: "hello"',
                    ["- codex/skills/shared/scripts/gemini_runner.py [file]"],
                    lane="review",
                    focus_root=project_root / "ios",
                    project_roots=(project_root / "ios", project_root / "server"),
                    run_marker="cadv-testmarker",
                    role_line="role",
                    output_contract="contract",
                )

            self.assertIn("## Projects In Scope", prompt)
            self.assertIn("- ios: ios", prompt)
            self.assertIn("- server: server", prompt)
            self.assertIn("Project Name: workspace", prompt)
            self.assertIn("Advisory Lane: review", prompt)
            self.assertIn("Project Scope Key: ios|server", prompt)
            self.assertIn("Target Directory: ios", prompt)
            self.assertIn("Workspace Root: ~/workspace", prompt)
            self.assertIn("Run Marker: cadv-testmarker", prompt)
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
                lane: str,
                focus_root: Path,
                project_roots: tuple[Path, ...] | None,
                run_marker: str,
                role_line: str,
                output_contract: str,
            ) -> str:
                self.assertEqual(brief_text, "brief")
                self.assertEqual(lane, "review")
                self.assertEqual(focus_root.resolve(), (project_root / "ios").resolve())
                self.assertEqual(
                    tuple(path.resolve() for path in project_roots or ()),
                    ((project_root / "ios").resolve(),),
                )
                self.assertTrue(run_marker.startswith("cadv-"))
                self.assertEqual(output_contract, "MODE=structural")
                return "assembled prompt"

            with mock.patch(
                "gemini_runner.detect_project_root", return_value=project_root
            ), mock.patch(
                "gemini_runner.detect_workspace_root", return_value=project_root
            ), mock.patch(
                "gemini_runner._normalize_multi_project_roots",
                return_value=(project_root / "ios",),
            ), mock.patch(
                "gemini_runner._focus_scope_root", return_value=project_root / "ios"
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
            self.assertEqual(run_gemini_mock.call_args.kwargs["scope_root"], project_root / "ios")

    def test_run_advisory_returns_code_5_for_e2big(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            brief_path = project_root / "brief.md"
            brief_path.write_text("brief", encoding="utf-8")
            error = OSError(errno.E2BIG, gemini_runner.INLINE_PROMPT_TOO_LARGE_MESSAGE)

            with mock.patch(
                "gemini_runner.detect_project_root", return_value=project_root
            ), mock.patch(
                "gemini_runner.detect_workspace_root", return_value=project_root
            ), mock.patch(
                "gemini_runner._normalize_multi_project_roots",
                return_value=(project_root,),
            ), mock.patch(
                "gemini_runner._focus_scope_root", return_value=project_root
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

    def test_run_advisory_surfaces_timeout_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            brief_path = project_root / "brief.md"
            brief_path.write_text("brief", encoding="utf-8")
            timeout = subprocess.TimeoutExpired(
                ["gemini"],
                1200,
                output="The latest turn only recorded empty Gemini intermediate messages so far.",
            )

            with mock.patch(
                "gemini_runner.detect_project_root", return_value=project_root
            ), mock.patch(
                "gemini_runner.detect_workspace_root", return_value=project_root
            ), mock.patch(
                "gemini_runner._normalize_multi_project_roots",
                return_value=(project_root,),
            ), mock.patch(
                "gemini_runner._focus_scope_root", return_value=project_root
            ), mock.patch(
                "gemini_runner.describe_paths", return_value=[]
            ), mock.patch(
                "gemini_runner.run_gemini", side_effect=timeout
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

            self.assertEqual(exit_code, 4)
            self.assertIn("timed out after 1200 seconds total wait", stderr.getvalue())
            self.assertIn("empty Gemini intermediate messages", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
