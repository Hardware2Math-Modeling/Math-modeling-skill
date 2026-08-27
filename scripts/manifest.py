"""Deterministic hashing and strict atomic JSON primitives."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable, Sequence

from handoff_schema import strict_json_tree_errors
from suite_validation import ensure_no_symlink_components


_CHUNK_SIZE = 1024 * 1024


def _absolute_safe_path(path: Path, label: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    if any(part == ".." for part in candidate.parts):
        raise ValueError(f"{label} must not contain '..' components")
    return ensure_no_symlink_components(candidate, label)


def _regular_file(path: Path, label: str) -> Path:
    safe = _absolute_safe_path(path, label)
    try:
        mode = safe.lstat().st_mode
    except OSError as error:
        raise ValueError(f"{label} must be an existing regular file: {safe}") from error
    if not stat.S_ISREG(mode):
        raise ValueError(f"{label} must be a regular non-symlink file: {safe}")
    return safe


def _directory(path: Path, label: str) -> Path:
    safe = _absolute_safe_path(path, label)
    try:
        mode = safe.lstat().st_mode
    except OSError as error:
        raise ValueError(f"{label} must be an existing directory: {safe}") from error
    if not stat.S_ISDIR(mode):
        raise ValueError(f"{label} must be a directory: {safe}")
    return safe


def safe_relative_path(path: str | os.PathLike[str], label: str) -> Path:
    """Return one canonical safe relative path shared by state operations."""

    try:
        raw = os.fspath(path)
    except TypeError as error:
        raise ValueError(f"{label} must be a safe relative path") from error
    if (
        type(raw) is not str
        or not raw
        or "\\" in raw
        or any(ord(character) < 32 or ord(character) == 127 for character in raw)
        or "\u2028" in raw
        or "\u2029" in raw
    ):
        raise ValueError(f"{label} must be a safe relative path")
    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    segments = raw.split("/")
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or any(segment in ("", ".", "..") for segment in segments)
        or PurePosixPath(*segments).as_posix() != raw
    ):
        raise ValueError(f"{label} must be a safe relative path")
    return Path(*segments)


def sha256_file(path: Path) -> str:
    """Hash one regular file in streaming chunks."""

    safe = _regular_file(path, "hash input")
    digest = hashlib.sha256()
    try:
        with safe.open("rb") as stream:
            while chunk := stream.read(_CHUNK_SIZE):
                digest.update(chunk)
    except OSError as error:
        raise ValueError(f"unable to hash regular file: {safe}") from error
    return digest.hexdigest()


def sha256_paths(root: Path, relative_paths: Iterable[Path]) -> dict[str, str]:
    """Return sorted relative-path to SHA-256 mappings."""

    safe_root = _directory(root, "hash root")
    normalized: list[Path] = []
    seen: set[str] = set()
    for index, relative in enumerate(relative_paths):
        item = safe_relative_path(relative, f"artifact path {index}")
        key = item.as_posix()
        if key in seen:
            raise ValueError(f"duplicate artifact path: {key}")
        seen.add(key)
        target = _absolute_safe_path(safe_root / item, f"artifact path {key}")
        if not target.is_relative_to(safe_root):
            raise ValueError(f"artifact path escapes hash root: {key}")
        normalized.append(item)
    return {
        relative.as_posix(): sha256_file(safe_root / relative)
        for relative in sorted(normalized, key=lambda item: item.as_posix())
    }


def atomic_write_json(path: Path, payload: object) -> None:
    """Write canonical UTF-8 JSON through a same-directory temporary file."""

    errors = strict_json_tree_errors(payload)
    if errors:
        raise ValueError("payload is not strict JSON:\n- " + "\n- ".join(errors))
    try:
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ) + "\n"
    except (TypeError, ValueError) as error:
        raise ValueError(f"payload cannot be serialized as strict JSON: {error}") from error

    safe = _absolute_safe_path(path, "JSON output")
    parent = _directory(safe.parent, "JSON output parent")
    if safe.exists() or safe.is_symlink():
        safe = _regular_file(safe, "JSON output")

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent,
            prefix=f".{safe.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, safe)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp with a Z suffix."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def relative_regular_files(root: Path) -> Sequence[Path]:
    """Enumerate regular non-symlink files below root in lexical order."""

    safe_root = _directory(root, "file tree root")
    result: list[Path] = []

    def visit(directory: Path, relative_parent: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as error:
            raise ValueError(f"unable to inspect file tree: {directory}") from error
        for entry in entries:
            name = safe_relative_path(entry.name, "file tree entry name")
            relative = safe_relative_path(
                (relative_parent / name).as_posix(),
                "file tree relative path",
            )
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError as error:
                raise ValueError(f"unable to inspect file tree entry: {relative}") from error
            if stat.S_ISLNK(mode):
                raise ValueError(f"file tree must not contain symlinks: {relative.as_posix()}")
            if stat.S_ISDIR(mode):
                visit(Path(entry.path), relative)
            elif stat.S_ISREG(mode):
                result.append(relative)
            else:
                raise ValueError(
                    f"file tree must contain only directories and regular files: "
                    f"{relative.as_posix()}"
                )

    visit(safe_root, Path())
    return tuple(sorted(result, key=lambda item: item.as_posix()))
