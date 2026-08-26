#!/usr/bin/env python3
"""Build a self-contained local Codex marketplace bundle."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
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
SENSITIVE_ENV_NAMES = {".env", ".envrc"}
GIT_TIMEOUT_SECONDS = 5


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


def _is_ignored_name(name: str) -> bool:
    return name in IGNORED_NAMES or name.endswith((".pyc", ".pyo"))


def _is_statically_ignored(relative_path: Path) -> bool:
    return any(_is_ignored_name(part) for part in relative_path.parts)


def _is_fallback_ignored(relative_path: Path) -> bool:
    return _is_statically_ignored(relative_path) or any(
        part in SENSITIVE_ENV_NAMES or part.startswith(".env.")
        for part in relative_path.parts
    )


def _git_source_files(source_root: Path) -> tuple[Path, ...] | None:
    """Return Git-selected source paths, or None when source is not a worktree."""
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                os.fspath(source_root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                ".",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None

    paths: set[Path] = set()
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative_path = Path(os.fsdecode(raw_path))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("git returned an invalid source path")
        if not _is_statically_ignored(relative_path):
            paths.add(relative_path)
    return tuple(sorted(paths, key=lambda path: (len(path.parts), path.as_posix())))


def _fallback_source_paths(source_root: Path) -> tuple[Path, ...]:
    """Walk a non-Git fixture without following directory symlinks."""
    paths: list[Path] = []
    pending: list[tuple[Path, Path]] = [(source_root, Path())]
    while pending:
        directory, relative_directory = pending.pop()
        try:
            with os.scandir(directory) as scan:
                entries = sorted(scan, key=lambda entry: entry.name, reverse=True)
        except OSError as error:
            raise ValueError(f"could not read source directory: {relative_directory}") from error
        for entry in entries:
            relative_path = relative_directory / entry.name
            if _is_fallback_ignored(relative_path):
                continue
            if entry.is_symlink():
                paths.append(relative_path)
            elif entry.is_dir(follow_symlinks=False):
                paths.append(relative_path)
                pending.append((Path(entry.path), relative_path))
            elif entry.is_file(follow_symlinks=False):
                paths.append(relative_path)
            else:
                raise ValueError(f"source contains unsupported file: {relative_path}")
    return tuple(sorted(paths, key=lambda path: (len(path.parts), path.as_posix())))


def _source_paths(source_root: Path) -> tuple[Path, ...]:
    git_files = _git_source_files(source_root)
    if git_files is None:
        return _fallback_source_paths(source_root)

    paths: set[Path] = set()
    for file_path in git_files:
        paths.add(file_path)
        paths.update(file_path.parents)
    paths.discard(Path())
    return tuple(
        sorted(
            (path for path in paths if not _is_statically_ignored(path)),
            key=lambda path: (len(path.parts), path.as_posix()),
        )
    )


def _reject_source_symlinks(source_root: Path, source_paths: tuple[Path, ...]) -> None:
    for relative_path in source_paths:
        source_path = source_root / relative_path
        try:
            mode = source_path.lstat().st_mode
        except FileNotFoundError as error:
            raise ValueError(f"source entry disappeared: {relative_path}") from error
        if stat.S_ISLNK(mode):
            raise ValueError(f"source contains symbolic link: {relative_path}")


def _copy_source_paths(
    source_root: Path, plugin_root: Path, source_paths: tuple[Path, ...]
) -> None:
    for relative_path in source_paths:
        source_path = source_root / relative_path
        destination_path = plugin_root / relative_path
        mode = source_path.lstat().st_mode
        if stat.S_ISDIR(mode):
            destination_path.mkdir(parents=True, exist_ok=True)
        elif stat.S_ISREG(mode):
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination_path)
        else:
            raise ValueError(f"source contains unsupported file: {relative_path}")


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

    source_paths = _source_paths(source_root)
    _reject_source_symlinks(source_root, source_paths)

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
    _copy_source_paths(source_root, plugin_root, source_paths)

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
