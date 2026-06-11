from __future__ import annotations

from argparse import Namespace
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = ROOT / "skills" / "agy-review"
SCRIPT_PATH = REVIEW_DIR / "scripts" / "run_agy_review.py"

spec = importlib.util.spec_from_file_location("run_agy_review", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules.setdefault("run_agy_review", module)
spec.loader.exec_module(module)


class AgyReviewPromptTests(unittest.TestCase):
    def test_standard_output_contract_mentions_antigravity_and_simplification(self) -> None:
        contract = module.build_output_contract(Namespace(mode="standard"))
        self.assertIn("Antigravity CLI", contract)
        self.assertIn("dead, redundant, over-complicated, or safe to simplify", contract)
        self.assertIn("preserves behavior, failure handling, and readability", contract)

    def test_structural_output_contract_mentions_architecture_scope(self) -> None:
        contract = module.build_output_contract(Namespace(mode="structural"))
        self.assertIn("## Structural & Architectural Risks", contract)
        self.assertIn("This is structural mode", contract)
        self.assertIn("surrounding modules, sibling directories, ownership boundaries", contract)

    def test_skill_docs_describe_interactive_mode_and_default_model(self) -> None:
        skill_text = (REVIEW_DIR / "SKILL.md").read_text(encoding="utf-8")
        agent_text = (REVIEW_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
        template_text = (REVIEW_DIR / "references" / "review-brief-template.md").read_text(encoding="utf-8")

        self.assertIn("agy -i", skill_text)
        self.assertIn('`--model "Gemini 3.5 Flash (High)"`', skill_text)
        self.assertIn("Claude Opus 4.6 (Thinking)", skill_text)
        self.assertIn("priority starting hints", skill_text)
        self.assertIn("structural mode", agent_text)
        self.assertIn("Relevant Modules Or Directories", template_text)


if __name__ == "__main__":
    unittest.main()
