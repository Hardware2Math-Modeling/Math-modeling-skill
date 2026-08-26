from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from install_local import install_local  # noqa: E402
from test_suite_validation import make_valid_suite  # noqa: E402


class InstallLocalTests(unittest.TestCase):
    def test_dry_run_builds_bundle_without_running_codex(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            bundle = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            calls: list[tuple[list[str], bool]] = []

            def runner(command: list[str], *, check: bool) -> None:
                calls.append((command, check))

            commands = install_local(
                source,
                bundle,
                apply=False,
                codex_bin="/fake/codex",
                runner=runner,
            )

            self.assertEqual(calls, [])
            self.assertTrue(
                (bundle / ".agents" / "plugins" / "marketplace.json").is_file()
            )
            self.assertEqual(
                commands,
                [
                    ["/fake/codex", "plugin", "marketplace", "add", str(bundle.resolve())],
                    [
                        "/fake/codex",
                        "plugin",
                        "add",
                        "math-modeling-suite@math-modeling-local",
                    ],
                ],
            )

    def test_apply_runs_commands_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            bundle = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            calls: list[list[str]] = []

            def runner(command: list[str], *, check: bool) -> None:
                self.assertTrue(check)
                calls.append(command)

            commands = install_local(
                source,
                bundle,
                apply=True,
                codex_bin="/fake/codex",
                runner=runner,
            )

            self.assertEqual(calls, commands)

    def test_registered_marketplace_skips_marketplace_add(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            bundle = base / "bundle"
            source.mkdir()
            make_valid_suite(source)

            commands = install_local(
                source,
                bundle,
                apply=False,
                marketplace_registered=True,
                codex_bin="codex",
            )

            self.assertEqual(
                commands,
                [
                    [
                        "codex",
                        "plugin",
                        "add",
                        "math-modeling-suite@math-modeling-local",
                    ]
                ],
            )

    def test_apply_reuses_a_valid_dry_run_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            bundle = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            install_local(source, bundle, apply=False, codex_bin="/fake/codex")
            calls: list[list[str]] = []

            def runner(command: list[str], *, check: bool) -> None:
                self.assertTrue(check)
                calls.append(command)

            commands = install_local(
                source,
                bundle,
                apply=True,
                codex_bin="/fake/codex",
                runner=runner,
            )

            self.assertEqual(calls, commands)

    def test_missing_codex_fails_before_creating_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            bundle = base / "bundle"
            source.mkdir()
            make_valid_suite(source)

            with patch("install_local.shutil.which", return_value=None):
                with self.assertRaisesRegex(FileNotFoundError, "Codex CLI"):
                    install_local(source, bundle, apply=True)

            self.assertFalse(bundle.exists())


if __name__ == "__main__":
    unittest.main()
