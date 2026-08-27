#!/usr/bin/env python3
"""Migrate one legacy handoff to the v2 schema without overwriting evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from handoff_schema import migrate_payload, validate_document


def _write_new_atomically(path: Path, content: str) -> None:
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
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        migrated = migrate_payload(payload)
        errors = validate_document(migrated, kind="handoff", mode="runtime")
        if errors:
            raise ValueError("migrated handoff is invalid:\n- " + "\n- ".join(errors))
        content = json.dumps(
            migrated,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            sort_keys=True,
        ) + "\n"
        _write_new_atomically(args.output, content)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        print(f"handoff migration failed: {error}", file=sys.stderr)
        return 1
    print(f"handoff migrated: {args.input} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
