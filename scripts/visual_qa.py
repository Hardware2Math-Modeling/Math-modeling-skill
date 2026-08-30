#!/usr/bin/env python3
"""Final-size render checks for registered scientific figure outputs."""

from __future__ import annotations

import math
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from xml.etree import ElementTree

from figure_qa import _parse_png, _safe_project_root, validate_figure_manifest
from manifest import safe_relative_path
from suite_validation import ensure_no_symlink_components


_LENGTH_RE = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(mm|cm|in|pt|px)?\s*$",
    re.IGNORECASE,
)
_MEDIA_BOX_RE = re.compile(
    rb"/MediaBox\s*\[\s*[-+0-9.]+\s+[-+0-9.]+\s+([-+0-9.]+)\s+([-+0-9.]+)\s*\]"
)


def _millimetres(value: str) -> float:
    match = _LENGTH_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"unsupported physical length: {value!r}")
    number = float(match.group(1))
    unit = (match.group(2) or "px").lower()
    factors = {
        "mm": 1.0,
        "cm": 10.0,
        "in": 25.4,
        "pt": 25.4 / 72.0,
        "px": 25.4 / 96.0,
    }
    return number * factors[unit]


def _svg_width_mm(path: Path) -> float:
    root = ElementTree.parse(path).getroot()
    width = root.get("width")
    if width is not None:
        return _millimetres(width)
    view_box = root.get("viewBox")
    if view_box is None:
        raise ValueError("SVG width and viewBox are both missing")
    values = [float(value) for value in view_box.replace(",", " ").split()]
    if len(values) != 4 or values[2] <= 0:
        raise ValueError("SVG viewBox is invalid")
    return values[2] * 25.4 / 96.0


def _pdf_width_mm(path: Path) -> float:
    match = _MEDIA_BOX_RE.search(path.read_bytes()[:1024 * 1024])
    if match is None:
        raise ValueError("PDF MediaBox is missing")
    width_points = float(match.group(1))
    if not math.isfinite(width_points) or width_points <= 0:
        raise ValueError("PDF MediaBox width is invalid")
    return width_points * 25.4 / 72.0


def _output_target(
    output: dict[str, object] | str,
    *,
    index: int,
    project_root: Path,
) -> tuple[Path, str]:
    path_value = output if type(output) is str else output.get("path")
    relative = safe_relative_path(path_value, f"output {index} path")
    target = ensure_no_symlink_components(project_root / relative, f"output {index} path")
    suffix = relative.suffix.lower().removeprefix(".")
    output_format = suffix if type(output) is str else output.get("format", suffix)
    if type(output_format) is not str:
        raise ValueError(f"output {index} format must be a string")
    return target, output_format.lower()


def _renderer_path(requested: Path | None) -> Path | None:
    if requested is None:
        discovered = shutil.which("pdftoppm")
        return Path(discovered) if discovered is not None else None
    candidate = Path(requested)
    if not candidate.is_absolute():
        return None
    try:
        mode = candidate.lstat().st_mode
    except OSError:
        return None
    if not stat.S_ISREG(mode) or not candidate.stat().st_mode & 0o111:
        return None
    return candidate


def _render_pdf(path: Path, executable: Path) -> str | None:
    with tempfile.TemporaryDirectory() as temporary:
        prefix = Path(temporary) / "render"
        try:
            completed = subprocess.run(
                [
                    str(executable),
                    "-png",
                    "-singlefile",
                    "-r",
                    "300",
                    str(path),
                    str(prefix),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return f"pdftoppm could not render {path.name}: {error}"
        rendered = prefix.with_suffix(".png")
        if completed.returncode != 0 or not rendered.is_file() or rendered.stat().st_size <= 0:
            detail = completed.stderr.strip() or f"exit status {completed.returncode}"
            return f"pdftoppm could not render {path.name}: {detail}"
    return None


def run_visual_qa(
    manifest: dict[str, object],
    *,
    project_root: Path,
    pdftoppm_executable: Path | None = None,
) -> dict[str, object]:
    """Check final-size dimensions and report renderer evidence without guessing."""

    root = _safe_project_root(project_root)
    messages = validate_figure_manifest(manifest, project_root=root)
    messages = list(messages)
    paper_width = manifest.get("paper_width_mm")
    if type(paper_width) not in (int, float) or paper_width <= 0:
        return {
            "status": "needs_review",
            "dimension_status": "needs_review",
            "render_status": "needs_review",
            "renderer": None,
            "messages": messages,
        }

    outputs = manifest.get("outputs")
    pdf_paths: list[Path] = []
    if type(outputs) is list:
        for index, output in enumerate(outputs):
            if type(output) not in (dict, str):
                continue
            try:
                target, output_format = _output_target(
                    output,
                    index=index,
                    project_root=root,
                )
                if output_format == "png":
                    width_px, _height_px, dpi_x, _dpi_y = _parse_png(target)
                    available_width = width_px / dpi_x * 25.4
                    if available_width + 0.1 < float(paper_width):
                        messages.append(
                            f"output {index} is too narrow for paper width "
                            f"{float(paper_width):g} mm at registered DPI"
                        )
                elif output_format == "svg":
                    physical_width = _svg_width_mm(target)
                    if physical_width + 0.1 < float(paper_width):
                        messages.append(
                            f"output {index} SVG width is smaller than requested paper width"
                        )
                elif output_format == "pdf":
                    pdf_paths.append(target)
                    physical_width = _pdf_width_mm(target)
                    if physical_width + 0.1 < float(paper_width):
                        messages.append(
                            f"output {index} PDF width is smaller than requested paper width"
                        )
            except (OSError, ValueError, ElementTree.ParseError) as error:
                messages.append(f"output {index} dimension check failed: {error}")

    renderer: Path | None = None
    render_status = "pass"
    if pdf_paths:
        renderer = _renderer_path(pdftoppm_executable)
        if renderer is None:
            render_status = "needs_review"
            messages.append(
                "pdftoppm is unavailable; final-size PDF rendering needs_review"
            )
        else:
            for pdf_path in pdf_paths:
                render_error = _render_pdf(pdf_path, renderer)
                if render_error is not None:
                    render_status = "needs_review"
                    messages.append(render_error)

    dimension_status = "pass"
    if any("width" in message or "dimension" in message for message in messages):
        dimension_status = "needs_review"
    status = "pass" if not messages and render_status == "pass" else "needs_review"
    return {
        "status": status,
        "dimension_status": dimension_status,
        "render_status": render_status,
        "renderer": str(renderer) if renderer is not None else None,
        "messages": messages,
    }


__all__ = ["run_visual_qa"]
