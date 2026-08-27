from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from project_state import (  # noqa: E402
    create_iteration,
    init_project,
    load_current,
    mark_stale,
    record_gate,
)


class ProjectStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temporary.name).resolve()
        self.input_dir = self.temp_path / "source-input"
        self.input_dir.mkdir()
        (self.input_dir / "problem.txt").write_text(
            "Q1: forecast demand\nQ2: optimize allocation\n",
            encoding="utf-8",
        )
        (self.input_dir / "data.csv").write_text("x,y\n1,2\n", encoding="utf-8")
        os.utime(
            self.input_dir / "data.csv",
            ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000),
        )
        os.chmod(self.input_dir / "data.csv", 0o640)
        self.source_mode = stat.S_IMODE((self.input_dir / "data.csv").stat().st_mode)
        self.project = self.temp_path / "modeling-project"
        self.state = init_project(
            self.project,
            python_executable=Path(sys.executable).resolve(),
            input_dir=self.input_dir,
            template_path=None,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_init_requires_absolute_python_and_creates_v001(self) -> None:
        self.assertEqual("v001", self.state["active_iteration"])
        self.assertEqual({"Q1": "v001", "Q2": "v001"}, self.state["question_sources"])
        self.assertTrue((self.project / "iterations/v001/manifests/input_manifest.json").is_file())
        for directory in ("state", "code", "data", "results", "figures", "paper", "manifests"):
            self.assertTrue((self.project / "iterations/v001" / directory).is_dir())

    def test_init_copies_inputs_and_records_complete_manifest_without_chmod(self) -> None:
        manifest = json.loads(
            (self.project / "iterations/v001/manifests/input_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual("2", manifest["schema_version"])
        self.assertEqual("input", manifest["manifest_type"])
        self.assertEqual(["input/data.csv", "input/problem.txt"], [entry["path"] for entry in manifest["entries"]])
        data_entry = manifest["entries"][0]
        self.assertEqual(len(b"x,y\n1,2\n"), data_entry["byte_size"])
        self.assertEqual(hashlib.sha256(b"x,y\n1,2\n").hexdigest(), data_entry["sha256"])
        self.assertEqual("input_dir", data_entry["source_label"])
        self.assertIs(data_entry["read_only"], True)
        self.assertEqual("2023-11-14T22:13:20Z", data_entry["modified_at"])
        self.assertEqual(self.source_mode, stat.S_IMODE((self.input_dir / "data.csv").stat().st_mode))
        self.assertEqual(b"x,y\n1,2\n", (self.project / "input/data.csv").read_bytes())

    def test_init_rejects_relative_python_path(self) -> None:
        with self.assertRaises(ValueError):
            init_project(
                self.temp_path / "relative-python-project",
                python_executable=Path("python3"),
                input_dir=self.input_dir,
                template_path=None,
            )

    def test_init_rejects_missing_input_directory(self) -> None:
        with self.assertRaises(ValueError):
            init_project(
                self.temp_path / "missing-input-project",
                python_executable=Path(sys.executable).resolve(),
                input_dir=self.temp_path / "missing-input",
                template_path=None,
            )

    def test_init_refuses_output_collision(self) -> None:
        with self.assertRaises(FileExistsError):
            init_project(
                self.project,
                python_executable=Path(sys.executable).resolve(),
                input_dir=self.input_dir,
                template_path=None,
            )

    def test_init_rejects_input_symlink(self) -> None:
        linked_input = self.temp_path / "linked-input"
        try:
            linked_input.symlink_to(self.input_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available")
        with self.assertRaises(ValueError):
            init_project(
                self.temp_path / "symlink-input-project",
                python_executable=Path(sys.executable).resolve(),
                input_dir=linked_input,
                template_path=None,
            )

    def test_init_rejects_project_inside_input_directory(self) -> None:
        with self.assertRaises(ValueError):
            init_project(
                self.input_dir / "nested-project",
                python_executable=Path(sys.executable).resolve(),
                input_dir=self.input_dir,
                template_path=None,
            )

    def test_new_iteration_never_overwrites_parent_and_preserves_unaffected_question(self) -> None:
        parent_file = self.project / "iterations/v001/results/evidence.txt"
        parent_file.write_text("parent evidence", encoding="utf-8")
        version = create_iteration(
            self.project,
            reason="revise Q2",
            affected_questions=["Q2"],
        )
        current = load_current(self.project)
        self.assertEqual("v002", version)
        self.assertEqual("v001", current["question_sources"]["Q1"])
        self.assertEqual("v002", current["question_sources"]["Q2"])
        self.assertEqual("parent evidence", parent_file.read_text(encoding="utf-8"))
        self.assertTrue((self.project / "iterations/v001").is_dir())
        self.assertTrue((self.project / "iterations/v002").is_dir())
        iteration_manifest = json.loads(
            (self.project / "iterations/v002/manifests/iteration_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("run", iteration_manifest["manifest_type"])
        entries = {entry["path"]: entry for entry in iteration_manifest["entries"]}
        copied_path = "iterations/v002/results/evidence.txt"
        self.assertIn(copied_path, entries)
        self.assertEqual("iteration-snapshot", entries[copied_path]["kind"])
        self.assertIn("not a model computation run", entries[copied_path]["description"])
        self.assertEqual(
            hashlib.sha256(b"parent evidence").hexdigest(),
            entries[copied_path]["sha256"],
        )

    def test_new_iteration_uses_next_numeric_version_after_existing_directory(self) -> None:
        (self.project / "iterations/v002").mkdir()
        self.assertEqual(
            "v003",
            create_iteration(self.project, reason="next version", affected_questions=["Q1"]),
        )

    def test_record_gate_appends_valid_audit_record_and_updates_current(self) -> None:
        digest = "a" * 64
        report = record_gate(
            self.project,
            gate_id="gate1",
            status="confirmed",
            confirmer="reviewer",
            artifact_hashes=[digest],
            note="accepted after review",
        )
        self.assertEqual("confirmed", load_current(self.project)["gates"]["gate1"])
        self.assertEqual(1, len(report["records"]))
        self.assertEqual("reviewer", report["records"][0]["confirmed_by"])
        self.assertEqual([digest], report["records"][0]["artifact_hashes"])
        self.assertEqual("accepted after review", report["records"][0]["notes"])

    def test_record_gate_rejects_unknown_gate_and_status(self) -> None:
        for gate_id, status in (("gate4", "pending"), ("gate1", "approved")):
            with self.subTest(gate_id=gate_id, status=status):
                with self.assertRaises(ValueError):
                    record_gate(
                        self.project,
                        gate_id=gate_id,
                        status=status,
                        confirmer="reviewer",
                        artifact_hashes=[],
                        note="invalid",
                    )

    def test_rejected_gate_uses_protocol_rollback_stage(self) -> None:
        expected = {
            "gate1": "problem-analysis",
            "gate2": "model-construction",
            "gate3": "validation",
        }
        for gate_id, rollback_stage in expected.items():
            with self.subTest(gate_id=gate_id):
                project = self.temp_path / f"project-{gate_id}"
                init_project(
                    project,
                    python_executable=Path(sys.executable).resolve(),
                    input_dir=self.input_dir,
                    template_path=None,
                )
                report = record_gate(
                    project,
                    gate_id=gate_id,
                    status="rejected",
                    confirmer="reviewer",
                    artifact_hashes=[],
                    note="return for revision",
                )
                self.assertEqual(rollback_stage, report["records"][0]["rollback_stage"])

    def test_record_gate_refuses_write_through_symlink(self) -> None:
        qa = self.project / "qa"
        qa.rmdir()
        outside = self.temp_path / "outside-qa"
        outside.mkdir()
        try:
            qa.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available")
        with self.assertRaises(ValueError):
            record_gate(
                self.project,
                gate_id="gate1",
                status="pending",
                confirmer="reviewer",
                artifact_hashes=[],
                note="must stay inside project",
            )
        self.assertFalse((outside / "gates.json").exists())

    def test_input_hash_change_marks_dependent_run_figure_validation_and_paper_stale(self) -> None:
        evidence = self.project / "iterations/v001/results/old-result.txt"
        evidence.write_text("keep me", encoding="utf-8")
        report = mark_stale(
            self.project,
            changed_paths=["input/data.csv"],
            question_ids=["Q2"],
        )
        loaded = json.loads((self.project / "qa/staleness.json").read_text(encoding="utf-8"))
        self.assertEqual(report, loaded)
        self.assertEqual("stale", report["status"])
        self.assertEqual(
            {"run", "figure", "validation", "paper"},
            set(report["invalidated"]["Q2"]),
        )
        self.assertEqual("stale", load_current(self.project)["status"])
        self.assertTrue((self.project / "qa/staleness.md").is_file())
        self.assertEqual("keep me", evidence.read_text(encoding="utf-8"))

    def test_mark_stale_rejects_unsafe_changed_path(self) -> None:
        for unsafe in ("/tmp/data.csv", "../data.csv", "input/../data.csv"):
            with self.subTest(path=unsafe):
                with self.assertRaises(ValueError):
                    mark_stale(self.project, changed_paths=[unsafe], question_ids=["Q1"])

    def test_load_current_rejects_duplicate_json_keys(self) -> None:
        (self.project / "current.json").write_text(
            '{"schema_version":"2","schema_version":"2"}\n',
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            load_current(self.project)

    def test_load_current_rejects_question_source_for_missing_iteration(self) -> None:
        current = load_current(self.project)
        current["question_sources"]["Q1"] = "v999"
        (self.project / "current.json").write_text(
            json.dumps(current, sort_keys=True),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            load_current(self.project)

    def test_cli_init_prints_absolute_current_json_path(self) -> None:
        cli_project = self.temp_path / "cli-project"
        result = subprocess.run(
            [
                str(Path(sys.executable).resolve()),
                str(SCRIPTS / "project_state.py"),
                "init",
                str(cli_project),
                "--python-executable",
                str(Path(sys.executable).resolve()),
                "--input-dir",
                str(self.input_dir),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"{cli_project / 'current.json'}\n", result.stdout)

    def test_cli_mutations_print_absolute_audit_json_paths(self) -> None:
        commands = (
            (
                ["new-iteration", str(self.project), "--reason", "revise Q2", "--question", "Q2"],
                self.project / "iterations/v002/state/iteration.json",
            ),
            (
                ["gate", str(self.project), "--gate-id", "gate1", "--status", "pending", "--confirmer", "reviewer"],
                self.project / "qa/gates.json",
            ),
            (
                ["stale", str(self.project), "--changed-path", "input/data.csv", "--question", "Q2"],
                self.project / "qa/staleness.json",
            ),
        )
        for arguments, expected_path in commands:
            with self.subTest(command=arguments[0]):
                result = subprocess.run(
                    [
                        str(Path(sys.executable).resolve()),
                        str(SCRIPTS / "project_state.py"),
                        *arguments,
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertTrue(expected_path.is_absolute())
                self.assertEqual(f"{expected_path}\n", result.stdout)


if __name__ == "__main__":
    unittest.main()
