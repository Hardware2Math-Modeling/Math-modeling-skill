#!/usr/bin/env python3
"""Build a self-contained local Codex marketplace bundle."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from suite_validation import (
    ARCHIVE_IGNORED_NAMES,
    PLUGIN_NAME,
    ensure_no_symlink_components,
    is_ignored_relative_path,
    is_sensitive_relative_path,
    validate_suite,
)


MARKETPLACE_NAME = "math-modeling-local"
MARKETPLACE_DISPLAY_NAME = "Local Math Modeling"
IGNORED_NAMES = ARCHIVE_IGNORED_NAMES
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
    return is_ignored_relative_path(relative_path)


def _is_fallback_ignored(relative_path: Path) -> bool:
    return _is_statically_ignored(relative_path) or any(
        part.casefold() in {".env", ".envrc"} or part.casefold().startswith(".env.")
        for part in relative_path.parts
    )


def _has_git_marker(source_root: Path) -> bool:
    """Return whether the source or one of its parents declares a Git root."""
    current = source_root
    while True:
        try:
            if (current / ".git").exists() or (current / ".git").is_symlink():
                return True
        except OSError:
            return True
        if current.parent == current:
            return False
        current = current.parent


def _git_source_files(source_root: Path) -> tuple[Path, ...] | None:
    """Return Git-selected source paths, or None when source is not a worktree."""
    try:
        probe = subprocess.run(
            ["git", "-C", os.fspath(source_root), "rev-parse", "--is-inside-work-tree"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        if _has_git_marker(source_root):
            raise ValueError("Git source inspection failed") from error
        return None
    if probe.returncode != 0 or probe.stdout.strip() != b"true":
        if _has_git_marker(source_root):
            raise ValueError("Git source inspection failed")
        return None

    try:
        index_result = subprocess.run(
            [
                "git",
                "-C",
                os.fspath(source_root),
                "ls-files",
                "--stage",
                "-z",
                "--",
                ".",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("Git source inspection failed") from error
    if index_result.returncode != 0:
        raise ValueError("Git source inspection failed")
    for raw_record in index_result.stdout.split(b"\0"):
        if not raw_record:
            continue
        try:
            metadata, raw_path = raw_record.split(b"\t", 1)
            mode, _object_id, stage = metadata.split(b" ", 2)
        except ValueError as error:
            raise ValueError("git returned invalid index metadata") from error
        relative_path = Path(os.fsdecode(raw_path))
        if stage != b"0":
            raise ValueError(
                f"Git source index contains an unmerged entry: {relative_path}"
            )
        if mode == b"160000":
            raise ValueError(
                f"Git submodules are not supported in bundles: {relative_path}"
            )
        if mode == b"120000":
            raise ValueError(f"source contains symbolic link: {relative_path}")
        if mode not in {b"100644", b"100755"}:
            raise ValueError(
                f"Git source index contains an unsupported entry: {relative_path}"
            )

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
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("Git source inspection failed") from error
    if result.returncode != 0:
        raise ValueError("Git source inspection failed")

    paths: set[Path] = set()
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative_path = Path(os.fsdecode(raw_path))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("git returned an invalid source path")
        if is_sensitive_relative_path(relative_path) and not any(
            part.casefold() == ".env" or part.casefold() == ".envrc" or part.casefold().startswith(".env.")
            for part in relative_path.parts
        ):
            raise ValueError(f"source contains sensitive file: {relative_path}")
        if not _is_fallback_ignored(relative_path):
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
            if is_sensitive_relative_path(relative_path):
                raise ValueError(f"source contains sensitive file: {relative_path}")
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
            (path for path in paths if not _is_fallback_ignored(path)),
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
    source_root = ensure_no_symlink_components(source_root, "source root").resolve()
    output_root = ensure_no_symlink_components(output_root, "bundle output")
    output_root = output_root.resolve()
    _require_output_outside_source(source_root, output_root)

    source_paths = _source_paths(source_root)
    _reject_source_symlinks(source_root, source_paths)

    errors = validate_suite(source_root)
    if errors:
        raise ValueError("source validation failed:\n- " + "\n- ".join(errors))

    output_existed = output_root.exists()
    if output_existed:
        if not output_root.is_dir() or any(output_root.iterdir()):
            raise FileExistsError(
                f"refusing to overwrite non-empty output: {output_root}"
            )
    else:
        output_root.parent.mkdir(parents=True, exist_ok=True)

    staging_root = Path(
        tempfile.mkdtemp(
            prefix=f".{output_root.name}.building-",
            dir=output_root.parent,
        )
    )
    removed_empty_output = False
    try:
        staged_plugin_root = staging_root / "plugins" / PLUGIN_NAME
        staged_plugin_root.parent.mkdir(parents=True, exist_ok=True)
        _copy_source_paths(source_root, staged_plugin_root, source_paths)
        staged_errors = validate_suite(staged_plugin_root)
        if staged_errors:
            raise ValueError(
                "staged plugin validation failed:\n- "
                + "\n- ".join(staged_errors)
            )

        marketplace_path = (
            staging_root / ".agents" / "plugins" / "marketplace.json"
        )
        marketplace_path.parent.mkdir(parents=True, exist_ok=True)
        marketplace_path.write_text(
            json.dumps(marketplace_payload(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        if output_existed:
            output_root.rmdir()
            removed_empty_output = True
        os.replace(staging_root, output_root)
    except BaseException:
        if staging_root.exists():
            shutil.rmtree(staging_root)
        if removed_empty_output and not output_root.exists():
            output_root.mkdir()
        raise

    return output_root / "plugins" / PLUGIN_NAME


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
