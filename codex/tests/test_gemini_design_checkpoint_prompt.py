from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "gemini-design-checkpoint"
SCRIPT_PATH = SKILL_DIR / "scripts" / "run_gemini_design_check.py"

spec = importlib.util.spec_from_file_location("run_gemini_design_check", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules.setdefault("run_gemini_design_check", module)
spec.loader.exec_module(module)


class GeminiDesignCheckpointPromptTests(unittest.TestCase):
    def test_output_contract_requires_best_practice_and_source_checks(self) -> None:
        contract = module.OUTPUT_CONTRACT
        self.assertIn("## Best-Practice Alignment", contract)
        self.assertIn("## System-Level Risks", contract)
        self.assertIn("## Module-Level Risks", contract)
        self.assertIn("consult official documentation and community experience", contract)
        self.assertIn("overall architecture and the module-level design", contract)
        self.assertIn("Seek disconfirming evidence", contract)
        self.assertIn("Treat a deviation from default best practice as justified only when", contract)

    def test_docs_require_official_and_community_context(self) -> None:
        skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        template_text = (SKILL_DIR / "references" / "design-brief-template.md").read_text(encoding="utf-8")
        agent_text = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")

        self.assertIn("official documentation and real community experience", skill_text)
        self.assertIn("priority starting points", skill_text)
        self.assertIn("may inspect any other workspace-local files or directories", skill_text)
        self.assertIn("disconfirming evidence", skill_text)
        self.assertIn("Relevant Official Docs", template_text)
        self.assertIn("Relevant Community References", template_text)
        self.assertIn("deviates from a default best practice", template_text)
        self.assertIn("official docs and community experience", agent_text)

    def test_main_delegates_to_shared_runner(self) -> None:
        with mock.patch.object(module.gemini_runner, "run_advisory", return_value=0) as run_advisory:
            self.assertEqual(module.main(), 0)

        kwargs = run_advisory.call_args.kwargs
        self.assertEqual(kwargs["label"], "design checkpoint")
        self.assertEqual(kwargs["lane"], "design")
        self.assertIn("## Best-Practice Alignment", kwargs["output_contract"])


if __name__ == "__main__":
    unittest.main()
