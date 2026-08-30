#!/usr/bin/env python3
"""Validate a versioned modeling handoff."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from handoff_schema import load_and_validate


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a modeling handoff document.")
    parser.add_argument("--input", required=True, type=Path, help="Handoff JSON path.")
    parser.add_argument(
        "--mode", choices=("runtime", "legacy"), default="runtime", help="Validation mode."
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args()
    try:
        load_and_validate(args.input, kind="handoff", mode=args.mode)
        errors: list[str] = []
    except ValueError as error:
        errors = [f"input: {error}"]
    if args.json:
        print(
            json.dumps(
                {"valid": not errors, "kind": "handoff", "errors": errors},
                ensure_ascii=False,
            )
        )
    elif errors:
        print("handoff invalid:")
        for error in errors:
            print(f"- {error}")
    else:
        print(f"handoff valid: {args.input}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
