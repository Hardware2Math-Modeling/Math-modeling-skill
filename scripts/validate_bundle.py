#!/usr/bin/env python3
"""Validate a local Codex marketplace bundle and its plugin copy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_bundle import MARKETPLACE_DISPLAY_NAME, MARKETPLACE_NAME
from suite_validation import PLUGIN_NAME, validate_suite


def _load_marketplace(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file():
        errors.append("missing .agents/plugins/marketplace.json")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        errors.append("marketplace.json must be readable valid JSON")
        return None
    if not isinstance(payload, dict):
        errors.append("marketplace.json must contain an object")
        return None
    return payload


def _resolve_plugin_root(
    bundle_root: Path, marketplace: dict[str, Any], errors: list[str]
) -> Path | None:
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list):
        errors.append("marketplace plugins must be an array")
        return None
    if not (
        len(plugins) == 1
        and isinstance(plugins[0], dict)
        and plugins[0].get("name") == PLUGIN_NAME
    ):
        errors.append(f"marketplace must contain only {PLUGIN_NAME}")
    matches = [
        entry
        for entry in plugins
        if isinstance(entry, dict) and entry.get("name") == PLUGIN_NAME
    ]
    if len(matches) != 1:
        errors.append(f"marketplace must contain exactly one {PLUGIN_NAME} entry")
        return None

    entry = matches[0]
    source = entry.get("source")
    if not isinstance(source, dict) or source.get("source") != "local":
        errors.append("marketplace plugin source must be local")
        return None
    raw_path = source.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        errors.append("marketplace source.path must be a non-empty string")
        return None
    expected_raw_path = f"./plugins/{PLUGIN_NAME}"

    try:
        candidate = (bundle_root / raw_path).resolve()
        expected = (bundle_root / "plugins" / PLUGIN_NAME).resolve()
    except (OSError, RuntimeError, ValueError):
        errors.append("marketplace source.path must be a valid path")
        return None
    try:
        candidate.relative_to(bundle_root)
    except ValueError:
        errors.append("marketplace source.path escapes the bundle root")
        return None

    if candidate != expected:
        errors.append(f"marketplace source.path must be {expected_raw_path}")
        return None
    if raw_path != expected_raw_path:
        errors.append(f"marketplace source.path must be {expected_raw_path}")
        return None

    expected_policy = {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    }
    if entry.get("policy") != expected_policy:
        errors.append("marketplace plugin policy must use AVAILABLE and ON_INSTALL")
    if entry.get("category") != "Education & Research":
        errors.append("marketplace plugin category must be Education & Research")
    return candidate


def validate_bundle(bundle_root: Path) -> list[str]:
    """Return deterministic validation errors for a marketplace bundle."""
    try:
        bundle_root = Path(bundle_root).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return ["bundle root must be a valid path"]
    errors: list[str] = []
    marketplace = _load_marketplace(
        bundle_root / ".agents" / "plugins" / "marketplace.json", errors
    )
    if marketplace is None:
        return errors
    if marketplace.get("name") != MARKETPLACE_NAME:
        errors.append(f"marketplace name must be {MARKETPLACE_NAME}")
    if marketplace.get("interface") != {"displayName": MARKETPLACE_DISPLAY_NAME}:
        errors.append(
            f"marketplace interface.displayName must be {MARKETPLACE_DISPLAY_NAME}"
        )

    plugin_root = _resolve_plugin_root(bundle_root, marketplace, errors)
    if plugin_root is None:
        return errors
    if not (plugin_root / ".codex-plugin" / "plugin.json").is_file():
        errors.append("marketplace source.path does not contain the plugin manifest")
        return errors
    errors.extend(f"plugin: {error}" for error in validate_suite(plugin_root))
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", help="Bundle root containing .agents and plugins.")
    return parser.parse_args()


def main() -> None:
    bundle_root = Path(parse_args().bundle).expanduser().resolve()
    errors = validate_bundle(bundle_root)
    if errors:
        print("Bundle validation failed:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print(f"Bundle validation passed: {bundle_root}")


if __name__ == "__main__":
    main()
