"""Command-line entry point for validating a Math Modeling plugin suite."""

from __future__ import annotations

import argparse
from pathlib import Path

from suite_validation import validate_suite


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Math Modeling plugin suite.")
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    # Keep the raw path until validate_suite can inspect every component;
    # resolving here would erase a symlink boundary before it is checked.
    root = args.root.expanduser()
    errors = validate_suite(root)
    if errors:
        print("Suite validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Suite validation passed: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
