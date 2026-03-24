from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "gemini-error-analysis"
SCRIPT_PATH = SKILL_DIR / "scripts" / "run_gemini_error_analysis.py"

spec = importlib.util.spec_from_file_location("run_gemini_error_analysis", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules.setdefault("run_gemini_error_analysis", module)
spec.loader.exec_module(module)


class GeminiErrorAnalysisPromptTests(unittest.TestCase):
    def test_output_contract_separates_code_and_environment(self) -> None:
        contract = module.OUTPUT_CONTRACT
        self.assertIn("## Code Logic Errors", contract)
        self.assertIn("## Environmental Issues", contract)
        self.assertIn("If the evidence is weak or incomplete, say so explicitly", contract)
        self.assertIn("Prefer to start with `## Likely Causes`", contract)
        self.assertIn("Do not narrate your inspection process", contract)
        self.assertIn("Do not ask what to do next", contract)

    def test_skill_docs_require_log_pruning(self) -> None:
        skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        template_text = (SKILL_DIR / "references" / "error-brief-template.md").read_text(encoding="utf-8")
        agent_text = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")

        self.assertIn("prune the failure locally", skill_text)
        self.assertIn("priority starting hints", skill_text)
        self.assertIn("may inspect any other workspace-local files or directories", skill_text)
        self.assertIn("Pruned Log Excerpt", template_text)
        self.assertIn("Environment Notes", template_text)
        self.assertIn("non-obvious build, test, runtime, or tooling failure", agent_text)

    def test_main_delegates_to_shared_runner(self) -> None:
        with mock.patch.object(module.gemini_runner, "run_advisory", return_value=0) as run_advisory:
            self.assertEqual(module.main(), 0)

        kwargs = run_advisory.call_args.kwargs
        self.assertEqual(kwargs["label"], "error analysis")
        self.assertEqual(kwargs["lane"], "error")
        self.assertIn("## Likely Causes", kwargs["output_contract"])


if __name__ == "__main__":
    unittest.main()
