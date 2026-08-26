#!/usr/bin/env python3
"""Build and optionally install the local math-modeling Codex plugin."""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from build_bundle import MARKETPLACE_NAME, build_bundle
from suite_validation import PLUGIN_NAME
from validate_bundle import validate_bundle


Runner = Callable[..., object]


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
) -> list[list[str]]:
    """Build or reuse a valid bundle, then preview or run Codex commands."""
    source_root = source_root.expanduser().resolve()
    bundle_root = bundle_root.expanduser().resolve()
    resolved_codex = codex_bin or shutil.which("codex")
    if apply and resolved_codex is None:
        raise FileNotFoundError(
            "Codex CLI was not found; install it or pass --codex-bin before using --apply"
        )
    command_bin = resolved_codex or "codex"

    if bundle_root.is_dir() and any(bundle_root.iterdir()):
        errors = validate_bundle(bundle_root)
    else:
        build_bundle(source_root, bundle_root)
        errors = validate_bundle(bundle_root)
    if errors:
        raise ValueError("bundle validation failed:\n- " + "\n- ".join(errors))

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
