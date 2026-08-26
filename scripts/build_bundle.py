#!/usr/bin/env python3
"""Build a self-contained local Codex marketplace bundle."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from suite_validation import PLUGIN_NAME, validate_suite


MARKETPLACE_NAME = "math-modeling-local"
MARKETPLACE_DISPLAY_NAME = "Local Math Modeling"
IGNORED_NAMES = {
    ".DS_Store",
    ".git",
    ".local-bundles",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".worktrees",
    "__pycache__",
}


def marketplace_payload() -> dict[str, object]:
    """Return the canonical repository-local marketplace metadata."""
    return {
        "name": MARKETPLACE_NAME,
        "interface": {"displayName": MARKETPLACE_DISPLAY_NAME},
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": {
                    "source": "local",
                    "path": f"./plugins/{PLUGIN_NAME}",
                },
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Education & Research",
            }
        ],
    }


def _ignore_copy_entries(_directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name in IGNORED_NAMES or name.endswith((".pyc", ".pyo"))
    }


def _require_output_outside_source(source_root: Path, output_root: Path) -> None:
    try:
        output_root.relative_to(source_root)
    except ValueError:
        return
    raise ValueError("bundle output must be outside the source tree")


def build_bundle(source_root: Path, output_root: Path) -> Path:
    """Validate and copy a plugin source into a standard marketplace bundle."""
    source_root = source_root.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    _require_output_outside_source(source_root, output_root)

    errors = validate_suite(source_root)
    if errors:
        raise ValueError("source validation failed:\n- " + "\n- ".join(errors))

    if output_root.exists():
        if not output_root.is_dir() or any(output_root.iterdir()):
            raise FileExistsError(
                f"refusing to overwrite non-empty output: {output_root}"
            )
    else:
        output_root.mkdir(parents=True)

    plugin_root = output_root / "plugins" / PLUGIN_NAME
    plugin_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_root, plugin_root, ignore=_ignore_copy_entries)

    marketplace_path = output_root / ".agents" / "plugins" / "marketplace.json"
    marketplace_path.parent.mkdir(parents=True, exist_ok=True)
    marketplace_path.write_text(
        json.dumps(marketplace_payload(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return plugin_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default=str(Path(__file__).resolve().parents[1]),
        help="Plugin source root; defaults to this repository.",
    )
    parser.add_argument("--output", required=True, help="Empty bundle output directory.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plugin_root = build_bundle(Path(args.source), Path(args.output))
    print(f"Bundle created: {plugin_root.parents[1]}")
    print(f"Plugin copy: {plugin_root}")


if __name__ == "__main__":
    main()
