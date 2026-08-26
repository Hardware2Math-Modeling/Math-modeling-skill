#!/usr/bin/env python3
"""Preview or apply a Codex cachebuster to the plugin version."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from suite_validation import SEMVER_RE, ensure_no_symlink_components


TOKEN_RE = re.compile(r"^[0-9A-Za-z-]+$")


def default_cachebuster() -> str:
    return datetime.now(timezone.utc).strftime("local-%Y%m%d-%H%M%S")


def replace_cachebuster(version: str, token: str) -> str:
    """Replace all build metadata with one Codex cachebuster suffix."""
    if SEMVER_RE.fullmatch(version) is None:
        raise ValueError(f"current version is not strict SemVer: {version}")
    if TOKEN_RE.fullmatch(token) is None:
        raise ValueError(
            "cachebuster token must contain only letters, digits, and hyphens"
        )
    base = version.split("+", 1)[0]
    return f"{base}+codex.{token}"


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"unable to read valid manifest JSON: {path}") from error
    if not isinstance(manifest, dict) or not isinstance(manifest.get("version"), str):
        raise ValueError("plugin manifest must contain a string version")
    return manifest


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    original_mode = stat.S_IMODE(path.stat().st_mode)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        temporary_path.chmod(original_mode)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def update_manifest(path: Path, token: str, *, apply: bool) -> tuple[str, str]:
    """Return old/new versions and write only when ``apply`` is true."""
    path = ensure_no_symlink_components(path, "manifest path")
    try:
        mode = path.lstat().st_mode
    except OSError:
        mode = None
    if mode is not None and not stat.S_ISREG(mode):
        raise ValueError("manifest path must be a regular file")
    path = path.resolve()
    manifest = _load_manifest(path)
    old_version = manifest["version"]
    new_version = replace_cachebuster(old_version, token)
    if apply:
        manifest["version"] = new_version
        _write_json_atomically(path, manifest)
    return old_version, new_version


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=str(
            Path(__file__).resolve().parents[1] / ".codex-plugin" / "plugin.json"
        ),
        help="Plugin manifest path.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Cachebuster token; defaults to local-<UTC timestamp>.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the proposed version. Without this flag the command is a preview.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    token = args.token or default_cachebuster()
    old_version, new_version = update_manifest(
        Path(args.manifest), token, apply=args.apply
    )
    action = "Updated" if args.apply else "Preview"
    print(f"{action}: {old_version} -> {new_version}")
    if not args.apply:
        print("No file changed. Re-run with --apply to write the version.")


if __name__ == "__main__":
    main()
