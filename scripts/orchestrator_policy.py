#!/usr/bin/env python3
"""Evaluate fail-closed authorization decisions for orchestrator actions."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

_SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if _SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, _SCRIPT_DIRECTORY)

from handoff_schema import (
    GATE_SCOPE_KINDS,
    strict_json_tree_errors,
    user_event_challenge_sha256,
    validate_document,
)
from latex_qa import evaluate_page_gate
from paper_content import validate_paper_content
from paper_production import (
    paper_finalization_sha256,
    validate_paper_finalization_record,
)


SUPPORTED_ACTIONS = (
    "model-construction",
    "model-solving",
    "paper-writing",
    "paper-production",
    "page-gate-acceptance",
    "external-data-download",
    "current-rule-claim",
    "current-template-claim",
    "submission-readiness",
    "project-complete",
)
_ACTION_GATES = {
    "model-construction": "gate1",
    "model-solving": "gate2",
    "paper-writing": "gate3",
    "paper-production": "gate3",
    "page-gate-acceptance": "gate3",
}
_VALIDATION_ACTIONS = {
    "paper-writing",
    "paper-production",
    "page-gate-acceptance",
}
_CONTENT_ACTIONS = {"paper-production", "page-gate-acceptance"}
_TEMPLATE_ACTIONS = {"paper-production", "page-gate-acceptance"}
_LATEX_ACTIONS = {"paper-production", "page-gate-acceptance"}
_ALLOWED_EVIDENCE = {
    "handoff",
    "iteration",
    "initialization",
    "preflight",
    "gate_report",
    "paper_content",
    "template_check",
    "page_gate",
    "external_data_approval",
    "official_verification",
    "accepted_model_interface",
    "paper_request",
    "question_version_evidence",
    "paper_finalization",
}
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_PREFLIGHT_FIELDS = {
    "status",
    "project_root",
    "python",
    "packages",
    "latex",
    "pdf_renderer",
    "template",
    "blockers",
    "warnings",
}
_PREFLIGHT_NESTED_FIELDS = {
    "python": {
        "status",
        "path",
        "resolved_path",
        "reported_executable",
        "version",
        "platform",
        "error",
    },
    "latex": {"status", "selected", "tools", "message"},
    "template": {"status", "requested_path", "resolved_path", "message"},
    "pdf_renderer": {
        "name",
        "status",
        "path",
        "sha256",
        "version_command",
        "version_exit_code",
        "version_signature",
        "version_output",
        "version_output_sha256",
        "trust_basis",
    },
}


def _preflight_record_errors(preflight: object) -> list[str]:
    """Reject forged/ambiguous diagnostic fields before reading pass status."""

    if type(preflight) is not dict:
        return ["preflight evidence must be a diagnostic record"]
    errors: list[str] = []
    unknown = sorted(set(preflight) - _PREFLIGHT_FIELDS)
    errors.extend(f"preflight unknown field: {field}" for field in unknown)
    for field, allowed in _PREFLIGHT_NESTED_FIELDS.items():
        value = preflight.get(field)
        if value is None:
            continue
        if type(value) is not dict:
            errors.append(f"preflight.{field} must be an object")
            continue
        nested_unknown = sorted(set(value) - allowed)
        errors.extend(
            f"preflight.{field} unknown field: {name}" for name in nested_unknown
        )
    for field in ("blockers", "warnings"):
        value = preflight.get(field)
        if type(value) is not list:
            errors.append(f"preflight.{field} must be an array")
        elif any(type(item) is not str or not item.strip() for item in value):
            errors.append(f"preflight.{field} must contain non-empty strings")
    return errors


def _validated_document(
    evidence: dict[str, object],
    field: str,
    kind: str,
    errors: list[str],
) -> dict[str, object] | None:
    value = evidence.get(field)
    if type(value) is not dict:
        errors.append(f"{field} must be a {kind} record")
        return None
    document_errors = validate_document(value, kind=kind, mode="runtime")
    if document_errors:
        errors.extend(f"{field}: {error}" for error in document_errors)
        return None
    return value


def _canonical_artifact_scope(value: object) -> list[dict[str, object]] | None:
    """Return a deterministic scope ordering for set-like gate evidence."""

    if type(value) is not list:
        return None
    entries: list[dict[str, object]] = []
    for item in value:
        if type(item) is not dict:
            return None
        if set(item) != {"path", "kind", "sha256"}:
            return None
        entries.append(
            {
                "path": item.get("path"),
                "kind": item.get("kind"),
                "sha256": item.get("sha256"),
            }
        )
    return sorted(entries, key=lambda item: (str(item["kind"]), str(item["path"])))


def _official_verification_errors(
    action: str,
    evidence: dict[str, object],
    expected_source_type: str,
    official_source_verifier: object | None,
) -> list[str]:
    errors: list[str] = []
    verification = evidence.get("official_verification")
    if type(verification) is not dict:
        return ["official verification record is required"]
    verification_errors = validate_document(
        verification, kind="official-verification", mode="runtime"
    )
    errors.extend(f"official verification: {error}" for error in verification_errors)
    if verification.get("source_type") != expected_source_type:
        errors.append(
            f"official verification source_type must be {expected_source_type} "
            f"for {action}"
        )
    source_url = verification.get("source_url")
    if type(source_url) is str:
        try:
            hostname = urlsplit(source_url).hostname
        except ValueError:
            hostname = None
        if hostname == "invalid" or (
            type(hostname) is str and hostname.lower().endswith(".invalid")
        ):
            errors.append("shape-only .invalid URLs are non-authorizing")

    if official_source_verifier is None:
        errors.append("trusted official source verifier is required")
        return errors
    verify = getattr(official_source_verifier, "verify_official_source", None)
    if not callable(verify):
        errors.append("trusted official source verifier interface is invalid")
        return errors
    if verification_errors:
        return errors
    try:
        verified = verify(
            competition=verification.get("competition"),
            source_type=verification.get("source_type"),
            source_url=verification.get("source_url"),
            verified_at=verification.get("verified_at"),
            content_sha256=verification.get("content_sha256"),
        )
    except Exception as error:
        errors.append(f"trusted official source verification failed: {error}")
    else:
        if verified is not True:
            errors.append("official source record was not verified by the trusted verifier")
    return errors


def _question_version_errors(
    evidence: dict[str, object],
    handoff: dict[str, object] | None,
    iteration: dict[str, object] | None,
) -> list[str]:
    errors: list[str] = []
    record = _validated_document(
        evidence,
        "question_version_evidence",
        "question-version-evidence",
        errors,
    )
    if record is None or handoff is None or iteration is None:
        return errors
    if record.get("active_iteration") != iteration.get("active_iteration"):
        errors.append(
            "question version evidence active_iteration must match the current pointer"
        )
    sources = iteration.get("question_sources")
    questions = record.get("questions")
    assert type(sources) is dict and type(questions) is list
    by_question = {
        item.get("question_id"): item
        for item in questions
        if type(item) is dict and type(item.get("question_id")) is str
    }
    if set(by_question) != set(sources):
        errors.append(
            "question version evidence must contain exactly one record for every "
            "current question_sources entry"
        )
    artifacts = handoff.get("artifacts")
    assert type(artifacts) is list
    for question_id, source_iteration in sources.items():
        question = by_question.get(question_id)
        if type(question) is not dict:
            continue
        if question.get("source_iteration") != source_iteration:
            errors.append(
                f"question version evidence for {question_id} must match current "
                "question_sources"
            )
        binding = question.get("dependency_manifest")
        if type(binding) is not dict:
            continue
        matches = [
            artifact
            for artifact in artifacts
            if type(artifact) is dict
            and artifact.get("kind") == "question-dependency-manifest"
            and artifact.get("path") == binding.get("path")
            and artifact.get("sha256") == binding.get("sha256")
        ]
        if len(matches) != 1:
            errors.append(
                f"question version evidence for {question_id} must bind exactly one "
                "current question-dependency-manifest artifact"
            )
    return errors


def _accepted_model_interface_errors(
    evidence: dict[str, object], handoff: dict[str, object] | None
) -> list[str]:
    errors: list[str] = []
    record = _validated_document(
        evidence,
        "accepted_model_interface",
        "accepted-model-interface",
        errors,
    )
    if record is None or handoff is None:
        return errors
    result = handoff.get("result")
    assert type(result) is dict
    if record.get("model_id") != result.get("accepted_model"):
        errors.append(
            "accepted model interface model_id must match the current handoff accepted_model"
        )
    binding = record.get("specification")
    artifacts = handoff.get("artifacts")
    assert type(artifacts) is list
    if type(binding) is dict:
        matches = [
            artifact
            for artifact in artifacts
            if type(artifact) is dict
            and artifact.get("kind") == "model-specification"
            and artifact.get("path") == binding.get("path")
            and artifact.get("sha256") == binding.get("sha256")
        ]
        if len(matches) != 1:
            errors.append(
                "accepted model interface must bind exactly one current "
                "model-specification artifact"
            )
    return errors


def _paper_request_errors(
    action: str,
    evidence: dict[str, object],
    trusted_user_event_verifier: object | None,
    *,
    allow_omitted_paper: bool = False,
) -> tuple[list[str], bool | None]:
    errors: list[str] = []
    if type(evidence.get("paper_request")) is not dict:
        return ["explicit paper request evidence is required"], None
    record = _validated_document(
        evidence, "paper_request", "paper-request", errors
    )
    if record is None:
        return errors, None
    requested = record.get("requested")
    event = record.get("request_event")
    deliverables = record.get("deliverables")
    assert type(event) is dict and type(deliverables) is list and type(requested) is bool
    challenge = user_event_challenge_sha256(
        "paper-request",
        {
            "schema_version": "2",
            "requested": requested,
            "deliverables": deliverables,
        },
    )
    if trusted_user_event_verifier is None:
        errors.append(
            "trusted user event verifier is required; a self-authored paper request "
            "is non-authorizing"
        )
    else:
        verify = getattr(trusted_user_event_verifier, "verify_user_event", None)
        if not callable(verify):
            errors.append("trusted user event verifier interface is invalid for paper request")
        else:
            try:
                verified = verify(
                    event_id=event.get("event_id"),
                    event_type="paper-request",
                    challenge_sha256=challenge,
                )
            except Exception as error:
                errors.append(f"trusted paper request verification failed: {error}")
            else:
                if verified != event:
                    errors.append("paper request is not the trusted user event receipt")
    required_deliverable = {
        "paper-writing": "paper-writing",
        "paper-production": "paper-production",
        "page-gate-acceptance": "paper-production",
        "submission-readiness": "paper-production",
    }.get(action)
    if required_deliverable is not None:
        if requested is not True:
            errors.append(f"paper request must explicitly request {required_deliverable}")
        if required_deliverable not in deliverables:
            errors.append(
                f"paper request deliverables must include {required_deliverable} for {action}"
            )
    elif action == "project-complete":
        if requested is True and "paper-production" not in deliverables:
            errors.append(
                "paper request deliverables must include paper-production for "
                "project-complete"
            )
        if requested is False and not allow_omitted_paper:
            errors.append("project completion does not permit an omitted paper in this route")
    return errors, requested


def _paper_finalization_errors(
    evidence: dict[str, object],
    handoff: dict[str, object] | None,
    iteration: dict[str, object] | None,
) -> list[str]:
    errors: list[str] = []
    envelope = evidence.get("paper_finalization")
    if type(envelope) is not dict:
        return ["Task 9 paper_finalization.json readiness authority is required"]
    if set(envelope) != {"path", "sha256", "record"}:
        errors.append(
            "paper_finalization envelope must contain exactly path, sha256, and record"
        )
    path = envelope.get("path")
    recorded_hash = envelope.get("sha256")
    record = envelope.get("record")
    if type(record) is not dict:
        errors.append("paper_finalization.record must be the complete Task 9 record")
        return errors
    record_errors = validate_paper_finalization_record(record)
    errors.extend(f"paper_finalization.record: {error}" for error in record_errors)
    if type(recorded_hash) is not str or _HASH_RE.fullmatch(recorded_hash) is None:
        errors.append("paper_finalization.sha256 must be a SHA-256 digest")
    else:
        try:
            actual_hash = paper_finalization_sha256(record)
        except ValueError as error:
            errors.append(f"paper_finalization.record cannot be hashed: {error}")
        else:
            if recorded_hash != actual_hash:
                errors.append(
                    "paper_finalization.sha256 must match the complete canonical record"
                )
    if iteration is not None:
        active_iteration = iteration.get("active_iteration")
        expected_path = (
            f"iterations/{active_iteration}/paper/paper_finalization.json"
        )
        if path != expected_path:
            errors.append(
                "paper_finalization.path must be the active iteration readiness authority"
            )
        if record.get("iteration") != active_iteration:
            errors.append(
                "paper_finalization.record iteration must match the active iteration"
            )
    if handoff is not None:
        artifacts = handoff.get("artifacts")
        assert type(artifacts) is list
        matches = [
            artifact
            for artifact in artifacts
            if type(artifact) is dict
            and artifact.get("kind") == "paper-finalization"
            and artifact.get("path") == path
            and artifact.get("sha256") == recorded_hash
        ]
        if len(matches) != 1:
            errors.append(
                "paper_finalization must bind exactly one current handoff "
                "paper-finalization artifact"
            )
        state = handoff.get("state")
        assert type(state) is dict
        completed = state.get("completed_stages")
        invalidated = state.get("invalidated_stages")
        if type(completed) is not list or "paper-production" not in completed:
            errors.append(
                "paper-production must be complete for paper finalization authority"
            )
        if type(invalidated) is list and "paper-production" in invalidated:
            errors.append("paper-production finalization authority is invalidated")
    return errors


def _preflight_errors(
    evidence: dict[str, object],
    handoff: dict[str, object] | None,
    initialization: dict[str, object] | None,
    *,
    require_latex: bool,
) -> list[str]:
    errors: list[str] = []
    if handoff is not None:
        state = handoff["state"]
        assert type(state) is dict
        completed = state["completed_stages"]
        invalidated = state["invalidated_stages"]
        assert type(completed) is list and type(invalidated) is list
        if "preflight" not in completed:
            errors.append("current handoff does not record preflight complete")
        if "preflight" in invalidated:
            errors.append("current preflight evidence is invalidated")

    preflight = evidence.get("preflight")
    record_errors = _preflight_record_errors(preflight)
    errors.extend(record_errors)
    if type(preflight) is not dict:
        return errors
    if preflight.get("status") not in ("pass", "warning"):
        errors.append("preflight status must be pass or non-blocking warning")
    blockers = preflight.get("blockers")
    if type(blockers) is not list or blockers:
        errors.append("preflight blockers must be an explicit empty list")
    python = preflight.get("python")
    if type(python) is not dict:
        errors.append("preflight Python evidence must be an object")
    else:
        if python.get("status") != "pass":
            errors.append("preflight Python identity probe must pass")
        supplied_path = (
            initialization.get("python_executable")
            if initialization is not None
            else None
        )
        if type(python.get("path")) is not str or python.get("path") != supplied_path:
            errors.append(
                "preflight Python path must exactly match the user-selected "
                "initialization path"
            )
    if require_latex:
        latex = preflight.get("latex")
        if type(latex) is not dict or latex.get("status") != "pass":
            errors.append("preflight LaTeX evidence must pass for paper production")
    return errors


def _gate_errors(
    gate_id: str,
    evidence: dict[str, object],
    handoff: dict[str, object] | None,
    iteration: dict[str, object] | None,
    trusted_user_event_verifier: object | None,
) -> list[str]:
    errors: list[str] = []
    if iteration is not None:
        gates = iteration["gates"]
        assert type(gates) is dict
        if gates.get(gate_id) != "confirmed":
            errors.append(f"{gate_id} current pointer status must be confirmed")

    report = evidence.get("gate_report")
    if type(report) is not dict:
        return [*errors, f"{gate_id} gate report is required"]
    if set(report) != {"schema_version", "records"}:
        errors.append(
            f"{gate_id} gate report must contain only schema_version and records"
        )
    if report.get("schema_version") != "2":
        errors.append(f'{gate_id} gate report schema_version must be "2"')
    records = report.get("records")
    if type(records) is not list:
        return [*errors, f"{gate_id} gate report records must be an array"]

    applicable: list[dict[str, object]] = []
    for index, record in enumerate(records):
        if type(record) is not dict:
            errors.append(f"gate report record[{index}] must be an object")
            continue
        record_errors = validate_document(record, kind="gate", mode="runtime")
        record_label = (
            f"{record.get('gate_id', 'unknown')} gate report record[{index}]"
        )
        errors.extend(f"{record_label}: {error}" for error in record_errors)
        if record.get("gate_id") == gate_id:
            applicable.append(record)
    if not applicable:
        return [*errors, f"{gate_id} gate report has no applicable record"]

    record = applicable[-1]
    if record.get("status") != "confirmed":
        errors.append(f"{gate_id} latest applicable record must be confirmed")

    current_scope: list[dict[str, object]] = []
    if handoff is not None:
        artifacts = handoff["artifacts"]
        assert type(artifacts) is list
        current_scope = sorted(
            [
                {
                    "path": artifact["path"],
                    "kind": artifact["kind"],
                    "sha256": artifact["sha256"],
                }
            for artifact in artifacts
            if type(artifact) is dict
            and artifact.get("kind") in GATE_SCOPE_KINDS[gate_id]
            and type(artifact.get("path")) is str
            and type(artifact.get("sha256")) is str
            and _HASH_RE.fullmatch(str(artifact["sha256"])) is not None
            ],
            key=lambda item: (str(item["kind"]), str(item["path"])),
        )
    recorded_scope = record.get("artifact_scope")
    canonical_recorded_scope = _canonical_artifact_scope(recorded_scope)
    if canonical_recorded_scope != current_scope:
        errors.append(f"{gate_id} artifact scope does not exactly match current relevant artifacts")
    recorded_hashes = record.get("artifact_hashes")
    expected_hashes = [entry["sha256"] for entry in current_scope]
    if type(recorded_hashes) is not list or not recorded_hashes:
        errors.append(f"{gate_id} must bind at least one current artifact hash")
    elif recorded_hashes != expected_hashes:
        errors.append(f"{gate_id} artifact hashes must exactly match current gate scope")

    confirmation = record.get("confirmation")
    if type(confirmation) is dict and canonical_recorded_scope is not None:
        challenge = user_event_challenge_sha256(
            "gate-confirmation",
            {
                "schema_version": "2",
                "gate_id": gate_id,
                "artifact_scope": canonical_recorded_scope,
            },
        )
        if trusted_user_event_verifier is None:
            errors.append(
                f"{gate_id} trusted user event verifier is required; "
                "a self-authored receipt is non-authorizing"
            )
        else:
            verify = getattr(trusted_user_event_verifier, "verify_user_event", None)
            if not callable(verify):
                errors.append(f"{gate_id} trusted user event verifier interface is invalid")
            else:
                try:
                    verified = verify(
                        event_id=confirmation.get("event_id"),
                        event_type="gate-confirmation",
                        challenge_sha256=challenge,
                    )
                except Exception as error:
                    errors.append(f"{gate_id} trusted user event verification failed: {error}")
                else:
                    if verified != confirmation:
                        errors.append(f"{gate_id} confirmation is not the trusted event receipt")
    return errors


def _validation_errors(
    handoff: dict[str, object] | None,
    iteration: dict[str, object] | None,
) -> list[str]:
    errors: list[str] = []
    if handoff is not None:
        state = handoff["state"]
        assert type(state) is dict
        if state.get("validation_status") != "pass":
            errors.append("current validation status must be pass")
        invalidated = state.get("invalidated_stages")
        if type(invalidated) is not list or invalidated:
            errors.append("current validation must have no invalidated stages")
        if state.get("status") == "needs_revision":
            errors.append("a needs_revision handoff cannot authorize paper work")
    if iteration is not None and iteration.get("status") == "stale":
        errors.append("stale iteration state cannot authorize paper work")
    return errors


def _paper_content_errors(record: object) -> list[str]:
    if type(record) is not dict:
        return ["paper content must be a frozen content record"]
    expected_fields = {"schema_version", "status", "content", "evidence"}
    errors: list[str] = []
    if set(record) != expected_fields:
        errors.append(
            "paper content record must contain exactly schema_version, status, "
            "content, and evidence"
        )
    if record.get("schema_version") != "1" or record.get("status") != "complete":
        errors.append("paper content record must have schema_version 1 and complete status")
    content = record.get("content")
    if type(content) is not dict:
        return [*errors, "paper content payload must be an object"]
    content_errors = [
        error
        for error in validate_paper_content(content)
        if "unverified without an absolute evidence_root" not in error
    ]
    errors.extend(f"paper content: {error}" for error in content_errors)

    evidence = record.get("evidence")
    recorded: dict[str, str] = {}
    if type(evidence) is not list:
        errors.append("paper content evidence must be an array")
    else:
        for index, entry in enumerate(evidence):
            if type(entry) is not dict or set(entry) != {"path", "sha256"}:
                errors.append(f"paper content evidence[{index}] is malformed")
                continue
            path = entry.get("path")
            digest = entry.get("sha256")
            if type(path) is not str or not path.strip():
                errors.append(f"paper content evidence[{index}].path is invalid")
                continue
            if type(digest) is not str or _HASH_RE.fullmatch(digest) is None:
                errors.append(f"paper content evidence[{index}].sha256 is invalid")
                continue
            if path in recorded:
                errors.append(f"paper content evidence path is duplicated: {path}")
            recorded[path] = digest

    declared: dict[str, str] = {}
    references: list[tuple[object, object]] = []
    claims = content.get("claims")
    if type(claims) is list:
        for claim in claims:
            if type(claim) is dict:
                references.append((claim.get("source_path"), claim.get("source_hash")))
    for field in ("figure_references", "table_references"):
        values = content.get(field)
        if type(values) is list:
            for value in values:
                if type(value) is dict:
                    references.append(
                        (value.get("manifest_path"), value.get("manifest_hash"))
                    )
    requirements = content.get("requirement_manifests")
    if type(requirements) is list:
        for requirement in requirements:
            if type(requirement) is dict:
                references.append(
                    (requirement.get("path"), requirement.get("sha256"))
                )
    for path, digest in references:
        if type(path) is str and type(digest) is str:
            if path in declared and declared[path] != digest:
                errors.append(f"paper content declares conflicting hashes for {path}")
            declared[path] = digest
    if recorded != declared:
        errors.append("paper content evidence does not exactly match declared references")
    return errors


def _template_errors(record: object) -> list[str]:
    if type(record) is not dict:
        return ["template check must be present before paper production"]
    if set(record) != {"status", "conflicts"}:
        return ["template check must contain exactly status and conflicts"]
    conflicts = record.get("conflicts")
    if record.get("status") != "pass" or type(conflicts) is not list or conflicts:
        return ["template check must pass with no unresolved conflicts"]
    return []


def _page_errors(record: object) -> list[str]:
    if type(record) is not dict:
        return ["page gate record is required before page-gate acceptance"]
    body_range = record.get("body_range")
    if type(body_range) is not dict:
        return ["page gate body_range must be an object"]
    computed = evaluate_page_gate(
        total_pages=record.get("total_pages"),
        body_pages=record.get("body_pages"),
        body_start=body_range.get("start"),
        body_end=body_range.get("end"),
    )
    if record != computed or computed["status"] != "pass":
        return ["page gate must be the exact passing evaluator output"]
    return []


def authorization_errors(
    action: str,
    evidence: object,
    *,
    trusted_user_event_verifier: object | None = None,
    official_source_verifier: object | None = None,
) -> list[str]:
    """Return deterministic blockers for one requested orchestrator action."""

    if action not in SUPPORTED_ACTIONS:
        raise ValueError(f"unsupported orchestrator action: {action!r}")
    if type(evidence) is not dict:
        return ["authorization evidence must be an object"]
    strict_errors = strict_json_tree_errors(evidence)
    if strict_errors:
        return [f"authorization evidence: {error}" for error in strict_errors]

    errors = [
        f"authorization evidence.{field} is not supported"
        for field in sorted(set(evidence) - _ALLOWED_EVIDENCE)
    ]
    official_type = {
        "current-rule-claim": "rule",
        "current-template-claim": "template",
        "submission-readiness": "rule",
        "project-complete": "rule",
    }.get(action)
    if official_type is not None:
        errors.extend(
            _official_verification_errors(
                action,
                evidence,
                official_type,
                official_source_verifier,
            )
        )
        if action in {"current-rule-claim", "current-template-claim"}:
            return errors

    handoff = _validated_document(evidence, "handoff", "handoff", errors)
    initialization = _validated_document(
        evidence, "initialization", "initialization", errors
    )
    errors.extend(
        _preflight_errors(
            evidence,
            handoff,
            initialization,
            require_latex=action in _LATEX_ACTIONS,
        )
    )

    iteration: dict[str, object] | None = None
    gate_id = _ACTION_GATES.get(action)
    if gate_id is not None or action in _VALIDATION_ACTIONS or action in {
        "submission-readiness",
        "project-complete",
    }:
        iteration = _validated_document(evidence, "iteration", "iteration", errors)
    if gate_id is not None:
        errors.extend(
            _gate_errors(
                gate_id,
                evidence,
                handoff,
                iteration,
                trusted_user_event_verifier,
            )
        )
    if action in _VALIDATION_ACTIONS or action in {
        "submission-readiness",
        "project-complete",
    }:
        errors.extend(_validation_errors(handoff, iteration))
    route_requires_question_evidence = action in {
        "model-construction",
        "model-solving",
        "paper-writing",
        "paper-production",
        "page-gate-acceptance",
        "submission-readiness",
        "project-complete",
    }
    if route_requires_question_evidence:
        errors.extend(_question_version_errors(evidence, handoff, iteration))
    if action == "model-solving":
        if handoff is not None:
            state = handoff["state"]
            assert type(state) is dict
            completed = state.get("completed_stages")
            invalidated = state.get("invalidated_stages")
            if type(completed) is not list or "model-construction" not in completed:
                errors.append("model-construction must be complete before model-solving")
            if type(invalidated) is list and "model-construction" in invalidated:
                errors.append("model-construction is invalidated and must be rerun")
        if iteration is not None and iteration.get("status") == "stale":
            errors.append("stale iteration cannot authorize model-solving")
        errors.extend(_accepted_model_interface_errors(evidence, handoff))
    paper_request_actions = {
        "paper-writing",
        "paper-production",
        "page-gate-acceptance",
        "submission-readiness",
        "project-complete",
    }
    paper_requested: bool | None = None
    if action in paper_request_actions:
        request_errors, paper_requested = _paper_request_errors(
            action,
            evidence,
            trusted_user_event_verifier,
            allow_omitted_paper=action == "project-complete",
        )
        errors.extend(request_errors)
    if action in _CONTENT_ACTIONS:
        if handoff is not None:
            state = handoff["state"]
            assert type(state) is dict and type(state["completed_stages"]) is list
            if "paper-writing" not in state["completed_stages"]:
                errors.append("paper-writing must be complete before paper production")
        errors.extend(_paper_content_errors(evidence.get("paper_content")))
    if action in _TEMPLATE_ACTIONS:
        errors.extend(_template_errors(evidence.get("template_check")))
    if action == "page-gate-acceptance":
        errors.extend(_page_errors(evidence.get("page_gate")))
    if action == "external-data-download":
        approval = evidence.get("external_data_approval")
        if type(approval) is not dict:
            errors.append("external data approval record is required")
        else:
            approval_errors = validate_document(
                approval,
                kind="external-data-approval",
                mode="runtime",
            )
            errors.extend(
                f"external data approval: {error}" for error in approval_errors
            )
    if action == "submission-readiness" or (
        action == "project-complete" and paper_requested is True
    ):
        errors.extend(
            _gate_errors(
                "gate3",
                evidence,
                handoff,
                iteration,
                trusted_user_event_verifier,
            )
        )
        errors.extend(_paper_finalization_errors(evidence, handoff, iteration))
    if action == "project-complete" and handoff is not None:
        state = handoff.get("state")
        assert type(state) is dict
        completed = state.get("completed_stages")
        for required_stage in ("model-construction", "model-solving", "validation"):
            if type(completed) is not list or required_stage not in completed:
                errors.append(
                    f"current {required_stage} stage must be complete before "
                    "project completion"
                )
        errors.extend(_accepted_model_interface_errors(evidence, handoff))

    return errors


__all__ = ["SUPPORTED_ACTIONS", "authorization_errors"]
