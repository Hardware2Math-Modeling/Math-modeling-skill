from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    ROOT
    / "skills"
    / "math-modeling-orchestrator"
    / "references"
    / "workflow.json"
)
PAPER_WRITING_PATH = ROOT / "skills" / "math-modeling-paper-writing" / "SKILL.md"


class WorkflowContractTests(unittest.TestCase):
    def load_workflow(self) -> dict[str, object]:
        return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))

    def test_schema_stages_and_optionality_are_exact(self) -> None:
        workflow = self.load_workflow()
        self.assertEqual("2", workflow["schema_version"])
        self.assertEqual(
            [
                ("preflight", "math-modeling-preflight", False),
                ("problem-analysis", "math-modeling-problem-analysis", False),
                ("data-analysis", "math-modeling-data-analysis", True),
                ("model-construction", "math-modeling-model-construction", False),
                ("model-solving", "math-modeling-model-solving", False),
                ("visualization", "math-modeling-visualization", True),
                ("validation", "math-modeling-validation", False),
                ("paper-writing", "math-modeling-paper-writing", True),
                ("paper-production", "math-modeling-paper-production", True),
            ],
            [
                (stage["id"], stage["skill"], stage["optional"])
                for stage in workflow["stages"]
            ],
        )

    def test_transitions_are_exact(self) -> None:
        self.assertEqual(
            {
                "preflight": ["problem-analysis"],
                "problem-analysis": ["data-analysis", "model-construction"],
                "data-analysis": ["model-construction"],
                "model-construction": ["model-solving"],
                "model-solving": ["visualization", "validation"],
                "visualization": ["validation"],
                "validation-pass": ["paper-writing", "complete"],
                "validation-fail": [
                    "problem-analysis",
                    "data-analysis",
                    "model-construction",
                    "model-solving",
                ],
                "paper-writing": ["paper-production"],
                "paper-production": ["complete"],
            },
            self.load_workflow()["transitions"],
        )

    def test_paper_and_visualization_guards_are_exact(self) -> None:
        guards = self.load_workflow()["guards"]
        self.assertEqual(
            {
                "allowed": True,
                "requires_reason": True,
                "requires_no_figure_claim": True,
            },
            guards["visualization-skip"],
        )
        self.assertEqual(
            {
                "optional": True,
                "requires_trusted_paper_request": True,
                "requires_current_question_dependencies": True,
                "requires_paper_writing": True,
            },
            guards["paper-production"],
        )
        self.assertEqual(
            {
                "optional": True,
                "requires_trusted_paper_request": True,
                "requires_current_question_dependencies": True,
                "requires_validation_pass": True,
                "requires_gate3": True,
                "requires_no_invalidated_inputs": True,
            },
            guards["paper-writing"],
        )

    def test_workflow_points_to_authoritative_non_exhaustive_policy(self) -> None:
        """Catches callers treating the compact workflow guard index as permission."""

        self.assertEqual(
            {
                "evaluator": "scripts/orchestrator_policy.py:authorization_errors",
                "workflow_guards_exhaustive": False,
            },
            self.load_workflow().get("authorization_policy"),
        )

    def test_failed_validation_cannot_reach_paper_or_complete(self) -> None:
        failed = self.load_workflow()["transitions"]["validation-fail"]
        for forbidden in ("paper-writing", "paper-production", "complete"):
            self.assertNotIn(forbidden, failed)

    def test_paper_writing_instruction_matches_workflow_successor(self) -> None:
        workflow = self.load_workflow()
        successors = workflow["transitions"]["paper-writing"]
        self.assertEqual(["paper-production"], successors)
        text = PAPER_WRITING_PATH.read_text(encoding="utf-8")
        self.assertIn(
            f"set `next.recommended_stage` to `{successors[0]}`",
            text,
        )


if __name__ == "__main__":
    unittest.main()
