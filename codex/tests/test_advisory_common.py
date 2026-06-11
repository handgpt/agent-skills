from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys


ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = ROOT.parent / "common" / "scripts"
if str(SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPTS))

import advisory_common


class AdvisoryCommonTests(unittest.TestCase):
    def test_describe_paths_filters_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "workspace"
            project_root.mkdir()
            inside_dir = project_root / "skills"
            inside_dir.mkdir()
            missing_inside = project_root / "missing.txt"
            outside_dir = Path(tmp_dir) / "outside"
            outside_dir.mkdir()

            entries = advisory_common.describe_paths(
                [str(inside_dir), str(missing_inside), str(outside_dir)],
                project_root,
            )

            self.assertEqual(
                entries,
                [f"- {inside_dir} [directory]", f"- {missing_inside} [missing]"],
            )

    def test_describe_paths_skips_symlink_to_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project_root = root / "workspace"
            project_root.mkdir()
            outside_file = root / "outside.txt"
            outside_file.write_text("outside", encoding="utf-8")
            linked_outside = project_root / "linked-outside.txt"
            linked_outside.symlink_to(outside_file)

            entries = advisory_common.describe_paths([str(linked_outside)], project_root)

            self.assertEqual(entries, [])

    def test_normalize_multi_project_roots_prefers_explicit_roots_within_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_root = Path(tmp_dir) / "workspace"
            ios_root = workspace_root / "ios"
            server_root = workspace_root / "server"
            ios_root.mkdir(parents=True)
            server_root.mkdir(parents=True)

            roots = advisory_common._normalize_multi_project_roots(
                [str(ios_root), str(server_root)],
                [],
                workspace_root,
                workspace_root,
            )

            self.assertEqual(roots, (ios_root.resolve(), server_root.resolve()))

    def test_output_validator_rejects_meta_chatter(self) -> None:
        validator = advisory_common.build_output_validator(
            "## Likely Causes\n- bullet\n\n## Confidence\nOne short paragraph."
        )

        self.assertIn(
            "meta chatter",
            validator("I will inspect the files now and report back."),
        )

    def test_output_normalizer_strips_leading_meta_preamble_before_heading(self) -> None:
        normalizer = advisory_common.build_output_normalizer(
            "## Verdict\n- bullet\n\n## Recommendation\n- bullet"
        )

        self.assertEqual(
            normalizer(
                "I will inspect the files now.\n\n## Verdict\nLooks sound.\n\n## Recommendation\n- proceed"
            ),
            "## Verdict\nLooks sound.\n\n## Recommendation\n- proceed",
        )


if __name__ == "__main__":
    unittest.main()
