from __future__ import annotations

import json
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

            with self.assertRaisesRegex(ValueError, "already registered"):
                install_local(
                    source,
                    bundle,
                    apply=False,
                    marketplace_registered=True,
                    codex_bin="codex",
                )
            self.assertFalse(bundle.exists())

            install_local(
                source,
                bundle,
                apply=False,
                codex_bin="codex",
            )

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

            calls: list[list[str]] = []

            def runner(command: list[str], *, check: bool) -> None:
                self.assertTrue(check)
                calls.append(command)

            def marketplace_reader(command: list[str]) -> str:
                self.assertEqual(
                    command,
                    ["codex", "plugin", "marketplace", "list", "--json"],
                )
                return json.dumps(
                    {
                        "marketplaces": [
                            {
                                "name": "math-modeling-local",
                                "root": str(bundle.resolve()),
                            }
                        ]
                    }
                )

            applied = install_local(
                source,
                bundle,
                apply=True,
                marketplace_registered=True,
                codex_bin="codex",
                runner=runner,
                marketplace_reader=marketplace_reader,
            )
            self.assertEqual(calls, applied)

            supplied = base / "supplied-bundle"
            install_local(source, supplied, apply=False, codex_bin="codex")

            def mismatched_reader(_command: list[str]) -> str:
                return json.dumps(
                    {
                        "marketplaces": [
                            {
                                "name": "math-modeling-local",
                                "root": str(bundle.resolve()),
                            }
                        ]
                    }
                )

            with self.assertRaisesRegex(ValueError, "does not match"):
                install_local(
                    source,
                    supplied,
                    apply=True,
                    marketplace_registered=True,
                    codex_bin="codex",
                    marketplace_reader=mismatched_reader,
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

    def test_rejects_bundle_root_symlink_before_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            target = base / "target"
            bundle = base / "bundle-link"
            source.mkdir()
            target.mkdir()
            make_valid_suite(source)
            try:
                bundle.symlink_to(target, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlinks unavailable: {error}")

            calls: list[list[str]] = []

            def runner(command: list[str], *, check: bool) -> None:
                calls.append(command)

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                install_local(
                    source,
                    bundle,
                    apply=True,
                    codex_bin="/fake/codex",
                    runner=runner,
                )

            self.assertEqual(calls, [])
            self.assertEqual(list(target.iterdir()), [])

            parent_target = base / "parent-target"
            parent_target.mkdir()
            parent_link = base / "parent-link"
            try:
                parent_link.symlink_to(parent_target, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlinks unavailable: {error}")
            with self.assertRaisesRegex(ValueError, "symbolic link"):
                install_local(
                    source,
                    parent_link / "nested-bundle",
                    apply=True,
                    codex_bin="/fake/codex",
                    runner=runner,
                )
            self.assertEqual(list(parent_target.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
