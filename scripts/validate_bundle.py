#!/usr/bin/env python3
"""Validate a local Codex marketplace bundle and its plugin copy."""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path
from typing import Any

from build_bundle import MARKETPLACE_DISPLAY_NAME, MARKETPLACE_NAME
from suite_validation import (
    PLUGIN_NAME,
    ensure_no_symlink_components,
    is_ignored_relative_path,
    is_sensitive_relative_path,
    validate_suite,
)


_MARKETPLACE_KEYS = {"name", "interface", "plugins"}
_MARKETPLACE_INTERFACE_KEYS = {"displayName"}
_MARKETPLACE_PLUGIN_KEYS = {"name", "source", "policy", "category"}
_MARKETPLACE_SOURCE_KEYS = {"source", "path"}
_MARKETPLACE_POLICY_KEYS = {"installation", "authentication"}


class _BundleScanError(Exception):
    """Raised when a bundle directory cannot be inspected safely."""


def _tree_policy_errors(root: Path) -> tuple[str, ...]:
    """Inspect every archive entry without following links or special nodes."""
    found: list[str] = []
    pending: list[tuple[Path, Path]] = [(root, Path())]
    while pending:
        directory, relative_directory = pending.pop()
        try:
            with os.scandir(directory) as scan:
                entries = sorted(scan, key=lambda entry: entry.name, reverse=True)
        except OSError as error:
            label = relative_directory.as_posix() or "."
            raise _BundleScanError(label) from error
        for entry in entries:
            relative_path = relative_directory / entry.name
            relative_label = relative_path.as_posix()
            if is_ignored_relative_path(relative_path):
                found.append(f"bundle contains forbidden path: {relative_label}")
            if is_sensitive_relative_path(relative_path):
                found.append(f"bundle contains sensitive file: {relative_label}")
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError as error:
                raise _BundleScanError(relative_label) from error
            if stat.S_ISLNK(mode):
                found.append(f"bundle contains symbolic link: {relative_label}")
            elif stat.S_ISDIR(mode):
                pending.append((Path(entry.path), relative_path))
            elif not stat.S_ISREG(mode):
                found.append(
                    f"bundle contains unsupported file type: {relative_label}"
                )
    return tuple(sorted(found))


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
    unexpected_entry = sorted(set(entry) - _MARKETPLACE_PLUGIN_KEYS)
    if unexpected_entry:
        errors.append(
            "marketplace plugin contains unsupported keys: "
            + ", ".join(unexpected_entry)
        )
    source = entry.get("source")
    if not isinstance(source, dict) or source.get("source") != "local":
        errors.append("marketplace plugin source must be local")
        return None
    unexpected_source = sorted(set(source) - _MARKETPLACE_SOURCE_KEYS)
    if unexpected_source:
        errors.append(
            "marketplace source contains unsupported keys: "
            + ", ".join(unexpected_source)
        )
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
    policy = entry.get("policy")
    if isinstance(policy, dict):
        unexpected_policy = sorted(set(policy) - _MARKETPLACE_POLICY_KEYS)
        if unexpected_policy:
            errors.append(
                "marketplace policy contains unsupported keys: "
                + ", ".join(unexpected_policy)
            )
    if entry.get("policy") != expected_policy:
        errors.append("marketplace plugin policy must use AVAILABLE and ON_INSTALL")
    if entry.get("category") != "Education & Research":
        errors.append("marketplace plugin category must be Education & Research")
    return candidate


def validate_bundle(bundle_root: Path) -> list[str]:
    """Return deterministic validation errors for a marketplace bundle."""
    try:
        bundle_root = ensure_no_symlink_components(bundle_root, "bundle root").resolve()
    except ValueError as error:
        if "symbolic link" in str(error):
            return [str(error)]
        return ["bundle root must be a valid path"]
    except (OSError, RuntimeError, TypeError):
        return ["bundle root must be a valid path"]
    errors: list[str] = []
    if bundle_root.is_dir():
        try:
            tree_errors = _tree_policy_errors(bundle_root)
        except _BundleScanError as error:
            return [f"bundle directory could not be inspected: {error}"]
        if tree_errors:
            errors.extend(tree_errors)
            return errors
    marketplace = _load_marketplace(
        bundle_root / ".agents" / "plugins" / "marketplace.json", errors
    )
    if marketplace is None:
        return errors
    unexpected_marketplace = sorted(set(marketplace) - _MARKETPLACE_KEYS)
    if unexpected_marketplace:
        errors.append(
            "marketplace contains unsupported keys: "
            + ", ".join(unexpected_marketplace)
        )
    if marketplace.get("name") != MARKETPLACE_NAME:
        errors.append(f"marketplace name must be {MARKETPLACE_NAME}")
    interface = marketplace.get("interface")
    if isinstance(interface, dict):
        unexpected_interface = sorted(set(interface) - _MARKETPLACE_INTERFACE_KEYS)
        if unexpected_interface:
            errors.append(
                "marketplace interface contains unsupported keys: "
                + ", ".join(unexpected_interface)
            )
    if interface != {"displayName": MARKETPLACE_DISPLAY_NAME}:
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
    # Keep the raw path here so validate_bundle can reject a symlink root before
    # path resolution erases the boundary that must be checked.
    bundle_root = Path(parse_args().bundle).expanduser()
    errors = validate_bundle(bundle_root)
    if errors:
        print("Bundle validation failed:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print(f"Bundle validation passed: {bundle_root}")


if __name__ == "__main__":
    main()
