from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from suite_validation import STAGE_SKILLS, validate_suite  # noqa: E402


WORKFLOW_PATH = (
    ROOT
    / "skills"
    / "math-modeling-orchestrator"
    / "references"
    / "workflow.json"
)
HANDOFF_PATH = WORKFLOW_PATH.parent / "handoff-contract.md"


class RepositoryContractTests(unittest.TestCase):
    def load_workflow(self) -> dict[str, object]:
        self.assertTrue(WORKFLOW_PATH.is_file(), f"missing workflow: {WORKFLOW_PATH}")
        return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))

    def test_repository_suite_is_valid(self) -> None:
        self.assertEqual([], validate_suite(ROOT))

    def test_workflow_registers_each_stage_once_in_order(self) -> None:
        workflow = self.load_workflow()
        stages = workflow["stages"]
        self.assertIsInstance(stages, list)
        skills = [stage["skill"] for stage in stages]
        self.assertEqual(list(STAGE_SKILLS), skills)
        self.assertEqual(len(skills), len(set(skills)))

    def test_validation_failure_cannot_route_to_paper_writing(self) -> None:
        workflow = self.load_workflow()
        validation_fail_destinations = workflow["transitions"]["validation-fail"]
        self.assertNotIn("paper-writing", validation_fail_destinations)
        self.assertIs(
            True,
            workflow["guards"]["paper-writing"]["requires_validation_pass"],
        )

    def test_handoff_contract_uses_canonical_schema_keys(self) -> None:
        contract = HANDOFF_PATH.read_text(encoding="utf-8")
        for key in (
            "statement",
            "objectives",
            "constraints",
            "current_stage",
            "warnings",
            "confidence",
            "rationale",
            "alternatives",
        ):
            self.assertRegex(contract, rf"(?m)^\s*{key}:")
        for legacy in ("title", "source", "stage", "reason", "needs"):
            self.assertNotRegex(contract, rf"(?m)^\s*{legacy}:")

    def test_stage_outputs_name_canonical_handoff_keys(self) -> None:
        for skill in STAGE_SKILLS:
            text = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
            with self.subTest(skill=skill):
                self.assertIn("state.current_stage", text)
                self.assertIn("quality.warnings", text)
                self.assertIn("quality.confidence", text)
                self.assertIn("next.rationale", text)
                self.assertIn("next.alternatives", text)
                self.assertNotIn("state.stage", text)
                self.assertNotIn("next.reason", text)
                self.assertNotIn("next.needs", text)


if __name__ == "__main__":
    unittest.main()
