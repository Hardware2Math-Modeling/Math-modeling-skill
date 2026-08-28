from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from handoff_schema import migrate_payload, validate_document  # noqa: E402


ORCHESTRATOR = ROOT / "skills" / "math-modeling-orchestrator" / "SKILL.md"
HANDOFF_CONTRACT = (
    ROOT
    / "skills"
    / "math-modeling-orchestrator"
    / "references"
    / "handoff-contract.md"
)
CUMCM_PACK = (
    ROOT
    / "skills"
    / "math-modeling-orchestrator"
    / "references"
    / "competition-packs"
    / "cumcm.json"
)
PROBLEM_ANALYSIS = ROOT / "skills" / "math-modeling-problem-analysis" / "SKILL.md"
DATA_ANALYSIS = ROOT / "skills" / "math-modeling-data-analysis" / "SKILL.md"
OPENAI_YAML = (
    ROOT / "skills" / "math-modeling-orchestrator" / "agents" / "openai.yaml"
)


def fenced_json_after(text: str, heading: str) -> dict[str, object]:
    """Return the first JSON object after a unique contract heading."""

    start = text.index(heading) + len(heading)
    fence = text.index("```json", start) + len("```json")
    end = text.index("```", fence)
    payload = json.loads(text[fence:end])
    if type(payload) is not dict:
        raise AssertionError(f"{heading} must own one JSON object")
    return payload


class OrchestratorContractTests(unittest.TestCase):
    def test_cumcm_pack_is_exact_nonfactual_machine_contract(self) -> None:
        """Catches invented current-year facts and drift in page/gate defaults."""

        pack = json.loads(CUMCM_PACK.read_text(encoding="utf-8"))
        self.assertEqual(
            {
                "competition": "CUMCM",
                "language": "zh-CN",
                "requires_official_verification": True,
                "gate_ids": ["gate1", "gate2", "gate3"],
                "paper_defaults": {
                    "body_pages": {"minimum": 25, "maximum": 27},
                    "total_pages": {"maximum": 30},
                },
                "official_sources": [],
            },
            pack,
        )

    def test_empty_official_sources_blocks_submission_ready_claim(self) -> None:
        """Catches treating an unverified competition pack as current official rules."""

        pack = json.loads(CUMCM_PACK.read_text(encoding="utf-8"))
        self.assertEqual([], pack["official_sources"])
        text = ORCHESTRATOR.read_text(encoding="utf-8")
        for predicate in (
            "official_sources: []",
            "submission-ready",
            "source",
            "SHA-256",
            "verification date",
        ):
            self.assertIn(predicate, text)

    def test_v1_chat_handoff_migrates_to_runtime_valid_v2_without_evidence_loss(self) -> None:
        """Catches bypassing migration or dropping equations, artifacts, and failed runs."""

        legacy = {
            "schema_version": "1",
            "task": {
                "statement": "保留完整题面",
                "objectives": ["回答 Q1 与 Q2"],
                "constraints": ["保留原始单位"],
            },
            "state": {"current_stage": "model-solving", "status": "complete"},
            "context": {
                "equations": [{"id": "eq-1", "expression": "y = ax + b"}],
                "assumptions": [],
            },
            "artifacts": [
                {
                    "path": "artifacts/failed-run.json",
                    "kind": "failed-run",
                    "description": "Preserved failed solver attempt.",
                    "sha256": "a" * 64,
                }
            ],
            "result": {
                "summary": "旧求解结果",
                "evidence": ["failed run: infeasible at seed 7"],
            },
            "next": {"rationale": "复核旧证据后再路由"},
        }
        migrated = migrate_payload(legacy)
        self.assertEqual([], validate_document(migrated, kind="handoff", mode="runtime"))
        self.assertEqual("保留完整题面", migrated["task"]["statement"])
        self.assertEqual(legacy["context"]["equations"], migrated["context"]["equations"])
        self.assertEqual(legacy["artifacts"], migrated["artifacts"])
        self.assertEqual(legacy["result"]["evidence"], migrated["result"]["evidence"])
        contract = HANDOFF_CONTRACT.read_text(encoding="utf-8")
        self.assertIn('schema_version: "2"', contract)
        self.assertIn("scripts/migrate_handoff.py", contract)
        self.assertIn("--mode runtime", contract)

    def test_new_problem_and_missing_preflight_evidence_route_to_preflight(self) -> None:
        """Catches authority or urgency skipping the mandatory first stage."""

        text = ORCHESTRATOR.read_text(encoding="utf-8")
        self.assertIn("$math-modeling-preflight", text)
        self.assertIn("before invoking problem analysis", text)
        self.assertIn("missing current preflight evidence", text)

    def test_missing_user_python_path_pauses_without_guessing(self) -> None:
        """Catches resolving PATH or switching interpreters when evidence is absent."""

        text = ORCHESTRATOR.read_text(encoding="utf-8")
        for predicate in (
            "user-provided absolute Python path",
            "pause",
            "do not guess",
            "do not switch",
        ):
            self.assertIn(predicate, text)

    def test_gate_examples_are_exact_runtime_valid_confirmed_records(self) -> None:
        """Catches oral approval or current.json status replacing auditable gate records."""

        contract = HANDOFF_CONTRACT.read_text(encoding="utf-8")
        for gate_id in ("gate1", "gate2", "gate3"):
            record = fenced_json_after(contract, f"### {gate_id} confirmed record")
            self.assertEqual(gate_id, record["gate_id"])
            self.assertEqual("confirmed", record["status"])
            self.assertEqual([], validate_document(record, kind="gate"))
            self.assertEqual(
                {
                    "schema_version",
                    "gate_id",
                    "status",
                    "confirmed_by",
                    "confirmed_at",
                    "confirmation",
                    "artifact_scope",
                    "artifact_hashes",
                    "notes",
                    "rollback_stage",
                },
                set(record),
            )
            self.assertEqual(
                "trusted_user_event",
                record["confirmation"]["provenance_type"],
            )
            self.assertEqual(
                [item["sha256"] for item in record["artifact_scope"]],
                record["artifact_hashes"],
            )
        text = ORCHESTRATOR.read_text(encoding="utf-8")
        self.assertIn("Oral approval", text)
        self.assertIn("current.json", text)
        self.assertIn("host verifier", text)

    def test_gate_placement_is_fail_closed(self) -> None:
        """Catches model, solve, or paper routes occurring before their decision gate."""

        text = ORCHESTRATOR.read_text(encoding="utf-8")
        for predicate in (
            "Gate 1 after problem analysis and assumptions",
            "Gate 2 after model, baseline, and validation plan",
            "Gate 3 after current validation, results, and figures",
            "Gate 3 confirmed before paper-writing",
        ):
            self.assertIn(predicate, text)

    def test_mixed_question_sources_and_staleness_precede_rerouting(self) -> None:
        """Catches overwriting unaffected Qn sources or reusing stale downstream evidence."""

        iteration = {
            "schema_version": "2",
            "project_id": "pressure-case",
            "active_iteration": "v002",
            "question_sources": {"Q1": "v001", "Q2": "v002"},
            "gates": {"gate1": "stale", "gate2": "stale", "gate3": "stale"},
            "status": "stale",
            "updated_at": "2026-08-27T00:00:00Z",
        }
        self.assertEqual([], validate_document(iteration, kind="iteration"))
        text = ORCHESTRATOR.read_text(encoding="utf-8")
        for predicate in (
            "question_sources",
            "new-iteration",
            "input, code, parameter, or method",
            "mark_stale",
            "before rerouting",
            "unaffected question sources",
        ):
            self.assertIn(predicate, text)

    def test_recommendation_and_nonpass_status_never_authorize_forward_or_complete(self) -> None:
        """Catches recommended_stage or unknown/failure being promoted to permission."""

        contract = HANDOFF_CONTRACT.read_text(encoding="utf-8")
        for predicate in (
            "recommendation, not permission",
            "needs_revision",
            "unknown",
            "failure",
            "cannot authorize a forward transition or `complete`",
        ):
            self.assertIn(predicate, contract)

    def test_external_data_approval_is_exact_and_required_before_download(self) -> None:
        """Catches a URL or vague authorization triggering an unapproved download."""

        contract = HANDOFF_CONTRACT.read_text(encoding="utf-8")
        approval = fenced_json_after(contract, "### External-data approval record")
        self.assertEqual(
            {"purpose", "fields", "source", "license", "risk", "user_confirmation"},
            set(approval),
        )
        self.assertIs(approval["user_confirmation"], True)
        text = DATA_ANALYSIS.read_text(encoding="utf-8")
        for phrase in ("用途", "字段", "许可证", "用户确认", "before any download"):
            self.assertIn(phrase, text)
        self.assertIn("user_confirmation: true", text)

    def test_official_read_only_verification_records_source_hash_and_date(self) -> None:
        """Catches untraceable official-rule/template checks and stale compliance claims."""

        contract = HANDOFF_CONTRACT.read_text(encoding="utf-8")
        record = fenced_json_after(contract, "### Official verification record")
        self.assertEqual(
            [], validate_document(record, kind="official-verification")
        )
        self.assertEqual("CUMCM", record["competition"])
        self.assertTrue(record["source_url"].startswith(("https://", "http://")))
        text = ORCHESTRATOR.read_text(encoding="utf-8")
        self.assertIn("official rule or template", text)
        self.assertIn("read-only verification", text)
        self.assertIn("official-verification.schema.json", text)

    def test_paper_routes_require_current_evidence_and_fail_closed_pauses(self) -> None:
        """Catches drafting/production on stale validation, missing content, or failed QA."""

        text = ORCHESTRATOR.read_text(encoding="utf-8")
        for predicate in (
            "current validation pass",
            "Gate 3 confirmed",
            "no invalidated inputs",
            "current complete paper content",
            "template conflict",
            "page-gate failure",
            "pause",
            "needs_revision",
        ):
            self.assertIn(predicate, text)

    def test_problem_analysis_owns_gate1_decision_material(self) -> None:
        """Catches Gate 1 being requested before question and assumption evidence exists."""

        text = PROBLEM_ANALYSIS.read_text(encoding="utf-8")
        self.assertIn("Gate 1", text)
        self.assertIn("subproblems", text)
        self.assertIn("model-changing assumptions", text)
        self.assertIn("external-data needs", text)

    def test_orchestrator_ui_metadata_preserves_invocation_policy(self) -> None:
        """Catches metadata edits disabling discovery or dropping explicit invocation."""

        text = OPENAI_YAML.read_text(encoding="utf-8")
        self.assertIn("$math-modeling-orchestrator", text)
        self.assertIn("allow_implicit_invocation: true", text)


if __name__ == "__main__":
    unittest.main()
