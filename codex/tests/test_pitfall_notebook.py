from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "pitfall-notebook"
SCRIPT_PATH = SKILL_DIR / "scripts" / "update_pitfall_notebook.py"

spec = importlib.util.spec_from_file_location("update_pitfall_notebook", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules.setdefault("update_pitfall_notebook", module)
spec.loader.exec_module(module)


class PitfallNotebookTests(unittest.TestCase):
    def test_update_notebook_creates_compact_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            notebook_path = Path(tmp_dir) / ".codex-pitfalls.md"
            updated_path = module.update_notebook(
                notebook_path=notebook_path,
                title=" Pytest cache after module move ",
                symptom=" import path still points to old module ",
                cause=" pytest cache and stale pycache ",
                rule=" clear caches after package moves ",
            )

            text = updated_path.read_text(encoding="utf-8")
            self.assertIn("# Codex Pitfalls", text)
            self.assertIn("## ", text)
            self.assertIn("- Symptom: import path still points to old module", text)
            self.assertIn("- Cause: pytest cache and stale pycache", text)
            self.assertIn("- Rule: clear caches after package moves", text)

    def test_update_notebook_dedupes_by_normalized_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            notebook_path = Path(tmp_dir) / ".codex-pitfalls.md"
            module.update_notebook(
                notebook_path=notebook_path,
                title="Same Pitfall",
                symptom="old symptom",
                cause="old cause",
                rule="old rule",
            )
            module.update_notebook(
                notebook_path=notebook_path,
                title=" same   pitfall ",
                symptom="new symptom",
                cause="new cause",
                rule="new rule",
            )

            text = notebook_path.read_text(encoding="utf-8")
            self.assertEqual(text.count("## "), 1)
            self.assertIn("new symptom", text)
            self.assertNotIn("old symptom", text)

    def test_main_uses_detected_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            with mock.patch.object(module, "detect_project_root", return_value=project_root):
                exit_code = module.main(
                    [
                        "--title",
                        "Network timeout hides root cause",
                        "--symptom",
                        "retry loop masks original failure",
                        "--cause",
                        "outer timeout swallowed inner exception",
                        "--rule",
                        "preserve original error in retry wrappers",
                    ]
                )

            self.assertEqual(exit_code, 0)
            notebook_text = (project_root / ".codex-pitfalls.md").read_text(encoding="utf-8")
            self.assertIn("Network timeout hides root cause", notebook_text)

    def test_update_notebook_enforces_rolling_buffer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            notebook_path = Path(tmp_dir) / ".codex-pitfalls.md"
            for index in range(module.MAX_ENTRIES + 2):
                module.update_notebook(
                    notebook_path=notebook_path,
                    title=f"pitfall {index}",
                    symptom=f"symptom {index}",
                    cause=f"cause {index}",
                    rule=f"rule {index}",
                )

            text = notebook_path.read_text(encoding="utf-8")
            self.assertEqual(text.count("## "), module.MAX_ENTRIES)
            self.assertIn("pitfall 11", text)
            self.assertNotIn("pitfall 0", text)

    def test_load_entries_handles_malformed_file_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            notebook_path = Path(tmp_dir) / ".codex-pitfalls.md"
            notebook_path.write_text("# Codex Pitfalls\n\nthis file was edited badly\n", encoding="utf-8")

            entries = module.load_entries(notebook_path)

            self.assertEqual(entries, [])
