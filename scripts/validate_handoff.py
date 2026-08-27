#!/usr/bin/env python3
"""Validate a versioned modeling handoff."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from handoff_schema import validate_document


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a modeling handoff document.")
    parser.add_argument("--input", required=True, type=Path, help="Handoff JSON path.")
    parser.add_argument(
        "--mode", choices=("runtime", "legacy"), default="runtime", help="Validation mode."
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        errors = validate_document(payload, kind="handoff", mode=args.mode)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        errors = [f"input: {error}"]
    if args.json:
        print(json.dumps({"valid": not errors, "kind": "handoff", "errors": errors}, ensure_ascii=False))
    elif errors:
        print("handoff invalid:")
        for error in errors:
            print(f"- {error}")
    else:
        print(f"handoff valid: {args.input}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
