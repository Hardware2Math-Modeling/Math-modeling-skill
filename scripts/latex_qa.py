#!/usr/bin/env python3
"""Conservative compiled-PDF, reference, marker, and page-limit QA."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import zlib
from pathlib import Path
from typing import Sequence

from manifest import sha256_file
from suite_validation import ensure_no_symlink_components


_PDFINFO_TIMEOUT_SECONDS = 15
_OBJECT_RE = re.compile(rb"(?m)^(\d+)\s+0\s+obj\b(.*?)^endobj\s*$", re.DOTALL)
_PAGE_TYPE_RE = re.compile(rb"/Type\s*/Page(?!s)\b")
_PAGES_COUNT_RE = re.compile(rb"/Type\s*/Pages\b.*?/Count\s+(\d+)\b", re.DOTALL)
_CONTENTS_RE = re.compile(rb"/Contents\s+(\d+)\s+0\s+R\b")
_STARTXREF_RE = re.compile(rb"startxref\s+(\d+)\s+%%EOF\s*\Z", re.DOTALL)
_LABEL_RE = re.compile(
    r"\\newlabel\{(?P<label>mm-body-(?:start|end))\}"
    r"\{\{[^{}]*\}\{(?P<page>[1-9][0-9]*)\}"
)
_UNRESOLVED_PATTERNS = (
    re.compile(r"undefined references", re.IGNORECASE),
    re.compile(r"reference [`'][^\n]+ undefined", re.IGNORECASE),
    re.compile(r"citation [`'][^\n]+ undefined", re.IGNORECASE),
    re.compile(r"undefined citations", re.IGNORECASE),
    re.compile(r"there were undefined citations", re.IGNORECASE),
)


def _regular_file(path: Path, label: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise ValueError(f"{label} must be an absolute path without '..'")
    safe = ensure_no_symlink_components(candidate, label)
    try:
        mode = safe.lstat().st_mode
    except OSError as error:
        raise ValueError(f"{label} must be an existing regular file: {safe}") from error
    if not stat.S_ISREG(mode):
        raise ValueError(f"{label} must be a regular non-symlink file: {safe}")
    return safe


def evaluate_page_gate(
    *,
    total_pages: int,
    body_pages: int,
    body_start: int,
    body_end: int,
) -> dict[str, object]:
    """Evaluate the locked 25--27 body and at-most-30 total page policy."""

    values = (total_pages, body_pages, body_start, body_end)
    failed: list[str] = []
    if any(type(value) is not int for value in values):
        failed.append("page counts and range boundaries must be integers")
    elif total_pages < 1:
        failed.append("total page count must be positive")
    else:
        if body_start < 1 or body_end < body_start:
            failed.append("body page range must be positive and ordered")
        if body_end > total_pages:
            failed.append("body page range must remain within the compiled PDF")
        expected = body_end - body_start + 1
        if body_pages != expected:
            failed.append("body page count must equal body_end - body_start + 1")
        if body_pages < 1 or body_pages > total_pages:
            failed.append("body page count must be positive and no larger than total pages")
        if total_pages > 30:
            failed.append("compiled PDF total pages must not exceed 30")

    actions: list[str] = []
    status = "fail" if failed else "pass"
    if not failed and not 25 <= body_pages <= 27:
        status = "needs_revision"
        if body_pages < 25:
            actions.append(
                "Add only evidence-backed derivation, analysis, validation, or limitations."
            )
        else:
            actions.append(
                "Remove repetition and improve figure or table layout while preserving evidence."
            )

    return {
        "status": status,
        "total_pages": total_pages,
        "body_pages": body_pages,
        "body_range": {
            "start": body_start,
            "end": body_end,
            "pages": body_pages,
        },
        "target_body_pages": {"minimum": 25, "maximum": 27},
        "maximum_total_pages": 30,
        "failed_checks": failed,
        "actions": actions,
        "no_padding": True,
    }


def _pdf_objects(data: bytes) -> tuple[dict[int, tuple[int, bytes]], list[str]]:
    errors: list[str] = []
    if not data.startswith(b"%PDF-"):
        errors.append("PDF header is missing")
        return {}, errors
    eof = _STARTXREF_RE.search(data)
    if eof is None:
        errors.append("PDF must end at a valid startxref/%%EOF trailer")
        return {}, errors
    xref_offset = int(eof.group(1))
    classic_xref = False
    xref_stream_dictionary: bytes | None = None
    xref_entries: dict[int, tuple[int, int, int]] = {}
    if 0 <= xref_offset < len(data) and data[xref_offset:].startswith(b"xref"):
        classic_xref = True
    elif 0 <= xref_offset < len(data):
        xref_match = re.match(
            rb"(\d+)\s+0\s+obj\s*<<(.*?)>>\s*stream\r?\n(.*?)\r?\nendstream",
            data[xref_offset:],
            re.DOTALL,
        )
        if xref_match is None or re.search(rb"/Type\s*/XRef\b", xref_match.group(2)) is None:
            errors.append("PDF startxref does not point to an xref table or stream")
        else:
            xref_stream_dictionary = xref_match.group(2)
            size_match = re.search(rb"/Size\s+(\d+)\b", xref_stream_dictionary)
            width_match = re.search(
                rb"/W\s*\[\s*(\d+)\s+(\d+)\s+(\d+)\s*\]",
                xref_stream_dictionary,
            )
            if size_match is None or width_match is None:
                errors.append("PDF xref stream lacks a supported Size/W declaration")
            else:
                size = int(size_match.group(1))
                widths = tuple(int(width_match.group(index)) for index in (1, 2, 3))
                index_match = re.search(rb"/Index\s*\[([^]]+)\]", xref_stream_dictionary)
                if index_match is None:
                    ranges = (0, size)
                else:
                    try:
                        ranges = tuple(int(item) for item in index_match.group(1).split())
                    except ValueError:
                        ranges = ()
                if not widths[0] or sum(widths) < 2 or len(ranges) % 2:
                    errors.append("PDF xref stream declarations are inconsistent")
                else:
                    stream = xref_match.group(3)
                    if re.search(rb"/Filter\s*/FlateDecode\b", xref_stream_dictionary):
                        try:
                            stream = zlib.decompress(stream)
                        except zlib.error:
                            errors.append("PDF xref stream FlateDecode data is broken")
                            stream = b""
                    elif re.search(rb"/Filter\b", xref_stream_dictionary):
                        errors.append("PDF xref stream uses an unsupported filter")
                        stream = b""
                    entry_count = sum(ranges[index + 1] for index in range(0, len(ranges), 2))
                    if len(stream) != entry_count * sum(widths):
                        errors.append("PDF xref stream length disagrees with its declarations")
                    else:
                        xref_object = int(xref_match.group(1))
                        cursor = 0
                        accounted = False
                        for range_index in range(0, len(ranges), 2):
                            first, count = ranges[range_index : range_index + 2]
                            for object_id in range(first, first + count):
                                fields: list[int] = []
                                for width in widths:
                                    fields.append(int.from_bytes(stream[cursor : cursor + width], "big"))
                                    cursor += width
                                xref_entries[object_id] = (fields[0], fields[1], fields[2])
                                if object_id == xref_object:
                                    accounted = fields[0] == 1 and fields[1] == xref_offset
                        if not accounted:
                            errors.append("PDF xref stream does not account for itself")

    objects: dict[int, tuple[int, bytes]] = {}
    for match in _OBJECT_RE.finditer(data):
        object_id = int(match.group(1))
        if object_id in objects:
            errors.append(f"PDF contains duplicate object {object_id}")
            continue
        objects[object_id] = (match.start(), match.group(2))
    if not objects:
        errors.append("PDF contains no complete indirect objects")
        return {}, errors
    if classic_xref:
        if re.search(rb"trailer\s*<<.*?/Root\s+\d+\s+0\s+R.*?>>", data, re.DOTALL) is None:
            errors.append("PDF trailer has no catalog root")
    elif xref_stream_dictionary is not None and re.search(
        rb"/Root\s+\d+\s+0\s+R\b", xref_stream_dictionary
    ) is None:
        errors.append("PDF xref stream has no catalog root")

    if xref_stream_dictionary is not None and xref_entries:
        for object_id, (offset, _) in objects.items():
            entry = xref_entries.get(object_id)
            if entry is None or entry[0] != 1 or entry[1] != offset:
                errors.append(
                    f"PDF xref stream entry for direct object {object_id} is free or has the wrong offset"
                )
        root_match = re.search(rb"/Root\s+(\d+)\s+0\s+R\b", xref_stream_dictionary)
        if root_match is not None:
            root_id = int(root_match.group(1))
            root_entry = xref_entries.get(root_id)
            if root_entry is None or root_entry[0] not in (1, 2):
                errors.append("PDF xref stream catalog entry is missing or free")
            elif root_entry[0] == 2:
                container = objects.get(root_entry[1])
                if container is None or re.search(rb"/Type\s*/ObjStm\b", container[1]) is None:
                    errors.append("PDF xref stream catalog object stream is unavailable")

    if not errors and classic_xref:
        xref_data = data[xref_offset : eof.start()]
        for object_id, (offset, _) in objects.items():
            entry = f"{offset:010d} 00000 n".encode("ascii")
            if entry not in xref_data:
                errors.append(f"PDF xref does not account for object {object_id}")
                break
    return objects, errors


def _fallback_page_count(
    data: bytes,
    objects: dict[int, tuple[int, bytes]],
) -> tuple[int | None, list[int], list[str]]:
    errors: list[str] = []
    page_objects = [
        (object_id, body)
        for object_id, (_, body) in sorted(objects.items())
        if _PAGE_TYPE_RE.search(body)
    ]
    declared = [int(match.group(1)) for match in _PAGES_COUNT_RE.finditer(data)]
    if not page_objects or not declared:
        return None, [], ["PDF page tree is missing or cannot be counted conservatively"]
    if max(declared) != len(page_objects):
        errors.append("PDF page-tree count disagrees with complete page objects")

    empty_pages: list[int] = []
    for page_number, (_, body) in enumerate(page_objects, start=1):
        content = _CONTENTS_RE.search(body)
        if content is None:
            empty_pages.append(page_number)
            continue
        content_object = objects.get(int(content.group(1)))
        if content_object is None:
            errors.append(f"PDF page {page_number} references a missing content object")
            continue
        stream_match = re.search(rb"stream\r?\n(.*?)\r?\nendstream", content_object[1], re.DOTALL)
        if stream_match is not None and not stream_match.group(1).strip():
            empty_pages.append(page_number)
    return len(page_objects), empty_pages, errors


def _pdfinfo_count(pdf: Path, executable: Path) -> tuple[int | None, str | None]:
    try:
        completed = subprocess.run(
            [str(executable), str(pdf)],
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_PDFINFO_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, str(error)
    if completed.returncode != 0:
        return None, completed.stderr.strip() or f"pdfinfo exited {completed.returncode}"
    match = re.search(r"(?m)^Pages:\s*([1-9][0-9]*)\s*$", completed.stdout)
    if match is None:
        return None, "pdfinfo did not report a positive Pages value"
    return int(match.group(1)), None


def _discovered_pdfinfo() -> Path | None:
    discovered = shutil.which("pdfinfo")
    if discovered is None:
        return None
    try:
        resolved = Path(discovered).resolve(strict=True)
        mode = resolved.stat(follow_symlinks=False).st_mode
    except (OSError, RuntimeError, ValueError):
        return None
    if not stat.S_ISREG(mode) or not os.access(resolved, os.X_OK):
        return None
    return resolved


def _aux_range(aux: Path | None) -> tuple[int | None, int | None, list[str]]:
    if aux is None:
        return None, None, ["compiled aux body markers are missing"]
    try:
        safe = _regular_file(aux, "aux file")
        text = safe.read_text(encoding="utf-8", errors="strict")
    except (ValueError, OSError, UnicodeError) as error:
        return None, None, [f"compiled aux body markers are unreadable: {error}"]
    found: dict[str, list[int]] = {"mm-body-start": [], "mm-body-end": []}
    for match in _LABEL_RE.finditer(text):
        found[match.group("label")].append(int(match.group("page")))
    if any(len(values) != 1 for values in found.values()):
        return None, None, ["compiled aux must contain exactly one start and end body marker"]
    return found["mm-body-start"][0], found["mm-body-end"][0], []


def _reference_errors(log_paths: Sequence[Path]) -> tuple[list[str], list[dict[str, str]]]:
    errors: list[str] = []
    logs: list[dict[str, str]] = []
    for index, path in enumerate(log_paths):
        safe = _regular_file(path, f"LaTeX log {index}")
        try:
            text = safe.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            errors.append(f"LaTeX log cannot be read: {error}")
            continue
        logs.append({"path": str(safe), "sha256": sha256_file(safe)})
        if any(pattern.search(text) for pattern in _UNRESOLVED_PATTERNS):
            errors.append(f"unresolved reference or citation reported in {safe.name}")
    return errors, logs


def _visual_review(
    path: Path | None,
    *,
    pdf_hash: str,
    total_pages: int | None,
) -> tuple[dict[str, object], list[str]]:
    if path is None:
        return {
            "status": "needs_review",
            "method": "verified_render_review_required",
            "failed_checks": [],
        }, []
    try:
        safe = _regular_file(path, "visual review")

        def reject_constant(value: str) -> object:
            raise ValueError(f"non-finite JSON constant: {value}")

        def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON key: {key}")
                result[key] = value
            return result

        payload = json.loads(
            safe.read_text(encoding="utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicates,
        )
        if type(payload) is not dict:
            raise ValueError("visual review must be a JSON object")
        required = {
            "status",
            "pdf_sha256",
            "page_coverage",
            "render_evidence",
            "reviewer",
        }
        if set(payload) != required or payload.get("status") != "verified":
            raise ValueError("visual review fields/status are not exactly verified")
        if payload.get("pdf_sha256") != pdf_hash:
            raise ValueError("visual review PDF hash does not match compiled PDF")
        coverage = payload.get("page_coverage")
        expected = {"start": 1, "end": total_pages, "pages": total_pages}
        if type(coverage) is not dict or coverage != expected:
            raise ValueError("visual review page coverage must include every compiled page")
        reviewer = payload.get("reviewer")
        if type(reviewer) is not str or not reviewer.strip():
            raise ValueError("visual review reviewer must be non-empty")
        evidence = payload.get("render_evidence")
        if type(evidence) is not list or not evidence:
            raise ValueError("visual review render_evidence must be non-empty")
        rendered: list[dict[str, str]] = []
        for index, entry in enumerate(evidence):
            if type(entry) is not dict or set(entry) != {"path", "sha256"}:
                raise ValueError(f"visual review render_evidence[{index}] is malformed")
            render = _regular_file(Path(str(entry["path"])), "visual review render evidence")
            digest = entry.get("sha256")
            if digest != sha256_file(render):
                raise ValueError("visual review render evidence hash is stale")
            rendered.append({"path": str(render), "sha256": str(digest)})
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        message = f"visual review is invalid: {error}"
        return {
            "status": "fail",
            "method": "verified_render_review_required",
            "failed_checks": [message],
        }, [message]
    return {
        "status": "pass",
        "method": "verified_render_review",
        "review_path": str(safe),
        "review_sha256": sha256_file(safe),
        "reviewer": reviewer.strip(),
        "page_coverage": coverage,
        "render_evidence": rendered,
        "failed_checks": [],
    }, []


def inspect_pdf(
    pdf_path: Path,
    *,
    aux_path: Path | None,
    log_paths: Sequence[Path],
    pdfinfo_path: Path | None = None,
    visual_review_path: Path | None = None,
) -> dict[str, object]:
    """Inspect a real compiled PDF and derive its body range from aux labels."""

    pdf = _regular_file(pdf_path, "compiled PDF")
    try:
        data = pdf.read_bytes()
    except OSError as error:
        raise ValueError(f"compiled PDF cannot be read: {pdf}") from error
    objects, structure_errors = _pdf_objects(data)
    fallback_pages, empty_pages, fallback_errors = _fallback_page_count(data, objects)

    pdfinfo = pdfinfo_path if pdfinfo_path is not None else _discovered_pdfinfo()
    tool = "conservative_pdf_parser"
    tool_error: str | None = None
    total_pages = fallback_pages
    if pdfinfo is not None:
        executable = _regular_file(Path(pdfinfo), "pdfinfo executable")
        if not os.access(executable, os.X_OK):
            raise ValueError("pdfinfo executable must be executable")
        reported, tool_error = _pdfinfo_count(pdf, executable)
        if reported is not None:
            total_pages = reported
            tool = "pdfinfo"
            if fallback_pages is not None and reported != fallback_pages:
                structure_errors.append("pdfinfo and PDF page tree disagree on total pages")

    effective_fallback_errors = (
        fallback_errors if total_pages is None or fallback_pages is not None else []
    )

    start, end, marker_errors = _aux_range(aux_path)
    reference_errors, logs = _reference_errors(log_paths)
    failed = [
        *structure_errors,
        *effective_fallback_errors,
        *marker_errors,
        *reference_errors,
    ]
    if tool_error is not None:
        failed.append(f"pdfinfo failed: {tool_error}")
    if empty_pages:
        failed.append(
            "compiled PDF contains empty or broken pages: "
            + ", ".join(str(page) for page in empty_pages)
        )

    visual_qa, visual_review_errors = _visual_review(
        visual_review_path,
        pdf_hash=sha256_file(pdf),
        total_pages=total_pages,
    )
    failed.extend(visual_review_errors)

    visual_errors = [
        *structure_errors,
        *effective_fallback_errors,
        *(
            [
                "compiled PDF contains empty or broken pages: "
                + ", ".join(str(page) for page in empty_pages)
            ]
            if empty_pages
            else []
        ),
    ]

    page_gate: dict[str, object] | None = None
    if total_pages is None:
        failed.append("compiled PDF total page count cannot be determined")
    if start is not None and end is not None and total_pages is not None:
        page_gate = evaluate_page_gate(
            total_pages=total_pages,
            body_pages=end - start + 1,
            body_start=start,
            body_end=end,
        )
        failed.extend(str(item) for item in page_gate["failed_checks"])

    if failed:
        status = "fail"
    elif page_gate is not None:
        status = str(page_gate["status"])
        if status == "pass" and fallback_pages is None:
            status = "needs_revision"
    else:
        status = "fail"

    body_pages = end - start + 1 if start is not None and end is not None else None
    return {
        "status": status,
        "pdf_path": str(pdf),
        "pdf_sha256": sha256_file(pdf),
        "total_pages": total_pages,
        "body_pages": body_pages,
        "body_range": (
            {"start": start, "end": end, "pages": body_pages}
            if start is not None and end is not None
            else None
        ),
        "body_range_source": "aux_labels" if start is not None and end is not None else None,
        "page_count_tool": tool,
        "failed_checks": failed,
        "actions": page_gate["actions"] if page_gate is not None else [],
        "empty_pages": empty_pages,
        "visual_qa": (
            {
                "status": "fail",
                "method": "compiled_structure_failed",
                "failed_checks": visual_errors,
            }
            if visual_errors
            else visual_qa
        ),
        "logs": logs,
        "compiled_pdf_authoritative": True,
        "no_padding": True,
    }


__all__ = ["evaluate_page_gate", "inspect_pdf"]
