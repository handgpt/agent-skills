from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = ROOT.parent / "common" / "scripts"


def _load_advisor_runner() -> object:
    shared_path = str(SHARED_SCRIPTS)
    previous_path = list(sys.path)
    previous_modules = {
        name: sys.modules.get(name)
        for name in ("advisory_common", "agy_runner", "grok_runner", "advisor_runner")
    }
    if shared_path in sys.path:
        sys.path.remove(shared_path)
    sys.path.insert(0, shared_path)
    for name in previous_modules:
        sys.modules.pop(name, None)
    try:
        spec = importlib.util.spec_from_file_location(
            "advisor_runner_under_test",
            SHARED_SCRIPTS / "advisor_runner.py",
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not load advisor_runner test module")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module.configure_platform(module.CODEX_ADVISOR_PLATFORM)
        return module
    finally:
        sys.path[:] = previous_path
        for name, old_module in previous_modules.items():
            if old_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old_module


advisor_runner = _load_advisor_runner()


class AdvisorRunnerTests(unittest.TestCase):
    def test_normalize_provider_aliases(self) -> None:
        self.assertEqual(advisor_runner.normalize_provider(""), "agy")
        self.assertEqual(advisor_runner.normalize_provider("antigravity-cli"), "agy")
        self.assertEqual(advisor_runner.normalize_provider("grok-build"), "grok")
        with self.assertRaisesRegex(ValueError, "Unsupported advisor provider"):
            advisor_runner.normalize_provider("unknown")

    def test_run_advisory_routes_to_configured_grok_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            brief = root / "brief.md"
            config = root / "advisor_cli.json"
            brief.write_text("# Change Summary\n\nTest route.", encoding="utf-8")
            config.write_text(json.dumps({"provider": "grok"}), encoding="utf-8")
            captured: dict[str, str] = {}

            def fake_run_provider(**kwargs: object) -> subprocess.CompletedProcess[str]:
                captured["provider"] = str(kwargs["provider"])
                captured["prompt"] = str(kwargs["prompt"])
                return subprocess.CompletedProcess(
                    ["advisor"],
                    0,
                    "## Top Findings\n- none",
                    "",
                )

            with (
                patch.dict(os.environ, {"CODEX_ADVISOR_CONFIG": str(config)}, clear=False),
                patch.object(advisor_runner.advisory_common, "detect_project_root", return_value=root),
                patch.object(advisor_runner.advisory_common, "detect_workspace_root", return_value=root),
                patch.object(advisor_runner, "_run_provider", side_effect=fake_run_provider),
                contextlib.redirect_stdout(io.StringIO()) as stdout,
            ):
                exit_code = advisor_runner.run_advisory(
                    description="test",
                    role_line="You are a reviewer.",
                    label="review",
                    lane="review",
                    output_contract="## Top Findings\n- bullet",
                    argv=[
                        "--brief-file",
                        str(brief),
                        "--project-root",
                        str(root),
                    ],
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(captured["provider"], "grok")
            self.assertIn("inside Grok CLI", captured["prompt"])
            self.assertIn("## Projects In Scope", captured["prompt"])
            self.assertIn("## Top Findings", stdout.getvalue())

    def test_cli_provider_override_wins_over_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            brief = root / "brief.md"
            config = root / "advisor_cli.json"
            brief.write_text("# Change Summary\n\nTest override.", encoding="utf-8")
            config.write_text(json.dumps({"provider": "agy"}), encoding="utf-8")
            captured: dict[str, str] = {}

            def fake_run_provider(**kwargs: object) -> subprocess.CompletedProcess[str]:
                captured["provider"] = str(kwargs["provider"])
                return subprocess.CompletedProcess(["advisor"], 0, "## Top Findings\n- none", "")

            with (
                patch.dict(os.environ, {"CODEX_ADVISOR_CONFIG": str(config)}, clear=False),
                patch.object(advisor_runner.advisory_common, "detect_project_root", return_value=root),
                patch.object(advisor_runner.advisory_common, "detect_workspace_root", return_value=root),
                patch.object(advisor_runner, "_run_provider", side_effect=fake_run_provider),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                exit_code = advisor_runner.run_advisory(
                    description="test",
                    role_line="You are a reviewer.",
                    label="review",
                    lane="review",
                    output_contract="## Top Findings\n- bullet",
                    argv=[
                        "--provider",
                        "grok",
                        "--brief-file",
                        str(brief),
                        "--project-root",
                        str(root),
                    ],
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(captured["provider"], "grok")

    def test_project_add_dirs_excludes_primary_root_and_missing_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project_a = root / "a"
            project_b = root / "b"
            missing = root / "missing"
            project_a.mkdir()
            project_b.mkdir()

            self.assertEqual(
                advisor_runner._project_add_dirs(root, (project_a, project_b, missing, project_a)),
                (project_a.resolve(), project_b.resolve()),
            )

    def test_output_file_excludes_antigravity_progress_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            brief = root / "brief.md"
            output = root / "review.md"
            brief.write_text("# Change Summary\n\nOutput file test.", encoding="utf-8")

            def fake_inner(**_kwargs: object) -> int:
                advisor_runner.agy_runner._emit_progress("[Antigravity step]", "progress")
                advisor_runner.agy_runner._emit_wait_progress(10, 0, 100, -1)
                print("final advisory")
                return 0

            progress = io.StringIO()
            with (
                patch.object(advisor_runner, "_run_advisory_inner", side_effect=fake_inner),
                contextlib.redirect_stderr(progress),
            ):
                advisor_runner.configure_platform(advisor_runner.CLAUDE_CODE_ADVISOR_PLATFORM)
                try:
                    exit_code = advisor_runner.run_advisory(
                        description="review",
                        role_line="role",
                        label="review",
                        lane="review",
                        output_contract="## Top Findings\n- bullet",
                        argv=[
                            "--brief-file",
                            str(brief),
                            "--output-file",
                            str(output),
                        ],
                    )
                finally:
                    advisor_runner.configure_platform(advisor_runner.CODEX_ADVISOR_PLATFORM)

            self.assertEqual(exit_code, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "final advisory\n")
            self.assertIn("[Antigravity step] progress", progress.getvalue())
            self.assertIn("[Antigravity wait] 10% (10s/100s)", progress.getvalue())


if __name__ == "__main__":
    unittest.main()
