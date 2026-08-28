from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "scripts" / "orchestrator_policy.py"
SCRIPTS = ROOT / "scripts"
SCHEMAS = ROOT / "skills/math-modeling-orchestrator/references/schemas"
HANDOFF_FIXTURE = ROOT / "tests/fixtures/handoff-v2.json"
sys.path.insert(0, str(SCRIPTS))

from handoff_schema import validate_document  # noqa: E402
from orchestrator_policy import authorization_errors  # noqa: E402
from tests.test_paper_content import valid_content  # noqa: E402


DIGEST = "a" * 64
PYTHON = "/opt/user-selected/python"


def confirmed_gate(gate_id: str) -> dict[str, object]:
    confirmation = {
        "schema_version": "2",
        "actor_type": "user",
        "confirmation_method": "explicit",
        "confirmed_by": "project owner",
        "confirmed_at": "2026-08-27T12:00:00Z",
        "artifact_hashes": [DIGEST],
    }
    return {
        "schema_version": "2",
        "gate_id": gate_id,
        "status": "confirmed",
        "confirmed_by": "project owner",
        "confirmed_at": "2026-08-27T12:00:00Z",
        "confirmation": confirmation,
        "artifact_hashes": [DIGEST],
        "notes": "Explicitly confirmed against the current artifact.",
        "rollback_stage": None,
    }


def valid_external_approval() -> dict[str, object]:
    return {
        "purpose": "Obtain public demand observations for Q1.",
        "fields": ["date", "demand"],
        "source": "https://example.invalid/data.csv",
        "license": "CC-BY-4.0",
        "risk": "The source may contain revisions or missing dates.",
        "user_confirmation": True,
    }


def complete_content_record() -> dict[str, object]:
    content = valid_content(1)
    return {
        "schema_version": "1",
        "status": "complete",
        "content": content,
        "evidence": [
            {
                "path": "results/q1-result.json",
                "sha256": "a" * 64,
            }
        ],
    }


def valid_authorization_evidence() -> dict[str, object]:
    handoff = json.loads(HANDOFF_FIXTURE.read_text(encoding="utf-8"))
    handoff["state"].update(
        {
            "current_stage": "paper-writing",
            "status": "complete",
            "validation_status": "pass",
            "completed_stages": [
                "preflight",
                "problem-analysis",
                "model-construction",
                "model-solving",
                "validation",
                "paper-writing",
            ],
            "invalidated_stages": [],
        }
    )
    handoff["artifacts"] = [
        {
            "path": "artifacts/current-validation.json",
            "kind": "validation",
            "description": "Current validation and result evidence.",
            "sha256": DIGEST,
        }
    ]
    return {
        "handoff": handoff,
        "iteration": {
            "schema_version": "2",
            "project_id": "example-project",
            "active_iteration": "v001",
            "question_sources": {"Q1": "v001"},
            "gates": {
                "gate1": "confirmed",
                "gate2": "confirmed",
                "gate3": "confirmed",
            },
            "status": "in_progress",
            "updated_at": "2026-08-27T12:01:00Z",
        },
        "initialization": {
            "schema_version": "2",
            "competition": "CUMCM",
            "python_executable": PYTHON,
            "template_path": None,
            "created_at": "2026-08-27T11:00:00Z",
        },
        "preflight": {
            "status": "pass",
            "project_root": "/project",
            "python": {
                "status": "pass",
                "path": PYTHON,
                "resolved_path": PYTHON,
                "reported_executable": PYTHON,
                "version": "Python 3.13.5",
                "platform": "fixture-platform",
                "error": None,
            },
            "packages": [],
            "latex": {
                "status": "pass",
                "selected": "xelatex",
                "tools": [],
                "message": "fixture tool is available",
            },
            "pdf_renderer": {
                "name": "pdftoppm",
                "status": "not_supplied",
                "path": None,
                "sha256": None,
                "version_command": None,
                "version_exit_code": None,
                "version_signature": None,
                "version_output": None,
                "version_output_sha256": None,
                "trust_basis": "user_supplied_preflight_binary",
            },
            "template": {
                "status": "user_provided",
                "requested_path": "/project/template.tex",
                "resolved_path": "/project/template.tex",
                "message": "user template is available",
            },
            "blockers": [],
            "warnings": [],
        },
        "gate_report": {
            "schema_version": "2",
            "records": [
                confirmed_gate("gate1"),
                confirmed_gate("gate2"),
                confirmed_gate("gate3"),
            ],
        },
        "paper_content": complete_content_record(),
        "template_check": {"status": "pass", "conflicts": []},
        "page_gate": {
            "status": "pass",
            "total_pages": 26,
            "body_pages": 26,
            "body_range": {"start": 1, "end": 26, "pages": 26},
            "target_body_pages": {"minimum": 25, "maximum": 27},
            "maximum_total_pages": 30,
            "failed_checks": [],
            "actions": [],
            "no_padding": True,
        },
        "external_data_approval": valid_external_approval(),
    }


class OrchestratorPolicyApiTests(unittest.TestCase):
    def test_policy_imports_through_repository_package_path(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-c", "from scripts.orchestrator_policy import authorization_errors"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_authorization_policy_exposes_error_evaluator(self) -> None:
        """Catches removal of the executable authorization decision boundary."""

        self.assertTrue(
            POLICY_PATH.is_file(),
            "scripts/orchestrator_policy.py must define the authorization boundary",
        )
        spec = importlib.util.spec_from_file_location("orchestrator_policy", POLICY_PATH)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(getattr(module, "authorization_errors", None)))


class ExternalDataApprovalSchemaTests(unittest.TestCase):
    def test_strict_external_data_approval_shape_is_runtime_validated(self) -> None:
        """Catches approval-by-boolean or malformed acquisition scope records."""

        schema = SCHEMAS / "external-data-approval.schema.json"
        self.assertTrue(schema.is_file(), "external approval schema must be published")
        self.assertEqual(
            [],
            validate_document(
                valid_external_approval(), kind="external-data-approval"
            ),
        )

        mutations: list[dict[str, object]] = []
        for field in valid_external_approval():
            missing = valid_external_approval()
            del missing[field]
            mutations.append(missing)
        invalid_confirmation = valid_external_approval()
        invalid_confirmation["user_confirmation"] = False
        mutations.append(invalid_confirmation)
        duplicate_fields = valid_external_approval()
        duplicate_fields["fields"] = ["demand", "demand"]
        mutations.append(duplicate_fields)
        extra = valid_external_approval()
        extra["approved_by_agent"] = True
        mutations.append(extra)

        for payload in mutations:
            with self.subTest(payload=payload):
                self.assertTrue(
                    validate_document(payload, kind="external-data-approval")
                )


class OrchestratorAuthorizationTests(unittest.TestCase):
    def test_unknown_preflight_fields_block_authorization(self) -> None:
        evidence = valid_authorization_evidence()
        evidence["preflight"]["forged_status"] = "pass"
        errors = authorization_errors("model-construction", evidence)
        self.assertTrue(any("preflight" in error and "unknown" in error for error in errors))

    def test_submission_readiness_requires_structured_official_verification(self) -> None:
        evidence = valid_authorization_evidence()
        errors = authorization_errors("submission-readiness", evidence)
        self.assertTrue(any("official verification" in error for error in errors))
        evidence["official_verification"] = {
            "schema_version": "2",
            "competition": "CUMCM",
            "source_type": "rule",
            "source_url": "https://example.invalid/rules.pdf",
            "verified_at": "2026-08-27T12:00:00Z",
            "content_sha256": "a" * 64,
        }
        self.assertEqual([], authorization_errors("submission-readiness", evidence))

    def test_complete_current_evidence_authorizes_each_supported_action(self) -> None:
        """Catches a policy branch that rejects a fully satisfied prerequisite set."""

        evidence = valid_authorization_evidence()
        for action in (
            "model-construction",
            "model-solving",
            "paper-writing",
            "paper-production",
            "page-gate-acceptance",
            "external-data-download",
        ):
            with self.subTest(action=action):
                self.assertEqual([], authorization_errors(action, evidence))

        with self.assertRaisesRegex(ValueError, "unsupported orchestrator action"):
            authorization_errors("project-complete", evidence)

    def test_missing_or_unbound_preflight_python_evidence_blocks_forward_work(self) -> None:
        """Catches routing without current evidence for the user-selected absolute Python."""

        cases: list[dict[str, object]] = []
        missing_initialization = valid_authorization_evidence()
        del missing_initialization["initialization"]
        cases.append(missing_initialization)

        relative_python = valid_authorization_evidence()
        relative_python["initialization"]["python_executable"] = "python3"
        cases.append(relative_python)

        mismatched_python = valid_authorization_evidence()
        mismatched_python["preflight"]["python"]["path"] = "/other/python"
        cases.append(mismatched_python)

        stale_preflight = valid_authorization_evidence()
        stale_preflight["handoff"]["state"]["invalidated_stages"] = ["preflight"]
        cases.append(stale_preflight)

        failed_probe = valid_authorization_evidence()
        failed_probe["preflight"]["python"]["status"] = "error"
        cases.append(failed_probe)

        for evidence in cases:
            with self.subTest(evidence=evidence):
                errors = authorization_errors("model-construction", evidence)
                self.assertTrue(errors)
                self.assertRegex(" ".join(errors).lower(), r"preflight|python")

    def test_missing_invalid_wrong_gate_or_stale_hash_blocks_gate_three_action(self) -> None:
        """Catches current-pointer claims that bypass exact user-confirmed Gate 3 evidence."""

        cases: list[dict[str, object]] = []
        missing = valid_authorization_evidence()
        del missing["gate_report"]
        cases.append(missing)

        agent_confirmation = valid_authorization_evidence()
        agent_confirmation["gate_report"]["records"][-1]["confirmation"][
            "actor_type"
        ] = "agent"
        cases.append(agent_confirmation)

        wrong_id = valid_authorization_evidence()
        wrong_id["gate_report"]["records"][-1]["gate_id"] = "gate2"
        cases.append(wrong_id)

        stale_hash = valid_authorization_evidence()
        stale_hash["gate_report"]["records"][-1]["artifact_hashes"] = [
            "b" * 64
        ]
        stale_hash["gate_report"]["records"][-1]["confirmation"][
            "artifact_hashes"
        ] = ["b" * 64]
        cases.append(stale_hash)

        pointer_only = valid_authorization_evidence()
        pointer_only["iteration"]["gates"]["gate3"] = "pending"
        cases.append(pointer_only)

        for evidence in cases:
            with self.subTest(evidence=evidence):
                errors = authorization_errors("paper-writing", evidence)
                self.assertTrue(errors)
                self.assertIn("gate3", " ".join(errors).lower())

    def test_corrupt_append_only_gate_history_blocks_authorization(self) -> None:
        """Catches a valid latest gate hiding a malformed earlier audit record."""

        evidence = valid_authorization_evidence()
        evidence["gate_report"]["records"][0]["confirmation"]["actor_type"] = (
            "agent"
        )

        errors = authorization_errors("paper-writing", evidence)
        self.assertTrue(errors)
        self.assertIn("gate report record[0]", " ".join(errors).lower())

    def test_nonpass_or_stale_validation_blocks_paper_writing(self) -> None:
        """Catches stale, invalidated, or non-pass validation authorizing paper work."""

        cases: list[dict[str, object]] = []
        for status in ("pending", "needs_revision", "stale"):
            evidence = valid_authorization_evidence()
            evidence["handoff"]["state"]["validation_status"] = status
            cases.append(evidence)
        invalidated = valid_authorization_evidence()
        invalidated["handoff"]["state"]["invalidated_stages"] = [
            "model-solving"
        ]
        cases.append(invalidated)
        stale_iteration = valid_authorization_evidence()
        stale_iteration["iteration"]["status"] = "stale"
        cases.append(stale_iteration)

        for evidence in cases:
            with self.subTest(evidence=evidence):
                errors = authorization_errors("paper-writing", evidence)
                self.assertTrue(errors)
                self.assertRegex(
                    " ".join(errors).lower(), r"validation|stale|invalidated"
                )

    def test_incomplete_paper_content_blocks_production(self) -> None:
        """Catches a complete-status wrapper hiding a missing question subsection."""

        evidence = valid_authorization_evidence()
        question = evidence["paper_content"]["content"]["sections"]["5"][
            "questions"
        ][0]
        del question["subsections"]["5.1.2"]

        errors = authorization_errors("paper-production", evidence)
        self.assertTrue(errors)
        self.assertIn("paper content", " ".join(errors).lower())

    def test_template_conflict_and_page_failure_block_their_actions(self) -> None:
        """Catches production or completion after unresolved template/page checks."""

        conflict = valid_authorization_evidence()
        conflict["template_check"] = {
            "status": "needs_revision",
            "conflicts": ["main entry omits paper-body.tex"],
        }
        template_errors = authorization_errors("paper-production", conflict)
        self.assertTrue(template_errors)
        self.assertIn("template", " ".join(template_errors).lower())

        failed_page = valid_authorization_evidence()
        failed_page["page_gate"]["status"] = "pass"
        failed_page["page_gate"]["total_pages"] = 31
        failed_page["page_gate"]["body_range"] = {
            "start": 1,
            "end": 26,
            "pages": 26,
        }
        page_errors = authorization_errors("page-gate-acceptance", failed_page)
        self.assertTrue(page_errors)
        self.assertIn("page", " ".join(page_errors).lower())

    def test_missing_or_invalid_external_approval_blocks_download(self) -> None:
        """Catches an absent, incomplete, or agent-expanded acquisition approval."""

        cases: list[dict[str, object]] = []
        missing = valid_authorization_evidence()
        del missing["external_data_approval"]
        cases.append(missing)
        false_confirmation = valid_authorization_evidence()
        false_confirmation["external_data_approval"]["user_confirmation"] = False
        cases.append(false_confirmation)
        incomplete = valid_authorization_evidence()
        del incomplete["external_data_approval"]["license"]
        cases.append(incomplete)
        extra = valid_authorization_evidence()
        extra["external_data_approval"]["agent_override"] = True
        cases.append(extra)

        for evidence in cases:
            with self.subTest(evidence=evidence):
                errors = authorization_errors("external-data-download", evidence)
                self.assertTrue(errors)
                self.assertIn("external data approval", " ".join(errors).lower())


if __name__ == "__main__":
    unittest.main()
