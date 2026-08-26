#!/usr/bin/env python3
"""Build and optionally install the local math-modeling Codex plugin."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from build_bundle import MARKETPLACE_NAME, build_bundle
from suite_validation import (
    PLUGIN_NAME,
    ensure_no_symlink_components,
)
from validate_bundle import validate_bundle


Runner = Callable[..., object]
MarketplaceReader = Callable[[list[str]], str | bytes]


def _default_marketplace_reader(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(
            "could not inspect configured Codex marketplaces"
        ) from error
    return result.stdout


def _require_registered_marketplace(
    codex_bin: str,
    bundle_root: Path,
    reader: MarketplaceReader,
) -> None:
    command = [codex_bin, "plugin", "marketplace", "list", "--json"]
    try:
        raw = reader(command)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(raw)
    except (UnicodeDecodeError, TypeError, json.JSONDecodeError, ValueError) as error:
        if isinstance(error, ValueError) and str(error).startswith("could not inspect"):
            raise
        raise ValueError("Codex marketplace list returned invalid JSON") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("marketplaces"), list):
        raise ValueError("Codex marketplace list must contain a marketplaces array")
    matches = [
        item
        for item in payload["marketplaces"]
        if isinstance(item, dict) and item.get("name") == MARKETPLACE_NAME
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Codex marketplace {MARKETPLACE_NAME} must be registered exactly once"
        )
    registered_root = matches[0].get("root")
    if not isinstance(registered_root, str) or not registered_root:
        raise ValueError(
            f"Codex marketplace {MARKETPLACE_NAME} has no usable root"
        )
    try:
        registered_path = ensure_no_symlink_components(
            Path(registered_root), "registered marketplace root"
        ).resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise ValueError(
            f"Codex marketplace {MARKETPLACE_NAME} has an unsafe root"
        ) from error
    if registered_path != bundle_root:
        raise ValueError(
            f"registered marketplace root {registered_path} does not match "
            f"bundle {bundle_root}"
        )


def _commands(
    codex_bin: str, bundle_root: Path, *, marketplace_registered: bool
) -> list[list[str]]:
    commands: list[list[str]] = []
    if not marketplace_registered:
        commands.append(
            [codex_bin, "plugin", "marketplace", "add", str(bundle_root)]
        )
    commands.append(
        [codex_bin, "plugin", "add", f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"]
    )
    return commands


def install_local(
    source_root: Path,
    bundle_root: Path,
    *,
    apply: bool,
    marketplace_registered: bool = False,
    codex_bin: str | None = None,
    runner: Runner = subprocess.run,
    marketplace_reader: MarketplaceReader | None = None,
) -> list[list[str]]:
    """Build or reuse a valid bundle, then preview or run Codex commands."""
    source_root = ensure_no_symlink_components(source_root, "source root").resolve()
    bundle_root = ensure_no_symlink_components(bundle_root, "bundle root")
    bundle_root = bundle_root.resolve()
    resolved_codex = codex_bin or shutil.which("codex")
    if apply and resolved_codex is None:
        raise FileNotFoundError(
            "Codex CLI was not found; install it or pass --codex-bin before using --apply"
        )
    command_bin = resolved_codex or "codex"

    existing_bundle = bundle_root.is_dir() and any(bundle_root.iterdir())
    if marketplace_registered and not existing_bundle:
        raise ValueError(
            "--marketplace-registered requires an existing non-empty bundle "
            "path that is already registered"
        )
    if existing_bundle:
        errors = validate_bundle(bundle_root)
    else:
        build_bundle(source_root, bundle_root)
        errors = validate_bundle(bundle_root)
    if errors:
        raise ValueError("bundle validation failed:\n- " + "\n- ".join(errors))

    if apply and marketplace_registered:
        _require_registered_marketplace(
            command_bin,
            bundle_root,
            marketplace_reader or _default_marketplace_reader,
        )

    commands = _commands(
        command_bin,
        bundle_root,
        marketplace_registered=marketplace_registered,
    )
    if apply:
        for command in commands:
            runner(command, check=True)
    return commands


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default=str(Path(__file__).resolve().parents[1]),
        help="Plugin source root; defaults to this repository.",
    )
    parser.add_argument("--bundle", required=True, help="Empty bundle output directory.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Run Codex marketplace and plugin commands. The default is dry-run.",
    )
    parser.add_argument(
        "--marketplace-registered",
        action="store_true",
        help=(
            "Skip marketplace add only when this exact --bundle path is already "
            "registered as the local marketplace."
        ),
    )
    parser.add_argument(
        "--codex-bin",
        default=None,
        help="Explicit Codex CLI path; otherwise resolve codex from PATH.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    commands = install_local(
        Path(args.source),
        Path(args.bundle),
        apply=args.apply,
        marketplace_registered=args.marketplace_registered,
        codex_bin=args.codex_bin,
    )
    if args.apply:
        print("Local plugin installation commands completed.")
        print("Restart Codex if it is open, then test the plugin in a new thread.")
        return

    print("Dry run complete. Bundle validated; no Codex configuration changed.")
    if args.marketplace_registered:
        print(
            "Assumption: this exact bundle path is already registered as "
            f"{MARKETPLACE_NAME}."
        )
    print("Commands that --apply would run:")
    for command in commands:
        print(f"  {shlex.join(command)}")


if __name__ == "__main__":
    main()
