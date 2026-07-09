from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = ROOT.parent / "common" / "scripts"


def _load_grok_runner() -> object:
    spec = importlib.util.spec_from_file_location("grok_runner_under_test", SHARED_SCRIPTS / "grok_runner.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load grok_runner test module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


grok_runner = _load_grok_runner()


class GrokRunnerTests(unittest.TestCase):
    def test_split_cli_command_preserves_env_assignments(self) -> None:
        command, env = grok_runner._split_cli_command("A=1 B='two words' /tmp/grok --flag", ["grok"])

        self.assertEqual(env, {"A": "1", "B": "two words"})
        self.assertEqual(command, ["/tmp/grok", "--flag"])

    def test_extract_stream_text_reads_json_events(self) -> None:
        stdout = "\n".join(
            [
                json.dumps({"type": "text", "data": "hello "}),
                json.dumps({"type": "output_text", "data": {"text": "world"}}),
                json.dumps({"type": "end", "session_id": "abc"}),
            ]
        )

        self.assertEqual(grok_runner._extract_stream_text(stdout), "hello world")
        self.assertEqual(grok_runner._extract_end_event(stdout)["type"], "end")

    def test_build_command_uses_prompt_file_and_bypass_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prompt_file = root / "prompt.txt"
            prompt_file.write_text("prompt", encoding="utf-8")
            help_text = "\n".join(
                [
                    "--cwd",
                    "--model",
                    "--reasoning-effort",
                    "--permission-mode",
                    "--always-approve",
                    "--no-memory",
                    "--verbatim",
                    "--output-format",
                    "--session-id",
                    "--prompt-file",
                ]
            )

            command, resume_used, session_id = grok_runner._build_command(
                ["grok"],
                help_text=help_text,
                prompt_file=prompt_file,
                launch_dir=root,
                model="",
                effort="",
                session="",
                new_session_id="session-1",
                output_format="streaming-json",
                permission_mode="bypassPermissions",
                sandbox="",
                always_approve=True,
                no_memory=True,
                verbatim=True,
            )

        self.assertFalse(resume_used)
        self.assertEqual(session_id, "session-1")
        self.assertIn("--permission-mode", command)
        self.assertIn("bypassPermissions", command)
        self.assertIn("--prompt-file", command)
        self.assertIn("--session-id", command)

    def test_build_command_ignores_unsupported_permission_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prompt_file = root / "prompt.txt"
            prompt_file.write_text("prompt", encoding="utf-8")

            command, _resume_used, _session_id = grok_runner._build_command(
                ["grok"],
                help_text="--cwd\n--output-format\n--session-id\n--prompt-file",
                prompt_file=prompt_file,
                launch_dir=root,
                model="",
                effort="",
                session="",
                new_session_id="session-1",
                output_format="streaming-json",
                permission_mode="bypassPermissions",
                sandbox="",
                always_approve=True,
                no_memory=True,
                verbatim=True,
            )

        self.assertNotIn("--permission-mode", command)
        self.assertNotIn("--always-approve", command)
        self.assertIn("--output-format", command)

    def test_run_grok_reads_streaming_json_from_fake_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            fake_cli = root / "fake_grok.py"
            fake_cli.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import json
                    import sys
                    if "--help" in sys.argv:
                        print("--cwd --permission-mode --always-approve --no-memory --verbatim --output-format --session-id --prompt-file")
                        raise SystemExit(0)
                    print(json.dumps({"type": "text", "data": "## Top Findings\\n- none"}), flush=True)
                    print(json.dumps({"type": "end", "session_id": "abc"}), flush=True)
                    """
                ),
                encoding="utf-8",
            )
            fake_cli.chmod(0o755)

            with patch.dict(
                os.environ,
                {
                    "CODEX_GROK_CMD": str(fake_cli),
                    "CODEX_GROK_POST_OUTPUT_GRACE": "0",
                },
                clear=False,
            ):
                result = grok_runner.run_grok(
                    "review prompt",
                    20,
                    root,
                    output_validator=lambda text: "" if "## Top Findings" in text else "missing heading",
                )

        self.assertEqual(result.returncode, 0)
        self.assertIn("## Top Findings", result.stdout)

    def test_probe_help_falls_back_to_default_support_on_help_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            fake_cli = root / "fake_grok.py"
            fake_cli.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import sys
                    print("daemon unavailable", file=sys.stderr)
                    raise SystemExit(1)
                    """
                ),
                encoding="utf-8",
            )
            fake_cli.chmod(0o755)

            self.assertEqual(grok_runner._probe_help([str(fake_cli)], root, {}), "")


if __name__ == "__main__":
    unittest.main()
