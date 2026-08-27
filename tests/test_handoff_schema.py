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
    migrate_payload,
    validate_document,
)


def valid_handoff() -> dict[str, object]:
    return copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))


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

    def test_needs_revision_rejects_unknown_recommended_stage(self) -> None:
        payload = valid_needs_revision()
        payload["next"]["recommended_stage"] = "manual-review"
        errors = validate_document(payload, kind="handoff", mode="runtime")
        self.assertTrue(any("manual-review" in error for error in errors))

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
