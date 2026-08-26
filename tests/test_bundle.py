from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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
    def test_builds_valid_marketplace_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            (source / ".git").mkdir()
            (source / ".git" / "HEAD").write_text(
                "ref: refs/heads/main\n", encoding="utf-8"
            )
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

    def test_refuses_output_inside_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            make_valid_suite(source)
            output = source / "generated-bundle"

            with self.assertRaisesRegex(ValueError, "outside the source tree"):
                build_bundle(source, output)

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


if __name__ == "__main__":
    unittest.main()
