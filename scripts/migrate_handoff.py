#!/usr/bin/env python3
"""Migrate one legacy handoff to the v2 schema without overwriting evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from handoff_schema import (
    artifact_filesystem_errors,
    load_and_validate,
    strict_json_tree_errors,
)
from suite_validation import ensure_no_symlink_components


def serialize_payload(payload: object, *, pretty: bool = False) -> str:
    """Serialize payload as strict UTF-8 JSON text."""

    errors = strict_json_tree_errors(payload)
    if errors:
        raise ValueError("payload is not strict JSON:\n- " + "\n- ".join(errors))
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            indent=2 if pretty else None,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
    except (TypeError, ValueError) as error:
        raise ValueError(f"payload cannot be serialized as strict JSON: {error}") from error


def _canonical_output_path(raw_path: str) -> Path:
    """Reject non-canonical lexical output paths before filesystem checks."""

    if not raw_path or "\x00" in raw_path:
        raise ValueError("output must be a non-empty canonical path")
    components = raw_path.split("/")
    if raw_path.startswith("/"):
        components = components[1:]
    if any(component in {"", ".", ".."} for component in components):
        raise ValueError("output path must not contain empty, '.' or '..' components")
    if "\\" in raw_path and any(
        component in {".", ".."} for component in raw_path.split("\\")
    ):
        raise ValueError("output path must not contain '.' or '..' components")
    for lexical in (PurePosixPath(raw_path), PureWindowsPath(raw_path)):
        if any(component in {".", ".."} for component in lexical.parts):
            raise ValueError("output path must not contain '.' or '..' components")
    return Path(raw_path)


def _write_new_atomically(path: Path, content: str) -> None:
    """Create a new file after a static symlink audit.

    Concurrent replacement of an already-audited parent is outside this
    cross-platform helper's threat boundary.
    """

    path = _canonical_output_path(os.fspath(path))
    try:
        path = ensure_no_symlink_components(path, "output")
    except ValueError as error:
        raise ValueError(str(error).replace("symbolic link", "symlink")) from error
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"output already exists: {path}")
    if not path.parent.is_dir():
        raise ValueError(f"output parent is not a directory: {path.parent}")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.link(temporary_name, path)
    except FileExistsError as error:
        raise FileExistsError(f"output already exists: {path}") from error
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate a modeling handoff to schema v2.")
    parser.add_argument("--input", required=True, type=Path, help="Legacy handoff JSON path.")
    parser.add_argument("--output", required=True, help="New v2 handoff path.")
    parser.add_argument("--pretty", action="store_true", help="Indent the output JSON.")
    args = parser.parse_args()
    try:
        output_path = _canonical_output_path(args.output)
        if output_path.exists() or output_path.is_symlink():
            raise FileExistsError(f"output already exists: {output_path}")
        migrated = load_and_validate(args.input, kind="handoff", mode="legacy")
        output_artifact_errors = artifact_filesystem_errors(migrated, output_path)
        if output_artifact_errors:
            raise ValueError(
                "migrated handoff is invalid at output root:\n- "
                + "\n- ".join(output_artifact_errors)
            )
        content = serialize_payload(migrated, pretty=args.pretty)
        _write_new_atomically(output_path, content)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        print(f"handoff migration failed: {error}", file=sys.stderr)
        return 1
    print(f"handoff migrated: {args.input} -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
