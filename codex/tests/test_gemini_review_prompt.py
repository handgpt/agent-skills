from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = ROOT / "skills" / "gemini-review"
SCRIPT_PATH = REVIEW_DIR / "scripts" / "run_gemini_review.py"

spec = importlib.util.spec_from_file_location("run_gemini_review", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules.setdefault("run_gemini_review", module)
spec.loader.exec_module(module)


class GeminiReviewPromptTests(unittest.TestCase):
    def test_output_contract_mentions_safe_simplification_scope(self) -> None:
        contract = module.OUTPUT_CONTRACT
        self.assertIn("dead, redundant, over-complicated, or safe to simplify", contract)
        self.assertIn("Prioritize correctness and behavioral risk first", contract)
        self.assertIn("preserves behavior, failure handling, and readability", contract)

    def test_skill_docs_describe_dead_code_and_bloat_review(self) -> None:
        skill_text = (REVIEW_DIR / "SKILL.md").read_text(encoding="utf-8")
        agent_text = (REVIEW_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
        template_text = (REVIEW_DIR / "references" / "review-brief-template.md").read_text(encoding="utf-8")

        self.assertIn("dead code", skill_text)
        self.assertIn("implementation bloat", skill_text)
        self.assertIn("unused code", agent_text)
        self.assertIn("implementation bloat", template_text)


if __name__ == "__main__":
    unittest.main()
