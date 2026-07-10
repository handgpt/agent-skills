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
from urllib.parse import quote


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

    def test_session_completion_probe_ignores_existing_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            updates = Path(tmp_dir) / "updates.jsonl"
            completed = {
                "params": {
                    "update": {
                        "sessionUpdate": "turn_completed",
                        "stop_reason": "end_turn",
                    }
                },
            }
            updates.write_text("审阅中\n" + json.dumps(completed) + "\n", encoding="utf-8")
            probe = grok_runner._SessionCompletionProbe(updates)

            self.assertFalse(probe.poll())
            with updates.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(completed) + "\n")
            self.assertEqual(probe.poll().stop_reason, "end_turn")

    def test_session_completion_probe_uses_last_completion_from_single_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            updates = Path(tmp_dir) / "updates.jsonl"
            updates.touch()
            probe = grok_runner._SessionCompletionProbe(updates)
            completions = [
                {
                    "params": {
                        "update": {
                            "sessionUpdate": "turn_completed",
                            "prompt_id": "first",
                            "stop_reason": "end_turn",
                        }
                    }
                },
                {
                    "params": {
                        "update": {
                            "sessionUpdate": "turn_completed",
                            "prompt_id": "second",
                            "stop_reason": "rate_limit",
                        }
                    }
                },
            ]
            with updates.open("a", encoding="utf-8") as handle:
                for completion in completions:
                    handle.write(json.dumps(completion) + "\n")

            self.assertEqual(probe.poll().stop_reason, "rate_limit")

    def test_session_completion_probe_detects_new_completion_after_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            updates = Path(tmp_dir) / "updates.jsonl"
            stale = {
                "params": {
                    "update": {
                        "sessionUpdate": "turn_completed",
                        "prompt_id": "old",
                        "stop_reason": "end_turn",
                    }
                },
            }
            current = {
                "params": {
                    "update": {
                        "sessionUpdate": "turn_completed",
                        "prompt_id": "new",
                        "stop_reason": "rate_limit",
                    }
                },
            }
            updates.write_text(json.dumps(stale) + "\n", encoding="utf-8")
            probe = grok_runner._SessionCompletionProbe(updates)

            replacement = updates.with_suffix(".replacement")
            replacement.write_text(json.dumps(stale) + "\n", encoding="utf-8")
            replacement.replace(updates)
            self.assertFalse(probe.poll())

            replacement.write_text(
                json.dumps(stale) + "\n" + json.dumps(current) + "\n",
                encoding="utf-8",
            )
            replacement.replace(updates)

            self.assertEqual(probe.poll().stop_reason, "rate_limit")

    def test_session_updates_path_uses_canonical_cwd_and_custom_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            grok_home = root / "custom-grok-home"

            updates = grok_runner._session_updates_path(
                root / "missing" / ".." / "project",
                "session-1",
                {"GROK_HOME": str(grok_home)},
            )

            self.assertEqual(updates.parent.name, "session-1")
            self.assertEqual(updates.parents[1].name, quote(str((root / "project").resolve()), safe=""))
            self.assertEqual(updates.parents[2], grok_home / "sessions")

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
                    print(json.dumps({"type": "end", "stopReason": "EndTurn", "session_id": "abc"}), flush=True)
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

    def test_run_grok_accepts_session_completion_when_stream_end_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            grok_home = root / "grok-home"
            fake_cli = root / "fake_grok.py"
            fake_cli.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import json
                    import os
                    import sys
                    import time
                    from pathlib import Path
                    from urllib.parse import quote

                    if "--help" in sys.argv:
                        print("--cwd --permission-mode --always-approve --no-memory --verbatim --output-format --session-id --prompt-file")
                        raise SystemExit(0)

                    def option(name):
                        index = sys.argv.index(name)
                        return sys.argv[index + 1]

                    session_id = option("--session-id")
                    cwd = option("--cwd")
                    updates = (
                        Path(os.environ["GROK_HOME"])
                        / "sessions"
                        / quote(str(Path(cwd).resolve()), safe="")
                        / session_id
                        / "updates.jsonl"
                    )
                    updates.parent.mkdir(parents=True)
                    print(json.dumps({"type": "text", "data": "## Top Findings\\n- complete"}), flush=True)
                    updates.write_text(
                        json.dumps({"params": {"update": {"sessionUpdate": "turn_completed", "stop_reason": "end_turn"}}}) + "\\n",
                        encoding="utf-8",
                    )
                    while True:
                        time.sleep(1)
                    """
                ),
                encoding="utf-8",
            )
            fake_cli.chmod(0o755)

            with patch.dict(
                os.environ,
                {
                    "CODEX_GROK_CMD": str(fake_cli),
                    "CODEX_GROK_POST_OUTPUT_GRACE": "0.1",
                    "GROK_HOME": str(grok_home),
                },
                clear=False,
            ):
                result = grok_runner.run_grok(
                    "review prompt",
                    10,
                    root,
                    output_validator=lambda text: "" if "## Top Findings" in text else "missing heading",
                )

        self.assertEqual(result.returncode, 0)
        self.assertIn("## Top Findings", result.stdout)

    def test_run_grok_preserves_rate_limit_diagnostics_over_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            grok_home = root / "grok-home"
            fake_cli = root / "fake_grok.py"
            fake_cli.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import json
                    import os
                    import sys
                    import time
                    from pathlib import Path
                    from urllib.parse import quote

                    if "--help" in sys.argv:
                        print("--cwd --permission-mode --always-approve --no-memory --verbatim --output-format --session-id --prompt-file")
                        raise SystemExit(0)

                    def option(name):
                        index = sys.argv.index(name)
                        return sys.argv[index + 1]

                    session_id = option("--session-id")
                    cwd = option("--cwd")
                    updates = (
                        Path(os.environ["GROK_HOME"])
                        / "sessions"
                        / quote(str(Path(cwd).resolve()), safe="")
                        / session_id
                        / "updates.jsonl"
                    )
                    updates.parent.mkdir(parents=True)
                    print(json.dumps({"type": "text", "data": "I'll inspect the workspace first."}), flush=True)
                    print(
                        "API error (status 429 Too Many Requests): subscription:free-usage-exhausted",
                        file=sys.stderr,
                        flush=True,
                    )
                    updates.write_text(
                        json.dumps({"params": {"update": {"sessionUpdate": "turn_completed", "stop_reason": "rate_limit"}}}) + "\\n",
                        encoding="utf-8",
                    )
                    while True:
                        time.sleep(1)
                    """
                ),
                encoding="utf-8",
            )
            fake_cli.chmod(0o755)

            with patch.dict(
                os.environ,
                {
                    "CODEX_GROK_CMD": str(fake_cli),
                    "CODEX_GROK_POST_OUTPUT_GRACE": "0.1",
                    "GROK_HOME": str(grok_home),
                },
                clear=False,
            ):
                result = grok_runner.run_grok(
                    "review prompt",
                    10,
                    root,
                    output_validator=lambda _text: "meta chatter instead of findings",
                )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("I'll inspect", result.stdout)
        self.assertIn("429 Too Many Requests", result.stderr)
        self.assertIn("stop_reason=rate_limit", result.stderr)
        self.assertIn("meta chatter instead of findings", result.stderr)

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
