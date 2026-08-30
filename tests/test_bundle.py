from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from build_bundle import build_bundle  # noqa: E402
from test_suite_validation import make_valid_suite, write_json  # noqa: E402
from validate_bundle import validate_bundle  # noqa: E402


def run_git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


class BundleTests(unittest.TestCase):
    def test_new_skill_assets_are_regular_and_project_state_is_not_bundled(self) -> None:
        asset_paths = (
            ROOT / "skills/math-modeling-visualization/assets/styles/modeling.mplstyle",
            ROOT / "skills/math-modeling-paper-production/assets/fallback-zh/main.tex",
            ROOT / "skills/math-modeling-method-library/assets/fixtures/method-smoke.json",
        )
        for asset in asset_paths:
            with self.subTest(asset=asset):
                self.assertTrue(asset.is_file())
                self.assertFalse(asset.is_symlink())

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            run_git(source, "init", "--quiet")
            (source / ".gitignore").write_text(
                "iterations/\nuser-project/\npytest-results.json\n", encoding="utf-8"
            )
            run_git(source, "add", ".gitignore")
            (source / "iterations/v001/state").mkdir(parents=True)
            (source / "iterations/v001/state/handoff.json").write_text(
                "test fixture state\n", encoding="utf-8"
            )
            (source / "user-project/results").mkdir(parents=True)
            (source / "user-project/results/q1.json").write_text(
                "user result\n", encoding="utf-8"
            )
            (source / "pytest-results.json").write_text(
                "generated test output\n", encoding="utf-8"
            )

            plugin_root = build_bundle(source, output)

            self.assertFalse((plugin_root / "iterations").exists())
            self.assertFalse((plugin_root / "user-project").exists())
            self.assertFalse((plugin_root / "pytest-results.json").exists())

    def test_fallback_templates_contain_no_credential_material(self) -> None:
        fallback = ROOT / "skills/math-modeling-paper-production/assets/fallback-zh"
        files = sorted(path for path in fallback.rglob("*") if path.is_file())
        self.assertTrue(files)
        for path in files:
            with self.subTest(path=path):
                self.assertFalse(path.is_symlink())
                text = path.read_text(encoding="utf-8").casefold()
                for marker in ("api_key", "access_token", "private_key", "password="):
                    self.assertNotIn(marker, text)

    def test_builds_valid_marketplace_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            run_git(source, "init", "--quiet")
            (source / ".worktrees" / "other").mkdir(parents=True)
            (source / ".worktrees" / "other" / "owned.txt").write_text(
                "do not bundle\n", encoding="utf-8"
            )
            (source / ".local-bundles" / "old").mkdir(parents=True)
            (source / ".local-bundles" / "old" / "owned.txt").write_text(
                "do not bundle\n", encoding="utf-8"
            )

            plugin_root = build_bundle(source, output)

            self.assertEqual(
                plugin_root,
                (output / "plugins" / "math-modeling-suite").resolve(),
            )
            self.assertFalse((plugin_root / ".git").exists())
            self.assertFalse((plugin_root / ".worktrees").exists())
            self.assertFalse((plugin_root / ".local-bundles").exists())
            self.assertEqual(validate_bundle(output), [])
            marketplace = json.loads(
                (output / ".agents" / "plugins" / "marketplace.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(marketplace["name"], "math-modeling-local")
            self.assertEqual(
                marketplace["plugins"][0]["source"]["path"],
                "./plugins/math-modeling-suite",
            )

    def test_git_ignored_files_are_excluded_and_tracked_files_are_included(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            tracked = source / "tracked-but-ignored.txt"
            tracked.write_text("tracked\n", encoding="utf-8")
            run_git(source, "init", "--quiet")
            run_git(source, "add", ".")
            (source / ".gitignore").write_text(
                ".env\nprivate-*.txt\ntracked-but-ignored.txt\n",
                encoding="utf-8",
            )
            run_git(source, "add", ".gitignore")
            (source / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
            (source / "private-local.txt").write_text(
                "private\n", encoding="utf-8"
            )

            plugin_root = build_bundle(source, output)

            self.assertFalse((plugin_root / ".env").exists())
            self.assertFalse((plugin_root / "private-local.txt").exists())
            self.assertEqual(
                (plugin_root / "tracked-but-ignored.txt").read_text(
                    encoding="utf-8"
                ),
                "tracked\n",
            )

            with patch(
                "build_bundle.subprocess.run",
                side_effect=OSError("git unavailable"),
            ):
                with self.assertRaisesRegex(
                    ValueError, "Git source inspection failed"
                ):
                    build_bundle(source, output.parent / "failed-bundle")

            submodule_source = base / "submodule-source"
            submodule_output = base / "submodule-bundle"
            submodule_source.mkdir()
            make_valid_suite(submodule_source)
            run_git(submodule_source, "init", "--quiet")
            run_git(submodule_source, "add", ".")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(submodule_source),
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "--quiet",
                    "-m",
                    "fixture",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            object_id = subprocess.run(
                ["git", "-C", str(submodule_source), "rev-parse", "HEAD"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            (submodule_source / "vendor").mkdir()
            (submodule_source / "vendor" / "required-guide.md").write_text(
                "required\n", encoding="utf-8"
            )
            run_git(
                submodule_source,
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{object_id},vendor",
            )

            with self.assertRaisesRegex(ValueError, "submodules are not supported"):
                build_bundle(submodule_source, submodule_output)
            self.assertFalse(submodule_output.exists())

    def test_git_tracked_environment_files_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            (source / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
            (source / ".env.production").write_text(
                "TOKEN=secret\n", encoding="utf-8"
            )
            (source / "credentials.json").write_text(
                "{\"token\": \"secret\"}\n", encoding="utf-8"
            )
            run_git(source, "init", "--quiet")
            run_git(source, "add", ".")

            with self.assertRaisesRegex(ValueError, "sensitive file"):
                build_bundle(source, output)

            (source / "credentials.json").unlink()
            run_git(source, "add", "-u", ".")
            plugin_root = build_bundle(source, output)

            self.assertFalse((plugin_root / ".env").exists())
            self.assertFalse((plugin_root / ".env.production").exists())

    def test_rejects_source_symlink_before_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            sentinel = base / "external-secret.txt"
            sentinel.write_text("do not bundle\n", encoding="utf-8")
            source_link = source / "external-secret.txt"
            try:
                source_link.symlink_to(sentinel)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlinks unavailable: {error}")

            with self.assertRaisesRegex(
                ValueError,
                r"source contains symbolic link: external-secret\.txt",
            ):
                build_bundle(source, output)

            self.assertFalse(output.exists())

    def test_rejects_source_directory_symlink_before_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            external_directory = base / "external-assets"
            source.mkdir()
            external_directory.mkdir()
            make_valid_suite(source)
            (external_directory / "secret.txt").write_text(
                "do not bundle\n", encoding="utf-8"
            )
            source_link = source / "linked-assets"
            try:
                source_link.symlink_to(external_directory, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            with self.assertRaisesRegex(
                ValueError,
                r"source contains symbolic link: linked-assets",
            ):
                build_bundle(source, output)

            self.assertFalse(output.exists())

    def test_statically_ignored_source_symlink_does_not_block_build(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            external_directory = base / "external-worktree"
            source.mkdir()
            external_directory.mkdir()
            make_valid_suite(source)
            (external_directory / "secret.txt").write_text(
                "do not bundle\n", encoding="utf-8"
            )
            ignored_link = source / ".worktrees"
            try:
                ignored_link.symlink_to(external_directory, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            plugin_root = build_bundle(source, output)

            self.assertFalse((plugin_root / ".worktrees").exists())

    def test_non_git_source_includes_ordinary_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            (source / "notes.txt").write_text("keep me\n", encoding="utf-8")
            (source / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
            (source / ".env.local").write_text(
                "LOCAL_TOKEN=secret\n", encoding="utf-8"
            )

            plugin_root = build_bundle(source, output)

            self.assertEqual(
                (plugin_root / "notes.txt").read_text(encoding="utf-8"),
                "keep me\n",
            )
            self.assertFalse((plugin_root / ".env").exists())
            self.assertFalse((plugin_root / ".env.local").exists())

    def test_refuses_non_empty_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            source.mkdir()
            output.mkdir()
            (output / "owned-by-user.txt").write_text("keep\n", encoding="utf-8")
            make_valid_suite(source)

            with self.assertRaisesRegex(FileExistsError, "non-empty"):
                build_bundle(source, output)

            self.assertEqual(
                (output / "owned-by-user.txt").read_text(encoding="utf-8"), "keep\n"
            )

            failed_output = base / "failed-bundle"
            with patch(
                "build_bundle.shutil.copy2", side_effect=OSError("copy failed")
            ):
                with self.assertRaisesRegex(OSError, "copy failed"):
                    build_bundle(source, failed_output)
            self.assertFalse(failed_output.exists())
            self.assertEqual(list(base.glob(".failed-bundle.building-*")), [])

            empty_output = base / "empty-failed-bundle"
            empty_output.mkdir()
            with patch(
                "build_bundle.shutil.copy2", side_effect=OSError("copy failed")
            ):
                with self.assertRaisesRegex(OSError, "copy failed"):
                    build_bundle(source, empty_output)
            self.assertTrue(empty_output.is_dir())
            self.assertEqual(list(empty_output.iterdir()), [])

    def test_refuses_output_inside_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            make_valid_suite(source)
            output = source / "generated-bundle"

            with self.assertRaisesRegex(ValueError, "outside the source tree"):
                build_bundle(source, output)

    def test_rejects_output_root_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            target = base / "target"
            output = base / "bundle-link"
            source.mkdir()
            target.mkdir()
            make_valid_suite(source)
            try:
                output.symlink_to(target, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlinks unavailable: {error}")

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                build_bundle(source, output)

            self.assertEqual(list(target.iterdir()), [])

            parent_target = base / "parent-target"
            parent_target.mkdir()
            parent_link = base / "parent-link"
            parent_link.symlink_to(parent_target, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                build_bundle(source, parent_link / "bundle")

            self.assertEqual(list(parent_target.iterdir()), [])

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                build_bundle(source, parent_link / ".." / "dotdot-bundle")
            self.assertFalse((base / "dotdot-bundle").exists())

            output.unlink()
            build_bundle(source, output)
            validation_link = base / "validation-link"
            validation_link.symlink_to(output, target_is_directory=True)

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "validate_bundle.py"),
                    str(validation_link),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("bundle root must not be a symbolic link", result.stdout)

            validation_parent = base / "validation-parent"
            validation_parent.symlink_to(base, target_is_directory=True)
            nested_link = validation_parent / output.name
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "validate_bundle.py"),
                    str(nested_link),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symbolic link", result.stdout)

    def test_rejects_marketplace_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            build_bundle(source, output)
            marketplace_path = output / ".agents" / "plugins" / "marketplace.json"
            marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
            marketplace["plugins"][0]["source"]["path"] = "../../outside"
            write_json(marketplace_path, marketplace)

            errors = validate_bundle(output)

            self.assertIn("marketplace source.path escapes the bundle root", errors)

    def test_rejects_malformed_marketplace_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            build_bundle(source, output)
            marketplace_path = output / ".agents" / "plugins" / "marketplace.json"
            marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
            marketplace["plugins"][0]["source"]["path"] = "\x00"
            write_json(marketplace_path, marketplace)

            errors = validate_bundle(output)

            self.assertIn("marketplace source.path must be a valid path", errors)

    def test_rejects_malformed_bundle_root(self) -> None:
        self.assertIn(
            "bundle root must be a valid path",
            validate_bundle(Path("\x00")),
        )

    def test_rejects_extra_marketplace_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            build_bundle(source, output)
            marketplace_path = output / ".agents" / "plugins" / "marketplace.json"
            marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
            marketplace["plugins"].append(
                {
                    "name": "unexpected-plugin",
                    "source": {"source": "local", "path": "./plugins/unexpected"},
                }
            )
            write_json(marketplace_path, marketplace)

            errors = validate_bundle(output)

            self.assertIn(
                "marketplace must contain only math-modeling-suite", errors
            )

            marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
            marketplace["plugins"] = [marketplace["plugins"][0]]
            marketplace["plugins"][0]["unexpected"] = True
            write_json(marketplace_path, marketplace)
            errors = validate_bundle(output)
            self.assertIn(
                "marketplace plugin contains unsupported keys: unexpected", errors
            )

    def test_rejects_absolute_marketplace_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            build_bundle(source, output)
            marketplace_path = output / ".agents" / "plugins" / "marketplace.json"
            marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
            marketplace["plugins"][0]["source"]["path"] = str(
                (output / "plugins" / "math-modeling-suite").resolve()
            )
            write_json(marketplace_path, marketplace)

            errors = validate_bundle(output)

            self.assertIn(
                "marketplace source.path must be ./plugins/math-modeling-suite",
                errors,
            )

    def test_rejects_symlink_inside_plugin_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            external = base / "external-secret.txt"
            source.mkdir()
            make_valid_suite(source)
            external.write_text("secret\n", encoding="utf-8")
            build_bundle(source, output)
            link = output / "plugins" / "math-modeling-suite" / "linked.txt"
            try:
                link.symlink_to(external)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlinks unavailable: {error}")

            errors = validate_bundle(output)

            self.assertIn(
                "bundle contains symbolic link: plugins/math-modeling-suite/linked.txt",
                errors,
            )

            sensitive = output / "plugins" / "math-modeling-suite" / ".env"
            sensitive.write_text("TOKEN=secret\n", encoding="utf-8")
            credentials = (
                output / "plugins" / "math-modeling-suite" / "credentials.json"
            )
            credentials.write_text("{}\n", encoding="utf-8")
            fifo = output / "plugins" / "math-modeling-suite" / "unsafe-node"
            try:
                os.mkfifo(fifo)
            except (AttributeError, NotImplementedError, OSError):
                fifo = None

            errors = validate_bundle(output)
            self.assertIn(
                "bundle contains sensitive file: plugins/math-modeling-suite/.env",
                errors,
            )
            self.assertIn(
                "bundle contains sensitive file: "
                "plugins/math-modeling-suite/credentials.json",
                errors,
            )

            injected_git = output / "plugins" / "math-modeling-suite" / ".git"
            injected_git.mkdir()
            (injected_git / "config").write_text("[core]\n", encoding="utf-8")
            errors = validate_bundle(output)
            self.assertIn(
                "bundle contains forbidden path: plugins/math-modeling-suite/.git",
                errors,
            )
            if fifo is not None:
                self.assertIn(
                    "bundle contains unsupported file type: "
                    "plugins/math-modeling-suite/unsafe-node",
                    errors,
                )

            for suffix in (".pem", ".key"):
                private_key = output / "plugins" / "math-modeling-suite" / f"private{suffix}"
                private_key.write_text("not a real key\n", encoding="utf-8")
                errors = validate_bundle(output)
                self.assertIn(
                    f"bundle contains sensitive file: plugins/math-modeling-suite/private{suffix}",
                    errors,
                )
                private_key.unlink()

            unreadable = output / "plugins" / "math-modeling-suite" / "unreadable"
            unreadable.mkdir()
            (unreadable / "hidden-link").symlink_to(base / "outside")
            original_scandir = os.scandir

            def scandir_with_denial(path: object):
                if Path(path).name == unreadable.name:
                    raise PermissionError("permission denied")
                return original_scandir(path)

            with patch("validate_bundle.os.scandir", side_effect=scandir_with_denial):
                errors = validate_bundle(output)
            self.assertIn(
                "bundle directory could not be inspected: "
                "plugins/math-modeling-suite/unreadable",
                errors,
            )


if __name__ == "__main__":
    unittest.main()
