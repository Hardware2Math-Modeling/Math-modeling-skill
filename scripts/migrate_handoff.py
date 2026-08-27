#!/usr/bin/env python3
"""Migrate one legacy handoff to the v2 schema without overwriting evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from handoff_schema import load_and_validate
from suite_validation import ensure_no_symlink_components


def serialize_payload(payload: object, *, pretty: bool = False) -> str:
    """Serialize payload as strict UTF-8 JSON text."""

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


def _write_new_atomically(path: Path, content: str) -> None:
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
    parser.add_argument("--output", required=True, type=Path, help="New v2 handoff path.")
    parser.add_argument("--pretty", action="store_true", help="Indent the output JSON.")
    args = parser.parse_args()
    try:
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError(f"output already exists: {args.output}")
        migrated = load_and_validate(args.input, kind="handoff", mode="legacy")
        content = serialize_payload(migrated, pretty=args.pretty)
        _write_new_atomically(args.output, content)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        print(f"handoff migration failed: {error}", file=sys.stderr)
        return 1
    print(f"handoff migrated: {args.input} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
