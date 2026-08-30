#!/usr/bin/env python3
"""Validate deterministic, evidence-backed results for one question."""

from __future__ import annotations

import math
import re

from manifest import safe_relative_path


_REQUIRED_FIELDS = (
    "question_id",
    "model_id",
    "assumptions",
    "baseline",
    "parameters",
    "metrics",
    "units",
    "run_manifest",
    "validation_plan",
    "validation_history",
    "validation_manifest",
    "figure_manifests",
    "claims",
    "freeze_status",
)
_QUESTION_RE = re.compile(r"^Q[1-9][0-9]*$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_FREEZE_STATUSES = ("draft", "confirmed")


def _nonempty(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _safe_source(value: object) -> bool:
    try:
        safe_relative_path(value, "source")
    except ValueError:
        return False
    return True


def _validate_baseline(value: object, errors: list[str]) -> None:
    if type(value) is not dict:
        errors.append("baseline must be an object with a named model and metric")
        return
    for field in ("model_id", "metric", "unit"):
        if not _nonempty(value.get(field)):
            errors.append(f"baseline.{field} must be a non-empty string")
    if not _finite_number(value.get("value")):
        errors.append("baseline.value must be a finite numeric value")


def _validate_metrics(value: object, errors: list[str]) -> None:
    if type(value) is not dict or not value:
        errors.append("metrics must be a non-empty object")
        return
    for name in sorted(value, key=lambda item: (type(item).__name__, repr(item))):
        metric = value[name]
        label = f"metrics.{name}"
        if not _nonempty(name):
            errors.append("metrics names must be non-empty strings")
        if type(metric) is not dict:
            errors.append(f"{label} must be an object with a finite numeric value")
            continue
        if "value" not in metric:
            errors.append(f"{label}.value is required")
        elif not _finite_number(metric["value"]):
            errors.append(f"{label}.value must be finite and numeric")
        if not _nonempty(metric.get("unit")):
            errors.append(f"{label}.unit must be a non-empty string")
        if not _safe_source(metric.get("source_path")):
            errors.append(f"{label}.source_path must be a safe project-relative path")
        if not _nonempty(metric.get("source_hash")) or not _HASH_RE.fullmatch(
            metric["source_hash"]
        ):
            errors.append(f"{label}.source_hash must be a lowercase SHA-256 hash")
        if metric.get("finite") is not True:
            errors.append(f"{label}.finite must be true for a verified numeric value")


def _validate_run_manifest(value: object, errors: list[str]) -> None:
    if type(value) is not dict:
        errors.append("run_manifest must be an object")
        return
    if not _nonempty(value.get("run_id")):
        errors.append("run_manifest.run_id must be a non-empty string")
    if type(value.get("seed")) is not int:
        errors.append("run_manifest.seed must be a fixed integer")
    if value.get("status") != "success":
        errors.append(
            f"run_manifest.status must be 'success', not {value.get('status')!r}"
        )


def _validate_validation_plan(value: object, errors: list[str]) -> None:
    if type(value) is not dict:
        errors.append("validation_plan must be an object")
        return
    if not _nonempty(value.get("validation_cycle_id")):
        errors.append("validation_plan.validation_cycle_id must be a non-empty string")
    if not _finite_number(value.get("threshold")):
        errors.append("validation_plan.threshold must be a finite numeric value")
    for field in ("split", "scope", "method"):
        if not _nonempty(value.get(field)):
            errors.append(f"validation_plan.{field} must be a non-empty string")
    if type(value.get("seed")) is not int:
        errors.append("validation_plan.seed must be a fixed integer")


def _validate_validation_history(
    history: object,
    plan: object,
    errors: list[str],
) -> None:
    if type(history) is not list:
        errors.append("validation_history must be a list")
        return

    cycle_ids: set[str] = set()
    for index, entry in enumerate(history):
        label = f"validation_history[{index}]"
        if type(entry) is not dict:
            errors.append(f"{label} must preserve a validation cycle outcome")
            continue
        cycle_valid = _nonempty(entry.get("validation_cycle_id"))
        threshold_valid = _finite_number(entry.get("threshold"))
        status_valid = _nonempty(entry.get("status"))
        if not cycle_valid:
            errors.append(f"{label}.validation_cycle_id must preserve the previous cycle")
        elif entry["validation_cycle_id"] in cycle_ids:
            errors.append(f"{label}.validation_cycle_id must be globally unique")
        else:
            cycle_ids.add(entry["validation_cycle_id"])
        if not threshold_valid:
            errors.append(f"{label}.threshold must be a finite numeric value")
        if not status_valid:
            errors.append(f"{label}.status must preserve the previous outcome")
    if type(plan) is not dict:
        return
    current_cycle = plan.get("validation_cycle_id")
    if _nonempty(current_cycle) and current_cycle in cycle_ids:
        errors.append(
            "validation_plan.validation_cycle_id must be unique and not reuse a "
            "historical validation cycle"
        )
    if not history:
        return
    latest = history[-1]
    if type(latest) is not dict:
        return
    previous_threshold = latest.get("threshold")
    current_threshold = plan.get("threshold")
    if not (_finite_number(previous_threshold) and _finite_number(current_threshold)):
        return
    if current_threshold != previous_threshold:
        previous_cycle = latest.get("validation_cycle_id")
        if not _nonempty(previous_cycle) or not _nonempty(latest.get("status")):
            errors.append(
                "validation_plan.threshold changed without preserving the previous "
                "validation cycle and outcome"
            )
        if not _nonempty(current_cycle) or current_cycle == previous_cycle:
            errors.append(
                "validation_plan.threshold changes require a new validation_cycle_id"
            )


def _validate_validation_manifest(
    value: object,
    plan: object,
    errors: list[str],
) -> None:
    if type(value) is not dict:
        errors.append("validation_manifest must be an object")
        return
    if value.get("status") != "pass":
        errors.append(
            "validation_manifest.status must be 'pass', "
            f"not {value.get('status')!r}"
        )
    cycle_id = value.get("validation_cycle_id")
    if not _nonempty(cycle_id):
        errors.append(
            "validation_manifest.validation_cycle_id must be a non-empty string"
        )
    elif type(plan) is not dict or cycle_id != plan.get("validation_cycle_id"):
        errors.append(
            "validation_manifest.validation_cycle_id must match the current "
            "validation_plan.validation_cycle_id"
        )


def _validate_figure_manifests(value: object, errors: list[str]) -> None:
    if type(value) is not list:
        errors.append("figure_manifests must be an explicit list")
        return
    for index, figure in enumerate(value):
        label = f"figure_manifests[{index}]"
        if type(figure) is not dict:
            errors.append(f"{label} must be a registered figure manifest object")
            continue
        if not _nonempty(figure.get("figure_id")):
            errors.append(f"{label}.figure_id must be a non-empty string")
        if figure.get("status") != "verified":
            errors.append(
                f"{label}.status must be 'verified', not {figure.get('status')!r}"
            )


def _validate_claims(
    value: object,
    metrics: object,
    errors: list[str],
) -> None:
    if type(value) is not list or not value:
        errors.append("claims must be a non-empty list")
        return
    seen: set[str] = set()
    for index, claim in enumerate(value):
        label = f"claims[{index}]"
        if type(claim) is not dict:
            errors.append(f"{label} must be an evidence-backed claim object")
            continue
        claim_id = claim.get("claim_id")
        if not _nonempty(claim_id):
            errors.append(f"{label}.claim_id must be a non-empty string")
        elif claim_id in seen:
            errors.append(f"{label}.claim_id must be unique")
        else:
            seen.add(claim_id)
        if not _nonempty(claim.get("statement")):
            errors.append(f"{label}.statement must be a non-empty string")
        metric_name = claim.get("metric")
        if not _nonempty(metric_name):
            errors.append(f"{label}.metric must name a result metric")
        elif type(metrics) is not dict or metric_name not in metrics:
            errors.append(f"{label}.metric must reference metrics")
        if not _safe_source(claim.get("source_path")):
            errors.append(f"{label}.source_path must be a safe project-relative path")
        if not _nonempty(claim.get("source_hash")) or not _HASH_RE.fullmatch(
            claim["source_hash"]
        ):
            errors.append(f"{label}.source_hash must be a lowercase SHA-256 hash")


def _evidence_status(value: object) -> object:
    if type(value) is dict:
        return value.get("status")
    return None


def _validate_freeze(payload: dict[str, object], errors: list[str]) -> None:
    freeze_status = payload.get("freeze_status")
    if freeze_status not in _FREEZE_STATUSES:
        errors.append(
            "freeze_status must be one of: " + ", ".join(_FREEZE_STATUSES)
        )
        return
    if freeze_status != "confirmed":
        return

    if _evidence_status(payload.get("run_manifest")) != "success":
        errors.append("freeze_status confirmed requires run_manifest status success")

    validation_manifest = payload.get("validation_manifest")
    if _evidence_status(validation_manifest) != "pass":
        errors.append("freeze_status confirmed requires validation_manifest status pass")
    if type(validation_manifest) is dict and type(payload.get("validation_plan")) is dict:
        if validation_manifest.get("validation_cycle_id") != payload[
            "validation_plan"
        ].get("validation_cycle_id"):
            errors.append(
                "freeze_status confirmed requires validation_manifest for the "
                "current validation cycle"
            )

    figures = payload.get("figure_manifests")
    if type(figures) is not list:
        errors.append("freeze_status confirmed requires figure_manifests to be a list")
    else:
        for index, figure in enumerate(figures):
            if _evidence_status(figure) != "verified":
                errors.append(
                    "freeze_status confirmed requires "
                    f"figure_manifests[{index}] to be verified"
                )

    metrics = payload.get("metrics")
    if type(metrics) is not dict or any(
        type(metric) is not dict
        or not _finite_number(metric.get("value"))
        or metric.get("finite") is not True
        for metric in metrics.values()
    ):
        errors.append("freeze_status confirmed requires finite verified metrics")


def validate_result_payload(payload: object) -> list[str]:
    """Return deterministic validation errors for one per-question result."""

    if type(payload) is not dict:
        return ["result payload must be an object"]

    errors: list[str] = []
    for field in _REQUIRED_FIELDS:
        if field not in payload:
            errors.append(f"{field} is required")

    question_id = payload.get("question_id")
    if not _nonempty(question_id) or not _QUESTION_RE.fullmatch(question_id):
        errors.append("question_id must use canonical Qn form")
    if not _nonempty(payload.get("model_id")):
        errors.append("model_id must be a non-empty string")

    assumptions = payload.get("assumptions")
    if (
        type(assumptions) is not list
        or not assumptions
        or any(not _nonempty(item) for item in assumptions)
    ):
        errors.append("assumptions must be a non-empty list of strings")

    _validate_baseline(payload.get("baseline"), errors)

    parameters = payload.get("parameters")
    if type(parameters) is not dict or not parameters:
        errors.append("parameters must be a non-empty object")

    metrics = payload.get("metrics")
    _validate_metrics(metrics, errors)

    units = payload.get("units")
    if (
        type(units) is not dict
        or not units
        or any(not _nonempty(name) or not _nonempty(unit) for name, unit in units.items())
    ):
        errors.append("units must map named quantities to non-empty unit strings")

    _validate_run_manifest(payload.get("run_manifest"), errors)
    plan = payload.get("validation_plan")
    _validate_validation_plan(plan, errors)
    _validate_validation_history(payload.get("validation_history"), plan, errors)
    _validate_validation_manifest(payload.get("validation_manifest"), plan, errors)
    _validate_figure_manifests(payload.get("figure_manifests"), errors)
    _validate_claims(payload.get("claims"), metrics, errors)
    _validate_freeze(payload, errors)
    return errors
