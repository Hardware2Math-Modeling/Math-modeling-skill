from __future__ import annotations

import copy
import json
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

    def test_runtime_rejects_legacy_and_type_confusion(self) -> None:
        payload = valid_handoff()
        payload["schema_version"] = 2
        errors = validate_document(payload, kind="handoff", mode="runtime")
        self.assertTrue(any("schema_version" in error for error in errors))

        legacy = {
            "schema_version": "1",
            "task": {"statement": "legacy"},
            "state": {"current_stage": "model-solving"},
            "result": {},
            "next": {},
        }
        errors = validate_document(legacy, kind="handoff", mode="runtime")
        self.assertTrue(any("schema_version" in error for error in errors))

    def test_empty_semantic_strings_are_rejected(self) -> None:
        payload = valid_handoff()
        payload["task"]["statement"] = "  "
        payload["quality"]["warnings"] = [""]
        errors = validate_document(payload, kind="handoff")
        self.assertTrue(any("task.statement" in error for error in errors))
        self.assertTrue(any("quality.warnings[0]" in error for error in errors))

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

    def test_needs_revision_requires_failed_checks_and_no_forward_authorization(self) -> None:
        payload = valid_handoff()
        payload["state"]["status"] = "needs_revision"
        payload["next"]["recommended_stage"] = "paper-writing"
        payload["next"]["failed_checks"] = []
        errors = validate_document(payload, kind="handoff", mode="runtime")
        self.assertTrue(any("failed_checks" in error for error in errors))
        self.assertTrue(any("paper-writing" in error for error in errors))

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
                schema = json.loads(
                    SCHEMAS.joinpath(f"{kind}.schema.json").read_text(encoding="utf-8")
                )
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
