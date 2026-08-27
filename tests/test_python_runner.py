from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from python_runner import RunFailed, run_python  # noqa: E402


class PythonRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name).resolve() / "modeling-project"
        self.project.mkdir()
        self.python = Path(sys.executable).resolve()
        self.input_file = self.project / "input.json"
        self.input_file.write_text('{"value": 5}\n', encoding="utf-8")
        self.script = self.project / "solve.py"
        self.script.write_text(
            "import json\n"
            "import os\n"
            "from pathlib import Path\n"
            "payload = json.loads(Path('input.json').read_text(encoding='utf-8'))\n"
            "Path('results/value.json').write_text(json.dumps({'value': payload['value'] * 2}), encoding='utf-8')\n"
            "print(os.environ['PYTHONHASHSEED'])\n"
            "print(os.environ['MPLBACKEND'])\n",
            encoding="utf-8",
        )
        self.failing_script = self.project / "fail.py"
        self.failing_script.write_text(
            "import sys\nprint('failed stdout')\nprint('failed stderr', file=sys.stderr)\nraise SystemExit(3)\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_captures_command_exit_code_logs_and_hashes_without_shell(self) -> None:
        observed_kwargs: list[dict[str, object]] = []
        real_run = subprocess.run

        def record_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            observed_kwargs.append(kwargs)
            return real_run(command, **kwargs)

        with patch("python_runner.subprocess.run", side_effect=record_run):
            result = run_python(
                self.python,
                self.script,
                cwd=self.project,
                output_dir=self.project / "results",
                input_paths=[self.input_file],
                seed=7,
                timeout_seconds=30,
            )

        output_dir = self.project / "results"
        self.assertEqual(0, result["exit_code"])
        self.assertEqual("success", result["status"])
        self.assertEqual(7, result["seed"])
        self.assertEqual(
            hashlib.sha256(self.script.read_bytes()).hexdigest(),
            result["code_hash"],
        )
        self.assertEqual(
            hashlib.sha256(self.input_file.read_bytes()).hexdigest(),
            result["input_hashes"]["input.json"],
        )
        self.assertEqual(
            hashlib.sha256((output_dir / "value.json").read_bytes()).hexdigest(),
            result["output_hashes"]["value.json"],
        )
        self.assertEqual("7\nAgg\n", (output_dir / "stdout.log").read_text(encoding="utf-8"))
        self.assertEqual("", (output_dir / "stderr.log").read_text(encoding="utf-8"))
        self.assertTrue((output_dir / "command.json").is_file())
        manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("2", manifest["schema_version"])
        self.assertEqual("run", manifest["manifest_type"])
        self.assertEqual([result], manifest["entries"])
        self.assertIs(observed_kwargs[0]["shell"], False)

    def test_json_io_mode_builds_the_declared_interface(self) -> None:
        script = self.project / "json_solver.py"
        script.write_text(
            "import argparse, json\n"
            "from pathlib import Path\n"
            "parser = argparse.ArgumentParser()\n"
            "parser.add_argument('--input', required=True)\n"
            "parser.add_argument('--output', required=True)\n"
            "parser.add_argument('--seed', required=True, type=int)\n"
            "args = parser.parse_args()\n"
            "payload = json.loads(Path(args.input).read_text(encoding='utf-8'))\n"
            "Path(args.output).write_text(json.dumps({'value': payload['value'], 'seed': args.seed}), encoding='utf-8')\n",
            encoding="utf-8",
        )
        output_dir = self.project / "json-results"
        output_path = output_dir / "output.json"

        result = run_python(
            self.python,
            script,
            cwd=self.project,
            output_dir=output_dir,
            input_paths=[self.input_file],
            seed=11,
            timeout_seconds=30,
            cli_mode="json_io",
            input_path=self.input_file,
            output_path=output_path,
        )

        self.assertEqual(
            [
                str(self.python),
                str(script),
                "--input",
                str(self.input_file),
                "--output",
                str(output_path),
                "--seed",
                "11",
            ],
            result["command"],
        )
        self.assertEqual({"value": 5, "seed": 11}, json.loads(output_path.read_text()))

    def test_json_io_zero_exit_without_declared_output_preserves_failure_evidence(self) -> None:
        script = self.project / "missing_output.py"
        script.write_text(
            "import argparse\n"
            "parser = argparse.ArgumentParser()\n"
            "parser.add_argument('--input', required=True)\n"
            "parser.add_argument('--output', required=True)\n"
            "parser.add_argument('--seed', required=True)\n"
            "parser.parse_args()\n",
            encoding="utf-8",
        )
        output_dir = self.project / "missing-output-results"
        output_path = output_dir / "output.json"

        with self.assertRaises(RunFailed) as raised:
            run_python(
                self.python,
                script,
                cwd=self.project,
                output_dir=output_dir,
                input_paths=[self.input_file],
                seed=13,
                timeout_seconds=30,
                cli_mode="json_io",
                input_path=self.input_file,
                output_path=output_path,
            )

        self.assertEqual(0, raised.exception.result["exit_code"])
        self.assertEqual("failed", raised.exception.result["status"])
        self.assertNotIn("output.json", raised.exception.result["output_hashes"])
        self.assertIn("declared JSON output", raised.exception.result["failure_reason"])
        manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual([raised.exception.result], manifest["entries"])

    def test_rejects_cwd_below_plugin_root_before_creating_output(self) -> None:
        plugin = self.project / "fixture-plugin"
        (plugin / ".codex-plugin").mkdir(parents=True)
        (plugin / ".codex-plugin/plugin.json").write_text("{}\n", encoding="utf-8")
        runtime = plugin / "runtime"
        runtime.mkdir()
        script = runtime / "noop.py"
        script.write_text("pass\n", encoding="utf-8")
        output_dir = runtime / "results"

        with self.assertRaises(ValueError):
            run_python(
                self.python,
                script,
                cwd=runtime,
                output_dir=output_dir,
                input_paths=[],
                seed=0,
                timeout_seconds=30,
            )

        self.assertFalse(output_dir.exists())

    def test_accepts_an_existing_empty_output_directory(self) -> None:
        output_dir = self.project / "results"
        output_dir.mkdir()

        result = run_python(
            self.python,
            self.script,
            cwd=self.project,
            output_dir=output_dir,
            input_paths=[self.input_file],
            seed=7,
            timeout_seconds=30,
        )

        self.assertEqual("success", result["status"])
        self.assertTrue((output_dir / "run_manifest.json").is_file())

    def test_nonzero_exit_raises_and_preserves_failed_run_evidence(self) -> None:
        output_dir = self.project / "failed"

        with self.assertRaises(RunFailed) as raised:
            run_python(
                self.python,
                self.failing_script,
                cwd=self.project,
                output_dir=output_dir,
                input_paths=[],
                seed=0,
                timeout_seconds=30,
            )

        self.assertEqual(3, raised.exception.result["exit_code"])
        self.assertEqual("failed", raised.exception.result["status"])
        self.assertEqual("failed stdout\n", (output_dir / "stdout.log").read_text(encoding="utf-8"))
        self.assertEqual("failed stderr\n", (output_dir / "stderr.log").read_text(encoding="utf-8"))
        manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("failed", manifest["entries"][0]["status"])

    def test_timeout_raises_and_preserves_timeout_manifest(self) -> None:
        script = self.project / "timeout.py"
        script.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
        output_dir = self.project / "timed-out"

        with self.assertRaises(RunFailed) as raised:
            run_python(
                self.python,
                script,
                cwd=self.project,
                output_dir=output_dir,
                input_paths=[],
                seed=1,
                timeout_seconds=0.05,
            )

        self.assertIsNone(raised.exception.result["exit_code"])
        self.assertEqual("timeout", raised.exception.result["status"])
        manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("timeout", manifest["entries"][0]["status"])

    def test_invalid_mode_or_relative_interpreter_is_rejected_without_output(self) -> None:
        cases = (
            {"python": self.python, "cli_mode": "invented"},
            {"python": Path("python3"), "cli_mode": "plain"},
        )
        for index, case in enumerate(cases):
            output_dir = self.project / f"invalid-{index}"
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    run_python(
                        case["python"],
                        self.script,
                        cwd=self.project,
                        output_dir=output_dir,
                        input_paths=[self.input_file],
                        seed=0,
                        timeout_seconds=30,
                        cli_mode=case["cli_mode"],
                    )
                self.assertFalse(output_dir.exists())


if __name__ == "__main__":
    unittest.main()
