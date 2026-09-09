from __future__ import annotations

from argparse import Namespace
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = ROOT / "skills" / "advisor-review"
SCRIPT_PATH = REVIEW_DIR / "scripts" / "run_advisor_review.py"

spec = importlib.util.spec_from_file_location("run_advisor_review", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules.setdefault("run_advisor_review", module)
spec.loader.exec_module(module)


class AdvisorReviewPromptTests(unittest.TestCase):
    def test_standard_output_contract_mentions_external_advisor_and_simplification(self) -> None:
        contract = module.build_output_contract(Namespace(mode="standard", focus="code"))
        self.assertIn("selected external advisor CLI", contract)
        self.assertIn("dead, redundant, over-complicated, or safe to simplify", contract)
        self.assertIn("preserves behavior, failure handling, and readability", contract)

    def test_structural_output_contract_mentions_architecture_scope(self) -> None:
        contract = module.build_output_contract(Namespace(mode="structural", focus="code"))
        self.assertIn("## Structural & Architectural Risks", contract)
        self.assertIn("This is structural mode", contract)
        self.assertIn("surrounding modules, sibling directories, ownership boundaries", contract)

    def test_artifact_output_contract_mentions_non_code_review_scope(self) -> None:
        contract = module.build_output_contract(Namespace(mode="standard", focus="article"))
        self.assertIn("## Accuracy & Evidence Risks", contract)
        self.assertIn("artifact satisfies its stated audience", contract)
        self.assertIn("prompt or workflow artifacts", contract)

    def test_structural_artifact_contract_keeps_structural_scope(self) -> None:
        contract = module.build_output_contract(Namespace(mode="structural", focus="doc"))
        self.assertIn("## Structure & Organization Risks", contract)
        self.assertIn("structural artifact mode", contract)



if __name__ == "__main__":
    unittest.main()
