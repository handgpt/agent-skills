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
    def test_candidate_commands_default_to_pro_alias(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            commands = gemini_runner._candidate_commands("gemini", "prompt", "session-1")

        self.assertTrue(commands)
        self.assertIn("--model", commands[0])
        self.assertIn("pro", commands[0])

    def test_candidate_commands_respect_model_override_env(self) -> None:
        with mock.patch.dict(os.environ, {gemini_runner.GEMINI_MODEL_ENV_VAR: "gemini-2.5-pro"}, clear=True):
            commands = gemini_runner._candidate_commands("gemini", "prompt", "")

        self.assertTrue(commands)
        self.assertIn("--model", commands[0])
        self.assertIn("gemini-2.5-pro", commands[0])

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

    def test_describe_paths_auto_expands_nearby_parent_directories_for_files(self) -> None:
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

            self.assertEqual(
                entries,
                [
                    f"- {target_file} [file]",
                    f"- {feature_dir} [directory, auto-expanded]",
                    f"- {project_root / 'src'} [directory, auto-expanded]",
                ],
            )

    def test_describe_paths_skips_auto_expand_for_large_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "workspace"
            large_dir = project_root / "large-module"
            large_dir.mkdir(parents=True)
            target_file = large_dir / "service.py"
            target_file.write_text("print('ok')\n", encoding="utf-8")
            bridge_root = gemini_runner.bridge_root_for_project(project_root)

            for index in range(gemini_runner.MAX_AUTO_EXPAND_DIRECTORY_ITEMS + 1):
                sibling = large_dir / f"sibling-{index}.py"
                sibling.write_text("pass\n", encoding="utf-8")

            entries = gemini_runner.describe_paths(
                [str(target_file)],
                project_root,
                bridge_root,
            )

            self.assertEqual(entries, [f"- {target_file} [file]"])

    def test_describe_paths_does_not_expand_grandparent_after_large_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "workspace"
            large_dir = project_root / "src" / "large-module"
            large_dir.mkdir(parents=True)
            target_file = large_dir / "service.py"
            target_file.write_text("print('ok')\n", encoding="utf-8")
            bridge_root = gemini_runner.bridge_root_for_project(project_root)

            for index in range(gemini_runner.MAX_AUTO_EXPAND_DIRECTORY_ITEMS + 1):
                sibling = large_dir / f"sibling-{index}.py"
                sibling.write_text("pass\n", encoding="utf-8")

            entries = gemini_runner.describe_paths(
                [str(target_file)],
                project_root,
                bridge_root,
            )

            self.assertEqual(entries, [f"- {target_file} [file]"])

    def test_describe_paths_ignores_hidden_children_in_expansion_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "workspace"
            feature_dir = project_root / "src" / "feature"
            feature_dir.mkdir(parents=True)
            target_file = feature_dir / "service.py"
            target_file.write_text("print('ok')\n", encoding="utf-8")
            bridge_root = gemini_runner.bridge_root_for_project(project_root)

            for index in range(gemini_runner.MAX_AUTO_EXPAND_DIRECTORY_ITEMS + 10):
                hidden_child = feature_dir / f".hidden-{index}"
                hidden_child.write_text("ignored\n", encoding="utf-8")

            entries = gemini_runner.describe_paths(
                [str(target_file)],
                project_root,
                bridge_root,
            )

            self.assertEqual(
                entries,
                [
                    f"- {target_file} [file]",
                    f"- {feature_dir} [directory, auto-expanded]",
                    f"- {project_root / 'src'} [directory, auto-expanded]",
                ],
            )

    def test_describe_paths_can_disable_auto_expand(self) -> None:
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
                strict_paths=True,
            )

            self.assertEqual(entries, [f"- {target_file} [file]"])

    def test_describe_paths_skips_auto_expand_for_noisy_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "workspace"
            noisy_dir = project_root / "node_modules" / "left-pad"
            noisy_dir.mkdir(parents=True)
            target_file = noisy_dir / "index.js"
            target_file.write_text("module.exports = {};\n", encoding="utf-8")
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

    def test_fallback_marker_detection(self) -> None:
        self.assertTrue(
            gemini_runner._should_fallback_resume(
                ["gemini", "--resume", "session", "-p", "prompt"],
                "Error: invalid session",
            )
        )
        self.assertTrue(
            gemini_runner._should_fallback_prompt(
                ["gemini", "-p", "prompt"],
                "unknown option: -p",
            )
        )
        self.assertFalse(
            gemini_runner._should_fallback_resume(
                ["gemini", "--resume", "session", "-p", "prompt"],
                "all good",
            )
        )
        self.assertFalse(
            gemini_runner._should_fallback_prompt(
                ["gemini", "-p", "prompt"],
                "completed successfully",
            )
        )

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
            ) -> str:
                self.assertEqual(output_contract, "MODE=structural")
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
