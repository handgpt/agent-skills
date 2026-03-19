from __future__ import annotations

import argparse
import json
import os
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
    def test_interactive_command_defaults_to_pro_alias(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            command = gemini_runner._interactive_command("gemini", "prompt", "session-1")

        self.assertIn("--model", command)
        self.assertIn("pro", command)
        self.assertIn("--approval-mode", command)
        self.assertIn("yolo", command)
        self.assertIn("--resume", command)
        self.assertIn("session-1", command)
        self.assertIn("-i", command)
        self.assertIn("prompt", command)

    def test_interactive_command_respects_model_override_env(self) -> None:
        with mock.patch.dict(os.environ, {gemini_runner.GEMINI_MODEL_ENV_VAR: "gemini-2.5-pro"}, clear=True):
            command = gemini_runner._interactive_command("gemini", "prompt", "")

        self.assertIn("--model", command)
        self.assertIn("gemini-2.5-pro", command)
        self.assertNotIn("--resume", command)

    def test_gemini_environment_disables_sandbox_for_full_access(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            env = gemini_runner._gemini_environment()

        self.assertEqual(env[gemini_runner.GEMINI_SANDBOX_ENV_VAR], "false")
        self.assertEqual(env["TERM"], "xterm-256color")
        self.assertEqual(env["COLORTERM"], "truecolor")

    def test_gemini_projects_returns_empty_mapping_for_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            projects_path = home / ".gemini" / "projects.json"
            projects_path.parent.mkdir(parents=True, exist_ok=True)
            projects_path.write_text("{not valid json", encoding="utf-8")

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                self.assertEqual(gemini_runner._gemini_projects(), {})

    def test_session_sort_key_falls_back_from_invalid_last_updated_to_start_time(self) -> None:
        chat_path = Path(__file__)
        ordering_key = gemini_runner._session_sort_key(
            chat_path,
            {
                "lastUpdated": "not-a-timestamp",
                "startTime": "2026-03-11T08:10:48+00:00",
            },
        )
        self.assertEqual(ordering_key[0], 1)
        self.assertGreater(ordering_key[1], 0)

    def test_latest_project_session_id_prefers_real_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            project_root.mkdir()
            chats_dir = home / ".gemini" / "tmp" / "workspace-alias" / "chats"
            chats_dir.mkdir(parents=True)
            projects_path = home / ".gemini" / "projects.json"
            projects_path.parent.mkdir(parents=True, exist_ok=True)
            projects_path.write_text(
                json.dumps({"projects": {str(project_root): "workspace-alias"}}),
                encoding="utf-8",
            )

            (chats_dir / "session-z-fallback.json").write_text(
                json.dumps({"sessionId": "fallback-only"}),
                encoding="utf-8",
            )
            (chats_dir / "session-2026-03-11T08-10.json").write_text(
                json.dumps(
                    {
                        "sessionId": "timestamp-wins",
                        "lastUpdated": "2026-03-11T08:10:48.133Z",
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                self.assertEqual(
                    gemini_runner.latest_project_session_id(project_root),
                    "timestamp-wins",
                )

    def test_stage_brief_file_prunes_old_and_excess_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            bridge_root = gemini_runner.bridge_root_for_project(project_root)
            briefs_dir = bridge_root / "briefs"
            briefs_dir.mkdir(parents=True, exist_ok=True)

            now = 2_000_000_000
            stale_age = gemini_runner.STAGED_BRIEF_TTL_SECONDS + 100
            for index in range(gemini_runner.MAX_STAGED_BRIEFS + 5):
                path = briefs_dir / f"old-{index}.md"
                path.write_text(f"old {index}", encoding="utf-8")
                timestamp = now - stale_age - index
                os.utime(path, (timestamp, timestamp))

            brief_path = project_root / "review-brief.md"
            brief_path.write_text("fresh brief", encoding="utf-8")

            with mock.patch("gemini_runner.time.time", return_value=now):
                staged_path = gemini_runner.stage_brief_file(brief_path, bridge_root)

            files = sorted(path.name for path in briefs_dir.iterdir() if path.is_file())
            self.assertEqual(files, [staged_path.name])

    def test_describe_paths_filters_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "workspace"
            project_root.mkdir()
            bridge_root = gemini_runner.bridge_root_for_project(project_root)
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
                    str(bridge_root),
                ],
                project_root,
                bridge_root,
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
            bridge_root = gemini_runner.bridge_root_for_project(project_root)

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                entries = gemini_runner.describe_paths(
                    [str(inside_dir), str(missing_inside)],
                    project_root,
                    bridge_root,
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
            bridge_root = gemini_runner.bridge_root_for_project(project_root)

            entries = gemini_runner.describe_paths(
                ["", "   "],
                project_root,
                bridge_root,
            )

            self.assertEqual(entries, [])

    def test_describe_paths_keeps_only_explicit_context_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "workspace"
            feature_dir = project_root / "src" / "feature"
            feature_dir.mkdir(parents=True)
            target_file = feature_dir / "service.py"
            target_file.write_text("print('ok')\n", encoding="utf-8")
            bridge_root = gemini_runner.bridge_root_for_project(project_root)

            entries = gemini_runner.describe_paths(
                [str(target_file)],
                project_root,
                bridge_root,
            )

            self.assertEqual(entries, [f"- {target_file} [file]"])

    def test_describe_paths_skips_symlink_to_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project_root = root / "workspace"
            project_root.mkdir()
            bridge_root = gemini_runner.bridge_root_for_project(project_root)
            outside_file = root / "outside.txt"
            outside_file.write_text("outside", encoding="utf-8")
            linked_outside = project_root / "linked-outside.txt"
            linked_outside.symlink_to(outside_file)

            entries = gemini_runner.describe_paths(
                [str(linked_outside)],
                project_root,
                bridge_root,
            )

            self.assertEqual(entries, [])

    def test_resume_retry_marker_detection(self) -> None:
        self.assertTrue(
            gemini_runner._should_retry_resume(
                ["gemini", "--resume", "session"],
                "Error: invalid session",
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

    def test_find_run_observation_in_payload_returns_latest_following_gemini_message(self) -> None:
        chat_path = Path(__file__)
        payload = {
            "lastUpdated": "2026-03-19T12:43:35.512Z",
            "messages": [
                {"type": "user", "content": [{"text": "ignore"}]},
                {"type": "gemini", "content": "ignore"},
                {"type": "user", "content": [{"text": "brief\nmarker-123"}]},
                {"type": "gemini", "content": "intermediate answer"},
                {"type": "gemini", "content": "final answer"},
            ]
        }

        observation = gemini_runner._find_run_observation_in_payload(payload, "marker-123", chat_path)

        self.assertTrue(observation.submitted)
        self.assertEqual(observation.response, "final answer")
        self.assertIsNone(observation.error)
        self.assertGreater(observation.last_updated, 0)

    def test_find_run_observation_in_payload_returns_api_errors(self) -> None:
        chat_path = Path(__file__)
        payload = {
            "messages": [
                {"type": "user", "content": [{"text": "brief\nmarker-123"}]},
                {"type": "error", "content": [{"text": "[API Error: 429 RESOURCE_EXHAUSTED]"}]},
            ]
        }

        observation = gemini_runner._find_run_observation_in_payload(payload, "marker-123", chat_path)

        self.assertTrue(observation.submitted)
        self.assertIsNone(observation.response)
        self.assertIn("429", observation.error or "")

    def test_build_prompt_hides_home_path_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            home = Path(tmp_dir)
            project_root = home / "workspace"
            bridge_root = gemini_runner.bridge_root_for_project(project_root)
            staged_brief = bridge_root / "briefs" / "review.md"
            staged_brief.parent.mkdir(parents=True, exist_ok=True)
            staged_brief.write_text("brief", encoding="utf-8")

            with mock.patch.object(gemini_runner.Path, "home", return_value=home):
                prompt = gemini_runner.build_prompt(
                    project_root,
                    staged_brief,
                    ["- codex/skills/shared/scripts/gemini_runner.py [file]"],
                    role_line="role",
                    output_contract="contract",
                    run_marker="cadv-test",
                )

            self.assertIn("- ~/workspace", prompt)
            self.assertIn("- .codex-gemini-advisories/briefs/review.md", prompt)
            self.assertNotIn(str(home), prompt)

    def test_build_submission_message_uses_at_file_inclusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "workspace"
            instruction_path = project_root / ".codex-gemini-advisories" / "i.md"
            instruction_path.parent.mkdir(parents=True, exist_ok=True)
            instruction_path.write_text("brief", encoding="utf-8")

            message = gemini_runner.build_submission_message(project_root, instruction_path, "cadv-test")

        self.assertTrue(message.startswith("@.codex-gemini-advisories/i.md"))
        self.assertIn("Ref cadv-test", message)
        self.assertNotIn("Read ", message)

    def test_run_advisory_accepts_parser_extension_and_output_contract_builder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            brief_path = project_root / "brief.md"
            brief_path.write_text("brief", encoding="utf-8")
            staged_brief = project_root / "staged-brief.md"
            staged_brief.write_text("staged", encoding="utf-8")

            def configure_parser(parser: argparse.ArgumentParser) -> None:
                parser.add_argument("--mode", choices=("standard", "structural"), default="standard")

            def build_prompt(
                project_root: Path,
                brief_path: Path,
                context_entries: list[str],
                *,
                role_line: str,
                output_contract: str,
                run_marker: str,
            ) -> str:
                self.assertEqual(output_contract, "MODE=structural")
                self.assertIn(gemini_runner.RUN_MARKER_PREFIX, run_marker)
                return "assembled prompt"

            with mock.patch("gemini_runner.detect_project_root", return_value=project_root), mock.patch(
                "gemini_runner.bridge_root_for_project", return_value=project_root / ".bridge"
            ), mock.patch("gemini_runner.stage_brief_file", return_value=staged_brief), mock.patch(
                "gemini_runner.describe_paths", return_value=[]
            ), mock.patch("gemini_runner.build_prompt", side_effect=build_prompt), mock.patch(
                "gemini_runner.run_gemini",
                return_value=mock.Mock(returncode=0, stdout="ok", stderr=""),
            ):
                exit_code = gemini_runner.run_advisory(
                    description="review",
                    role_line="role",
                    label="review",
                    configure_parser=configure_parser,
                    output_contract_builder=lambda args: f"MODE={args.mode}",
                    argv=["--brief-file", str(brief_path), "--mode", "structural"],
                )

            self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
