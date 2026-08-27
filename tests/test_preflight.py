from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from preflight import diagnose_environment  # noqa: E402


class PreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temporary.name).resolve()
        self.project = self.temp_path / "modeling-project"
        self.project.mkdir()
        self.python = Path(sys.executable).resolve()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_reports_missing_package_with_exact_interpreter_command_without_pip(self) -> None:
        observed_commands: list[list[str]] = []
        real_run = subprocess.run

        def record_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            observed_commands.append(command)
            return real_run(command, **kwargs)

        with (
            patch("preflight.shutil.which", return_value=None),
            patch("preflight.subprocess.run", side_effect=record_run),
        ):
            report = diagnose_environment(
                project_root=self.project,
                python_executable=self.python,
                required_packages=["package_that_cannot_be_present_in_fixture"],
                template_path=None,
            )

        self.assertEqual(report["python"]["status"], "pass")
        self.assertEqual(report["packages"][0]["status"], "missing")
        self.assertIn(
            f"{self.python} -m pip install",
            report["packages"][0]["install_command"],
        )
        self.assertEqual(
            [str(self.python), "-c", "import sys; print(sys.executable); print(sys.version)"],
            observed_commands[0],
        )
        self.assertFalse(
            any("-m" in command and "pip" in command for command in observed_commands),
            observed_commands,
        )

    def test_rejects_relative_or_nonregular_interpreter_before_diagnosis(self) -> None:
        for interpreter in (Path("python3"), self.project):
            with self.subTest(interpreter=interpreter):
                with self.assertRaises(ValueError):
                    diagnose_environment(
                        project_root=self.project,
                        python_executable=interpreter,
                        required_packages=[],
                        template_path=None,
                    )

    def test_records_supplied_and_reported_python_identity(self) -> None:
        with patch("preflight.shutil.which", return_value=None):
            report = diagnose_environment(
                project_root=self.project,
                python_executable=self.python,
                required_packages=[],
                template_path=None,
            )

        python = report["python"]
        self.assertEqual(str(self.python), python["path"])
        self.assertEqual(str(self.python), python["resolved_path"])
        self.assertEqual(
            self.python,
            Path(python["reported_executable"]).resolve(strict=True),
        )
        self.assertIn(str(sys.version_info.major), python["version"])
        self.assertTrue(python["platform"])

    def test_checks_latex_tools_in_priority_order_and_scopes_missing_tool(self) -> None:
        observed_tools: list[str] = []

        def missing_tool(name: str) -> None:
            observed_tools.append(name)
            return None

        with patch("preflight.shutil.which", side_effect=missing_tool):
            result_only = diagnose_environment(
                project_root=self.project,
                python_executable=self.python,
                required_packages=[],
                template_path=None,
            )
            paper = diagnose_environment(
                project_root=self.project,
                python_executable=self.python,
                required_packages=[],
                template_path=None,
                paper_production=True,
            )

        self.assertEqual(
            ["tectonic", "latexmk", "xelatex", "pdflatex"] * 2,
            observed_tools,
        )
        self.assertEqual("warning", result_only["latex"]["status"])
        self.assertEqual("blocking", paper["latex"]["status"])
        self.assertEqual("warning", result_only["status"])
        self.assertEqual("blocking", paper["status"])

    def test_missing_user_template_selects_non_submission_fallback(self) -> None:
        with patch("preflight.shutil.which", return_value=None):
            report = diagnose_environment(
                project_root=self.project,
                python_executable=self.python,
                required_packages=[],
                template_path=self.project / "missing-template.tex",
            )

        self.assertEqual("fallback_non_submission", report["template"]["status"])
        self.assertEqual(
            str(self.project / "missing-template.tex"),
            report["template"]["requested_path"],
        )


if __name__ == "__main__":
    unittest.main()
