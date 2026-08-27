from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
import sys

sys.path.insert(0, str(SCRIPTS))

from manifest import (  # noqa: E402
    atomic_write_json,
    relative_regular_files,
    sha256_file,
    sha256_paths,
    utc_now,
)


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        (self.root / "nested").mkdir()
        (self.root / "alpha.txt").write_bytes(b"abc")
        (self.root / "nested/zeta.txt").write_bytes(b"zeta")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_sha256_file_hashes_regular_file(self) -> None:
        self.assertEqual(
            hashlib.sha256(b"abc").hexdigest(),
            sha256_file(self.root / "alpha.txt"),
        )

    def test_sha256_paths_returns_lexically_sorted_relative_mapping(self) -> None:
        hashes = sha256_paths(
            self.root,
            [Path("nested/zeta.txt"), Path("alpha.txt")],
        )
        self.assertEqual(["alpha.txt", "nested/zeta.txt"], list(hashes))
        self.assertEqual(hashlib.sha256(b"zeta").hexdigest(), hashes["nested/zeta.txt"])

    def test_sha256_paths_rejects_absolute_and_traversing_paths(self) -> None:
        for unsafe in (self.root / "alpha.txt", Path("../outside.txt"), Path("nested/../alpha.txt")):
            with self.subTest(path=unsafe):
                with self.assertRaises(ValueError):
                    sha256_paths(self.root, [unsafe])

    def test_relative_regular_files_returns_lexical_paths(self) -> None:
        self.assertEqual(
            [Path("alpha.txt"), Path("nested/zeta.txt")],
            list(relative_regular_files(self.root)),
        )

    def test_hashing_rejects_symlink_components(self) -> None:
        link = self.root / "linked.txt"
        try:
            link.symlink_to(self.root / "alpha.txt")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available")
        with self.assertRaises(ValueError):
            sha256_file(link)
        with self.assertRaises(ValueError):
            relative_regular_files(self.root)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable")
    def test_relative_regular_files_rejects_special_files(self) -> None:
        fifo = self.root / "unsafe-node"
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            relative_regular_files(self.root)

    def test_atomic_write_json_is_canonical_and_replaces_regular_file(self) -> None:
        target = self.root / "state.json"
        target.write_text("old", encoding="utf-8")
        atomic_write_json(target, {"z": 1, "a": "中文"})
        self.assertEqual(
            '{\n  "a": "中文",\n  "z": 1\n}\n',
            target.read_text(encoding="utf-8"),
        )
        self.assertEqual({"a": "中文", "z": 1}, json.loads(target.read_text()))

    def test_atomic_write_json_rejects_non_strict_json(self) -> None:
        for payload in ({1: "bad-key"}, {"value": math.inf}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    atomic_write_json(self.root / "state.json", payload)

    def test_atomic_write_json_rejects_symlink_parent(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        link = self.root / "linked-dir"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available")
        with self.assertRaises(ValueError):
            atomic_write_json(link / "escaped.json", {"safe": True})
        self.assertFalse((outside / "escaped.json").exists())

    def test_utc_now_returns_real_utc_z_timestamp(self) -> None:
        timestamp = utc_now()
        self.assertRegex(timestamp, re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"))


if __name__ == "__main__":
    unittest.main()
