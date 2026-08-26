from __future__ import annotations

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from update_cachebuster import replace_cachebuster, update_manifest  # noqa: E402


class CachebusterTests(unittest.TestCase):
    def test_replaces_existing_codex_suffix(self) -> None:
        self.assertEqual(
            replace_cachebuster(
                "0.1.0+codex.local-20260101-000000", "local-20260826-120000"
            ),
            "0.1.0+codex.local-20260826-120000",
        )

    def test_preserves_prerelease_base(self) -> None:
        self.assertEqual(
            replace_cachebuster("1.2.3-beta.1+old", "local-20260826-120000"),
            "1.2.3-beta.1+codex.local-20260826-120000",
        )

    def test_preview_does_not_write_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "plugin.json"
            manifest.write_text('{"version": "0.1.0"}\n', encoding="utf-8")

            old_version, new_version = update_manifest(
                manifest, "local-20260826-120000", apply=False
            )

            self.assertEqual(old_version, "0.1.0")
            self.assertEqual(new_version, "0.1.0+codex.local-20260826-120000")
            self.assertEqual(
                json.loads(manifest.read_text(encoding="utf-8"))["version"], "0.1.0"
            )

    def test_apply_writes_manifest_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "plugin.json"
            manifest.write_text('{"version": "0.1.0"}\n', encoding="utf-8")

            update_manifest(manifest, "local-20260826-120000", apply=True)

            self.assertEqual(
                json.loads(manifest.read_text(encoding="utf-8"))["version"],
                "0.1.0+codex.local-20260826-120000",
            )
            self.assertEqual(list(Path(directory).glob(".*.tmp")), [])

    def test_apply_preserves_manifest_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "plugin.json"
            manifest.write_text('{"version": "0.1.0"}\n', encoding="utf-8")
            manifest.chmod(0o640)

            update_manifest(manifest, "local-20260826-120000", apply=True)

            self.assertEqual(stat.S_IMODE(manifest.stat().st_mode), 0o640)

    def test_rejects_unsafe_token(self) -> None:
        with self.assertRaisesRegex(ValueError, "cachebuster token"):
            replace_cachebuster("0.1.0", "../../escape")


if __name__ == "__main__":
    unittest.main()
