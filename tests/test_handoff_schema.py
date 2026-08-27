from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "handoff-v2.json"
SCHEMAS = (
    ROOT / "skills" / "math-modeling-orchestrator" / "references" / "schemas"
)
sys.path.insert(0, str(SCRIPTS))

from handoff_schema import (  # noqa: E402
    load_and_validate,
    load_json_strict,
    migrate_payload,
    validate_document,
)
from migrate_handoff import _canonical_output_path, serialize_payload  # noqa: E402


def valid_handoff() -> dict[str, object]:
    return copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))


def valid_handoff_with_computed_value() -> dict[str, object]:
    payload = valid_handoff()
    payload["result"]["computed_values"] = [{"name": "objective", "value": 1.0}]
    return payload


def valid_legacy_handoff() -> dict[str, object]:
    return {
        "schema_version": "1",
        "task": {"statement": "legacy task"},
        "state": {"current_stage": "model-solving"},
        "context": {"assumptions": []},
        "result": {},
        "next": {},
    }


def valid_needs_revision() -> dict[str, object]:
    payload = valid_handoff()
    payload["state"]["status"] = "needs_revision"
    payload["next"]["recommended_stage"] = "model-solving"
    payload["next"]["failed_checks"] = ["constraint residual exceeded tolerance"]
    return payload


def valid_pending_gate() -> dict[str, object]:
    return {
        "schema_version": "2",
        "gate_id": "gate1",
        "status": "pending",
        "confirmed_by": None,
        "confirmed_at": None,
        "artifact_hashes": [],
        "notes": "",
        "rollback_stage": None,
    }


def valid_confirmed_gate() -> dict[str, object]:
    payload = valid_pending_gate()
    payload.update(
        {
            "status": "confirmed",
            "confirmed_by": "reviewer",
            "confirmed_at": "2026-08-27T00:00:00Z",
            "artifact_hashes": ["a" * 64],
        }
    )
    return payload


def valid_iteration() -> dict[str, object]:
    return {
        "schema_version": "2",
        "project_id": "example-project",
        "active_iteration": "v001",
        "question_sources": {"Q1": "v001"},
        "gates": {"gate1": "pending", "gate2": "pending", "gate3": "pending"},
        "status": "in_progress",
        "updated_at": "2026-08-27T00:00:00Z",
    }


def valid_manifest() -> dict[str, object]:
    return {
        "schema_version": "2",
        "manifest_type": "input",
        "created_at": "2026-08-27T00:00:00Z",
        "entries": [{"path": "input/problem.pdf", "sha256": "a" * 64}],
    }


def load_schema(kind: str) -> dict[str, object]:
    return json.loads(
        SCHEMAS.joinpath(f"{kind}.schema.json").read_text(encoding="utf-8")
    )


class HandoffSchemaTests(unittest.TestCase):
    def test_valid_v2_handoff_is_accepted(self) -> None:
        self.assertEqual([], validate_document(valid_handoff(), kind="handoff"))

    def test_runtime_handoff_requires_full_objects(self) -> None:
        payload = {
            "schema_version": "2",
            "task": {},
            "state": {},
            "result": {},
            "next": {},
        }
        errors = validate_document(payload, kind="handoff", mode="runtime")
        self.assertIn("context", " ".join(errors))
        self.assertIn("quality", " ".join(errors))

    def test_runtime_rejects_schema_version_type_confusion(self) -> None:
        payload = valid_handoff()
        payload["schema_version"] = 2
        errors = validate_document(payload, kind="handoff", mode="runtime")
        self.assertTrue(any("schema_version" in error for error in errors))

    def test_direct_payload_rejects_non_string_root_key(self) -> None:
        payload = valid_handoff()
        payload[1] = "not-json"
        payload["unexpected"] = "also invalid"
        errors = validate_document(payload, kind="handoff")
        self.assertTrue(any("<key:int>" in error for error in errors))
        self.assertTrue(any("string key" in error for error in errors))

    def test_direct_payload_rejects_non_string_nested_object_key(self) -> None:
        payload = valid_handoff()
        payload["task"][1] = "not-json"
        payload["task"]["unexpected"] = "also invalid"
        errors = validate_document(payload, kind="handoff")
        self.assertTrue(any("task.<key:int>" in error for error in errors))
        self.assertTrue(any("string key" in error for error in errors))

    def test_runtime_rejects_legacy_schema_version(self) -> None:
        payload = valid_handoff()
        payload["schema_version"] = "1"
        errors = validate_document(payload, kind="handoff", mode="runtime")
        self.assertTrue(any("schema_version" in error for error in errors))

    def test_legacy_mode_accepts_explicit_legacy_handoff(self) -> None:
        legacy = {
            "schema_version": "1",
            "task": {"statement": "legacy"},
            "state": {"current_stage": "model-solving"},
            "result": {},
            "next": {},
        }
        self.assertEqual([], validate_document(legacy, kind="handoff", mode="legacy"))

    def test_legacy_mode_rejects_non_string_root_key_before_migration(self) -> None:
        legacy = valid_legacy_handoff()
        legacy[1] = "not-json"
        errors = validate_document(legacy, kind="handoff", mode="legacy")
        self.assertEqual(errors, validate_document(legacy, kind="handoff", mode="legacy"))
        self.assertTrue(any("<key:int>" in error for error in errors))
        with self.assertRaisesRegex(ValueError, "string key"):
            migrate_payload(legacy)

    def test_legacy_mode_rejects_non_string_task_key_before_migration(self) -> None:
        legacy = valid_legacy_handoff()
        legacy["task"][1] = "not-json"
        errors = validate_document(legacy, kind="handoff", mode="legacy")
        self.assertTrue(any("task.<key:int>" in error for error in errors))
        with self.assertRaisesRegex(ValueError, "string key"):
            migrate_payload(legacy)

    def test_legacy_mode_rejects_evidence_reference_cycle_before_migration(self) -> None:
        legacy = valid_legacy_handoff()
        cyclic: dict[str, object] = {}
        cyclic["self"] = cyclic
        legacy["context"]["assumptions"] = [cyclic]
        errors = validate_document(legacy, kind="handoff", mode="legacy")
        self.assertTrue(
            any(
                "context.assumptions[0].self" in error
                and "reference cycle" in error
                for error in errors
            )
        )
        with self.assertRaisesRegex(ValueError, "reference cycle"):
            migrate_payload(legacy)

    def test_legacy_mode_rejects_evidence_set_before_migration(self) -> None:
        legacy = valid_legacy_handoff()
        legacy["context"]["assumptions"] = [{"value": {"not-json"}}]
        errors = validate_document(legacy, kind="handoff", mode="legacy")
        self.assertTrue(any("context.assumptions[0].value" in error for error in errors))
        with self.assertRaisesRegex(ValueError, "strict JSON"):
            migrate_payload(legacy)

    def test_legacy_mode_rejects_evidence_nan_before_migration(self) -> None:
        legacy = valid_legacy_handoff()
        legacy["context"]["assumptions"] = [{"value": float("nan")}]
        errors = validate_document(legacy, kind="handoff", mode="legacy")
        self.assertTrue(any("context.assumptions[0].value" in error for error in errors))
        with self.assertRaisesRegex(ValueError, "finite JSON number"):
            migrate_payload(legacy)

    def test_empty_task_statement_is_rejected(self) -> None:
        payload = valid_handoff()
        payload["task"]["statement"] = "  "
        errors = validate_document(payload, kind="handoff")
        self.assertTrue(any("task.statement" in error for error in errors))

    def test_empty_quality_warning_is_rejected(self) -> None:
        payload = valid_handoff()
        payload["quality"]["warnings"] = [""]
        errors = validate_document(payload, kind="handoff")
        self.assertTrue(any("quality.warnings[0]" in error for error in errors))

    def test_recursive_empty_evidence_string_is_rejected(self) -> None:
        payload = valid_handoff()
        payload["context"]["decisions"] = [
            {"statement": "kept", "nested": {"reason": ""}}
        ]
        errors = validate_document(payload, kind="handoff")
        self.assertTrue(any("context.decisions[0].nested.reason" in error for error in errors))

    def test_direct_evidence_rejects_nonfinite_nan(self) -> None:
        payload = valid_handoff_with_computed_value()
        payload["result"]["computed_values"][0]["value"] = float("nan")
        errors = validate_document(payload, kind="handoff")
        self.assertTrue(any("result.computed_values[0].value" in error for error in errors))

    def test_direct_evidence_rejects_nonfinite_infinity(self) -> None:
        payload = valid_handoff_with_computed_value()
        payload["result"]["computed_values"][0]["value"] = float("inf")
        errors = validate_document(payload, kind="handoff")
        self.assertTrue(any("result.computed_values[0].value" in error for error in errors))

    def test_direct_evidence_rejects_non_json_set(self) -> None:
        payload = valid_handoff_with_computed_value()
        payload["result"]["computed_values"][0]["value"] = {"not-json"}
        errors = validate_document(payload, kind="handoff")
        self.assertTrue(any("result.computed_values[0].value" in error for error in errors))

    def test_direct_evidence_rejects_non_json_tuple(self) -> None:
        payload = valid_handoff_with_computed_value()
        payload["result"]["computed_values"][0]["value"] = (1, 2)
        errors = validate_document(payload, kind="handoff")
        self.assertTrue(any("result.computed_values[0].value" in error for error in errors))

    def test_evidence_mixed_key_types_report_deterministic_error(self) -> None:
        payload = valid_handoff_with_computed_value()
        payload["result"]["computed_values"][0]["value"] = {1: "x", "a": "y"}
        first = validate_document(payload, kind="handoff")
        second = validate_document(payload, kind="handoff")
        self.assertEqual(first, second)
        self.assertTrue(any("result.computed_values[0].value" in error for error in first))
        self.assertTrue(any("string key" in error for error in first))

    def test_evidence_invalid_key_errors_ignore_insertion_order(self) -> None:
        first_payload = valid_handoff_with_computed_value()
        first_payload["result"]["computed_values"][0]["value"] = {
            1: "integer",
            (2,): "tuple",
        }
        second_payload = valid_handoff_with_computed_value()
        second_payload["result"]["computed_values"][0]["value"] = {
            (2,): "tuple",
            1: "integer",
        }
        self.assertEqual(
            validate_document(first_payload, kind="handoff"),
            validate_document(second_payload, kind="handoff"),
        )

    def test_direct_evidence_rejects_cyclic_container(self) -> None:
        payload = valid_handoff_with_computed_value()
        cyclic: dict[str, object] = {}
        cyclic["self"] = cyclic
        payload["result"]["computed_values"][0]["value"] = cyclic
        errors = validate_document(payload, kind="handoff")
        self.assertTrue(
            any(
                "result.computed_values[0].value.self" in error
                and "reference cycle" in error
                for error in errors
            )
        )

    def test_schema_recursively_rejects_empty_evidence_strings(self) -> None:
        schema = load_schema("handoff")
        evidence_objects = schema["$defs"]["evidenceObjects"]
        self.assertEqual(
            {"$ref": "#/$defs/evidenceValue"},
            evidence_objects["items"]["additionalProperties"],
        )
        evidence_value = schema["$defs"]["evidenceValue"]
        self.assertIn(
            {"type": "string", "minLength": 1, "pattern": "\\S"},
            evidence_value["oneOf"],
        )
        self.assertIn(
            {
                "type": "object",
                "additionalProperties": {"$ref": "#/$defs/evidenceValue"},
            },
            evidence_value["oneOf"],
        )
        self.assertIn(
            {
                "type": "array",
                "items": {"$ref": "#/$defs/evidenceValue"},
            },
            evidence_value["oneOf"],
        )

    def test_unknown_fields_and_unsafe_artifact_paths_are_rejected(self) -> None:
        for unsafe in ("", "/tmp/result.json", "../result.json", "a/../../result.json", "C:\\result.json"):
            with self.subTest(path=unsafe):
                payload = valid_handoff()
                payload["artifacts"][0]["path"] = unsafe
                errors = validate_document(payload, kind="handoff")
                self.assertTrue(any("artifacts[0].path" in error for error in errors))

        payload = valid_handoff()
        payload["invented"] = "value"
        self.assertTrue(
            any("invented" in error for error in validate_document(payload, kind="handoff"))
        )

    def test_dot_segment_artifact_path_is_rejected(self) -> None:
        payload = valid_handoff()
        payload["artifacts"][0]["path"] = "artifacts/./x"
        errors = validate_document(payload, kind="handoff")
        self.assertTrue(any("artifacts[0].path" in error for error in errors))

    def test_empty_segment_artifact_path_is_rejected(self) -> None:
        payload = valid_handoff()
        payload["artifacts"][0]["path"] = "artifacts//x"
        errors = validate_document(payload, kind="handoff")
        self.assertTrue(any("artifacts[0].path" in error for error in errors))

    def test_trailing_empty_segment_artifact_path_is_rejected(self) -> None:
        payload = valid_handoff()
        payload["artifacts"][0]["path"] = "artifacts/"
        errors = validate_document(payload, kind="handoff")
        self.assertTrue(any("artifacts[0].path" in error for error in errors))

    def test_schema_rejects_noncanonical_relative_path_segments(self) -> None:
        pattern = load_schema("handoff")["$defs"]["relativePath"]["pattern"]
        self.assertIsNotNone(re.fullmatch(pattern, "artifacts/result.json"))
        for invalid in (
            "artifacts/./x",
            "artifacts//x",
            "artifacts/",
            "artifacts/\x00x",
        ):
            with self.subTest(path=invalid):
                self.assertIsNone(re.fullmatch(pattern, invalid))

    def test_schema_and_runtime_reject_whitespace_only_relative_paths(self) -> None:
        pattern = load_schema("handoff")["$defs"]["relativePath"]["pattern"]
        for invalid in ("   ", "\t"):
            with self.subTest(path=invalid):
                payload = valid_handoff()
                payload["artifacts"][0]["path"] = invalid
                errors = validate_document(payload, kind="handoff")
                self.assertTrue(any("artifacts[0].path" in error for error in errors))
                self.assertIsNone(re.fullmatch(pattern, invalid))

    def test_schema_and_runtime_reject_control_character_path_bypasses(self) -> None:
        pattern = load_schema("handoff")["$defs"]["relativePath"]["pattern"]
        for invalid in ("a\n/../x", "a\n//x", "a\n/./x", "a\n/", "a\x7fx"):
            with self.subTest(path=invalid):
                payload = valid_handoff()
                payload["artifacts"][0]["path"] = invalid
                errors = validate_document(payload, kind="handoff")
                self.assertTrue(any("artifacts[0].path" in error for error in errors))
                self.assertIsNone(re.fullmatch(pattern, invalid))

    def test_valid_needs_revision_is_accepted(self) -> None:
        self.assertEqual(
            [], validate_document(valid_needs_revision(), kind="handoff", mode="runtime")
        )

    def test_needs_revision_requires_failed_checks(self) -> None:
        payload = valid_needs_revision()
        payload["next"]["failed_checks"] = []
        errors = validate_document(payload, kind="handoff", mode="runtime")
        self.assertTrue(any("failed_checks" in error for error in errors))

    def test_needs_revision_rejects_forward_authorization(self) -> None:
        payload = valid_needs_revision()
        payload["next"]["recommended_stage"] = "paper-writing"
        errors = validate_document(payload, kind="handoff", mode="runtime")
        self.assertTrue(any("paper-writing" in error for error in errors))

    def test_needs_revision_rejects_complete_authorization(self) -> None:
        payload = valid_needs_revision()
        payload["next"]["recommended_stage"] = "complete"
        errors = validate_document(payload, kind="handoff", mode="runtime")
        self.assertTrue(any("complete" in error for error in errors))

    def test_needs_revision_rejects_unknown_recommended_stage(self) -> None:
        payload = valid_needs_revision()
        payload["next"]["recommended_stage"] = "manual-review"
        errors = validate_document(payload, kind="handoff", mode="runtime")
        self.assertTrue(any("manual-review" in error for error in errors))

    def test_non_revision_rejects_unknown_recommended_stage(self) -> None:
        payload = valid_handoff()
        payload["next"]["recommended_stage"] = "manual-review"
        errors = validate_document(payload, kind="handoff", mode="runtime")
        self.assertTrue(any("manual-review" in error for error in errors))

    def test_non_revision_accepts_complete_recommended_stage(self) -> None:
        payload = valid_handoff()
        payload["next"]["recommended_stage"] = "complete"
        self.assertEqual([], validate_document(payload, kind="handoff", mode="runtime"))

    def test_schema_defines_unified_recommended_stage_enum(self) -> None:
        schema = load_schema("handoff")
        self.assertEqual(
            [*schema["$defs"]["stage"]["enum"], "complete"],
            schema["$defs"]["recommendedStage"]["enum"],
        )
        self.assertEqual(
            {"anyOf": [{"type": "null"}, {"$ref": "#/$defs/recommendedStage"}]},
            schema["properties"]["next"]["properties"]["recommended_stage"],
        )

    def test_schema_encodes_stage_aware_needs_revision_conditions(self) -> None:
        schema = load_schema("handoff")
        conditions = schema["allOf"]
        revision_condition = conditions[0]
        self.assertEqual(
            "needs_revision",
            revision_condition["if"]["properties"]["state"]["properties"]["status"]["const"],
        )
        self.assertEqual(
            1,
            revision_condition["then"]["properties"]["next"]["properties"]["failed_checks"]["minItems"],
        )
        stage_conditions = {
            condition["if"]["properties"]["state"]["properties"]["current_stage"]["const"]: condition
            for condition in conditions[1:]
        }
        stages = load_schema("handoff")["$defs"]["stage"]["enum"]
        self.assertEqual(set(stages), set(stage_conditions))
        for index, stage in enumerate(stages):
            with self.subTest(stage=stage):
                status = stage_conditions[stage]["if"]["properties"]["state"]["properties"]["status"]["const"]
                self.assertEqual("needs_revision", status)
                allowed = stage_conditions[stage]["then"]["properties"]["next"]["properties"]["recommended_stage"]["enum"]
                self.assertEqual([None, *stages[: index + 1]], allowed)

    def test_pending_gate_needs_no_confirmation_evidence(self) -> None:
        self.assertEqual([], validate_document(valid_pending_gate(), kind="gate"))

    def test_gate_rejects_duplicate_artifact_hashes(self) -> None:
        payload = valid_pending_gate()
        digest = "a" * 64
        payload["artifact_hashes"] = [digest, digest]
        errors = validate_document(payload, kind="gate")
        self.assertTrue(any("artifact_hashes[1]" in error and "duplicate" in error for error in errors))

    def test_gate_schema_encodes_status_conditions(self) -> None:
        schema = load_schema("gate")
        confirmed, rejected = schema["allOf"]
        self.assertEqual(
            "confirmed", confirmed["if"]["properties"]["status"]["const"]
        )
        confirmed_properties = confirmed["then"]["properties"]
        self.assertEqual("string", confirmed_properties["confirmed_by"]["type"])
        self.assertEqual("string", confirmed_properties["confirmed_at"]["type"])
        self.assertEqual(1, confirmed_properties["artifact_hashes"]["minItems"])
        self.assertEqual(
            "rejected", rejected["if"]["properties"]["status"]["const"]
        )
        self.assertEqual(
            "string", rejected["then"]["properties"]["rollback_stage"]["type"]
        )

    def test_confirmed_gate_accepts_utc_hash_evidence(self) -> None:
        self.assertEqual([], validate_document(valid_confirmed_gate(), kind="gate"))

    def test_confirmed_gate_rejects_non_utc_timestamp(self) -> None:
        payload = valid_confirmed_gate()
        payload["confirmed_at"] = "2026-08-27T08:00:00+08:00"
        errors = validate_document(payload, kind="gate")
        self.assertTrue(any("confirmed_at" in error for error in errors))

    def test_confirmed_gate_rejects_impossible_utc_timestamp(self) -> None:
        payload = valid_confirmed_gate()
        payload["confirmed_at"] = "2026-02-31T25:99:99Z"
        errors = validate_document(payload, kind="gate")
        self.assertTrue(any("confirmed_at" in error for error in errors))

    def test_gate_schema_confirmed_fields_are_nonempty_utc_and_hashed(self) -> None:
        schema = load_schema("gate")
        confirmed = schema["allOf"][0]["then"]["properties"]
        self.assertEqual(1, confirmed["confirmed_by"]["minLength"])
        self.assertEqual("\\S", confirmed["confirmed_by"]["pattern"])
        self.assertEqual("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]+)?Z$", confirmed["confirmed_at"]["pattern"])

    def test_iteration_rejects_non_utc_updated_at(self) -> None:
        payload = valid_iteration()
        payload["updated_at"] = "2026-08-27T08:00:00+08:00"
        errors = validate_document(payload, kind="iteration")
        self.assertTrue(any("updated_at" in error for error in errors))

    def test_iteration_question_sources_rejects_mixed_key_types(self) -> None:
        payload = valid_iteration()
        payload["question_sources"] = {
            "Q1": "v001",
            1: "v001",
            (2,): "v001",
        }
        first = validate_document(payload, kind="iteration")
        second = validate_document(payload, kind="iteration")
        self.assertEqual(first, second)
        self.assertTrue(any("question_sources.<key:int>" in error for error in first))
        self.assertTrue(any("question_sources.<key:tuple>" in error for error in first))

    def test_iteration_rejects_impossible_utc_timestamp(self) -> None:
        payload = valid_iteration()
        payload["updated_at"] = "2026-99-99T99:99:99Z"
        errors = validate_document(payload, kind="iteration")
        self.assertTrue(any("updated_at" in error for error in errors))

    def test_manifest_rejects_non_utc_created_at(self) -> None:
        payload = valid_manifest()
        payload["created_at"] = "2026-08-27T08:00:00+08:00"
        errors = validate_document(payload, kind="manifest")
        self.assertTrue(any("created_at" in error for error in errors))

    def test_manifest_rejects_impossible_utc_timestamp(self) -> None:
        payload = valid_manifest()
        payload["created_at"] = "2026-02-31T00:00:00Z"
        errors = validate_document(payload, kind="manifest")
        self.assertTrue(any("created_at" in error for error in errors))

    def test_schema_timestamps_require_utc_z(self) -> None:
        utc_pattern = "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]+)?Z$"
        self.assertEqual(utc_pattern, load_schema("iteration")["properties"]["updated_at"]["pattern"])
        self.assertEqual(utc_pattern, load_schema("manifest")["properties"]["created_at"]["pattern"])
        self.assertEqual(utc_pattern, load_schema("gate")["properties"]["confirmed_at"]["pattern"])

    def test_manifest_schema_uses_recursive_nonempty_evidence_values(self) -> None:
        schema = load_schema("manifest")
        self.assertEqual(
            {"$ref": "#/$defs/evidenceValue"},
            schema["properties"]["entries"]["items"]["additionalProperties"],
        )
        self.assertIn(
            {"type": "string", "minLength": 1, "pattern": "\\S"},
            schema["$defs"]["evidenceValue"]["oneOf"],
        )

    def test_manifest_rejects_empty_nested_entry_evidence(self) -> None:
        payload = valid_manifest()
        payload["entries"][0]["metadata"] = {"source": ""}
        errors = validate_document(payload, kind="manifest")
        self.assertTrue(any("entries[0].metadata.source" in error for error in errors))

    def test_iteration_schema_requires_nonempty_project_id(self) -> None:
        schema = load_schema("iteration")
        self.assertEqual("\\S", schema["properties"]["project_id"]["pattern"])

    def test_v1_minimal_handoff_migrates_without_losing_task_text(self) -> None:
        legacy = {
            "schema_version": "1",
            "task": {"statement": "保留这段题面"},
            "state": {"current_stage": "model-solving"},
            "result": {},
            "next": {},
        }
        migrated = migrate_payload(legacy)
        self.assertEqual(migrated["schema_version"], "2")
        self.assertEqual(migrated["task"]["statement"], "保留这段题面")
        self.assertEqual(migrated["state"]["current_stage"], "model-solving")
        self.assertEqual(migrated["context"]["assumptions"], [])
        self.assertTrue(
            any("schema_version 1" in item["statement"] for item in migrated["context"]["decisions"])
        )
        self.assertEqual([], validate_document(migrated, kind="handoff"))

    def test_migration_marks_unhashed_legacy_pass_stale(self) -> None:
        legacy = {
            "schema_version": "1",
            "task": {"statement": "legacy task"},
            "state": {
                "current_stage": "validation",
                "validation_status": "pass",
            },
            "result": {"summary": "Legacy validation passed."},
            "next": {"rationale": "Legacy route."},
        }
        migrated = migrate_payload(legacy)
        self.assertEqual("stale", migrated["state"]["validation_status"])
        self.assertTrue(any("hash" in warning for warning in migrated["quality"]["warnings"]))

    def test_migration_rejects_unrecognized_legacy_artifact_entries(self) -> None:
        legacy = valid_legacy_handoff()
        legacy["state"]["validation_status"] = "pass"
        legacy["artifacts"] = [
            {"path": "artifacts/result.json", "kind": "result", "description": "evidence", "sha256": "a" * 64},
            "unrecognized",
        ]
        with self.assertRaisesRegex(ValueError, r"artifacts\[1\]"):
            migrate_payload(legacy)

    def test_legacy_pass_with_incomplete_artifact_is_always_stale(self) -> None:
        complete = {
            "path": "artifacts/result.json",
            "kind": "result",
            "description": "evidence",
            "sha256": "a" * 64,
        }
        for missing in complete:
            with self.subTest(missing=missing):
                legacy = valid_legacy_handoff()
                legacy["state"]["validation_status"] = "pass"
                artifact = dict(complete)
                artifact.pop(missing)
                legacy["artifacts"] = [artifact]
                migrated = migrate_payload(legacy)
                self.assertEqual("stale", migrated["state"]["validation_status"])
                self.assertTrue(any("hash" in warning for warning in migrated["quality"]["warnings"]))

    def test_legacy_mode_explicitly_migrates_for_validation(self) -> None:
        legacy = {
            "schema_version": "1",
            "task": {"statement": "legacy task"},
            "state": {"current_stage": "model-solving"},
            "result": {},
            "next": {},
        }
        self.assertEqual([], validate_document(legacy, kind="handoff", mode="legacy"))

    def test_load_and_validate_reports_invalid_json_and_field_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid_json = Path(directory) / "invalid.json"
            invalid_json.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "valid JSON"):
                load_and_validate(invalid_json, kind="handoff")

            invalid_payload = valid_handoff()
            invalid_payload["state"]["current_stage"] = "invented"
            invalid_path = Path(directory) / "invalid-payload.json"
            invalid_path.write_text(json.dumps(invalid_payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "state.current_stage"):
                load_and_validate(invalid_path, kind="handoff")

    def test_load_and_validate_rejects_nonstandard_json_constants(self) -> None:
        for constant in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(constant=constant), tempfile.TemporaryDirectory() as directory:
                payload = valid_handoff_with_computed_value()
                payload["result"]["computed_values"][0]["value"] = constant
                path = Path(directory) / "handoff.json"
                path.write_text(json.dumps(payload), encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "non-standard JSON constant"):
                    load_and_validate(path, kind="handoff")

    def test_strict_loader_and_clis_reject_duplicate_json_keys(self) -> None:
        root_duplicate = '{"schema_version":"2","schema_version":"1"}'
        nested_duplicate = '{"schema_version":"1","task":{"statement":"a","statement":"b"}}'
        for text in (root_duplicate, nested_duplicate):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "duplicate key"):
                    load_json_strict(text)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            runtime_path = base / "runtime.json"
            legacy_path = base / "legacy.json"
            output_path = base / "v2.json"
            runtime_path.write_text(root_duplicate, encoding="utf-8")
            legacy_path.write_text(nested_duplicate, encoding="utf-8")
            validated = subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_handoff.py"), "--input", str(runtime_path), "--json"],
                check=False, capture_output=True, text=True,
            )
            migrated = subprocess.run(
                [sys.executable, str(SCRIPTS / "migrate_handoff.py"), "--input", str(legacy_path), "--output", str(output_path)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(1, validated.returncode)
            self.assertFalse(json.loads(validated.stdout)["valid"])
            self.assertIn("duplicate key", validated.stdout)
            self.assertEqual(1, migrated.returncode)
            self.assertIn("duplicate key", migrated.stderr)
            self.assertFalse(output_path.exists())

    def test_validation_cli_json_rejects_nonstandard_constant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = valid_handoff_with_computed_value()
            payload["result"]["computed_values"][0]["value"] = float("nan")
            path = Path(directory) / "handoff.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "validate_handoff.py"),
                    "--input",
                    str(path),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertFalse(report["valid"])
            self.assertTrue(any("non-standard JSON constant" in error for error in report["errors"]))

    def test_migration_cli_rejects_nonstandard_constant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            legacy = {
                "schema_version": "1",
                "task": {"statement": "legacy task"},
                "state": {"current_stage": "model-solving"},
                "result": {"computed_values": [{"name": "objective", "value": float("inf")}]},
                "next": {},
            }
            input_path = Path(directory) / "legacy.json"
            output_path = Path(directory) / "v2.json"
            input_path.write_text(json.dumps(legacy), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "migrate_handoff.py"),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn("non-standard JSON constant", result.stderr)
            self.assertFalse(output_path.exists())

    def test_migration_cli_rejects_artifact_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = base / "project"
            external = base / "external"
            project.mkdir()
            external.mkdir()
            external.joinpath("result.json").write_text("{}", encoding="utf-8")
            try:
                project.joinpath("artifacts").symlink_to(external, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlinks unavailable: {error}")
            legacy = {
                "schema_version": "1",
                "task": {"statement": "legacy task"},
                "state": {"current_stage": "model-solving"},
                "result": {},
                "next": {},
                "artifacts": [
                    {
                        "path": "artifacts/result.json",
                        "kind": "result",
                        "description": "external evidence",
                    }
                ],
            }
            input_path = project / "legacy.json"
            output_path = project / "v2.json"
            input_path.write_text(json.dumps(legacy), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "migrate_handoff.py"),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn("symlink", result.stderr)
            self.assertFalse(output_path.exists())

    def test_migration_cli_validates_artifacts_against_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output_root = base / "output"
            outside = base / "outside"
            source.joinpath("artifacts").mkdir(parents=True)
            output_root.mkdir()
            outside.mkdir()
            source.joinpath("artifacts/result.json").write_text("{}", encoding="utf-8")
            outside.joinpath("result.json").write_text("{}", encoding="utf-8")
            try:
                output_root.joinpath("artifacts").symlink_to(outside, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlinks unavailable: {error}")
            legacy = valid_legacy_handoff()
            legacy["artifacts"] = [{"path": "artifacts/result.json", "kind": "result", "description": "evidence"}]
            input_path = source / "legacy.json"
            output_path = output_root / "v2.json"
            input_path.write_text(json.dumps(legacy), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "migrate_handoff.py"), "--input", str(input_path), "--output", str(output_path)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn("symlink", result.stderr)
            self.assertFalse(output_path.exists())

    def test_migration_cli_rejects_symlinked_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = base / "project"
            outside = base / "outside"
            project.mkdir()
            outside.mkdir()
            try:
                project.joinpath("linked-output").symlink_to(outside, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlinks unavailable: {error}")
            legacy_path = project / "legacy.json"
            legacy_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "task": {"statement": "legacy task"},
                        "state": {"current_stage": "model-solving"},
                        "result": {},
                        "next": {},
                    }
                ),
                encoding="utf-8",
            )
            output_path = project / "linked-output" / "v2.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "migrate_handoff.py"),
                    "--input",
                    str(legacy_path),
                    "--output",
                    str(output_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn("symlink", result.stderr)
            self.assertFalse(outside.joinpath("v2.json").exists())

    def test_migration_cli_rejects_normalized_symlinked_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = base / "project"
            outside = base / "outside"
            project.mkdir()
            outside.mkdir()
            try:
                project.joinpath("linked-output").symlink_to(
                    outside, target_is_directory=True
                )
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlinks unavailable: {error}")
            legacy_path = project / "legacy.json"
            legacy_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "task": {"statement": "legacy task"},
                        "state": {"current_stage": "model-solving"},
                        "result": {},
                        "next": {},
                    }
                ),
                encoding="utf-8",
            )
            output_path = project / "missing" / ".." / "linked-output" / "v2.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "migrate_handoff.py"),
                    "--input",
                    str(legacy_path),
                    "--output",
                    str(output_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn("must not contain", result.stderr)
            self.assertFalse(outside.joinpath("v2.json").exists())

    def test_migration_serialization_disallows_nonstandard_constants(self) -> None:
        migrated = migrate_payload(
            {
                "schema_version": "1",
                "task": {"statement": "legacy task"},
                "state": {"current_stage": "model-solving"},
                "result": {},
                "next": {},
            }
        )
        migrated["result"]["computed_values"] = [
            {"name": "objective", "value": float("nan")}
        ]
        with self.assertRaisesRegex(ValueError, "JSON"):
            serialize_payload(migrated, pretty=False)

    def test_serialization_preflights_all_strict_json_values(self) -> None:
        for invalid in ((1, 2), {1: "value"}, float("nan")):
            with self.subTest(value=type(invalid).__name__):
                with self.assertRaisesRegex(ValueError, "strict JSON"):
                    serialize_payload({"value": invalid})

    def test_windows_output_paths_reject_lexical_traversal(self) -> None:
        for invalid in (
            r"C:\project\..\outside\v2.json",
            r"\\server\share\..\outside\v2.json",
            r"C:project\..\outside\v2.json",
            r"C:\project\.\v2.json",
        ):
            with self.subTest(path=invalid), self.assertRaisesRegex(ValueError, r"\.\."):
                _canonical_output_path(invalid)
        self.assertEqual(Path(r"C:\project\v2.json"), _canonical_output_path(r"C:\project\v2.json"))

    def test_deep_direct_and_text_json_fail_without_recursion_error(self) -> None:
        payload = valid_handoff_with_computed_value()
        nested: object = "leaf"
        for _ in range(1400):
            nested = [nested]
        payload["result"]["computed_values"][0]["value"] = nested
        errors = validate_document(payload, kind="handoff")
        self.assertTrue(any("maximum JSON depth" in error for error in errors))
        deep_text = "[" * 1400 + "0" + "]" * 1400
        with self.assertRaisesRegex(ValueError, "depth"):
            load_json_strict(deep_text)

    def test_deep_validation_cli_json_returns_machine_readable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = valid_handoff_with_computed_value()
            nested: object = "leaf"
            for _ in range(300):
                nested = [nested]
            payload["result"]["computed_values"][0]["value"] = nested
            path = Path(directory) / "deep.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_handoff.py"), "--input", str(path), "--json"],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(1, result.returncode)
            report = json.loads(result.stdout)
            self.assertFalse(report["valid"])
            self.assertIn("maximum JSON depth", " ".join(report["errors"]))

    def test_load_and_validate_rejects_artifact_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = base / "project"
            external = base / "external"
            project.mkdir()
            external.mkdir()
            external.joinpath("result.json").write_text("{}", encoding="utf-8")
            try:
                project.joinpath("artifacts").symlink_to(external, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlinks unavailable: {error}")
            payload = valid_handoff()
            handoff = project / "handoff.json"
            handoff.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, r"artifacts\[0\]\.path.*symlink"):
                load_and_validate(handoff, kind="handoff")

    def test_all_versioned_schema_documents_are_strict_json_objects(self) -> None:
        for kind in ("handoff", "iteration", "manifest", "gate"):
            with self.subTest(kind=kind):
                schema = load_schema(kind)
                self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
                self.assertEqual("object", schema["type"])
                self.assertFalse(schema["additionalProperties"])
                self.assertIn("schema_version", schema["required"])

    def test_cli_validation_and_migration(self) -> None:
        valid = subprocess.run(
            [sys.executable, str(SCRIPTS / "validate_handoff.py"), "--input", str(FIXTURE)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, valid.returncode, valid.stdout + valid.stderr)
        self.assertIn("handoff valid", valid.stdout)

        with tempfile.TemporaryDirectory() as directory:
            legacy_path = Path(directory) / "legacy.json"
            output_path = Path(directory) / "v2.json"
            legacy_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "task": {"statement": "legacy task"},
                        "state": {"current_stage": "model-solving"},
                        "result": {},
                        "next": {},
                    }
                ),
                encoding="utf-8",
            )
            migrated = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "migrate_handoff.py"),
                    "--input",
                    str(legacy_path),
                    "--output",
                    str(output_path),
                    "--pretty",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, migrated.returncode, migrated.stdout + migrated.stderr)
            self.assertEqual("2", json.loads(output_path.read_text(encoding="utf-8"))["schema_version"])
            self.assertEqual(
                "2", load_and_validate(output_path, kind="handoff")["schema_version"]
            )

            refused = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "migrate_handoff.py"),
                    "--input",
                    str(legacy_path),
                    "--output",
                    str(output_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, refused.returncode)
            self.assertIn("exists", refused.stderr)


if __name__ == "__main__":
    unittest.main()
