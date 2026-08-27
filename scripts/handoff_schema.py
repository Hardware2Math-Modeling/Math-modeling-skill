"""Versioned schemas, validation, and migration for modeling state documents."""

from __future__ import annotations

import copy
import json
import math
import re
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


STAGES = (
    "preflight",
    "problem-analysis",
    "data-analysis",
    "model-construction",
    "model-solving",
    "visualization",
    "validation",
    "paper-writing",
    "paper-production",
)
STATUSES = ("pending", "in_progress", "complete", "needs_revision", "skipped")
VALIDATION_STATUSES = ("pending", "pass", "needs_revision", "stale")
CONTEXT_FIELDS = (
    "assumptions",
    "variables",
    "data",
    "methods",
    "decisions",
    "equations",
    "parameters",
)
RESULT_FIELDS = (
    "summary",
    "details",
    "accepted_model",
    "rejected_alternatives",
    "evidence",
    "computed_values",
    "citations",
)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ITERATION_RE = re.compile(r"^v[0-9]{3,}$")
_QUESTION_RE = re.compile(r"^Q[1-9][0-9]*$")
_UTC_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$"
)


def _reject_json_constant(constant: str) -> object:
    raise ValueError(f"non-standard JSON constant {constant!r} is not allowed")


def load_json_strict(source: str | Path) -> object:
    """Load RFC-compliant JSON text or a UTF-8 JSON file."""

    if isinstance(source, Path):
        label = str(source)
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ValueError(f"unable to read valid JSON from {label}: {error}") from error
    else:
        label = "input text"
        text = source
    try:
        return json.loads(text, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"unable to read valid JSON from {label}: {error}") from error


def _is_utc_timestamp(value: object) -> bool:
    """Return whether value is a real UTC-Z timestamp, not just lexical shape."""

    if not _is_string(value) or _UTC_RE.fullmatch(value) is None:
        return False
    # Fractional seconds are deliberately accepted at arbitrary precision by the
    # lexical contract; datetime validates the calendar/date-time portion.
    base = value[:-1].split(".", 1)[0]
    try:
        datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return True


def _path(parent: str, field: str) -> str:
    return f"{parent}.{field}" if parent else field


def _is_string(value: object) -> bool:
    return type(value) is str


def _is_nonempty_string(value: object) -> bool:
    return _is_string(value) and bool(value.strip())


def _object(
    value: object,
    *,
    path: str,
    required: tuple[str, ...],
    allowed: tuple[str, ...],
    errors: list[str],
) -> dict[str, Any] | None:
    if type(value) is not dict:
        errors.append(f"{path or '$'} must be an object")
        return None
    result = value
    for field in required:
        if field not in result:
            errors.append(f"{_path(path, field)} is required")
    for field in sorted(set(result) - set(allowed)):
        errors.append(f"{_path(path, field)} is not allowed")
    return result


def _nonempty_string(value: object, path: str, errors: list[str]) -> None:
    if not _is_nonempty_string(value):
        errors.append(f"{path} must be a non-empty string")


def _enum(value: object, allowed: tuple[str, ...], path: str, errors: list[str]) -> None:
    if not _is_string(value) or value not in allowed:
        errors.append(f"{path} must be one of: {', '.join(allowed)}")


def _string_array(value: object, path: str, errors: list[str]) -> None:
    if type(value) is not list:
        errors.append(f"{path} must be an array")
        return
    for index, item in enumerate(value):
        _nonempty_string(item, f"{path}[{index}]", errors)


def _stage_array(value: object, path: str, errors: list[str]) -> None:
    if type(value) is not list:
        errors.append(f"{path} must be an array")
        return
    seen: set[str] = set()
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        _enum(item, STAGES, item_path, errors)
        if _is_string(item):
            if item in seen:
                errors.append(f"{item_path} duplicates {item!r}")
            seen.add(item)


def _evidence_array(value: object, path: str, errors: list[str]) -> None:
    if type(value) is not list:
        errors.append(f"{path} must be an array")
        return
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if type(item) is not dict or not item:
            errors.append(f"{item_path} must be a non-empty object")
            continue
        _evidence_value(item, item_path, errors)


def _evidence_value(
    value: object,
    path: str,
    errors: list[str],
    active_containers: set[int] | None = None,
) -> None:
    """Validate one recursive evidence value against strict JSON types."""

    if active_containers is None:
        active_containers = set()
    if _is_string(value):
        if not value.strip():
            errors.append(f"{path} must not be an empty string")
        return
    if value is None or type(value) is bool or type(value) is int:
        return
    if type(value) is float:
        if not math.isfinite(value):
            errors.append(f"{path} must be a finite JSON number")
        return
    if type(value) is list:
        identity = id(value)
        if identity in active_containers:
            errors.append(f"{path} must not contain a reference cycle")
            return
        active_containers.add(identity)
        try:
            for index, item in enumerate(value):
                _evidence_value(
                    item, f"{path}[{index}]", errors, active_containers
                )
        finally:
            active_containers.remove(identity)
        return
    if type(value) is dict:
        identity = id(value)
        if identity in active_containers:
            errors.append(f"{path} must not contain a reference cycle")
            return
        active_containers.add(identity)
        try:
            invalid_types = sorted(
                {type(key).__name__ for key in value if type(key) is not str}
            )
            for type_name in invalid_types:
                errors.append(
                    f"{path} must use a string key (found {type_name})"
                )
            for key in sorted(key for key in value if type(key) is str):
                _evidence_value(
                    value[key], _path(path, key), errors, active_containers
                )
        finally:
            active_containers.remove(identity)
        return
    errors.append(f"{path} must contain only strict JSON values")


def _safe_relative_path(value: object, path: str, errors: list[str]) -> None:
    if not _is_nonempty_string(value):
        errors.append(f"{path} must be a non-empty relative path")
        return
    assert isinstance(value, str)
    if "\x00" in value or "\\" in value:
        errors.append(f"{path} must use a safe project-relative path")
        return
    segments = value.split("/")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(segment in ("", ".", "..") for segment in segments)
    ):
        errors.append(f"{path} must use a safe project-relative path")


def _validate_handoff(payload: object, errors: list[str]) -> None:
    fields = (
        "schema_version",
        "task",
        "state",
        "context",
        "artifacts",
        "quality",
        "result",
        "next",
    )
    root = _object(payload, path="", required=fields, allowed=fields, errors=errors)
    if root is None:
        return
    if root.get("schema_version") != "2" or not _is_string(root.get("schema_version")):
        errors.append('schema_version must be exactly the string "2"')

    task_fields = ("statement", "objectives", "constraints")
    task = _object(
        root.get("task"),
        path="task",
        required=task_fields,
        allowed=task_fields,
        errors=errors,
    )
    if task is not None:
        _nonempty_string(task.get("statement"), "task.statement", errors)
        _string_array(task.get("objectives"), "task.objectives", errors)
        _string_array(task.get("constraints"), "task.constraints", errors)

    state_fields = (
        "current_stage",
        "status",
        "validation_status",
        "completed_stages",
        "invalidated_stages",
    )
    state = _object(
        root.get("state"),
        path="state",
        required=state_fields,
        allowed=state_fields,
        errors=errors,
    )
    if state is not None:
        _enum(state.get("current_stage"), STAGES, "state.current_stage", errors)
        _enum(state.get("status"), STATUSES, "state.status", errors)
        _enum(
            state.get("validation_status"),
            VALIDATION_STATUSES,
            "state.validation_status",
            errors,
        )
        _stage_array(state.get("completed_stages"), "state.completed_stages", errors)
        _stage_array(state.get("invalidated_stages"), "state.invalidated_stages", errors)

    context = _object(
        root.get("context"),
        path="context",
        required=CONTEXT_FIELDS,
        allowed=CONTEXT_FIELDS,
        errors=errors,
    )
    if context is not None:
        for field in CONTEXT_FIELDS:
            _evidence_array(context.get(field), f"context.{field}", errors)

    artifacts = root.get("artifacts")
    if type(artifacts) is not list:
        errors.append("artifacts must be an array")
    else:
        artifact_fields = ("path", "kind", "description", "sha256")
        for index, value in enumerate(artifacts):
            item_path = f"artifacts[{index}]"
            artifact = _object(
                value,
                path=item_path,
                required=("path", "kind", "description"),
                allowed=artifact_fields,
                errors=errors,
            )
            if artifact is None:
                continue
            _safe_relative_path(artifact.get("path"), f"{item_path}.path", errors)
            _nonempty_string(artifact.get("kind"), f"{item_path}.kind", errors)
            _nonempty_string(
                artifact.get("description"), f"{item_path}.description", errors
            )
            if "sha256" in artifact and (
                not _is_string(artifact["sha256"])
                or _HASH_RE.fullmatch(artifact["sha256"]) is None
            ):
                errors.append(f"{item_path}.sha256 must be 64 lowercase hexadecimal characters")

    quality_fields = ("checks", "warnings", "confidence", "limitations")
    quality = _object(
        root.get("quality"),
        path="quality",
        required=quality_fields,
        allowed=quality_fields,
        errors=errors,
    )
    if quality is not None:
        _evidence_array(quality.get("checks"), "quality.checks", errors)
        _string_array(quality.get("warnings"), "quality.warnings", errors)
        _enum(quality.get("confidence"), ("high", "medium", "low"), "quality.confidence", errors)
        _string_array(quality.get("limitations"), "quality.limitations", errors)

    result = _object(
        root.get("result"),
        path="result",
        required=RESULT_FIELDS,
        allowed=RESULT_FIELDS,
        errors=errors,
    )
    if result is not None:
        _nonempty_string(result.get("summary"), "result.summary", errors)
        _string_array(result.get("details"), "result.details", errors)
        accepted_model = result.get("accepted_model")
        if accepted_model is not None:
            _nonempty_string(accepted_model, "result.accepted_model", errors)
        _evidence_array(
            result.get("rejected_alternatives"), "result.rejected_alternatives", errors
        )
        _string_array(result.get("evidence"), "result.evidence", errors)
        _evidence_array(result.get("computed_values"), "result.computed_values", errors)
        _evidence_array(result.get("citations"), "result.citations", errors)

    next_fields = ("recommended_stage", "rationale", "alternatives", "failed_checks")
    next_value = _object(
        root.get("next"),
        path="next",
        required=next_fields,
        allowed=next_fields,
        errors=errors,
    )
    if next_value is not None:
        recommended = next_value.get("recommended_stage")
        if recommended is not None:
            _nonempty_string(recommended, "next.recommended_stage", errors)
            if _is_string(recommended) and recommended not in (*STAGES, "complete"):
                errors.append(
                    f"next.recommended_stage {recommended!r} must be a workflow stage or complete"
                )
        _nonempty_string(next_value.get("rationale"), "next.rationale", errors)
        _string_array(next_value.get("alternatives"), "next.alternatives", errors)
        _string_array(next_value.get("failed_checks"), "next.failed_checks", errors)

    if state is not None and next_value is not None and state.get("status") == "needs_revision":
        failed_checks = next_value.get("failed_checks")
        if type(failed_checks) is list and not failed_checks:
            errors.append("next.failed_checks must name at least one failed check for needs_revision")
        current = state.get("current_stage")
        recommended = next_value.get("recommended_stage")
        if recommended == "complete":
            errors.append(
                "next.recommended_stage 'complete' cannot authorize a forward "
                "transition for needs_revision"
            )
        if current in STAGES and recommended in STAGES:
            if STAGES.index(recommended) > STAGES.index(current):
                errors.append(
                    f"next.recommended_stage {recommended!r} cannot authorize a forward "
                    "transition for needs_revision"
                )


def _validate_iteration(payload: object, errors: list[str]) -> None:
    fields = (
        "schema_version",
        "project_id",
        "active_iteration",
        "question_sources",
        "gates",
        "status",
        "updated_at",
    )
    root = _object(payload, path="", required=fields, allowed=fields, errors=errors)
    if root is None:
        return
    if root.get("schema_version") != "2" or not _is_string(root.get("schema_version")):
        errors.append('schema_version must be exactly the string "2"')
    _nonempty_string(root.get("project_id"), "project_id", errors)
    active = root.get("active_iteration")
    if not _is_string(active) or _ITERATION_RE.fullmatch(active) is None:
        errors.append("active_iteration must match vNNN")
    sources = root.get("question_sources")
    if type(sources) is not dict:
        errors.append("question_sources must be an object")
    else:
        for question in sorted(sources):
            value = sources[question]
            if _QUESTION_RE.fullmatch(str(question)) is None:
                errors.append(f"question_sources.{question} must use a Q<number> key")
            if not _is_string(value) or _ITERATION_RE.fullmatch(value) is None:
                errors.append(f"question_sources.{question} must match vNNN")
    gates = _object(
        root.get("gates"),
        path="gates",
        required=("gate1", "gate2", "gate3"),
        allowed=("gate1", "gate2", "gate3"),
        errors=errors,
    )
    if gates is not None:
        for gate in ("gate1", "gate2", "gate3"):
            _enum(gates.get(gate), ("pending", "confirmed", "rejected", "stale"), f"gates.{gate}", errors)
    _enum(root.get("status"), ("pending", "in_progress", "complete", "needs_revision", "stale"), "status", errors)
    updated = root.get("updated_at")
    if not _is_utc_timestamp(updated):
        errors.append("updated_at must be a UTC timestamp ending in Z")


def _validate_manifest(payload: object, errors: list[str]) -> None:
    fields = ("schema_version", "manifest_type", "created_at", "entries")
    root = _object(payload, path="", required=fields, allowed=fields, errors=errors)
    if root is None:
        return
    if root.get("schema_version") != "2" or not _is_string(root.get("schema_version")):
        errors.append('schema_version must be exactly the string "2"')
    _enum(root.get("manifest_type"), ("input", "environment", "run", "figure", "paper"), "manifest_type", errors)
    created = root.get("created_at")
    if not _is_utc_timestamp(created):
        errors.append("created_at must be a UTC timestamp ending in Z")
    _evidence_array(root.get("entries"), "entries", errors)


def _validate_gate(payload: object, errors: list[str]) -> None:
    fields = (
        "schema_version",
        "gate_id",
        "status",
        "confirmed_by",
        "confirmed_at",
        "artifact_hashes",
        "notes",
        "rollback_stage",
    )
    root = _object(payload, path="", required=fields, allowed=fields, errors=errors)
    if root is None:
        return
    if root.get("schema_version") != "2" or not _is_string(root.get("schema_version")):
        errors.append('schema_version must be exactly the string "2"')
    _enum(root.get("gate_id"), ("gate1", "gate2", "gate3"), "gate_id", errors)
    _enum(root.get("status"), ("pending", "confirmed", "rejected"), "status", errors)
    confirmer = root.get("confirmed_by")
    confirmed_at = root.get("confirmed_at")
    if confirmer is not None:
        _nonempty_string(confirmer, "confirmed_by", errors)
    if confirmed_at is not None and not _is_utc_timestamp(confirmed_at):
        errors.append("confirmed_at must be null or a UTC timestamp ending in Z")
    hashes = root.get("artifact_hashes")
    if type(hashes) is not list:
        errors.append("artifact_hashes must be an array")
    else:
        seen_hashes: set[str] = set()
        for index, item in enumerate(hashes):
            if not _is_string(item) or _HASH_RE.fullmatch(item) is None:
                errors.append(f"artifact_hashes[{index}] must be a SHA-256 digest")
            elif item in seen_hashes:
                errors.append(f"artifact_hashes[{index}] duplicates {item!r}")
            else:
                seen_hashes.add(item)
    if not _is_string(root.get("notes")):
        errors.append("notes must be a string")
    rollback = root.get("rollback_stage")
    if rollback is not None:
        _enum(rollback, STAGES, "rollback_stage", errors)
    status = root.get("status")
    if status == "confirmed":
        if confirmer is None:
            errors.append("confirmed_by is required when status is confirmed")
        if confirmed_at is None:
            errors.append("confirmed_at is required when status is confirmed")
        if type(hashes) is list and not hashes:
            errors.append("artifact_hashes must not be empty when status is confirmed")
    if status == "rejected" and rollback is None:
        errors.append("rollback_stage is required when status is rejected")


def validate_document(
    payload: object, *, kind: str, mode: str = "runtime"
) -> list[str]:
    """Return deterministic field-path errors for one v2 document."""

    validators = {
        "handoff": _validate_handoff,
        "iteration": _validate_iteration,
        "manifest": _validate_manifest,
        "gate": _validate_gate,
    }
    if kind not in validators:
        raise ValueError(f"unsupported document kind: {kind}")
    if mode not in ("runtime", "legacy"):
        raise ValueError(f"unsupported validation mode: {mode}")
    candidate = payload
    if mode == "legacy":
        if kind != "handoff":
            raise ValueError("legacy mode is only supported for handoff documents")
        if type(payload) is dict and payload.get("schema_version") == "1":
            try:
                candidate = migrate_payload(payload)
            except ValueError as error:
                return [f"schema_version: {error}"]
    errors: list[str] = []
    validators[kind](candidate, errors)
    return errors


def _copy_array(value: object) -> list[Any]:
    return copy.deepcopy(value) if type(value) is list else []


def _copy_object(value: object) -> dict[str, Any]:
    return copy.deepcopy(value) if type(value) is dict else {}


def _legacy_artifacts(value: object) -> list[dict[str, Any]]:
    if type(value) is not list:
        return []
    migrated: list[dict[str, Any]] = []
    for item in value:
        if type(item) is not dict:
            continue
        artifact = {
            field: copy.deepcopy(item[field])
            for field in ("path", "kind", "description", "sha256")
            if field in item
        }
        if artifact:
            migrated.append(artifact)
    return migrated


def migrate_payload(payload: dict[str, object]) -> dict[str, object]:
    """Return a v2 payload while preserving all recognized v1 evidence."""

    if type(payload) is not dict:
        raise ValueError("legacy handoff must be an object")
    version = payload.get("schema_version")
    if version == "2" and _is_string(version):
        return copy.deepcopy(payload)
    if version != "1" or not _is_string(version):
        raise ValueError('schema_version must be exactly the string "1" or "2"')

    legacy_task = _copy_object(payload.get("task"))
    legacy_state = _copy_object(payload.get("state"))
    legacy_context = _copy_object(payload.get("context"))
    legacy_quality = _copy_object(payload.get("quality"))
    legacy_result = _copy_object(payload.get("result"))
    legacy_next = _copy_object(payload.get("next"))

    statement = legacy_task.get("statement")
    if not _is_nonempty_string(statement):
        statement = "Legacy handoff omitted task.statement."
    current_stage = legacy_state.get("current_stage")
    if current_stage not in STAGES or not _is_string(current_stage):
        current_stage = "preflight"
    status = legacy_state.get("status")
    if status not in STATUSES or not _is_string(status):
        status = "needs_revision"
    validation_status = legacy_state.get("validation_status")
    if validation_status not in VALIDATION_STATUSES or not _is_string(validation_status):
        validation_status = "pending"

    context = {field: _copy_array(legacy_context.get(field)) for field in CONTEXT_FIELDS}
    context["decisions"].append(
        {
            "statement": "Migrated from schema_version 1.",
            "provenance": "scripts/migrate_handoff.py",
        }
    )
    artifacts = _legacy_artifacts(payload.get("artifacts"))
    warnings = _copy_array(legacy_quality.get("warnings"))
    has_hash_evidence = bool(artifacts) and all(
        _is_string(artifact.get("sha256"))
        and _HASH_RE.fullmatch(artifact["sha256"]) is not None
        for artifact in artifacts
    )
    if validation_status == "pass" and not has_hash_evidence:
        validation_status = "stale"
        warnings.append(
            "Legacy validation pass had no complete artifact hash evidence and was marked stale."
        )

    summary = legacy_result.get("summary")
    if not _is_nonempty_string(summary):
        summary = "Legacy handoff did not record a result summary."
    rationale = legacy_next.get("rationale")
    if not _is_nonempty_string(rationale):
        rationale = "Migration requires review before any forward transition."
    failed_checks = _copy_array(legacy_next.get("failed_checks"))
    recommended_stage = copy.deepcopy(legacy_next.get("recommended_stage"))
    if recommended_stage is not None and not _is_nonempty_string(recommended_stage):
        recommended_stage = None
    if status == "needs_revision":
        if not failed_checks:
            failed_checks.append(
                "Legacy handoff marked needs_revision without naming its failed checks."
            )
        if recommended_stage in STAGES and STAGES.index(recommended_stage) > STAGES.index(current_stage):
            recommended_stage = current_stage

    migrated: dict[str, object] = {
        "schema_version": "2",
        "task": {
            "statement": copy.deepcopy(statement),
            "objectives": _copy_array(legacy_task.get("objectives")),
            "constraints": _copy_array(legacy_task.get("constraints")),
        },
        "state": {
            "current_stage": current_stage,
            "status": status,
            "validation_status": validation_status,
            "completed_stages": _copy_array(legacy_state.get("completed_stages")),
            "invalidated_stages": _copy_array(legacy_state.get("invalidated_stages")),
        },
        "context": context,
        "artifacts": artifacts,
        "quality": {
            "checks": _copy_array(legacy_quality.get("checks")),
            "warnings": warnings,
            "confidence": (
                copy.deepcopy(legacy_quality.get("confidence"))
                if legacy_quality.get("confidence") in ("high", "medium", "low")
                and _is_string(legacy_quality.get("confidence"))
                else "low"
            ),
            "limitations": _copy_array(legacy_quality.get("limitations")),
        },
        "result": {
            "summary": copy.deepcopy(summary),
            "details": _copy_array(legacy_result.get("details")),
            "accepted_model": (
                copy.deepcopy(legacy_result.get("accepted_model"))
                if _is_nonempty_string(legacy_result.get("accepted_model"))
                else None
            ),
            "rejected_alternatives": _copy_array(
                legacy_result.get("rejected_alternatives")
            ),
            "evidence": _copy_array(legacy_result.get("evidence")),
            "computed_values": _copy_array(legacy_result.get("computed_values")),
            "citations": _copy_array(legacy_result.get("citations")),
        },
        "next": {
            "recommended_stage": recommended_stage,
            "rationale": copy.deepcopy(rationale),
            "alternatives": _copy_array(legacy_next.get("alternatives")),
            "failed_checks": failed_checks,
        },
    }
    return migrated


def _artifact_filesystem_errors(
    payload: dict[str, object], document_path: Path
) -> list[str]:
    """Reject artifact paths whose existing symlinks resolve outside the document root."""

    errors: list[str] = []
    artifacts = payload.get("artifacts")
    if type(artifacts) is not list:
        return errors
    try:
        root = document_path.parent.resolve(strict=True)
    except OSError as error:
        return [f"artifacts: unable to resolve project root: {error}"]
    for index, artifact in enumerate(artifacts):
        if type(artifact) is not dict or not _is_nonempty_string(artifact.get("path")):
            continue
        relative = artifact["path"]
        assert isinstance(relative, str)
        try:
            resolved = root.joinpath(relative).resolve(strict=False)
        except (OSError, RuntimeError) as error:
            errors.append(f"artifacts[{index}].path cannot be resolved safely: {error}")
            continue
        if not resolved.is_relative_to(root):
            errors.append(f"artifacts[{index}].path escapes the project root through a symlink")
    return errors


def load_and_validate(
    path: Path, *, kind: str, mode: str = "runtime"
) -> dict[str, object]:
    """Load JSON, validate it, and raise ValueError on an invalid document."""

    payload = load_json_strict(path)
    errors = validate_document(payload, kind=kind, mode=mode)
    if errors:
        raise ValueError(f"invalid {kind} document:\n- " + "\n- ".join(errors))
    result = (
        migrate_payload(payload)
        if mode == "legacy" and payload.get("schema_version") == "1"
        else payload
    )
    if kind == "handoff":
        filesystem_errors = _artifact_filesystem_errors(result, path)
        if filesystem_errors:
            raise ValueError(
                f"invalid {kind} document:\n- " + "\n- ".join(filesystem_errors)
            )
    return result
