from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "scripts" / "orchestrator_policy.py"
SCRIPTS = ROOT / "scripts"
SCHEMAS = ROOT / "skills/math-modeling-orchestrator/references/schemas"
HANDOFF_FIXTURE = ROOT / "tests/fixtures/handoff-v2.json"
sys.path.insert(0, str(SCRIPTS))

from handoff_schema import validate_document  # noqa: E402
from authorization_capability import _install_host_capability  # noqa: E402
from orchestrator_policy import authorization_errors  # noqa: E402
from paper_production import paper_finalization_sha256  # noqa: E402
from tests.test_paper_content import valid_content  # noqa: E402


DIGEST = "a" * 64
PYTHON = "/opt/user-selected/python"
GATE_SCOPES = {
    "gate1": [
        {
            "path": "artifacts/problem-analysis.json",
            "kind": "problem-analysis",
            "sha256": "1" * 64,
        }
    ],
    "gate2": [
        {
            "path": "artifacts/model-specification.json",
            "kind": "model-specification",
            "sha256": "2" * 64,
        }
    ],
    "gate3": [
        {
            "path": "artifacts/q1-figure-manifest.json",
            "kind": "figure-manifest",
            "sha256": "6" * 64,
        },
        {
            "path": "artifacts/q1-result-contract.json",
            "kind": "result-contract",
            "sha256": "3" * 64,
        },
        {
            "path": "artifacts/q1-run-manifest.json",
            "kind": "run-manifest",
            "sha256": "4" * 64,
        },
        {
            "path": "artifacts/q1-validation-manifest.json",
            "kind": "validation-manifest",
            "sha256": "5" * 64,
        },
    ],
}
DEPENDENCY_ARTIFACT = {
    "path": "iterations/v001/manifests/Q1-dependencies.json",
    "kind": "question-dependency-manifest",
    "sha256": "7" * 64,
}
_FIXTURE_TEMPORARIES: list[tempfile.TemporaryDirectory[str]] = []


def challenge_sha256(event_type: str, payload: dict[str, object]) -> str:
    encoded = json.dumps(
        {"event_type": event_type, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def trusted_event_receipt(
    *, event_id: str, event_type: str, payload: dict[str, object]
) -> dict[str, object]:
    return {
        "schema_version": "2",
        "provenance_type": "trusted_user_event",
        "provider": "fixture-host-boundary",
        "event_id": event_id,
        "event_type": event_type,
        "actor_id": "project-owner",
        "occurred_at": "2026-08-27T12:00:00Z",
        "challenge_sha256": challenge_sha256(event_type, payload),
    }


def gate_challenge(gate_id: str) -> dict[str, object]:
    return {
        "schema_version": "2",
        "gate_id": gate_id,
        "artifact_scope": GATE_SCOPES[gate_id],
    }


def confirmed_gate(gate_id: str) -> dict[str, object]:
    event_id = f"fixture-{gate_id}-confirmation"
    confirmation = trusted_event_receipt(
        event_id=event_id,
        event_type="gate-confirmation",
        payload=gate_challenge(gate_id),
    )
    return {
        "schema_version": "2",
        "gate_id": gate_id,
        "status": "confirmed",
        "confirmed_by": "project-owner",
        "confirmed_at": "2026-08-27T12:00:00Z",
        "confirmation": confirmation,
        "artifact_scope": GATE_SCOPES[gate_id],
        "artifact_hashes": [entry["sha256"] for entry in GATE_SCOPES[gate_id]],
        "notes": "Explicitly confirmed against the current artifact.",
        "rollback_stage": None,
    }


class FixtureTrustedUserEventVerifier:
    def __init__(self) -> None:
        self.receipts: dict[str, dict[str, object]] = {}
        for gate_id in GATE_SCOPES:
            record = confirmed_gate(gate_id)
            receipt = record["confirmation"]
            assert type(receipt) is dict and type(receipt["event_id"]) is str
            self.receipts[receipt["event_id"]] = receipt
        for requested in (True, False):
            paper_request = valid_paper_request(requested)
            request_receipt = paper_request["request_event"]
            assert type(request_receipt) is dict and type(request_receipt["event_id"]) is str
            self.receipts[request_receipt["event_id"]] = request_receipt

    def verify_user_event(
        self, *, event_id: str, event_type: str, challenge_sha256: str
    ) -> dict[str, object] | None:
        receipt = self.receipts.get(event_id)
        if (
            receipt is None
            or receipt.get("event_type") != event_type
            or receipt.get("challenge_sha256") != challenge_sha256
        ):
            return None
        return json.loads(json.dumps(receipt))


class FixtureOfficialSourceVerifier:
    def verify_official_source(
        self,
        *,
        competition: str,
        source_type: str,
        source_url: str,
        verified_at: str,
        content_sha256: str,
    ) -> bool:
        return (
            competition == "CUMCM"
            and source_type in {"rule", "template"}
            and source_url.startswith("https://contest.example.org/")
            and verified_at == "2026-08-27T12:00:00Z"
            and content_sha256 == "a" * 64
        )


def valid_paper_request(requested: bool = True) -> dict[str, object]:
    deliverables = ["paper-writing", "paper-production"] if requested else []
    payload: dict[str, object] = {
        "schema_version": "2",
        "requested": requested,
        "deliverables": deliverables,
    }
    return {
        **payload,
        "request_event": trusted_event_receipt(
            event_id=("fixture-paper-request" if requested else "fixture-no-paper-request"),
            event_type="paper-request",
            payload=payload,
        ),
    }


def valid_question_version_evidence() -> dict[str, object]:
    return {
        "schema_version": "2",
        "active_iteration": "v001",
        "questions": [
            {
                "question_id": "Q1",
                "source_iteration": "v001",
                "dependency_manifest": {
                    "path": DEPENDENCY_ARTIFACT["path"],
                    "sha256": DEPENDENCY_ARTIFACT["sha256"],
                },
                "status": "current",
            }
        ],
    }


def valid_accepted_model_interface() -> dict[str, object]:
    specification = GATE_SCOPES["gate2"][0]
    return {
        "schema_version": "2",
        "status": "accepted",
        "model_id": "Linear allocation model",
        "specification": {
            "path": specification["path"],
            "sha256": specification["sha256"],
        },
        "inputs": ["demand"],
        "outputs": ["allocation"],
    }


def valid_paper_finalization_record() -> dict[str, object]:
    renderer_path = "/opt/user-selected/pdftoppm"
    version_output = "pdftoppm version 99.0.0\n"
    return {
        "schema_version": "1",
        "manifest_type": "paper_finalization",
        "iteration": "v001",
        "created_at": "2026-08-27T12:05:00Z",
        "status": "pass",
        "submission_ready": True,
        "readiness_authority": True,
        "candidate_manifest": {
            "path": "iterations/v001/paper/paper_manifest.json",
            "sha256": "8" * 64,
        },
        "candidate_pdf": {
            "path": "iterations/v001/paper/paper.pdf",
            "sha256": "9" * 64,
        },
        "review_request": {
            "path": "iterations/v001/paper/visual_review_request.json",
            "sha256": "b" * 64,
        },
        "render_manifest": {
            "path": "iterations/v001/paper/paper_render_manifest.json",
            "sha256": "c" * 64,
            "renderer": {
                "name": "pdftoppm",
                "status": "available",
                "path": renderer_path,
                "sha256": "d" * 64,
                "version_command": [renderer_path, "-v"],
                "version_exit_code": 0,
                "version_signature": "pdftoppm version 99.0.0",
                "version_output": version_output,
                "version_output_sha256": hashlib.sha256(
                    version_output.encode("utf-8")
                ).hexdigest(),
                "trust_basis": "user_supplied_preflight_binary",
            },
            "pages": [
                {
                    "page": 1,
                    "path": (
                        "iterations/v001/paper/render-attempts/"
                        "attempt-001/pages/page-001.png"
                    ),
                    "sha256": "e" * 64,
                    "width_px": 1200,
                    "height_px": 1800,
                }
            ],
        },
        "visual_review": {
            "path": "qa/paper-visual-review.json",
            "sha256": "f" * 64,
            "reviewer": "fixture-reviewer",
            "reviewed_at": "2026-08-27T12:04:00Z",
            "checklist": {
                "blank_pages": "pass",
                "cropping": "pass",
                "garbled_text": "pass",
                "overlap": "pass",
                "abnormal_font_or_hidden_padding": "pass",
            },
        },
    }


TRUSTED_USER_EVENT_VERIFIER = FixtureTrustedUserEventVerifier()
OFFICIAL_SOURCE_VERIFIER = FixtureOfficialSourceVerifier()
HOST_CAPABILITY = _install_host_capability(
    verify_user_event=TRUSTED_USER_EVENT_VERIFIER.verify_user_event,
    verify_official_source=OFFICIAL_SOURCE_VERIFIER.verify_official_source,
)
OFFICIAL_ONLY_CAPABILITY = _install_host_capability(
    verify_user_event=lambda **_: None,
    verify_official_source=OFFICIAL_SOURCE_VERIFIER.verify_official_source,
)


def authorize(action: str, evidence: object) -> list[str]:
    project_root = None
    if type(evidence) is dict and type(evidence.get("preflight")) is dict:
        project_root = evidence["preflight"].get("project_root")
    return authorization_errors(
        action,
        evidence,
        project_root=project_root,
        host_capability=HOST_CAPABILITY,
    )


def valid_external_approval() -> dict[str, object]:
    return {
        "purpose": "Obtain public demand observations for Q1.",
        "fields": ["date", "demand"],
        "source": "https://example.invalid/data.csv",
        "license": "CC-BY-4.0",
        "risk": "The source may contain revisions or missing dates.",
        "user_confirmation": True,
    }


def valid_official_verification(source_type: str = "rule") -> dict[str, object]:
    return {
        "schema_version": "2",
        "competition": "CUMCM",
        "source_type": source_type,
        "source_url": "https://contest.example.org/rules.pdf",
        "verified_at": "2026-08-27T12:00:00Z",
        "content_sha256": "a" * 64,
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


def _materialize_authorization_project(
    evidence: dict[str, object],
) -> dict[str, object]:
    temporary = tempfile.TemporaryDirectory()
    _FIXTURE_TEMPORARIES.append(temporary)
    project = Path(temporary.name).resolve()
    (project / "template.tex").write_text("fixture template\n", encoding="utf-8")

    handoff = evidence["handoff"]
    artifacts = handoff["artifacts"]
    digests: dict[str, str] = {}
    for artifact in artifacts:
        path = artifact["path"]
        target = project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = f"fixture authorization artifact: {path}\n".encode("utf-8")
        target.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        artifact["sha256"] = digest
        digests[path] = digest

    for record in evidence["gate_report"]["records"]:
        gate_id = record["gate_id"]
        allowed_kinds = {
            "gate1": {"problem-analysis"},
            "gate2": {"model-specification"},
            "gate3": {
                "result-contract",
                "run-manifest",
                "validation-manifest",
                "figure-manifest",
            },
        }[gate_id]
        scope = sorted(
            [
                {
                    "path": artifact["path"],
                    "kind": artifact["kind"],
                    "sha256": artifact["sha256"],
                }
                for artifact in artifacts
                if artifact["kind"] in allowed_kinds
            ],
            key=lambda item: (item["kind"], item["path"]),
        )
        record["artifact_scope"] = scope
        record["artifact_hashes"] = [entry["sha256"] for entry in scope]
        confirmation = record["confirmation"]
        confirmation["challenge_sha256"] = challenge_sha256(
            "gate-confirmation",
            {
                "schema_version": "2",
                "gate_id": gate_id,
                "artifact_scope": scope,
            },
        )
        TRUSTED_USER_EVENT_VERIFIER.receipts[confirmation["event_id"]] = json.loads(
            json.dumps(confirmation)
        )

    specification = evidence["accepted_model_interface"]["specification"]
    specification["sha256"] = digests[specification["path"]]
    dependency = evidence["question_version_evidence"]["questions"][0][
        "dependency_manifest"
    ]
    dependency["sha256"] = digests[dependency["path"]]
    for entry in evidence["paper_content"]["evidence"]:
        entry["sha256"] = digests[entry["path"]]
    for claim in evidence["paper_content"]["content"]["claims"]:
        claim["source_hash"] = digests[claim["source_path"]]

    evidence["preflight"]["project_root"] = str(project)
    evidence["preflight"]["template"]["requested_path"] = str(
        project / "template.tex"
    )
    evidence["preflight"]["template"]["resolved_path"] = str(
        project / "template.tex"
    )
    for relative, payload in (
        ("current.json", evidence["iteration"]),
        ("iterations/v001/state/handoff.json", evidence["handoff"]),
    ):
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    return evidence


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
        *[
            {**entry, "description": f"Current {entry['kind']} evidence."}
            for scope in GATE_SCOPES.values()
            for entry in scope
        ],
        {
            **DEPENDENCY_ARTIFACT,
            "description": "Current question dependency manifest.",
        },
        {
            "path": "results/q1-result.json",
            "kind": "result",
            "description": "Current paper-content source evidence.",
            "sha256": DIGEST,
        },
    ]
    evidence = {
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
        "accepted_model_interface": valid_accepted_model_interface(),
        "paper_request": valid_paper_request(),
        "question_version_evidence": valid_question_version_evidence(),
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
    return _materialize_authorization_project(evidence)


def with_valid_paper_finalization(
    evidence: dict[str, object],
) -> dict[str, object]:
    project = Path(evidence["preflight"]["project_root"])
    record = valid_paper_finalization_record()
    path = "iterations/v001/paper/paper_finalization.json"
    completed = evidence["handoff"]["state"]["completed_stages"]
    if "paper-production" not in completed:
        completed.append("paper-production")

    def write_json(relative: str, payload: dict[str, object]) -> str:
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        content = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        target.write_bytes(content)
        return hashlib.sha256(content).hexdigest()

    renderer_path = project / "host-tools/pdftoppm"
    renderer_path.parent.mkdir(parents=True, exist_ok=True)
    renderer_path.write_bytes(b"fixture pdftoppm executable\n")
    renderer = record["render_manifest"]["renderer"]
    renderer["path"] = str(renderer_path)
    renderer["sha256"] = hashlib.sha256(renderer_path.read_bytes()).hexdigest()
    renderer["version_command"] = [str(renderer_path), "-v"]

    pdf_path = record["candidate_pdf"]["path"]
    pdf_target = project / pdf_path
    pdf_target.parent.mkdir(parents=True, exist_ok=True)
    pdf_target.write_bytes(b"fixture final paper PDF\n")
    record["candidate_pdf"]["sha256"] = hashlib.sha256(
        pdf_target.read_bytes()
    ).hexdigest()

    for page in record["render_manifest"]["pages"]:
        page_target = project / page["path"]
        page_target.parent.mkdir(parents=True, exist_ok=True)
        page_target.write_bytes(b"fixture rendered page\n")
        page["sha256"] = hashlib.sha256(page_target.read_bytes()).hexdigest()

    candidate_manifest = {
        "schema_version": "1",
        "manifest_type": "paper",
        "iteration": "v001",
        "status": "pass",
        "pdf": {
            "path": pdf_path,
            "sha256": record["candidate_pdf"]["sha256"],
        },
    }
    record["candidate_manifest"]["sha256"] = write_json(
        record["candidate_manifest"]["path"], candidate_manifest
    )
    review_request = {
        "schema_version": "1",
        "manifest_type": "paper_visual_review_request",
        "iteration": "v001",
        "status": "pending",
        "candidate_manifest": dict(record["candidate_manifest"]),
        "candidate_pdf": {
            "path": pdf_path,
            "sha256": record["candidate_pdf"]["sha256"],
            "total_pages": len(record["render_manifest"]["pages"]),
        },
    }
    record["review_request"]["sha256"] = write_json(
        record["review_request"]["path"], review_request
    )
    render_manifest = {
        "schema_version": "1",
        "manifest_type": "paper_render",
        "iteration": "v001",
        "renderer": dict(renderer),
        "pages": json.loads(json.dumps(record["render_manifest"]["pages"])),
    }
    record["render_manifest"]["sha256"] = write_json(
        record["render_manifest"]["path"], render_manifest
    )
    visual_review = {
        "schema_version": "1",
        "manifest_type": "paper_visual_review",
        "iteration": "v001",
        "status": "pass",
        "pdf_sha256": record["candidate_pdf"]["sha256"],
        "render_manifest_sha256": record["render_manifest"]["sha256"],
        "reviewer": record["visual_review"]["reviewer"],
        "reviewed_at": record["visual_review"]["reviewed_at"],
        "checklist": dict(record["visual_review"]["checklist"]),
    }
    record["visual_review"]["sha256"] = write_json(
        record["visual_review"]["path"], visual_review
    )

    digest = write_json(path, record)
    self_hash = paper_finalization_sha256(record)
    assert digest == self_hash
    evidence["paper_finalization"] = {
        "path": path,
        "sha256": digest,
        "record": record,
    }
    evidence["handoff"]["artifacts"].append(
        {
            "path": path,
            "kind": "paper-finalization",
            "description": "Current Task 9 readiness authority.",
            "sha256": digest,
        }
    )
    write_json("current.json", evidence["iteration"])
    write_json("iterations/v001/state/handoff.json", evidence["handoff"])
    return evidence


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

    def test_duck_typed_verifier_kwargs_are_not_public_api(self) -> None:
        """Catches reintroducing caller-supplied verifier keyword arguments."""

        with self.assertRaises(TypeError):
            authorization_errors(
                "current-rule-claim",
                {"official_verification": valid_official_verification()},
                official_source_verifier=object(),
            )


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
    def test_model_construction_rejects_absent_dependency_file(self) -> None:
        """Catches path/hash string comparison without reading the project file."""

        evidence = valid_authorization_evidence()
        dependency_path = (
            Path(evidence["preflight"]["project_root"])
            / evidence["question_version_evidence"]["questions"][0][
                "dependency_manifest"
            ]["path"]
        )
        dependency_path.unlink()
        self.assertFalse(dependency_path.exists())

        errors = authorize("model-construction", evidence)

        self.assertTrue(errors, "an absent dependency file must not authorize")

    def test_model_solving_rejects_absent_model_specification_file(self) -> None:
        """Catches accepted-interface authorization using metadata without bytes."""

        evidence = valid_authorization_evidence()
        binding = evidence["accepted_model_interface"]["specification"]
        specification_path = Path(evidence["preflight"]["project_root"]) / binding["path"]
        specification_path.unlink()

        errors = authorize("model-solving", evidence)

        self.assertTrue(errors, "an absent model specification file must not authorize")

    def test_gate_rejects_absent_scoped_project_file(self) -> None:
        """Catches Gate 3 trusting matching metadata for a missing scoped file."""

        evidence = valid_authorization_evidence()
        validation = next(
            artifact
            for artifact in evidence["handoff"]["artifacts"]
            if artifact["kind"] == "validation-manifest"
        )
        (Path(evidence["preflight"]["project_root"]) / validation["path"]).unlink()

        errors = authorize("paper-writing", evidence)

        self.assertTrue(errors, "a Gate-scoped missing file must not authorize")

    def test_caller_created_echo_verifier_cannot_authorize_paper_writing(self) -> None:
        """Catches caller-owned receipt lookup masquerading as a host capability."""

        evidence = valid_authorization_evidence()
        receipts = {
            record["confirmation"]["event_id"]: record["confirmation"]
            for record in evidence["gate_report"]["records"]
        }
        request_event = evidence["paper_request"]["request_event"]
        receipts[request_event["event_id"]] = request_event

        class CallerEchoVerifier:
            def verify_user_event(
                self, *, event_id: str, event_type: str, challenge_sha256: str
            ) -> dict[str, object] | None:
                receipt = receipts.get(event_id)
                if (
                    type(receipt) is dict
                    and receipt.get("event_type") == event_type
                    and receipt.get("challenge_sha256") == challenge_sha256
                ):
                    return receipt
                return None

        errors = authorization_errors(
            "paper-writing",
            evidence,
            host_capability=CallerEchoVerifier(),
        )

        self.assertTrue(errors, "a caller-created echo verifier must not authorize")

    def test_arbitrary_verifier_objects_and_malformed_records_fail_closed(self) -> None:
        """Catches truthy placeholders replacing host verifiers or strict route records."""

        evidence = valid_authorization_evidence()
        for field in (
            "accepted_model_interface",
            "paper_request",
            "question_version_evidence",
        ):
            malformed = valid_authorization_evidence()
            malformed[field] = {"status": "accepted", "agent_override": True}
            action = "model-solving" if field == "accepted_model_interface" else "paper-writing"
            with self.subTest(field=field):
                self.assertTrue(
                    authorization_errors(
                        action,
                        malformed,
                        host_capability=object(),
                    )
                )

        class CallerTrueVerifier:
            def verify_official_source(self, **_: object) -> bool:
                return True

        claim = valid_authorization_evidence()
        claim["official_verification"] = valid_official_verification()
        errors = authorization_errors(
            "current-rule-claim",
            claim,
            host_capability=CallerTrueVerifier(),
        )
        self.assertTrue(errors)
        self.assertIn("capability", " ".join(errors).lower())

    def test_current_route_records_are_strict_and_bound_to_artifacts(self) -> None:
        """Catches well-shaped but stale interface/dependency/request records."""

        interface = valid_authorization_evidence()
        interface["accepted_model_interface"]["specification"]["sha256"] = "f" * 64
        self.assertTrue(authorize("model-solving", interface))

        dependency = valid_authorization_evidence()
        dependency["question_version_evidence"]["questions"][0][
            "source_iteration"
        ] = "v999"
        self.assertTrue(authorize("model-construction", dependency))

        request = valid_authorization_evidence()
        request["paper_request"]["deliverables"] = ["paper-writing"]
        self.assertTrue(authorize("paper-production", request))

    def test_unrelated_paper_artifact_does_not_invalidate_gate3_scope(self) -> None:
        """Catches exact Gate 3 scope accidentally including later paper output."""

        evidence = valid_authorization_evidence()
        project = Path(evidence["preflight"]["project_root"])
        paper_path = "iterations/v001/paper/paper-content.json"
        paper_file = project / paper_path
        paper_file.parent.mkdir(parents=True, exist_ok=True)
        paper_file.write_bytes(b"fixture later paper content\n")
        evidence["handoff"]["artifacts"].append(
            {
                "path": paper_path,
                "kind": "paper-content",
                "description": "Generated only after Gate 3 confirmation.",
                "sha256": hashlib.sha256(paper_file.read_bytes()).hexdigest(),
            }
        )
        (project / "iterations/v001/state/handoff.json").write_text(
            json.dumps(
                evidence["handoff"],
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.assertEqual([], authorize("paper-writing", evidence))

    def test_submission_readiness_cannot_ignore_invalid_project_and_finalization(self) -> None:
        """Catches an official-source record bypassing Task 9 readiness authority."""

        evidence = valid_authorization_evidence()
        evidence["official_verification"] = valid_official_verification()
        evidence["handoff"]["schema_version"] = "1"
        evidence["handoff"]["state"]["status"] = "needs_revision"
        evidence["iteration"]["status"] = "stale"
        evidence["template_check"] = {
            "status": "needs_revision",
            "conflicts": ["template conflict"],
        }
        evidence["page_gate"]["total_pages"] = 31

        errors = authorization_errors("submission-readiness", evidence)

        self.assertTrue(errors)
        self.assertRegex(" ".join(errors).lower(), r"handoff|stale|finalization")

    def test_submission_readiness_rejects_shape_only_finalization(self) -> None:
        """Catches orchestrator-side shape validation replacing Task 9 authority."""

        evidence = with_valid_paper_finalization(valid_authorization_evidence())
        evidence["official_verification"] = valid_official_verification()
        finalization_path = (
            Path(evidence["preflight"]["project_root"])
            / evidence["paper_finalization"]["path"]
        )
        finalization_path.unlink()
        self.assertFalse(finalization_path.exists())

        errors = authorize("submission-readiness", evidence)

        self.assertTrue(errors, "shape-only finalization must not authorize readiness")

    def test_submission_readiness_requires_common_modeling_prerequisites(self) -> None:
        """Catches Task 9 authority bypassing current modeling/interface evidence."""

        baseline = with_valid_paper_finalization(valid_authorization_evidence())
        baseline["official_verification"] = valid_official_verification()
        cases: list[tuple[str, dict[str, object], str]] = []
        for stage in ("model-construction", "model-solving", "validation"):
            missing_stage = json.loads(json.dumps(baseline))
            missing_stage["handoff"]["state"]["completed_stages"].remove(stage)
            cases.append((f"missing-{stage}", missing_stage, stage))
        missing_interface = json.loads(json.dumps(baseline))
        del missing_interface["accepted_model_interface"]
        cases.append(("missing-interface", missing_interface, "accepted_model_interface"))

        for label, evidence, expected in cases:
            with self.subTest(case=label):
                project = Path(evidence["preflight"]["project_root"])
                (project / "iterations/v001/state/handoff.json").write_text(
                    json.dumps(
                        evidence["handoff"],
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                errors = authorize("submission-readiness", evidence)
                self.assertTrue(errors)
                self.assertIn(expected, " ".join(errors))

    def test_project_complete_is_machine_checked_and_fail_closed(self) -> None:
        """Catches workflow completion having no executable policy action."""

        try:
            errors = authorization_errors("project-complete", valid_authorization_evidence())
        except ValueError as error:
            self.fail(f"project-complete must be an executable fail-closed action: {error}")
        self.assertTrue(errors)

        paper = with_valid_paper_finalization(valid_authorization_evidence())
        paper["official_verification"] = valid_official_verification()
        self.assertEqual([], authorize("project-complete", paper))

        no_paper = valid_authorization_evidence()
        no_paper["paper_request"] = valid_paper_request(False)
        no_paper["official_verification"] = valid_official_verification()
        self.assertEqual([], authorize("project-complete", no_paper))

        stale = with_valid_paper_finalization(valid_authorization_evidence())
        stale["official_verification"] = valid_official_verification()
        stale["paper_finalization"]["record"]["submission_ready"] = False
        self.assertTrue(authorize("project-complete", stale))

    def test_no_paper_completion_requires_trusted_current_modeling_evidence(self) -> None:
        """Catches the optional paper branch bypassing model or validation freshness."""

        baseline = valid_authorization_evidence()
        baseline["paper_request"] = valid_paper_request(False)
        baseline["official_verification"] = valid_official_verification()

        missing_host = authorization_errors(
            "project-complete",
            baseline,
            host_capability=OFFICIAL_ONLY_CAPABILITY,
        )
        self.assertTrue(missing_host)
        self.assertIn("paper request", " ".join(missing_host).lower())

        cases: list[dict[str, object]] = []
        missing_model = json.loads(json.dumps(baseline))
        missing_model["handoff"]["state"]["completed_stages"].remove("model-solving")
        cases.append(missing_model)
        stale_validation = json.loads(json.dumps(baseline))
        stale_validation["handoff"]["state"]["validation_status"] = "stale"
        cases.append(stale_validation)
        stale_dependency = json.loads(json.dumps(baseline))
        stale_dependency["question_version_evidence"]["questions"][0][
            "dependency_manifest"
        ]["sha256"] = "0" * 64
        cases.append(stale_dependency)
        stale_interface = json.loads(json.dumps(baseline))
        stale_interface["accepted_model_interface"]["specification"]["sha256"] = (
            "0" * 64
        )
        cases.append(stale_interface)

        for evidence in cases:
            with self.subTest(evidence=evidence):
                self.assertTrue(authorize("project-complete", evidence))

    def test_no_paper_completion_rejects_absent_validation_artifact_file(self) -> None:
        """Catches favorable modeling metadata authorizing absent project evidence."""

        evidence = valid_authorization_evidence()
        evidence["paper_request"] = valid_paper_request(False)
        evidence["official_verification"] = valid_official_verification()
        validation = next(
            artifact
            for artifact in evidence["handoff"]["artifacts"]
            if artifact["kind"] == "validation-manifest"
        )
        validation_path = (
            Path(evidence["preflight"]["project_root"]) / validation["path"]
        )
        validation_path.unlink()

        errors = authorize("project-complete", evidence)

        self.assertTrue(
            errors,
            "no-paper completion must read its current validation artifact",
        )

    def test_model_solving_rejects_invalidated_construction_and_stale_iteration(self) -> None:
        """Catches Gate 2 alone bypassing current upstream model evidence."""

        evidence = valid_authorization_evidence()
        evidence["handoff"]["state"]["invalidated_stages"] = [
            "model-construction",
            "model-solving",
        ]
        evidence["iteration"]["status"] = "stale"

        errors = authorize("model-solving", evidence)

        self.assertTrue(errors)
        self.assertRegex(" ".join(errors).lower(), r"model-construction|stale")

    def test_model_solving_rejects_needs_revision_construction(self) -> None:
        """Catches completed-stage names overriding current revision status."""

        evidence = valid_authorization_evidence()
        evidence["handoff"]["state"].update(
            {
                "current_stage": "model-construction",
                "status": "needs_revision",
            }
        )
        evidence["handoff"]["next"].update(
            {
                "recommended_stage": "model-construction",
                "failed_checks": ["model construction requires revision"],
            }
        )
        self.assertEqual(
            [], validate_document(evidence["handoff"], kind="handoff", mode="runtime")
        )

        errors = authorize("model-solving", evidence)

        self.assertTrue(errors)
        self.assertIn("needs_revision", " ".join(errors))

    def test_forward_and_completion_actions_reject_noncurrent_iteration_status(self) -> None:
        """Catches pending/revision/stale pointers authorizing downstream work."""

        actions = (
            "model-construction",
            "model-solving",
            "paper-writing",
            "paper-production",
            "page-gate-acceptance",
            "submission-readiness",
            "project-complete",
        )
        for action in actions:
            for status in ("pending", "needs_revision", "stale"):
                with self.subTest(action=action, status=status):
                    evidence = valid_authorization_evidence()
                    if action == "submission-readiness":
                        evidence = with_valid_paper_finalization(evidence)
                        evidence["official_verification"] = valid_official_verification()
                    elif action == "project-complete":
                        evidence["paper_request"] = valid_paper_request(False)
                        evidence["official_verification"] = valid_official_verification()
                    evidence["iteration"]["status"] = status

                    errors = authorize(action, evidence)

                    self.assertTrue(
                        errors,
                        f"{action} must reject iteration status {status}",
                    )

    def test_forward_and_completion_actions_reject_noncurrent_project_status(self) -> None:
        """Catches pending/revision/skipped handoffs authorizing current work."""

        actions = (
            "model-construction",
            "model-solving",
            "paper-writing",
            "paper-production",
            "page-gate-acceptance",
            "submission-readiness",
            "project-complete",
        )
        for action in actions:
            for status in ("pending", "needs_revision", "skipped"):
                with self.subTest(action=action, status=status):
                    evidence = valid_authorization_evidence()
                    if action == "submission-readiness":
                        evidence = with_valid_paper_finalization(evidence)
                        evidence["official_verification"] = valid_official_verification()
                    elif action == "project-complete":
                        evidence["paper_request"] = valid_paper_request(False)
                        evidence["official_verification"] = valid_official_verification()
                    evidence["handoff"]["state"]["status"] = status
                    if status == "needs_revision":
                        evidence["handoff"]["next"].update(
                            {
                                "recommended_stage": evidence["handoff"]["state"][
                                    "current_stage"
                                ],
                                "failed_checks": ["current stage requires revision"],
                            }
                        )
                    self.assertEqual(
                        [],
                        validate_document(
                            evidence["handoff"], kind="handoff", mode="runtime"
                        ),
                    )

                    errors = authorize(action, evidence)

                    self.assertTrue(
                        errors,
                        f"{action} must reject project status {status}",
                    )

    def test_forward_work_rejects_noncurrent_project_pointer_on_disk(self) -> None:
        """Catches caller-supplied iteration shape replacing canonical current.json."""

        evidence = valid_authorization_evidence()
        project = Path(evidence["preflight"]["project_root"])
        current = json.loads(json.dumps(evidence["iteration"]))
        current["status"] = "needs_revision"
        (project / "current.json").write_text(
            json.dumps(current, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

        errors = authorize("model-construction", evidence)

        self.assertTrue(errors)
        self.assertIn("current", " ".join(errors).lower())

    def test_forward_work_rejects_noncurrent_project_handoff_on_disk(self) -> None:
        """Catches caller-supplied handoff shape replacing active project state."""

        evidence = valid_authorization_evidence()
        project = Path(evidence["preflight"]["project_root"])
        handoff = json.loads(json.dumps(evidence["handoff"]))
        handoff["state"]["status"] = "needs_revision"
        handoff["next"].update(
            {
                "recommended_stage": handoff["state"]["current_stage"],
                "failed_checks": ["active handoff requires revision"],
            }
        )
        handoff_path = project / "iterations/v001/state/handoff.json"
        handoff_path.write_text(
            json.dumps(handoff, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

        errors = authorize("model-construction", evidence)

        self.assertTrue(errors)
        self.assertIn("handoff", " ".join(errors).lower())

    def test_official_claim_type_and_shape_only_host_are_non_authorizing(self) -> None:
        """Catches template/type confusion and example records authorizing current rules."""

        wrong_type = valid_authorization_evidence()
        wrong_type["official_verification"] = valid_official_verification("template")
        wrong_type_errors = authorization_errors("current-rule-claim", wrong_type)
        self.assertTrue(wrong_type_errors)
        self.assertIn("rule", " ".join(wrong_type_errors).lower())

        shape_only = valid_authorization_evidence()
        shape_only["official_verification"] = valid_official_verification("rule")
        shape_only_errors = authorization_errors("current-rule-claim", shape_only)
        self.assertTrue(shape_only_errors)
        self.assertRegex(" ".join(shape_only_errors).lower(), r"official|trusted|event")

        rule = {"official_verification": valid_official_verification("rule")}
        template = {"official_verification": valid_official_verification("template")}
        self.assertEqual([], authorize("current-rule-claim", rule))
        self.assertEqual([], authorize("current-template-claim", template))

    def test_route_actions_require_interface_request_and_question_freshness(self) -> None:
        """Catches prose-only route prerequisites being omitted from policy."""

        for action, phrase in (
            ("model-construction", "question"),
            ("model-solving", "interface"),
            ("paper-writing", "paper request"),
            ("paper-production", "paper request"),
        ):
            with self.subTest(action=action):
                evidence = valid_authorization_evidence()
                if action == "model-construction":
                    del evidence["question_version_evidence"]
                elif action == "model-solving":
                    del evidence["accepted_model_interface"]
                else:
                    del evidence["paper_request"]
                errors = authorize(action, evidence)
                self.assertTrue(errors)
                self.assertIn(phrase, " ".join(errors).lower())

    def test_self_authored_gate_receipt_and_subset_scope_do_not_authorize(self) -> None:
        """Catches a caller-authored receipt or partial relevant scope satisfying Gate 3."""

        self_attested = valid_authorization_evidence()
        self_attested_errors = authorization_errors("paper-writing", self_attested)
        self.assertTrue(self_attested_errors)
        self.assertRegex(
            " ".join(self_attested_errors).lower(),
            r"host capability|provenance",
        )

        partial_scope = valid_authorization_evidence()
        partial_scope["handoff"]["artifacts"].append(
            {
                "path": "artifacts/second-validation.json",
                "kind": "validation-manifest",
                "description": "Second current Gate 3 validation artifact.",
                "sha256": "b" * 64,
            }
        )
        partial_errors = authorize("paper-writing", partial_scope)
        self.assertTrue(partial_errors)
        self.assertIn("gate3", " ".join(partial_errors).lower())

    def test_unknown_preflight_fields_block_authorization(self) -> None:
        evidence = valid_authorization_evidence()
        evidence["preflight"]["forged_status"] = "pass"
        errors = authorize("model-construction", evidence)
        self.assertTrue(any("preflight" in error and "unknown" in error for error in errors))

    def test_submission_readiness_requires_structured_official_verification(self) -> None:
        evidence = with_valid_paper_finalization(valid_authorization_evidence())
        errors = authorize("submission-readiness", evidence)
        self.assertTrue(any("official verification" in error for error in errors))
        evidence["official_verification"] = valid_official_verification()
        self.assertEqual([], authorize("submission-readiness", evidence))

        shape_only = with_valid_paper_finalization(valid_authorization_evidence())
        shape_only["official_verification"] = valid_official_verification()
        shape_only["official_verification"]["source_url"] = (
            "https://example.invalid/rules.pdf"
        )
        self.assertTrue(authorize("submission-readiness", shape_only))

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
                self.assertEqual([], authorize(action, evidence))

        with self.assertRaisesRegex(ValueError, "unsupported orchestrator action"):
            authorization_errors("unsupported-action", evidence)

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
                errors = authorize("model-construction", evidence)
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
            "provenance_type"
        ] = "self_attested"
        cases.append(agent_confirmation)

        wrong_id = valid_authorization_evidence()
        wrong_id["gate_report"]["records"][-1]["gate_id"] = "gate2"
        cases.append(wrong_id)

        stale_hash = valid_authorization_evidence()
        stale_hash["gate_report"]["records"][-1]["artifact_hashes"] = [
            "b" * 64
        ]
        stale_hash["gate_report"]["records"][-1]["confirmation"][
            "challenge_sha256"
        ] = "b" * 64
        cases.append(stale_hash)

        pointer_only = valid_authorization_evidence()
        pointer_only["iteration"]["gates"]["gate3"] = "pending"
        cases.append(pointer_only)

        for evidence in cases:
            with self.subTest(evidence=evidence):
                errors = authorize("paper-writing", evidence)
                self.assertTrue(errors)
                self.assertIn("gate3", " ".join(errors).lower())

    def test_corrupt_append_only_gate_history_blocks_authorization(self) -> None:
        """Catches a valid latest gate hiding a malformed earlier audit record."""

        evidence = valid_authorization_evidence()
        evidence["gate_report"]["records"][0]["confirmation"]["provenance_type"] = (
            "self_attested"
        )

        errors = authorize("paper-writing", evidence)
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
                errors = authorize("paper-writing", evidence)
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

        errors = authorize("paper-production", evidence)
        self.assertTrue(errors)
        self.assertIn("paper content", " ".join(errors).lower())

    def test_template_conflict_and_page_failure_block_their_actions(self) -> None:
        """Catches production or completion after unresolved template/page checks."""

        conflict = valid_authorization_evidence()
        conflict["template_check"] = {
            "status": "needs_revision",
            "conflicts": ["main entry omits paper-body.tex"],
        }
        template_errors = authorize("paper-production", conflict)
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
        page_errors = authorize("page-gate-acceptance", failed_page)
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


def tearDownModule() -> None:
    while _FIXTURE_TEMPORARIES:
        _FIXTURE_TEMPORARIES.pop().cleanup()


if __name__ == "__main__":
    unittest.main()
