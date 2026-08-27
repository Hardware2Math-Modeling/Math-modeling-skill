from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from suite_validation import ALL_SKILLS, STAGE_SKILLS, validate_suite  # noqa: E402


WORKFLOW_PATH = (
    ROOT
    / "skills"
    / "math-modeling-orchestrator"
    / "references"
    / "workflow.json"
)
HANDOFF_PATH = WORKFLOW_PATH.parent / "handoff-contract.md"
ORCHESTRATOR_PATH = WORKFLOW_PATH.parents[1] / "SKILL.md"
PAPER_WRITING_PATH = ROOT / "skills" / "math-modeling-paper-writing" / "SKILL.md"


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

    def test_new_skills_are_discoverable_and_method_library_is_not_a_stage(self) -> None:
        for skill in (
            "math-modeling-preflight",
            "math-modeling-visualization",
            "math-modeling-paper-production",
            "math-modeling-method-library",
        ):
            with self.subTest(skill=skill):
                self.assertIn(skill, ALL_SKILLS)
                self.assertTrue((ROOT / "skills" / skill / "SKILL.md").is_file())
                self.assertTrue(
                    (ROOT / "skills" / skill / "agents" / "openai.yaml").is_file()
                )
        stage_skills = [item["skill"] for item in self.load_workflow()["stages"]]
        self.assertNotIn("math-modeling-method-library", stage_skills)
        self.assertEqual("math-modeling-preflight", stage_skills[0])
        self.assertEqual("math-modeling-paper-production", stage_skills[-1])

    def test_validation_failure_cannot_route_to_paper_writing(self) -> None:
        workflow = self.load_workflow()
        validation_fail_destinations = workflow["transitions"]["validation-fail"]
        self.assertEqual(
            [
                "problem-analysis",
                "data-analysis",
                "model-construction",
                "model-solving",
            ],
            validation_fail_destinations,
        )
        self.assertIs(
            True,
            workflow["guards"]["paper-writing"]["requires_validation_pass"],
        )
        self.assertIs(
            True,
            workflow["guards"]["paper-writing"]["requires_no_invalidated_inputs"],
        )
        for forbidden in ("paper-writing", "paper-production", "complete"):
            self.assertNotIn(forbidden, validation_fail_destinations)

    def test_paper_writing_recommends_its_only_legal_successor(self) -> None:
        workflow = self.load_workflow()
        self.assertEqual(
            ["paper-production"],
            workflow["transitions"]["paper-writing"],
        )
        text = PAPER_WRITING_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "set `next.recommended_stage` to `paper-production`",
            text,
        )
        self.assertNotIn("set `next.recommended_stage` to `complete`", text)

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

    def test_orchestrator_starts_every_new_problem_with_preflight(self) -> None:
        text = ORCHESTRATOR_PATH.read_text(encoding="utf-8").lower()
        self.assertIn("$math-modeling-preflight", text)
        self.assertIn("first for every new problem", text)
        self.assertIn(
            "resume or skip only when an existing handoff records that stage complete",
            text,
        )

    def test_needs_revision_does_not_advance_downstream(self) -> None:
        text = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
        for rule in (
            "Workflow transitions apply after a stage returns `complete`, or after an optional stage returns `skipped` with its guard and rationale satisfied.",
            "A `needs_revision` result never advances to a downstream stage.",
            "retry the current stage",
            "earliest invalidated upstream stage",
            "rerun every invalidated downstream stage",
        ):
            self.assertIn(rule, text)

    def test_handoff_exposes_revision_state_machine_fields(self) -> None:
        workflow = self.load_workflow()
        handoff = workflow["handoff"]
        self.assertEqual(
            [
                "current_stage",
                "status",
                "validation_status",
                "completed_stages",
                "invalidated_stages",
            ],
            handoff["state_fields"],
        )
        self.assertEqual(
            ["pending", "pass", "needs_revision", "stale"],
            handoff["validation_statuses"],
        )


if __name__ == "__main__":
    unittest.main()
