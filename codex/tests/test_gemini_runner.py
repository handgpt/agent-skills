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


def _session_filename(label: str, session_id: str, ext: str = ".json") -> str:
    return f"session-{label}-{session_id[:8]}{ext}"


def _write_jsonl_session_file(
    home: Path,
    short_id: str,
    filename: str,
    metadata: dict[str, object],
    messages: list[dict[str, object]],
    *,
    extra_lines: list[dict[str, object]] | None = None,
    mtime: float | None = None,
) -> Path:
    """Write a Gemini CLI v0.39+ JSONL session file."""
    chats_dir = home / ".gemini" / gemini_runner.GEMINI_TMP_DIRNAME / short_id / "chats"
    chats_dir.mkdir(parents=True, exist_ok=True)
    path = chats_dir / filename
    lines = [json.dumps(metadata)]
    for msg in messages:
        lines.append(json.dumps(msg))
    for extra in (extra_lines or []):
        lines.append(json.dumps(extra))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


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

    def test_interactive_command_starts_with_explicit_session_id(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            command = gemini_runner._interactive_command(
                "gemini", 'line 1\nline "2"', "session-2"
            )

        self.assertIn("--model", command)
        self.assertIn("pro", command)
        self.assertIn("--approval-mode", command)
        self.assertIn("yolo", command)
        self.assertIn("--session-id", command)
        self.assertNotIn("--resume", command)
        self.assertIn("session-2", command)
        self.assertIn("-i", command)
        self.assertNotIn("--output-format", command)
        self.assertEqual(command[-1], 'line 1\nline "2"')

    def test_interactive_command_resumes_existing_session_when_requested(self) -> None:
        command = gemini_runner._interactive_command(
            "gemini", "prompt", "session-2", resume=True
        )

        self.assertIn("--resume", command)
        self.assertNotIn("--session-id", command)
        self.assertIn("session-2", command)
        self.assertIn("-i", command)
        self.assertEqual(command[-1], gemini_runner.RESUME_CONTINUATION_PROMPT)
        self.assertNotEqual(command[-1], "prompt")

    def test_safe_prompt_argument_prefixes_hyphen_led_prompt(self) -> None:
        self.assertEqual(gemini_runner._safe_prompt_argument("- risky"), "\n- risky")

    def test_gemini_environment_disables_sandbox_for_full_access(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            env = gemini_runner._gemini_environment()

        self.assertEqual(env[gemini_runner.GEMINI_SANDBOX_ENV_VAR], "false")
        self.assertEqual(env["TERM"], "xterm-256color")
        self.assertEqual(env["COLORTERM"], "truecolor")

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

    def test_output_validator_accepts_preamble_before_first_heading(self) -> None:
        validator = gemini_runner.build_output_validator(
            "## Top Findings\n- bullet\n\n## Overall Assessment\nOne short paragraph."
        )

        self.assertEqual(
            validator(
                "Here is the review.\n\n## Top Findings\n- ok\n\n## Overall Assessment\nDone."
            ),
            "",
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

    def test_output_normalizer_strips_leading_meta_preamble_before_heading(self) -> None:
        normalizer = gemini_runner.build_output_normalizer(
            "## Verdict\n- bullet\n\n## Recommendation\n- bullet"
        )

        self.assertEqual(
            normalizer(
                "I will inspect the files now.\n\n## Verdict\nLooks sound.\n\n## Recommendation\n- proceed"
            ),
            "## Verdict\nLooks sound.\n\n## Recommendation\n- proceed",
        )

    def test_output_validator_rejects_meta_chatter(self) -> None:
        validator = gemini_runner.build_output_validator(
            "## Likely Causes\n- bullet\n\n## Confidence\nOne short paragraph."
        )

        self.assertIn(
            "meta chatter",
            validator("I will inspect the files now and report back."),
        )

    def test_output_validator_rejects_wrong_heading_shape(self) -> None:
        validator = gemini_runner.build_output_validator(
            "## Verdict\nOne short paragraph.\n\n## Recommendation\n- bullet"
        )

        self.assertIn(
            "wrong advisory shape",
            validator("## Top Findings\n- one\n\n## Overall Assessment\nGood."),
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

    def test_session_file_globs_targets_session_short_id(self) -> None:
        self.assertEqual(
            gemini_runner._session_file_globs("12345678-aaaa-bbbb-cccc-ddddeeeeffff"),
            ["session-*-12345678.json", "session-*-12345678.jsonl"],
        )
        self.assertEqual(
            gemini_runner._session_file_globs(""),
            ["session-*.json", "session-*.jsonl"],
        )

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

    def test_load_jsonl_conversation_basic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "session-test-abcd1234.jsonl"
            lines = [
                json.dumps({"sessionId": "abcd1234", "projectHash": "ph", "startTime": "2026-04-26T00:00:00Z"}),
                json.dumps({"id": "m1", "timestamp": "2026-04-26T00:01:00Z", "type": "user", "content": "hello"}),
                json.dumps({"$set": {"lastUpdated": "2026-04-26T00:02:00Z"}}),
                json.dumps({"id": "m2", "timestamp": "2026-04-26T00:02:00Z", "type": "gemini", "content": "hi"}),
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            conversation = gemini_runner._load_conversation(path)
            self.assertIsNotNone(conversation)
            self.assertEqual(conversation["sessionId"], "abcd1234")
            self.assertEqual(conversation["lastUpdated"], "2026-04-26T00:02:00Z")
            messages = gemini_runner._conversation_messages(conversation)
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[0]["type"], "user")
            self.assertEqual(messages[1]["type"], "gemini")

    def test_load_jsonl_conversation_rewind_is_inclusive(self) -> None:
        """$rewindTo removes the target message AND everything after it."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "session-rewind-abcd1234.jsonl"
            lines = [
                json.dumps({"sessionId": "abcd1234", "projectHash": "ph", "startTime": "2026-04-26T00:00:00Z"}),
                json.dumps({"id": "m1", "timestamp": "2026-04-26T00:01:00Z", "type": "user", "content": "q1"}),
                json.dumps({"id": "m2", "timestamp": "2026-04-26T00:02:00Z", "type": "gemini", "content": "a1"}),
                json.dumps({"id": "m3", "timestamp": "2026-04-26T00:03:00Z", "type": "user", "content": "q2"}),
                json.dumps({"$rewindTo": "m2"}),
                json.dumps({"id": "m4", "timestamp": "2026-04-26T00:04:00Z", "type": "user", "content": "q2-revised"}),
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            conversation = gemini_runner._load_conversation(path)
            messages = gemini_runner._conversation_messages(conversation)
            ids = [m["id"] for m in messages]
            # m2 and m3 should be removed (inclusive); m1 survives, m4 added after
            self.assertEqual(ids, ["m1", "m4"])

    def test_load_jsonl_conversation_truncated_line_salvages_prior(self) -> None:
        """A partially-written trailing line should not drop the whole file."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "session-trunc-abcd1234.jsonl"
            lines = [
                json.dumps({"sessionId": "abcd1234", "projectHash": "ph", "startTime": "2026-04-26T00:00:00Z"}),
                json.dumps({"id": "m1", "timestamp": "2026-04-26T00:01:00Z", "type": "user", "content": "hello"}),
                '{"id": "m2", "timestamp": "2026-04-26T00:02:00Z", "typ',  # truncated
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            conversation = gemini_runner._load_conversation(path)
            self.assertIsNotNone(conversation)
            self.assertEqual(conversation["sessionId"], "abcd1234")
            messages = gemini_runner._conversation_messages(conversation)
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]["id"], "m1")

    def test_load_jsonl_message_replacement(self) -> None:
        """A repeated message id replaces the earlier version in-place."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "session-replace-abcd1234.jsonl"
            lines = [
                json.dumps({"sessionId": "abcd1234", "projectHash": "ph", "startTime": "2026-04-26T00:00:00Z"}),
                json.dumps({"id": "m1", "timestamp": "2026-04-26T00:01:00Z", "type": "gemini", "content": "draft"}),
                json.dumps({"id": "m1", "timestamp": "2026-04-26T00:01:05Z", "type": "gemini", "content": "final"}),
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            conversation = gemini_runner._load_conversation(path)
            messages = gemini_runner._conversation_messages(conversation)
            self.assertEqual(len(messages), 1)
            self.assertEqual(gemini_runner._extract_text_from_content(messages[0]["content"]), "final")

    def test_load_jsonl_conversation_without_metadata_keeps_message_fragment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "session-2026-05-07T09-37-dfae7019.jsonl"
            lines = [
                json.dumps({"id": "g1", "timestamp": "2026-05-07T09:57:51Z", "type": "gemini", "content": "final"}),
                json.dumps({"$set": {"lastUpdated": "2026-05-07T09:57:51Z"}}),
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            conversation = gemini_runner._load_conversation(path)
            self.assertIsNotNone(conversation)
            self.assertNotIn("sessionId", conversation)
            messages = gemini_runner._conversation_messages(conversation)
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]["content"], "final")

    def test_glob_session_files_finds_both_json_and_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            d = Path(tmp_dir)
            (d / "session-2026-test-abcd1234.json").write_text("{}", encoding="utf-8")
            (d / "session-2026-test-abcd1234.jsonl").write_text("{}\n", encoding="utf-8")
            (d / "other-file.txt").write_text("", encoding="utf-8")

            files = gemini_runner._glob_session_files(
                d, gemini_runner._session_file_globs("abcd1234-session")
            )
            names = sorted(p.name for p in files)
            self.assertEqual(names, ["session-2026-test-abcd1234.json", "session-2026-test-abcd1234.jsonl"])

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

    def test_merged_session_messages_includes_metadata_less_jsonl_fragment_by_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            _write_projects_registry(home, project_root, "proj-1")
            session_id = "dfae7019-ed32-4341-86e4-11ce2e6d6591"
            _write_jsonl_session_file(
                home,
                "proj-1",
                _session_filename("metadata", session_id, ".jsonl"),
                {
                    "sessionId": session_id,
                    "lastUpdated": "2026-05-07T09:47:05Z",
                    "startTime": "2026-05-07T09:37:00Z",
                    "kind": "main",
                },
                [
                    {
                        "id": "u1",
                        "timestamp": "2026-05-07T09:37:01Z",
                        "type": "user",
                        "content": "prompt",
                    },
                    {
                        "id": "g1",
                        "timestamp": "2026-05-07T09:47:05Z",
                        "type": "gemini",
                        "content": "",
                        "thoughts": [{"subject": "working"}],
                    },
                ],
                mtime=100.0,
            )
            chats_dir = home / ".gemini" / gemini_runner.GEMINI_TMP_DIRNAME / "proj-1" / "chats"
            fragment_path = chats_dir / _session_filename("fragment", session_id, ".jsonl")
            fragment_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "id": "g2",
                                "timestamp": "2026-05-07T09:57:51Z",
                                "type": "gemini",
                                "content": "final answer",
                            }
                        ),
                        json.dumps({"$set": {"lastUpdated": "2026-05-07T09:57:51Z"}}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            os.utime(fragment_path, (200.0, 200.0))

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                messages = gemini_runner._merged_session_messages(project_root, session_id)

            self.assertEqual([message["id"] for message in messages], ["u1", "g1", "g2"])
            self.assertEqual(messages[-1]["content"], "final answer")
            self.assertEqual(
                gemini_runner._interactive_outcome(messages),
                ("success", "final answer"),
            )

    def test_interactive_outcome_returns_success_after_final_gemini_message(self) -> None:
        outcome = gemini_runner._interactive_outcome(
            [
                {"type": "user", "content": "prompt"},
                {"type": "gemini", "content": "", "toolCalls": [{"status": "success"}]},
                {"type": "gemini", "content": "final answer"},
            ]
        )

        self.assertEqual(outcome, ("success", "final answer"))

    def test_interactive_outcome_accepts_metadata_less_gemini_fragment(self) -> None:
        outcome = gemini_runner._interactive_outcome(
            [
                {
                    "id": "g2",
                    "type": "gemini",
                    "timestamp": "2026-05-07T09:57:51Z",
                    "content": "final answer",
                }
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
            "gemini_runner._drain_pty_output",
            side_effect=lambda fd, output: (output, False),
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

    def test_run_interactive_attempt_waits_for_pty_quiet_after_json_outcome(self) -> None:
        project_root = Path("/workspace")
        prompt = "prompt"
        command = ["gemini", "-i", prompt]
        process = mock.Mock()
        process.poll.return_value = None
        final_messages = [
            {"type": "user", "content": prompt},
            {"id": "g1", "type": "gemini", "content": "done"},
        ]

        with mock.patch(
            "gemini_runner._launch_interactive_process", return_value=(process, 11)
        ), mock.patch(
            "gemini_runner._drain_pty_output",
            side_effect=[("streaming", True), ("streaming", False)],
        ) as drain_mock, mock.patch(
            "gemini_runner._close_interactive_process"
        ) as close_mock, mock.patch(
            "gemini_runner.time.monotonic",
            side_effect=[0.0, 0.1, 1.0, 3.2],
        ), mock.patch(
            "gemini_runner.time.time", return_value=100.0
        ), mock.patch(
            "gemini_runner.time.sleep"
        ), mock.patch(
            "gemini_runner._merged_session_messages",
            side_effect=[[], final_messages, final_messages],
        ), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            result = gemini_runner._run_interactive_attempt(
                command,
                1200,
                project_root,
                resumed_session_id="session-a",
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "done")
        self.assertEqual(drain_mock.call_count, 2)
        process.poll.assert_called_once()
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

        resumed_messages = [
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
            {"type": "user", "content": gemini_runner.RESUME_CONTINUATION_PROMPT},
            {"id": "g2", "type": "gemini", "content": "done"},
        ]

        with mock.patch(
            "gemini_runner._launch_interactive_process",
            side_effect=[(process_one, 11), (process_two, 12)],
        ) as launch_mock, mock.patch(
            "gemini_runner._drain_pty_output",
            side_effect=lambda fd, output: (output, False),
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
                resumed_messages,
            ],
        ), mock.patch.object(
            gemini_runner, "INTERACTIVE_STABILITY_SECONDS", 0.0
        ), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ) as stderr:
            result = gemini_runner._run_interactive_attempt(
                command,
                1200,
                project_root,
                resumed_session_id="session-a",
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "done")
        self.assertIn(gemini_runner.EXIT_RESUME_PROGRESS_NOTE, stderr.getvalue())
        self.assertEqual(close_mock.call_count, 2)
        resumed_command = launch_mock.call_args_list[1].args[0]
        self.assertIn("--resume", resumed_command)
        self.assertNotIn("--session-id", resumed_command)
        self.assertEqual(resumed_command[-1], gemini_runner.RESUME_CONTINUATION_PROMPT)

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
        resumed_thought_messages = thought_only_messages + [
            {"type": "user", "content": gemini_runner.RESUME_CONTINUATION_PROMPT},
            {
                "id": "g2",
                "type": "gemini",
                "content": "",
                "thoughts": [
                    {
                        "timestamp": "2026-03-20T01:00:01Z",
                        "subject": "Continuing",
                        "description": "Still working.",
                    }
                ],
            },
        ]
        second_resumed_thought_messages = resumed_thought_messages + [
            {"type": "user", "content": gemini_runner.RESUME_CONTINUATION_PROMPT},
            {
                "id": "g3",
                "type": "gemini",
                "content": "",
                "thoughts": [
                    {
                        "timestamp": "2026-03-20T01:00:02Z",
                        "subject": "Continuing again",
                        "description": "Still working.",
                    }
                ],
            },
        ]

        with mock.patch(
            "gemini_runner._launch_interactive_process",
            side_effect=[(processes[0], 11), (processes[1], 12), (processes[2], 13)],
        ), mock.patch(
            "gemini_runner._drain_pty_output",
            side_effect=lambda fd, output: (output, False),
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
            side_effect=[
                [],
                thought_only_messages,
                thought_only_messages,
                thought_only_messages,
                resumed_thought_messages,
                resumed_thought_messages,
                resumed_thought_messages,
                second_resumed_thought_messages,
                second_resumed_thought_messages,
            ],
        ), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ) as stderr:
            result = gemini_runner._run_interactive_attempt(
                command,
                1,
                project_root,
                resumed_session_id="session-a",
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn(gemini_runner.EXIT_RESUME_PROGRESS_NOTE, stderr.getvalue())
        self.assertIn("100% (1s/1s)", stderr.getvalue())
        self.assertGreaterEqual(close_mock.call_count, 2)

    def test_run_gemini_uses_interactive_runner(self) -> None:
        project_root = Path("/workspace")
        interactive = subprocess.CompletedProcess(["gemini"], 0, "interactive", "")

        with mock.patch(
            "gemini_runner._run_interactive", return_value=interactive
        ) as interactive_mock:
            result = gemini_runner.run_gemini(
                "prompt",
                30,
                project_root,
            )

        self.assertEqual(result.stdout, "interactive")
        interactive_mock.assert_called_once()

    def test_run_interactive_starts_with_generated_session_id(self) -> None:
        project_root = Path("/workspace")
        invalid = subprocess.CompletedProcess(["gemini"], 0, "I will inspect files.", "")
        validator = gemini_runner.build_output_validator(
            "## Top Findings\n- bullet\n\n## Overall Assessment\nOne short paragraph."
        )

        with mock.patch("gemini_runner.shutil.which", return_value="/usr/bin/gemini"), mock.patch(
            "gemini_runner.uuid4", return_value="generated-session-id"
        ), mock.patch(
            "gemini_runner._run_interactive_attempt",
            return_value=invalid,
        ) as attempt_mock:
            result = gemini_runner._run_interactive(
                "prompt",
                30,
                project_root,
                output_validator=validator,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("meta chatter", result.stderr)
        attempt_mock.assert_called_once()
        called_command = attempt_mock.call_args.args[0]
        self.assertNotIn("--resume", called_command)
        self.assertIn("--session-id", called_command)
        self.assertIn("generated-session-id", called_command)
        self.assertEqual(
            attempt_mock.call_args.kwargs["resumed_session_id"],
            "generated-session-id",
        )

    def test_run_interactive_returns_normalized_output(self) -> None:
        project_root = Path("/workspace")
        success = subprocess.CompletedProcess(
            ["gemini"],
            0,
            "I will inspect the files now.\n\n## Likely Causes\n- config drift\n\n## Confidence\nMedium.",
            "",
        )
        normalizer = gemini_runner.build_output_normalizer(
            "## Likely Causes\n- bullet\n\n## Confidence\nOne short paragraph."
        )
        validator = gemini_runner.build_output_validator(
            "## Likely Causes\n- bullet\n\n## Confidence\nOne short paragraph."
        )

        with mock.patch("gemini_runner.shutil.which", return_value="/usr/bin/gemini"), mock.patch(
            "gemini_runner._run_interactive_attempt",
            return_value=success,
        ):
            result = gemini_runner._run_interactive(
                "prompt",
                30,
                project_root,
                output_normalizer=normalizer,
                output_validator=validator,
            )

        self.assertEqual(
            result.stdout,
            "## Likely Causes\n- config drift\n\n## Confidence\nMedium.",
        )

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
            self.assertIn("## Inlined Brief", prompt)
            self.assertIn('Quote: "hello"', prompt)
            self.assertNotIn(str(home), prompt)

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
                lane: str,
                focus_root: Path,
                project_roots: tuple[Path, ...] | None,
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
                    ],
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(run_gemini_mock.call_args.args[2], project_root.resolve())

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
