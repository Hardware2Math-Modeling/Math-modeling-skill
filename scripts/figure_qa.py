#!/usr/bin/env python3
"""Deterministic figure-manifest, output-format, and freshness checks."""

from __future__ import annotations

import json
import re
import math
import stat
import struct
import zlib
from pathlib import Path
from xml.etree import ElementTree

from manifest import atomic_write_json, safe_relative_path, sha256_file
from suite_validation import ensure_no_symlink_components


FIGURE_ROLES = ("evidence", "validation", "diagnostic", "conceptual")
FIGURE_STATUSES = ("draft", "verified", "stale", "needs_review")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PDF_MEDIA_BOX_RE = re.compile(
    rb"/MediaBox\s*\[\s*([-+0-9.]+)\s+([-+0-9.]+)\s+([-+0-9.]+)\s+([-+0-9.]+)\s*\]"
)
_SVG_LENGTH_RE = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(mm|cm|in|pt|px)?\s*$",
    re.IGNORECASE,
)


def _nonempty(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _safe_project_root(project_root: Path) -> Path:
    root = Path(project_root)
    if not root.is_absolute():
        raise ValueError("project_root must be an absolute path")
    safe = ensure_no_symlink_components(root, "project_root")
    try:
        mode = safe.lstat().st_mode
    except OSError as error:
        raise ValueError("project_root must be an existing directory") from error
    if not stat.S_ISDIR(mode):
        raise ValueError("project_root must be an existing directory")
    return safe


def _relative_target(
    value: object,
    *,
    label: str,
    project_root: Path | None,
    errors: list[str],
) -> tuple[Path | None, str | None]:
    try:
        relative = safe_relative_path(value, label)
    except ValueError:
        errors.append(f"{label} must be a safe relative path")
        return None, None
    relative_text = relative.as_posix()
    if project_root is None:
        return None, relative_text
    try:
        target = ensure_no_symlink_components(
            project_root / relative,
            label,
        )
    except ValueError as error:
        errors.append(str(error))
        return None, relative_text
    if not target.is_relative_to(project_root):
        errors.append(f"{label} must remain within project_root")
        return None, relative_text
    return target, relative_text


def _regular_file(path: Path, label: str, errors: list[str]) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        errors.append(f"{label} must be an existing regular file")
        return False
    if not stat.S_ISREG(mode):
        errors.append(f"{label} must be an existing regular non-symlink file")
        return False
    if path.stat(follow_symlinks=False).st_size <= 0:
        errors.append(f"{label} must be nonempty")
        return False
    return True


def _parse_png(path: Path) -> tuple[int, int, float, float]:
    data = path.read_bytes()
    if not data.startswith(_PNG_SIGNATURE):
        raise ValueError("PNG signature is invalid")
    offset = len(_PNG_SIGNATURE)
    width: int | None = None
    height: int | None = None
    dpi_x: float | None = None
    dpi_y: float | None = None
    saw_end = False
    while offset < len(data):
        if len(data) - offset < 12:
            raise ValueError("PNG chunk header is truncated")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("PNG chunk is truncated")
        payload = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length : end])[0]
        if zlib.crc32(chunk_type + payload) & 0xFFFFFFFF != expected_crc:
            raise ValueError("PNG chunk CRC is invalid")
        if chunk_type == b"IHDR":
            if width is not None or length != 13:
                raise ValueError("PNG IHDR is invalid")
            width, height = struct.unpack(">II", payload[:8])
            if width <= 0 or height <= 0:
                raise ValueError("PNG dimensions must be positive")
        elif chunk_type == b"pHYs":
            if length != 9:
                raise ValueError("PNG pHYs is invalid")
            pixels_x, pixels_y, unit = struct.unpack(">IIB", payload)
            if unit != 1 or pixels_x <= 0 or pixels_y <= 0:
                raise ValueError("PNG pHYs must declare pixels per metre")
            dpi_x = pixels_x * 0.0254
            dpi_y = pixels_y * 0.0254
        elif chunk_type == b"IEND":
            if length != 0:
                raise ValueError("PNG IEND is invalid")
            saw_end = True
            if end != len(data):
                raise ValueError("PNG has trailing bytes after IEND")
            break
        offset = end
    if width is None or height is None:
        raise ValueError("PNG IHDR is missing")
    if dpi_x is None or dpi_y is None:
        raise ValueError("PNG DPI pHYs metadata is missing")
    if not saw_end:
        raise ValueError("PNG IEND is missing")
    return width, height, dpi_x, dpi_y


def _validate_png(
    output: dict[str, object],
    path: Path,
    label: str,
    errors: list[str],
) -> None:
    try:
        actual_width, actual_height, actual_dpi_x, actual_dpi_y = _parse_png(path)
    except (OSError, ValueError, struct.error) as error:
        errors.append(f"{label} is not a valid PNG: {error}")
        return
    for field, actual in (("width_px", actual_width), ("height_px", actual_height)):
        value = output.get(field)
        if type(value) is not int or value <= 0:
            errors.append(f"{label}.{field} must be a positive integer")
        else:
            if value != actual:
                errors.append(f"{label}.{field} does not match PNG header")
    declared_dpi: list[float] = []
    for field, actual in (("dpi_x", actual_dpi_x), ("dpi_y", actual_dpi_y)):
        value = output.get(field)
        if type(value) not in (int, float) or value <= 0:
            errors.append(f"{label}.{field} must declare positive DPI")
            continue
        declared_dpi.append(float(value))
        if abs(float(value) - actual) > 0.51:
            errors.append(f"{label}.{field} does not match PNG pHYs DPI")
    if len(declared_dpi) != 2 or min(declared_dpi) < 300:
        errors.append(f"{label} requires dpi_x and dpi_y of at least 300 DPI")
    if actual_dpi_x < 299.5 or actual_dpi_y < 299.5:
        errors.append(f"{label} PNG header requires at least 300 DPI")


def _validate_pdf(path: Path, label: str, errors: list[str]) -> None:
    try:
        content = path.read_bytes()
    except OSError as error:
        errors.append(f"{label} PDF cannot be read: {error}")
        return
    if not content.startswith(b"%PDF-"):
        errors.append(f"{label} has an invalid PDF signature")
        return
    match = _PDF_MEDIA_BOX_RE.search(content[:1024 * 1024])
    if match is None:
        errors.append(f"{label} PDF page size MediaBox is missing or invalid")
        return
    try:
        x0, y0, x1, y1 = (float(value) for value in match.groups())
    except ValueError:
        errors.append(f"{label} PDF page size MediaBox is invalid")
        return
    if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
        errors.append(f"{label} PDF page size MediaBox is invalid")
    elif x1 <= x0 or y1 <= y0:
        errors.append(f"{label} PDF page size MediaBox must be positive")


def _svg_length_mm(value: str) -> float:
    match = _SVG_LENGTH_RE.fullmatch(value)
    if match is None:
        raise ValueError("SVG dimension is invalid")
    number = float(match.group(1))
    factors = {
        "mm": 1.0,
        "cm": 10.0,
        "in": 25.4,
        "pt": 25.4 / 72.0,
        "px": 25.4 / 96.0,
    }
    return number * factors[(match.group(2) or "px").lower()]


def _validate_svg(path: Path, label: str, errors: list[str]) -> None:
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError) as error:
        errors.append(f"{label} has invalid SVG content: {error}")
        return
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        errors.append(f"{label} has an invalid SVG signature")
        return
    width = root.get("width")
    height = root.get("height")
    try:
        if width is not None or height is not None:
            if width is None or height is None:
                raise ValueError("SVG width and height must both be declared")
            if _svg_length_mm(width) <= 0 or _svg_length_mm(height) <= 0:
                raise ValueError("SVG dimensions must be positive")
        else:
            view_box = root.get("viewBox")
            if view_box is None:
                raise ValueError("SVG dimensions and viewBox are missing")
            values = [float(value) for value in view_box.replace(",", " ").split()]
            if len(values) != 4 or not all(math.isfinite(value) for value in values):
                raise ValueError("SVG viewBox is invalid")
            if values[2] <= 0 or values[3] <= 0:
                raise ValueError("SVG viewBox dimensions must be positive")
    except (TypeError, ValueError) as error:
        errors.append(f"{label} SVG dimension check failed: {error}")


def _validate_axes(manifest: dict[str, object], errors: list[str]) -> None:
    axes = manifest.get("axes")
    if type(axes) is not list or not axes:
        errors.append("axes must be a nonempty array with labels and units")
        return
    seen: set[str] = set()
    for index, axis in enumerate(axes):
        label = f"axes[{index}]"
        if type(axis) is not dict:
            errors.append(f"{label} must be an object")
            continue
        axis_id = axis.get("id")
        if not _nonempty(axis_id):
            errors.append(f"{label}.id must be nonempty")
        elif axis_id in seen:
            errors.append(f"{label}.id must be unique")
        else:
            seen.add(axis_id)
        if not _nonempty(axis.get("label")):
            errors.append(f"{label}.label must be nonempty")
        if not _nonempty(axis.get("unit")):
            errors.append(f"{label}.unit must be nonempty")


def _validate_legend(manifest: dict[str, object], errors: list[str]) -> None:
    legend = manifest.get("legend")
    if type(legend) is not dict:
        errors.append("legend must be an object")
        return
    present = legend.get("present")
    if type(present) is not bool:
        errors.append("legend.present must be boolean")
    elif present:
        labels = legend.get("labels")
        if type(labels) is not list or not labels or not all(_nonempty(item) for item in labels):
            errors.append("legend.labels must be a nonempty string array when present")
    elif not _nonempty(legend.get("reason")):
        errors.append("legend.reason must explain an intentionally absent legend")


def _validate_sources(
    manifest: dict[str, object],
    *,
    project_root: Path | None,
    errors: list[str],
) -> None:
    sources = manifest.get("sources")
    if type(sources) is not list or not sources:
        errors.append("sources must be a nonempty array")
        return
    seen: set[str] = set()
    for index, source in enumerate(sources):
        label = f"source {index}"
        if type(source) is not dict:
            errors.append(f"{label} must be an object")
            continue
        target, relative = _relative_target(
            source.get("path"),
            label=f"{label} path",
            project_root=project_root,
            errors=errors,
        )
        if relative is not None:
            if relative in seen:
                errors.append(f"{label} path is duplicated: {relative}")
            seen.add(relative)
        expected_hash = source.get("sha256")
        if type(expected_hash) is not str or _HASH_RE.fullmatch(expected_hash) is None:
            errors.append(f"{label} sha256 must be a lowercase SHA-256 digest")
        if target is None or project_root is None:
            continue
        if not _regular_file(target, label, errors):
            continue
        if type(expected_hash) is str and _HASH_RE.fullmatch(expected_hash):
            try:
                current_hash = sha256_file(target)
            except ValueError as error:
                errors.append(f"{label} cannot be hashed: {error}")
                continue
            if current_hash != expected_hash:
                errors.append(f"{label} is stale: registered SHA-256 does not match")


def _validate_outputs(
    manifest: dict[str, object],
    *,
    project_root: Path | None,
    errors: list[str],
) -> None:
    outputs = manifest.get("outputs")
    if type(outputs) is not list or not outputs:
        errors.append("outputs must be a nonempty array")
        return
    seen: set[str] = set()
    supported = {"pdf", "svg", "png"}
    for index, raw_output in enumerate(outputs):
        label = f"output {index}"
        if type(raw_output) is str:
            output: dict[str, object] = {"path": raw_output}
        elif type(raw_output) is dict:
            output = raw_output
        else:
            errors.append(f"{label} must be a path string or object")
            continue
        target, relative = _relative_target(
            output.get("path"),
            label=f"{label} path",
            project_root=project_root,
            errors=errors,
        )
        if relative is not None:
            if relative in seen:
                errors.append(f"{label} path is duplicated: {relative}")
            seen.add(relative)
        suffix = Path(relative).suffix.lower().removeprefix(".") if relative else ""
        declared = output.get("format", suffix)
        if type(declared) is not str or declared.lower() not in supported:
            errors.append(f"{label} format must be pdf, svg, or png")
            continue
        output_format = declared.lower()
        if suffix != output_format:
            errors.append(f"{label} format must match its file extension")
        if target is None or project_root is None:
            continue
        if not _regular_file(target, label, errors):
            continue
        if output_format == "pdf":
            _validate_pdf(target, label, errors)
        elif output_format == "svg":
            _validate_svg(target, label, errors)
        else:
            _validate_png(output, target, label, errors)


def validate_figure_manifest(
    manifest: dict[str, object],
    *,
    project_root: Path | None = None,
) -> list[str]:
    """Return deterministic figure-manifest and source-freshness errors."""

    errors: list[str] = []
    if type(manifest) is not dict:
        return ["figure manifest must be an object"]
    root: Path | None = None
    if project_root is not None:
        try:
            root = _safe_project_root(project_root)
        except ValueError as error:
            return [str(error)]

    if manifest.get("schema_version") != "1":
        errors.append('schema_version must be exactly "1"')
    if not _nonempty(manifest.get("figure_id")):
        errors.append("figure_id must be nonempty")
    if not _nonempty(manifest.get("question_id")):
        errors.append("question_id must be nonempty")
    role = manifest.get("role")
    if role not in FIGURE_ROLES or type(role) is not str:
        errors.append("role must be evidence, validation, diagnostic, or conceptual")
    claim_type = manifest.get("claim_type")
    exploratory = (
        manifest.get("exploratory_draft") is True
        and role == "diagnostic"
        and claim_type == "exploratory"
        and manifest.get("status") == "draft"
    )
    if not _nonempty(manifest.get("claim_id")) and not exploratory:
        errors.append("claim_id must be nonempty except for an explicitly labeled exploratory draft")
    if role == "conceptual":
        if claim_type != "conceptual":
            errors.append("conceptual figures cannot support a data or evidence claim")
        if "示意图" not in str(manifest.get("caption", "")):
            errors.append('conceptual figure captions must include "示意图"')
    if role == "diagnostic" and claim_type == "data":
        errors.append("diagnostic figures cannot support a data evidence claim")

    _validate_sources(manifest, project_root=root, errors=errors)
    _validate_outputs(manifest, project_root=root, errors=errors)
    _validate_axes(manifest, errors)
    _validate_legend(manifest, errors)

    for field in ("caption", "paper_reference"):
        if not _nonempty(manifest.get(field)):
            errors.append(f"{field} must be nonempty")
    paper_width = manifest.get("paper_width_mm")
    if type(paper_width) not in (int, float) or paper_width <= 0:
        errors.append("paper_width_mm must be positive")
    for field in ("grayscale_status", "colorblind_status", "render_status"):
        if manifest.get(field) not in ("pass", "needs_review"):
            errors.append(f"{field} must be pass or needs_review")
    status = manifest.get("status")
    if status not in FIGURE_STATUSES or type(status) is not str:
        errors.append("status must be draft, verified, stale, or needs_review")
    if status == "verified":
        pending = [
            field
            for field in ("grayscale_status", "colorblind_status", "render_status")
            if manifest.get(field) != "pass"
        ]
        if pending:
            errors.append("status verified requires all visual QA checks to pass")
        if errors:
            errors.append("status verified is invalid while figure checks fail")
    return errors


def _manifest_target(manifest_path: Path, project_root: Path) -> Path:
    candidate = Path(manifest_path)
    if candidate.is_absolute():
        target = ensure_no_symlink_components(candidate, "figure manifest path")
        if not target.is_relative_to(project_root):
            raise ValueError("figure manifest path must remain within project_root")
        safe_relative_path(
            target.relative_to(project_root).as_posix(),
            "figure manifest path",
        )
        return target
    relative = safe_relative_path(candidate, "figure manifest path")
    return ensure_no_symlink_components(
        project_root / relative,
        "figure manifest path",
    )


def _load_manifest(path: Path) -> dict[str, object]:
    def reject_nonfinite(value: str) -> object:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw, parse_constant=reject_nonfinite)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"unable to read strict figure manifest: {error}") from error
    if type(payload) is not dict:
        raise ValueError("figure manifest must be a JSON object")
    return payload


def refresh_figure_status(
    manifest_path: Path,
    *,
    project_root: Path,
) -> dict[str, object]:
    """Recompute source hashes and persist verified/stale status."""

    root = _safe_project_root(project_root)
    target = _manifest_target(manifest_path, root)
    manifest = _load_manifest(target)
    sources = manifest.get("sources")
    if type(sources) is list:
        for index, source in enumerate(sources):
            if type(source) is not dict:
                continue
            structural_errors: list[str] = []
            source_path, _ = _relative_target(
                source.get("path"),
                label=f"source {index} path",
                project_root=root,
                errors=structural_errors,
            )
            expected = source.get("sha256")
            if source_path is None or not source_path.is_file():
                source.pop("observed_sha256", None)
                continue
            try:
                observed = sha256_file(source_path)
            except ValueError:
                source.pop("observed_sha256", None)
                continue
            if observed != expected:
                source["observed_sha256"] = observed
            else:
                source.pop("observed_sha256", None)

    errors = validate_figure_manifest(manifest, project_root=root)
    visual_review_pending = any(
        manifest.get(field) != "pass"
        for field in ("grayscale_status", "colorblind_status", "render_status")
    )
    if any("stale" in error for error in errors):
        manifest["status"] = "stale"
    elif errors or visual_review_pending:
        manifest["status"] = "needs_review"
    else:
        manifest["status"] = "verified"
    atomic_write_json(target, manifest)
    return manifest


__all__ = [
    "FIGURE_ROLES",
    "refresh_figure_status",
    "validate_figure_manifest",
]
