#!/usr/bin/env python3
"""Export a prebuilt Matplotlib figure from registered result evidence."""

from __future__ import annotations

import copy
import os
import stat
import tempfile
from pathlib import Path

from figure_qa import (
    _load_manifest,
    _manifest_target,
    _safe_project_root,
    refresh_figure_status,
    validate_figure_manifest,
)
from manifest import safe_relative_path, sha256_file
from suite_validation import ensure_no_symlink_components


STYLE_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "math-modeling-visualization"
    / "assets"
    / "styles"
    / "modeling.mplstyle"
)


def _registered_source(
    manifest: dict[str, object],
    source_path: Path,
) -> dict[str, object]:
    sources = manifest.get("sources")
    if type(sources) is not list:
        raise ValueError("figure manifest sources must be a nonempty array")
    matches = [
        source
        for source in sources
        if type(source) is dict and source.get("path") == source_path.as_posix()
    ]
    if len(matches) != 1:
        raise ValueError("source result path must appear exactly once in the figure manifest")
    return matches[0]


def _planned_outputs(
    manifest: dict[str, object],
    project_root: Path,
) -> list[tuple[dict[str, object], Path, str]]:
    raw_outputs = manifest.get("outputs")
    if type(raw_outputs) is not list or not raw_outputs:
        raise ValueError("figure manifest outputs must be a nonempty array")
    planned: list[tuple[dict[str, object], Path, str]] = []
    formats: set[str] = set()
    seen: set[str] = set()
    for index, raw_output in enumerate(raw_outputs):
        if type(raw_output) is str:
            output: dict[str, object] = {"path": raw_output}
        elif type(raw_output) is dict:
            output = raw_output
        else:
            raise ValueError(f"output {index} must be a path string or object")
        relative = safe_relative_path(output.get("path"), f"output {index} path")
        relative_text = relative.as_posix()
        if relative_text in seen:
            raise ValueError(f"duplicate output path: {relative_text}")
        seen.add(relative_text)
        suffix = relative.suffix.lower().removeprefix(".")
        output_format = output.get("format", suffix)
        if type(output_format) is not str or output_format.lower() not in {"pdf", "png", "svg"}:
            raise ValueError(f"output {index} format must be pdf, png, or svg")
        output_format = output_format.lower()
        if suffix != output_format:
            raise ValueError(f"output {index} format must match its file extension")
        target = ensure_no_symlink_components(project_root / relative, f"output {index} path")
        if not target.is_relative_to(project_root):
            raise ValueError(f"output {index} path must remain within project_root")
        parent_mode = target.parent.lstat().st_mode
        if not stat.S_ISDIR(parent_mode):
            raise ValueError(f"output {index} parent must be an existing directory")
        try:
            target_mode = target.lstat().st_mode
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(target_mode):
                raise ValueError(f"output {index} must be absent or a regular file")
        planned.append((output, target, output_format))
        formats.add(output_format)
    if "pdf" not in formats or not formats.intersection({"png", "svg"}):
        raise ValueError("registered export must include PDF plus PNG or SVG")
    return planned


def export_figure(
    figure: object,
    *,
    source_result_path: Path,
    figure_manifest_path: Path,
    project_root: Path,
) -> dict[str, object]:
    """Apply the shared style and atomically write registered figure outputs."""

    root = _safe_project_root(project_root)
    relative_source = safe_relative_path(source_result_path, "source_result_path")
    source_target = ensure_no_symlink_components(
        root / relative_source,
        "source_result_path",
    )
    if not source_target.is_file():
        raise ValueError("source result path must be an existing regular file")
    manifest_target = _manifest_target(figure_manifest_path, root)
    manifest = _load_manifest(manifest_target)
    registered = _registered_source(manifest, relative_source)
    expected_hash = registered.get("sha256")
    try:
        observed_hash = sha256_file(source_target)
    except ValueError as error:
        raise ValueError(f"source result cannot be hashed: {error}") from error
    if expected_hash != observed_hash:
        raise ValueError("source result is stale; refusing to draw")

    planned = _planned_outputs(manifest, root)
    savefig = getattr(figure, "savefig", None)
    if not callable(savefig):
        raise TypeError("figure must expose a callable savefig method")
    if not STYLE_PATH.is_file():
        raise RuntimeError(f"shared Matplotlib style is missing: {STYLE_PATH}")
    try:
        from matplotlib import style as matplotlib_style
    except ImportError as error:
        raise RuntimeError(
            "Matplotlib is required for figure export; install it through the approved environment"
        ) from error
    matplotlib_style.use(STYLE_PATH)

    temporary_outputs: list[tuple[Path, Path]] = []
    try:
        for output, target, output_format in planned:
            descriptor, temporary_name = tempfile.mkstemp(
                dir=target.parent,
                prefix=f".{target.stem}.",
                suffix=target.suffix,
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            savefig(
                temporary,
                format=output_format,
                dpi=300,
                bbox_inches="tight",
                facecolor="white",
            )
            candidate = copy.deepcopy(manifest)
            candidate_output = copy.deepcopy(output)
            candidate_output["path"] = temporary.relative_to(root).as_posix()
            candidate["outputs"] = [candidate_output]
            candidate["status"] = "draft"
            errors = validate_figure_manifest(candidate, project_root=root)
            if errors:
                raise ValueError(
                    f"exported {output_format.upper()} failed validation:\n- "
                    + "\n- ".join(errors)
                )
            temporary_outputs.append((temporary, target))
        for temporary, target in temporary_outputs:
            os.replace(temporary, target)
        temporary_outputs.clear()
    finally:
        for temporary, _target in temporary_outputs:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    return refresh_figure_status(manifest_target, project_root=root)


__all__ = ["STYLE_PATH", "export_figure"]
