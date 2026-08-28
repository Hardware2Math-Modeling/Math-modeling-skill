#!/usr/bin/env python3
"""Select, assemble, compile, and audit immutable LaTeX paper outputs."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import stat
import struct
import subprocess
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from handoff_schema import strict_json_tree_errors
from latex_qa import inspect_pdf
from manifest import relative_regular_files, safe_relative_path, sha256_file, utc_now
from paper_content import validate_paper_content
from project_state import load_current
from suite_validation import ensure_no_symlink_components


_COMPILER_PRIORITY = ("tectonic", "latexmk", "xelatex")
_COMPILER_TIMEOUT_SECONDS = 180
_RENDER_TIMEOUT_SECONDS = 180
_RENDER_DPI = 200
_ITERATION_RE = re.compile(r"^v[0-9]{3,}$")
_RENDER_ATTEMPT_RE = re.compile(r"^attempt-([0-9]{3,})$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_POPPLER_VERSION_RE = re.compile(
    r"^pdftoppm version [0-9]+(?:\.[0-9]+){1,3}(?:[-+._A-Za-z0-9]*)?$"
)
_RENDERER_TRUST_BASIS = "user_supplied_preflight_binary"
_UPSTREAM_STAGES = {
    "problem-analysis",
    "model-construction",
    "model-solving",
    "validation",
}
_BUILTIN_FALLBACK = (
    Path(__file__).resolve().parents[1]
    / "skills/math-modeling-paper-production/assets/fallback-zh"
)


def _absolute(path: Path, label: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise ValueError(f"{label} must be an absolute path without '..'")
    return ensure_no_symlink_components(candidate, label)


def _directory(path: Path, label: str) -> Path:
    safe = _absolute(path, label)
    try:
        mode = safe.lstat().st_mode
    except OSError as error:
        raise ValueError(f"{label} must be an existing directory: {safe}") from error
    if not stat.S_ISDIR(mode):
        raise ValueError(f"{label} must be a directory: {safe}")
    return safe


def _regular_file(path: Path, label: str) -> Path:
    safe = _absolute(path, label)
    try:
        mode = safe.lstat().st_mode
    except OSError as error:
        raise ValueError(f"{label} must be an existing regular file: {safe}") from error
    if not stat.S_ISREG(mode):
        raise ValueError(f"{label} must be a regular non-symlink file: {safe}")
    return safe


def _strict_json(path: Path, label: str) -> dict[str, object]:
    safe = _regular_file(path, label)

    def reject_constant(value: str) -> object:
        raise ValueError(f"non-finite JSON constant: {value}")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            safe.read_text(encoding="utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"{label} must contain strict JSON: {error}") from error
    if type(value) is not dict:
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _canonical_json_bytes(payload: object) -> bytes:
    errors = strict_json_tree_errors(payload)
    if errors:
        raise ValueError("paper manifest is not strict JSON:\n- " + "\n- ".join(errors))
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"
    return content.encode("utf-8")


def _write_new_json(path: Path, payload: object) -> None:
    _write_new_bytes(path, _canonical_json_bytes(payload), "paper manifest")


def _open_directory_fd(path: Path, label: str) -> int:
    candidate = Path(path)
    if not candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise ValueError(f"{label} must be an absolute path without '..'")
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open("/", flags)
    try:
        for part in candidate.parts[1:]:
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
    except OSError as error:
        os.close(descriptor)
        raise ValueError(f"{label} must be an existing non-symlink directory") from error
    return descriptor


def _mkdir_new(path: Path, label: str) -> Path:
    target = Path(path)
    if not target.is_absolute() or any(part == ".." for part in target.parts):
        raise ValueError(f"{label} must be an absolute path without '..'")
    parent_fd = _open_directory_fd(target.parent, f"{label} parent")
    try:
        os.mkdir(target.name, dir_fd=parent_fd)
    except FileExistsError as error:
        raise FileExistsError(f"{label} already exists: {target}") from error
    finally:
        os.close(parent_fd)
    descriptor = _open_directory_fd(target, label)
    os.close(descriptor)
    return target


def _write_new_bytes(path: Path, data: bytes, label: str) -> None:
    target = Path(path)
    if not target.is_absolute() or any(part == ".." for part in target.parts):
        raise ValueError(f"{label} must be an absolute path without '..'")
    parent_fd = _open_directory_fd(target.parent, f"{label} parent")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    temporary_name = f".{target.name}.{secrets.token_hex(12)}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=parent_fd)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write while publishing immutable artifact")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.link(
            temporary_name,
            target.name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
            follow_symlinks=False,
        )
        os.fsync(parent_fd)
    except FileExistsError as error:
        raise FileExistsError(f"{label} already exists: {target}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        os.close(parent_fd)


def _copy_new_file(source: Path, destination: Path, label: str) -> None:
    safe_source = _regular_file(source, f"{label} source")
    try:
        content = safe_source.read_bytes()
    except OSError as error:
        raise ValueError(f"{label} source cannot be read: {safe_source}") from error
    _write_new_bytes(destination, content, label)


def _ensure_subdirectory(root: Path, relative: Path, label: str) -> Path:
    root_path = Path(root)
    descriptor = _open_directory_fd(root_path, label)
    try:
        for part in relative.parts:
            try:
                os.mkdir(part, dir_fd=descriptor)
            except FileExistsError:
                pass
            flags = os.O_RDONLY
            if hasattr(os, "O_DIRECTORY"):
                flags |= os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
    except OSError as error:
        raise ValueError(f"{label} must remain a non-symlink directory tree") from error
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    return root_path / relative


def _template_files(path: Path, label: str) -> tuple[Path, list[Path], str]:
    safe = _absolute(path, label)
    try:
        mode = safe.lstat().st_mode
    except OSError as error:
        raise ValueError(f"{label} must be an existing template file or directory") from error
    if stat.S_ISREG(mode):
        return safe.parent, [Path(safe.name)], "file"
    if not stat.S_ISDIR(mode):
        raise ValueError(f"{label} must be a regular file or directory")
    files = list(relative_regular_files(safe))
    if not files:
        raise ValueError(f"{label} must contain regular files")
    return safe, files, "directory"


def _tree_hash(root: Path, files: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files, key=lambda item: item.as_posix()):
        name = relative.as_posix().encode("utf-8")
        file_digest = bytes.fromhex(sha256_file(root / relative))
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(file_digest)
    return digest.hexdigest()


def _template_metadata(root: Path, files: Sequence[Path]) -> dict[str, object]:
    manifest_name = Path("template-manifest.json")
    if manifest_name not in files:
        return {}
    return _strict_json(root / manifest_name, "template metadata")


def _template_entry(
    root: Path,
    files: Sequence[Path],
    metadata: dict[str, object],
) -> str:
    requested = metadata.get("main_entry")
    if requested is not None:
        relative = safe_relative_path(requested, "template main_entry")
        if relative not in files or relative.suffix.lower() != ".tex":
            raise ValueError("template main_entry must name a copied .tex file")
        return relative.as_posix()
    if Path("main.tex") in files:
        return "main.tex"
    tex_files = [relative for relative in files if relative.suffix.lower() == ".tex"]
    if len(tex_files) != 1:
        raise ValueError("template must contain main.tex or declare one .tex main_entry")
    return tex_files[0].as_posix()


def select_template(
    user_template: Path | None,
    fallback_dir: Path,
    official_template: Path | None = None,
    *,
    locally_verified_template: Path | None = None,
) -> dict[str, object]:
    """Choose and hash a template without copying or mutating any destination."""

    fallback_root, fallback_files, _ = _template_files(Path(fallback_dir), "fallback template")
    fallback_hash = _tree_hash(fallback_root, fallback_files)
    fallback_entry = _template_entry(
        fallback_root,
        fallback_files,
        _template_metadata(fallback_root, fallback_files),
    )
    fallback_main_hash = sha256_file(fallback_root / fallback_entry)

    def inspected(
        candidate: Path,
        *,
        role: str,
        require_verified: bool,
    ) -> tuple[Path, Path, list[Path], str, dict[str, object], str, bool] | None:
        try:
            root, files, source_kind = _template_files(candidate, f"{role} template")
            metadata = _template_metadata(root, files)
            digest = _tree_hash(root, files)
        except ValueError:
            if role == "user":
                raise
            return None
        fallback_identity = digest == fallback_hash or (
            len(files) == 1 and sha256_file(root / files[0]) == fallback_main_hash
        )
        if fallback_identity:
            if role not in ("user", "fallback"):
                return None
            return candidate, root, files, source_kind, metadata, digest, False
        if require_verified:
            required = ("source_url", "license", "verification_date", "sha256")
            verified = (
                metadata.get("status") == "verified"
                and all(
                    type(metadata.get(field)) is str
                    and bool(str(metadata[field]).strip())
                    for field in required
                )
                and _HASH_RE.fullmatch(str(metadata.get("sha256"))) is not None
            )
            if not verified:
                return None
        return candidate, root, files, source_kind, metadata, digest, True

    choice = None
    selected_role = "fallback"
    candidates = (
        (user_template, "user", False),
        (official_template, "explicit_official", True),
        (locally_verified_template, "locally_verified_official", True),
    )
    for candidate, role, require_verified in candidates:
        if candidate is None or not Path(candidate).exists():
            continue
        choice = inspected(Path(candidate), role=role, require_verified=require_verified)
        if choice is not None:
            selected_role = role
            break
    if choice is None:
        choice = inspected(Path(fallback_dir), role="fallback", require_verified=False)
        assert choice is not None
        selected_role = "fallback"

    selected, root, files, source_kind, metadata, selected_hash, distinct = choice
    if not distinct or selected_role == "fallback":
        status = "fallback_non_submission"
        eligible = False
        selected_role = "fallback"
    elif selected_role == "user":
        status = "user_provided"
        eligible = True
    else:
        status = "official_verified"
        eligible = True
    main_entry = _template_entry(root, files, metadata)
    engine = metadata.get("engine", "xelatex")
    if engine not in ("xelatex", "tectonic"):
        raise ValueError("template engine metadata must be exactly xelatex or tectonic")

    source = _absolute(selected, "selected template")
    return {
        "template_status": status,
        "source": str(source),
        "selection_tier": selected_role,
        "source_kind": source_kind,
        "sha256": selected_hash,
        "files": [
            {
                "path": relative.as_posix(),
                "sha256": sha256_file(root / relative),
            }
            for relative in sorted(files, key=lambda item: item.as_posix())
        ],
        "main_entry": main_entry,
        "engine": engine.strip(),
        "source_url": metadata.get("source_url"),
        "license": metadata.get("license"),
        "verification_date": metadata.get("verification_date"),
        "submission_ready_eligible": eligible,
    }


def _preflight_output_paths(paper: Path) -> None:
    for relative in (
        "template",
        "build",
        "logs",
        "paper_manifest.json",
        "paper_publication_receipt.json",
        "paper.pdf",
        "visual_review_request.json",
        "paper_finalization.json",
    ):
        target = paper / relative
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"paper production output already exists: {target}")


def _current_validation(iteration_root: Path) -> dict[str, object]:
    handoff = _strict_json(iteration_root / "state/handoff.json", "current handoff")
    state = handoff.get("state")
    if type(state) is not dict or state.get("validation_status") != "pass":
        raise ValueError("current validation status must be pass before paper production")
    invalidated = state.get("invalidated_stages")
    if type(invalidated) is not list or any(type(item) is not str for item in invalidated):
        raise ValueError("current handoff invalidated_stages must be an explicit string list")
    affected = sorted(_UPSTREAM_STAGES.intersection(invalidated))
    if affected:
        raise ValueError("current validation depends on invalidated stages: " + ", ".join(affected))
    return handoff


def _staleness_check(project: Path) -> None:
    path = project / "qa/staleness.json"
    if not path.exists() and not path.is_symlink():
        return
    report = _strict_json(path, "staleness report")
    if report.get("status") != "stale":
        return
    invalidated = report.get("invalidated")
    if type(invalidated) is dict and any(
        type(items) is list and any(item in ("validation", "paper") for item in items)
        for items in invalidated.values()
    ):
        raise ValueError("staleness report invalidates validation or paper evidence")


def _frozen_content(path: Path, iteration_root: Path) -> tuple[dict[str, object], str]:
    safe = _regular_file(path, "frozen paper content")
    if not safe.is_relative_to(iteration_root):
        raise ValueError("frozen paper content must belong to the active iteration")
    frozen = _strict_json(safe, "frozen paper content")
    if frozen.get("status") != "complete":
        raise ValueError("frozen paper content status must be complete")
    content = frozen.get("content")
    evidence = frozen.get("evidence")
    if type(content) is not dict or type(evidence) is not list:
        raise ValueError("frozen paper content must contain content and evidence")
    seen: set[str] = set()
    recorded: dict[str, str] = {}
    for index, entry in enumerate(evidence):
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise ValueError(f"frozen content evidence[{index}] is malformed")
        relative = safe_relative_path(entry.get("path"), f"frozen content evidence[{index}].path")
        key = relative.as_posix()
        if key in seen:
            raise ValueError(f"duplicate frozen content evidence path: {key}")
        seen.add(key)
        expected = entry.get("sha256")
        if type(expected) is not str or _HASH_RE.fullmatch(expected) is None:
            raise ValueError(f"frozen content evidence[{index}].sha256 is invalid")
        target = _regular_file(
            iteration_root / relative,
            f"frozen content evidence[{index}] artifact",
        )
        if not target.is_relative_to(iteration_root) or sha256_file(target) != expected:
            raise ValueError(f"frozen content evidence is stale: {key}")
        recorded[key] = expected
    expected_evidence: dict[str, str] = {}
    references: list[tuple[object, object]] = []
    for claim in content.get("claims", []):
        if type(claim) is dict:
            references.append((claim.get("source_path"), claim.get("source_hash")))
    for field in ("figure_references", "table_references"):
        for reference in content.get(field, []):
            if type(reference) is dict:
                references.append(
                    (reference.get("manifest_path"), reference.get("manifest_hash"))
                )
    for requirement in content.get("requirement_manifests", []):
        if type(requirement) is dict:
            references.append((requirement.get("path"), requirement.get("sha256")))
    for raw_path, raw_hash in references:
        relative = safe_relative_path(raw_path, "frozen content declared evidence path")
        if type(raw_hash) is not str or _HASH_RE.fullmatch(raw_hash) is None:
            raise ValueError("frozen content declared evidence hash is invalid")
        key = relative.as_posix()
        if key in expected_evidence and expected_evidence[key] != raw_hash:
            raise ValueError(f"frozen content declares conflicting evidence hashes: {key}")
        expected_evidence[key] = raw_hash
    if recorded != expected_evidence:
        raise ValueError("frozen content evidence list does not exactly match declared evidence")
    errors = validate_paper_content(content, evidence_root=iteration_root)
    if errors:
        raise ValueError("frozen paper content no longer validates:\n- " + "\n- ".join(errors))
    return content, sha256_file(safe)


def _registered_environment(
    path: Path,
    project: Path,
    handoff: dict[str, object],
    *,
    expected_hash: str | None = None,
) -> tuple[Path, dict[str, object], str]:
    safe = _regular_file(path, "environment manifest")
    if not safe.is_relative_to(project):
        raise ValueError("environment manifest must belong to the current project")
    report = _strict_json(safe, "environment manifest")
    environment_hash = sha256_file(safe)
    if expected_hash is not None and environment_hash != expected_hash:
        raise ValueError("environment manifest no longer matches the candidate hash")
    artifacts = handoff.get("artifacts")
    if type(artifacts) is not list:
        raise ValueError("current handoff must register environment evidence")
    expected_path = safe.relative_to(project).as_posix()
    registrations = [
        artifact
        for artifact in artifacts
        if type(artifact) is dict
        and artifact.get("path") == expected_path
        and artifact.get("kind") in ("environment", "preflight")
    ]
    if len(registrations) != 1 or registrations[0].get("sha256") != environment_hash:
        raise ValueError("environment manifest is not current registered handoff evidence")
    if report.get("project_root") != str(project):
        raise ValueError("environment manifest project_root does not match the current project")
    return safe, report, environment_hash


def _environment(
    path: Path,
    project: Path,
    handoff: dict[str, object],
    requested_compiler: Path | None,
) -> tuple[dict[str, object], list[dict[str, object]], str]:
    _, report, environment_hash = _registered_environment(path, project, handoff)
    latex = report.get("latex")
    if type(latex) is not dict or latex.get("status") != "pass":
        raise ValueError("environment manifest must report LaTeX status pass")
    tools = latex.get("tools")
    if type(tools) is not list:
        raise ValueError("environment manifest LaTeX tools must be a list")

    available: dict[str, dict[str, object]] = {}
    for index, tool in enumerate(tools):
        if type(tool) is not dict:
            raise ValueError(f"environment LaTeX tool {index} must be an object")
        name = tool.get("name")
        if name not in _COMPILER_PRIORITY or tool.get("status") not in ("available", "pass"):
            continue
        raw_path = tool.get("path")
        if type(raw_path) is not str:
            raise ValueError(f"available LaTeX tool {name} must have an absolute path")
        executable = _regular_file(Path(raw_path), f"environment LaTeX tool {name}")
        if not os.access(executable, os.X_OK):
            raise ValueError(f"environment LaTeX tool {name} is not executable")
        diagnosed_hash = tool.get("sha256")
        if (
            type(diagnosed_hash) is not str
            or _HASH_RE.fullmatch(diagnosed_hash) is None
            or sha256_file(executable) != diagnosed_hash
        ):
            raise ValueError(f"environment LaTeX tool {name} hash no longer matches diagnosis")
        normalized = dict(tool)
        normalized["path"] = str(executable)
        available[str(name)] = normalized
    ordered = [available[name] for name in _COMPILER_PRIORITY if name in available]
    if not ordered:
        raise ValueError("environment manifest contains no usable diagnosed compiler")

    if requested_compiler is not None:
        executable = _regular_file(requested_compiler, "explicit compiler")
        if not os.access(executable, os.X_OK):
            raise ValueError("explicit compiler must be executable")
        matches = [tool for tool in ordered if tool["path"] == str(executable)]
        if not matches:
            raise ValueError("explicit compiler does not match current preflight evidence")
        ordered = matches
    return report, ordered, environment_hash


def _copy_selected_template(selection: dict[str, object], destination: Path) -> None:
    source = _absolute(Path(str(selection["source"])), "selected template source")
    source_kind = selection["source_kind"]
    root = source.parent if source_kind == "file" else source
    _mkdir_new(destination, "copied template root")
    files = selection["files"]
    assert type(files) is list
    for entry in files:
        assert type(entry) is dict
        relative = safe_relative_path(entry["path"], "selected template file")
        source_file = _regular_file(root / relative, "selected template file")
        if sha256_file(source_file) != entry["sha256"]:
            raise ValueError(f"selected template changed before copy: {relative.as_posix()}")
        target = destination / relative
        _ensure_subdirectory(destination, relative.parent, "copied template directory")
        _copy_new_file(source_file, target, "copied template file")
    copied = [Path(str(entry["path"])) for entry in files]
    if _tree_hash(destination, copied) != selection["sha256"]:
        raise ValueError("copied template tree hash does not match the selected source")


def _latex_text(value: object) -> str:
    if type(value) is not str:
        return ""
    return value


def _frontmatter(content: dict[str, object]) -> str:
    abstract = content["abstract"]
    assert type(abstract) is dict
    paragraphs = [*abstract["intro_sentences"]]
    for question in abstract["question_paragraphs"]:
        paragraphs.append(
            " ".join(
                _latex_text(question[field])
                for field in ("leading_summary", "modeling_steps", "answer")
            )
        )
    keywords = "，".join(str(item) for item in content["keywords"])
    rendered = (
        "\\begin{abstract}\n"
        + "\n\n\\par\n".join(_latex_text(item) for item in paragraphs)
        + "\n\\end{abstract}\n"
        + f"\\noindent\\textbf{{关键词：}}{keywords}\n"
    )
    english = content.get("english_abstract")
    if english is not None:
        if type(english) is not dict:
            raise ValueError("authorized English abstract must be an object")
        english_keywords = ", ".join(str(item) for item in english["keywords"])
        rendered += (
            "\\section*{English Abstract}\n"
            + _latex_text(english["text"])
            + "\n\\noindent\\textbf{Keywords:} "
            + english_keywords
            + "\n"
        )
    return rendered


def _body(content: dict[str, object]) -> str:
    sections = content["sections"]
    assert type(sections) is dict
    lines: list[str] = []
    for number in range(1, 9):
        section = sections[str(number)]
        assert type(section) is dict
        lines.append(f"\\section{{{section['title']}}}")
        if number == 1:
            lines.append("\\phantomsection\\label{mm-body-start}")
            for subsection in section["subsections"].values():
                lines.append(f"\\subsection{{{subsection['title']}}}")
                lines.append(_latex_text(subsection["content"]))
        elif number == 4:
            lines.append(_latex_text(section["content"]))
            lines.append("\\begin{center}\\begin{tabular}{lll}\\toprule")
            lines.append("符号 & 说明 & 单位 \\\\ \\midrule")
            for symbol in content["symbols"]:
                lines.append(
                    f"{symbol['symbol']} & {symbol['description']} & {symbol['unit']} \\\\"
                )
            lines.append("\\bottomrule\\end{tabular}\\end{center}")
        elif number == 5:
            for question in section["questions"]:
                lines.append(f"\\subsection{{{question['title']}}}")
                for subsection in question["subsections"].values():
                    lines.append(f"\\subsubsection{{{subsection['title']}}}")
                    lines.append(_latex_text(subsection["content"]))
        else:
            lines.append(_latex_text(section["content"]))
    lines.append("\\phantomsection\\label{mm-body-end}")
    return "\n\n".join(lines) + "\n"


def _validate_template_integration(template: Path, main_entry: str) -> None:
    main = _regular_file(template / main_entry, "template main entry")
    try:
        text = main.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError("template main entry must be readable UTF-8") from error
    uncommented = "\n".join(line.split("%", 1)[0] for line in text.splitlines())
    slots = (
        "paper-frontmatter.tex",
        "paper-body.tex",
        "paper-appendices.tex",
    )
    positions: list[int] = []
    for slot in slots:
        pattern = re.compile(r"\\input\s*\{\s*" + re.escape(slot) + r"\s*\}")
        matches = list(pattern.finditer(uncommented))
        if len(matches) != 1:
            raise ValueError(
                f"template conflict: main entry must consume {slot} exactly once"
            )
        positions.append(matches[0].start())
    if positions != sorted(positions):
        raise ValueError(
            "template conflict: generated input slots must be frontmatter, body, appendix"
        )


def _appendices(content: dict[str, object]) -> str:
    lines = ["\\appendix", "\\section{参考文献}"]
    references = content["references"]
    if references:
        lines.append("\\begin{thebibliography}{99}")
        for reference in references:
            lines.append(
                f"\\bibitem{{{reference['citation_id']}}} {_latex_text(reference['entry'])}"
            )
        lines.append("\\end{thebibliography}")
    else:
        lines.append("本稿未使用外部参考文献。")
    lines.extend(["\\section{代码清单与关键代码}"])
    for item in content["code_appendix"]:
        lines.append(f"\\texttt{{{item['path']}}}: {_latex_text(item['description'])}\\par")
    lines.extend(["\\section{AI 使用说明与人工复核记录}"])
    for item in content["ai_use_disclosure"]:
        lines.append(
            f"{item['tool']}：{item['purpose']}；采用内容：{item['output_used']}。\\par"
        )
    for record in content["human_review_records"]:
        lines.append(
            f"复核 {record['review_id']}：{record['scope']}，状态 {record['status']}，"
            f"复核人 {record['reviewed_by']}。\\par"
        )
    lines.extend(["\\section{补充表格、推导和图表}"])
    for item in content["supplemental_appendix"]:
        lines.append(f"\\subsection{{{item['title']}}}")
        lines.append(_latex_text(item["content"]))
    return "\n\n".join(lines) + "\n"


def _write_assembly(template: Path, content: dict[str, object]) -> list[dict[str, str]]:
    rendered = {
        "paper-frontmatter.tex": _frontmatter(content),
        "paper-body.tex": _body(content),
        "paper-appendices.tex": _appendices(content),
    }
    entries: list[dict[str, str]] = []
    for name, value in rendered.items():
        path = template / name
        _write_new_bytes(path, value.encode("utf-8"), "generated assembly file")
        entries.append({"path": name, "sha256": sha256_file(path)})
    return entries


def _template_hashes(
    template: Path,
    selection: dict[str, object],
    assembly: Sequence[dict[str, str]],
) -> dict[str, str]:
    expected: dict[str, str] = {}
    selected_files = selection.get("files")
    if type(selected_files) is not list:
        raise ValueError("selected template file manifest is invalid")
    for entry in [*selected_files, *assembly]:
        if type(entry) is not dict:
            raise ValueError("template file manifest entry is invalid")
        relative = safe_relative_path(entry.get("path"), "template manifest path")
        digest = entry.get("sha256")
        if type(digest) is not str or _HASH_RE.fullmatch(digest) is None:
            raise ValueError("template manifest hash is invalid")
        if relative.as_posix() in expected:
            raise ValueError(f"duplicate template manifest path: {relative.as_posix()}")
        expected[relative.as_posix()] = digest
    observed_files = relative_regular_files(template)
    if {path.as_posix() for path in observed_files} != set(expected):
        raise ValueError("copied/assembled template tree has unexpected or missing files")
    observed = {
        relative.as_posix(): sha256_file(template / relative)
        for relative in observed_files
    }
    if observed != expected:
        raise ValueError("copied/assembled template tree hash verification failed")
    return expected


def _command(tool: dict[str, object], main: Path, output: Path) -> list[str]:
    executable = str(tool["path"])
    name = tool["name"]
    if name == "tectonic":
        return [executable, "--outdir", str(output), str(main)]
    if name == "latexmk":
        return [
            executable,
            "-xelatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            f"-outdir={output}",
            str(main),
        ]
    if name == "xelatex":
        return [
            executable,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            "-output-directory",
            str(output),
            str(main),
        ]
    raise ValueError(f"unsupported diagnosed compiler: {name}")


def _engine_tools(
    tools: Sequence[dict[str, object]], engine: object
) -> list[dict[str, object]]:
    compatible = {
        "xelatex": {"latexmk", "xelatex"},
        "tectonic": {"tectonic"},
    }
    if engine not in compatible:
        raise ValueError("template engine metadata must be exactly xelatex or tectonic")
    selected = [tool for tool in tools if tool.get("name") in compatible[str(engine)]]
    if not selected:
        raise ValueError(
            f"no diagnosed compiler is compatible with template engine {engine}"
        )
    return selected


def _project_relative(project: Path, path: Path) -> str:
    safe = _absolute(path, "paper artifact")
    if not safe.is_relative_to(project):
        raise ValueError("paper artifact escapes project root")
    return safe.relative_to(project).as_posix()


def _attempt_compilation(
    *,
    project: Path,
    template: Path,
    main_entry: str,
    tools: Sequence[dict[str, object]],
    build: Path,
    logs: Path,
) -> tuple[list[dict[str, object]], Path | None, Path | None, list[Path]]:
    attempts: list[dict[str, object]] = []
    all_logs: list[Path] = []
    candidate: Path | None = None
    aux: Path | None = None
    for index, tool in enumerate(tools, start=1):
        attempt_build = build / f"attempt-{index:02d}"
        _mkdir_new(attempt_build, "compiler attempt build directory")
        command = _command(tool, template / main_entry, attempt_build)
        stem = Path(main_entry).stem
        produced_pdf = attempt_build / f"{stem}.pdf"
        produced_aux = attempt_build / f"{stem}.aux"
        passes: list[dict[str, object]] = []
        previous_aux_hash: str | None = None
        converged = tool["name"] != "xelatex"
        candidate_error: str | None = None
        candidate_is_regular = False
        max_passes = 3 if tool["name"] == "xelatex" else 1

        for pass_number in range(1, max_passes + 1):
            log_path = logs / (
                f"attempt-{index:02d}-{tool['name']}-pass-{pass_number:02d}.log"
            )
            try:
                completed = subprocess.run(
                    command,
                    cwd=template,
                    check=False,
                    shell=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=_COMPILER_TIMEOUT_SECONDS,
                )
                exit_code: int | None = completed.returncode
                stdout = completed.stdout
                stderr = completed.stderr
                execution_error = None
            except (OSError, subprocess.TimeoutExpired) as error:
                exit_code = None
                stdout = getattr(error, "stdout", "") or ""
                stderr = getattr(error, "stderr", "") or ""
                execution_error = str(error)
            process_log = (
                json.dumps({"command": command}, ensure_ascii=False, allow_nan=False)
                + "\n\n[stdout]\n"
                + str(stdout)
                + "\n[stderr]\n"
                + str(stderr)
                + (
                    f"\n[execution_error]\n{execution_error}\n"
                    if execution_error
                    else ""
                )
            )
            _write_new_bytes(
                log_path,
                process_log.encode("utf-8"),
                "compiler process log",
            )
            all_logs.append(log_path)

            pass_record: dict[str, object] = {
                "pass": pass_number,
                "command": command,
                "exit_code": exit_code,
                "log_path": _project_relative(project, log_path),
                "log_sha256": sha256_file(log_path),
            }
            build_log = attempt_build / f"{stem}.log"
            if build_log.is_file() and not build_log.is_symlink():
                build_log_snapshot = logs / (
                    f"attempt-{index:02d}-{tool['name']}-pass-{pass_number:02d}-"
                    f"{stem}.log"
                )
                _copy_new_file(build_log, build_log_snapshot, "compiler build log snapshot")
                all_logs.append(build_log_snapshot)
                pass_record["build_log_path"] = _project_relative(
                    project, build_log_snapshot
                )
                pass_record["build_log_sha256"] = sha256_file(build_log_snapshot)

            candidate_error = None
            candidate_is_regular = False
            try:
                candidate_mode = produced_pdf.lstat().st_mode
            except FileNotFoundError:
                pass
            except OSError as error:
                candidate_error = f"compiler PDF cannot be inspected: {error}"
            else:
                if stat.S_ISLNK(candidate_mode):
                    candidate_error = "compiler PDF must not be a symlink"
                elif not stat.S_ISREG(candidate_mode):
                    candidate_error = "compiler PDF must be a regular file"
                else:
                    candidate_is_regular = True
            pass_record["candidate_error"] = candidate_error

            aux_hash: str | None = None
            if produced_aux.is_file() and not produced_aux.is_symlink():
                aux_hash = sha256_file(produced_aux)
                pass_record["aux_sha256"] = aux_hash
            passes.append(pass_record)

            if exit_code != 0 or not candidate_is_regular:
                break
            if tool["name"] != "xelatex":
                break
            if pass_number >= 2 and aux_hash is not None and aux_hash == previous_aux_hash:
                converged = True
                break
            previous_aux_hash = aux_hash

        final_pass = passes[-1]
        exit_code = final_pass["exit_code"]
        if (
            tool["name"] == "xelatex"
            and exit_code == 0
            and candidate_is_regular
            and not converged
        ):
            candidate_error = "direct XeLaTeX auxiliary files did not converge after 3 passes"
        attempt = {
            "tool": tool["name"],
            "path": tool["path"],
            "compiler_sha256": sha256_file(Path(str(tool["path"]))),
            "version": tool.get("version"),
            "command": final_pass["command"],
            "exit_code": exit_code,
            "log_path": final_pass["log_path"],
            "log_sha256": final_pass["log_sha256"],
            "candidate_pdf": (
                _project_relative(project, produced_pdf) if candidate_is_regular else None
            ),
            "candidate_pdf_sha256": (
                sha256_file(produced_pdf) if candidate_is_regular else None
            ),
            "candidate_error": candidate_error,
            "passes": passes,
        }
        if final_pass.get("build_log_path") is not None:
            attempt["build_log_path"] = final_pass["build_log_path"]
            attempt["build_log_sha256"] = final_pass["build_log_sha256"]
        attempts.append(attempt)
        if exit_code == 0 and candidate_is_regular and converged:
            candidate = produced_pdf
            aux = (
                produced_aux
                if produced_aux.is_file() and not produced_aux.is_symlink()
                else None
            )
            break
    return attempts, candidate, aux, all_logs


def _project_evidence_file(project: Path, value: object, label: str) -> Path:
    relative = safe_relative_path(value, label)
    target = _regular_file(project / relative, label)
    if not target.is_relative_to(project):
        raise ValueError(f"{label} escapes project root")
    return target


def _exact_keys(value: object, required: set[str], label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != required:
        raise ValueError(f"{label} fields are not exact")
    return value


def _utc_timestamp(value: object, label: str) -> str:
    if type(value) is not str or not value.endswith("Z"):
        raise ValueError(f"{label} must be a UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"{label} must be a real UTC timestamp") from error
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{label} must be UTC")
    return value


def _publication_transaction_id(manifest_bytes: bytes, request_bytes: bytes) -> str:
    digest = hashlib.sha256()
    for content in (manifest_bytes, request_bytes):
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _publication_output_record(
    *,
    path: str,
    payload: dict[str, object],
    created_at: str,
) -> tuple[dict[str, object], bytes]:
    content = _canonical_json_bytes(payload)
    return (
        {
            "path": path,
            "created_at": created_at,
            "payload": payload,
            "canonical_bytes_base64": base64.b64encode(content).decode("ascii"),
            "sha256": hashlib.sha256(content).hexdigest(),
            "byte_size": len(content),
        },
        content,
    )


def _publication_receipt(
    *,
    iteration: str,
    created_at: str,
    manifest_path: str,
    manifest: dict[str, object],
    request_path: str,
    request: dict[str, object],
) -> tuple[dict[str, object], bytes, bytes]:
    manifest_record, manifest_bytes = _publication_output_record(
        path=manifest_path,
        payload=manifest,
        created_at=created_at,
    )
    request_record, request_bytes = _publication_output_record(
        path=request_path,
        payload=request,
        created_at=created_at,
    )
    receipt = {
        "schema_version": "1",
        "manifest_type": "paper_publication_transaction",
        "iteration": iteration,
        "created_at": created_at,
        "transaction_created_at": created_at,
        "transaction_id": _publication_transaction_id(manifest_bytes, request_bytes),
        "outputs": {
            "paper_manifest": manifest_record,
            "visual_review_request": request_record,
        },
    }
    return receipt, manifest_bytes, request_bytes


def _load_publication_receipt(
    project: Path,
    paper: Path,
    iteration: str,
    *,
    require_public: bool,
) -> tuple[
    Path,
    dict[str, object],
    dict[str, tuple[Path, dict[str, object], bytes]],
]:
    receipt_path = _regular_file(
        paper / "paper_publication_receipt.json", "paper publication receipt"
    )
    try:
        receipt_bytes = receipt_path.read_bytes()
    except OSError as error:
        raise ValueError("paper publication receipt cannot be read") from error
    receipt = _strict_json(receipt_path, "paper publication receipt")
    if receipt_bytes != _canonical_json_bytes(receipt):
        raise ValueError("paper publication receipt bytes are not canonical")
    _exact_keys(
        receipt,
        {
            "schema_version",
            "manifest_type",
            "iteration",
            "created_at",
            "transaction_created_at",
            "transaction_id",
            "outputs",
        },
        "paper publication receipt",
    )
    created_at = _utc_timestamp(receipt.get("created_at"), "publication created_at")
    if (
        receipt.get("schema_version") != "1"
        or receipt.get("manifest_type") != "paper_publication_transaction"
        or receipt.get("iteration") != iteration
        or receipt.get("transaction_created_at") != created_at
    ):
        raise ValueError("paper publication receipt identity/timestamp is invalid")
    outputs = _exact_keys(
        receipt.get("outputs"),
        {"paper_manifest", "visual_review_request"},
        "paper publication receipt outputs",
    )
    expected = {
        "paper_manifest": (
            paper / "paper_manifest.json",
            f"iterations/{iteration}/paper/paper_manifest.json",
        ),
        "visual_review_request": (
            paper / "visual_review_request.json",
            f"iterations/{iteration}/paper/visual_review_request.json",
        ),
    }
    records: dict[str, tuple[Path, dict[str, object], bytes]] = {}
    for name, (target, relative) in expected.items():
        record = _exact_keys(
            outputs.get(name),
            {
                "path",
                "created_at",
                "payload",
                "canonical_bytes_base64",
                "sha256",
                "byte_size",
            },
            f"publication receipt {name} record",
        )
        payload = record.get("payload")
        encoded = record.get("canonical_bytes_base64")
        if type(payload) is not dict or type(encoded) is not str:
            raise ValueError(f"publication receipt {name} payload/bytes are invalid")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError(f"publication receipt {name} bytes are not valid base64") from error
        if (
            record.get("path") != relative
            or record.get("created_at") != created_at
            or payload.get("created_at") != created_at
            or content != _canonical_json_bytes(payload)
            or record.get("sha256") != hashlib.sha256(content).hexdigest()
            or record.get("byte_size") != len(content)
        ):
            raise ValueError(f"publication receipt {name} record is mismatched or tampered")
        if require_public:
            public = _regular_file(target, f"published {name}")
            try:
                public_bytes = public.read_bytes()
            except OSError as error:
                raise ValueError(f"published {name} cannot be read") from error
            if public_bytes != content:
                raise ValueError(f"published {name} bytes differ from the transaction receipt")
        records[name] = (target, payload, content)
    manifest_bytes = records["paper_manifest"][2]
    request_bytes = records["visual_review_request"][2]
    transaction_id = receipt.get("transaction_id")
    if (
        type(transaction_id) is not str
        or transaction_id != _publication_transaction_id(manifest_bytes, request_bytes)
    ):
        raise ValueError("paper publication transaction id is mismatched or tampered")
    return receipt_path, receipt, records


def _renderer_probe_output(completed: subprocess.CompletedProcess[str]) -> str:
    return completed.stdout + completed.stderr


def _poppler_signature(output: str) -> str | None:
    lines = output.splitlines()
    if not lines or _POPPLER_VERSION_RE.fullmatch(lines[0]) is None:
        return None
    return lines[0]


def _candidate_renderer_evidence(
    project: Path,
    iteration: str,
    candidate: dict[str, object],
    requested: Path,
) -> tuple[Path, str, dict[str, object], Path]:
    handoff = _current_validation(
        _directory(project / "iterations" / iteration, "active iteration")
    )
    environment = _exact_keys(
        candidate.get("environment"), {"path", "sha256"}, "candidate environment record"
    )
    expected_hash = environment.get("sha256")
    if type(expected_hash) is not str or _HASH_RE.fullmatch(expected_hash) is None:
        raise ValueError("candidate environment hash is invalid")
    environment_path = _project_evidence_file(
        project, environment.get("path"), "candidate environment manifest"
    )
    _, report, environment_hash = _registered_environment(
        environment_path,
        project,
        handoff,
        expected_hash=expected_hash,
    )
    renderer = _exact_keys(
        report.get("pdf_renderer"),
        {
            "name",
            "status",
            "path",
            "sha256",
            "version_command",
            "version_exit_code",
            "version_signature",
            "version_output",
            "version_output_sha256",
            "trust_basis",
        },
        "preflight PDF renderer record",
    )
    raw_path = renderer.get("path")
    if type(raw_path) is not str or not Path(raw_path).is_absolute():
        raise ValueError("preflight PDF renderer path must be exact and absolute")
    executable = _regular_file(Path(raw_path), "preflight PDF renderer executable")
    requested_executable = _regular_file(Path(requested), "explicit PDF renderer executable")
    output = renderer.get("version_output")
    signature = renderer.get("version_signature")
    version_command = renderer.get("version_command")
    executable_hash = renderer.get("sha256")
    output_hash = renderer.get("version_output_sha256")
    if (
        renderer.get("name") != "pdftoppm"
        or renderer.get("status") != "available"
        or executable.name != "pdftoppm"
        or str(requested_executable) != str(executable)
        or not os.access(executable, os.X_OK)
        or type(executable_hash) is not str
        or _HASH_RE.fullmatch(executable_hash) is None
        or sha256_file(executable) != executable_hash
        or version_command != [str(executable), "-v"]
        or renderer.get("version_exit_code") != 0
        or type(output) is not str
        or not output
        or type(signature) is not str
        or signature != _poppler_signature(output)
        or type(output_hash) is not str
        or output_hash != hashlib.sha256(output.encode("utf-8")).hexdigest()
        or renderer.get("trust_basis") != _RENDERER_TRUST_BASIS
    ):
        raise ValueError("explicit renderer does not match current preflight Poppler evidence")
    return environment_path, environment_hash, dict(renderer), executable


def _run_renderer_version(executable: Path) -> subprocess.CompletedProcess[str]:
    command = [str(executable), "-v"]
    try:
        return subprocess.run(
            command,
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_RENDER_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"registered PDF renderer version probe failed: {error}") from error


def _validate_renderer_version(
    completed: subprocess.CompletedProcess[str],
    executable: Path,
    evidence: dict[str, object],
) -> None:
    command = [str(executable), "-v"]
    output = _renderer_probe_output(completed)
    if (
        completed.returncode != 0
        or evidence.get("version_command") != command
        or evidence.get("version_exit_code") != completed.returncode
        or evidence.get("version_output") != output
        or evidence.get("version_signature") != _poppler_signature(output)
        or evidence.get("version_output_sha256")
        != hashlib.sha256(output.encode("utf-8")).hexdigest()
    ):
        raise ValueError("renderer version probe no longer matches current preflight evidence")


def _probe_registered_renderer(
    executable: Path,
    evidence: dict[str, object],
) -> subprocess.CompletedProcess[str]:
    completed = _run_renderer_version(executable)
    _validate_renderer_version(completed, executable, evidence)
    return completed


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    distances = (
        (abs(estimate - left), left),
        (abs(estimate - above), above),
        (abs(estimate - upper_left), upper_left),
    )
    return min(distances, key=lambda item: item[0])[1]


def _render_png(path: Path) -> tuple[int, int]:
    data = _regular_file(path, "rendered page PNG").read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("rendered page PNG signature is invalid")
    offset = 8
    width: int | None = None
    height: int | None = None
    channels: int | None = None
    compressed = bytearray()
    saw_end = False
    while offset < len(data):
        if len(data) - offset < 12:
            raise ValueError("rendered page PNG chunk header is truncated")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("rendered page PNG chunk is truncated")
        payload = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length : end])[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != expected_crc:
            raise ValueError("rendered page PNG chunk CRC is invalid")
        if kind == b"IHDR":
            if width is not None or length != 13:
                raise ValueError("rendered page PNG IHDR is invalid")
            width, height, bit_depth, color_type, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", payload)
            )
            if width <= 0 or height <= 0:
                raise ValueError("rendered page PNG dimensions must be positive")
            channel_map = {0: 1, 2: 3, 4: 2, 6: 4}
            channels = channel_map.get(color_type)
            if (
                bit_depth != 8
                or channels is None
                or compression != 0
                or filtering != 0
                or interlace != 0
            ):
                raise ValueError("rendered page PNG encoding is unsupported for audit")
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            if length != 0 or end != len(data):
                raise ValueError("rendered page PNG IEND/trailing bytes are invalid")
            saw_end = True
            break
        offset = end
    if width is None or height is None or channels is None or not compressed or not saw_end:
        raise ValueError("rendered page PNG is incomplete")
    try:
        raw = zlib.decompress(bytes(compressed))
    except zlib.error as error:
        raise ValueError("rendered page PNG pixels cannot be decompressed") from error
    stride = width * channels
    if len(raw) != height * (stride + 1):
        raise ValueError("rendered page PNG pixel length is inconsistent")
    previous = bytearray(stride)
    rows: list[bytearray] = []
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        encoded = raw[cursor : cursor + stride]
        cursor += stride
        reconstructed = bytearray(stride)
        for index, byte in enumerate(encoded):
            left = reconstructed[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                predictor = _paeth(left, above, upper_left)
            else:
                raise ValueError("rendered page PNG uses an invalid row filter")
            reconstructed[index] = (byte + predictor) & 0xFF
        rows.append(reconstructed)
        previous = reconstructed
    visible = False
    for row in rows:
        for offset in range(0, len(row), channels):
            pixel = row[offset : offset + channels]
            if channels == 1:
                colors, alpha = pixel, 255
            elif channels == 2:
                colors, alpha = pixel[:1], pixel[1]
            elif channels == 3:
                colors, alpha = pixel, 255
            else:
                colors, alpha = pixel[:3], pixel[3]
            if alpha > 0 and any(channel < 250 for channel in colors):
                visible = True
                break
        if visible:
            break
    if not visible:
        raise ValueError("rendered page PNG appears blank or fully transparent")
    return width, height


def _load_render_attempts(
    project: Path,
    paper: Path,
    iteration: str,
) -> list[tuple[int, Path, Path, dict[str, object]]]:
    root = paper / "render-attempts"
    if not root.exists() and not root.is_symlink():
        return []
    root = _directory(root, "render attempts root")
    numbered: list[tuple[int, Path, Path, dict[str, object]]] = []
    for entry in root.iterdir():
        match = _RENDER_ATTEMPT_RE.fullmatch(entry.name)
        if match is None:
            raise ValueError("render attempts root contains an unexpected entry")
        number = int(match.group(1))
        if number < 1 or entry.name != f"attempt-{number:03d}":
            raise ValueError("render attempt directory name is not canonical")
        attempt = _directory(entry, f"render attempt {entry.name}")
        record_path = _regular_file(attempt / "attempt.json", "prior render attempt record")
        try:
            record_bytes = record_path.read_bytes()
        except OSError as error:
            raise ValueError("prior render attempt record cannot be read") from error
        record = _strict_json(record_path, "prior render attempt record")
        if record_bytes != _canonical_json_bytes(record):
            raise ValueError("prior render attempt record is not canonical")
        _exact_keys(
            record,
            {
                "schema_version",
                "manifest_type",
                "iteration",
                "attempt_id",
                "created_at",
                "status",
                "error",
                "environment",
                "renderer",
                "candidate",
                "version_command",
                "render_command",
                "exit_code",
                "log",
                "pages",
            },
            "prior render attempt record",
        )
        _utc_timestamp(record.get("created_at"), "prior render attempt created_at")
        if (
            record.get("schema_version") != "1"
            or record.get("manifest_type") != "paper_render_attempt"
            or record.get("iteration") != iteration
            or record.get("attempt_id") != entry.name
        ):
            raise ValueError("prior render attempt identity is mismatched or tampered")
        numbered.append((number, attempt, record_path, record))
    numbered.sort(key=lambda item: item[0])
    if [number for number, *_ in numbered] != list(range(1, len(numbered) + 1)):
        raise ValueError("render attempt sequence has a gap or duplicate")
    return numbered


def _render_attempt_log(
    project: Path,
    iteration: str,
    attempt: Path,
    record: dict[str, object],
) -> tuple[Path, str, str]:
    attempt_id = record.get("attempt_id")
    log = _exact_keys(
        record.get("log"), {"path", "sha256"}, "prior render attempt log"
    )
    expected_log = f"iterations/{iteration}/paper/render-attempts/{attempt_id}/render.log"
    log_path = _project_evidence_file(project, log.get("path"), "prior render attempt log")
    if log_path != attempt / "render.log" or log.get("path") != expected_log:
        raise ValueError("prior render attempt log path is not canonical")
    log_hash = sha256_file(log_path)
    if log.get("sha256") != log_hash:
        raise ValueError("prior render attempt log hash is stale or tampered")
    try:
        log_text = log_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError("prior render attempt log is not readable UTF-8") from error
    header = (
        f"attempt_id: {attempt_id}\n"
        f"created_at: {record.get('created_at')}\n"
        "version_command: "
        + json.dumps(record.get("version_command"))
        + "\n"
    )
    status = record.get("status")
    error = record.get("error")
    trailer = f"attempt_status: {status}\nerror: {error or ''}\n"
    exit_code = record.get("exit_code")
    if type(exit_code) is int:
        render_exit_code = str(exit_code)
    elif exit_code is None:
        render_exit_code = "not_started"
    else:
        raise ValueError("prior render attempt exit code is invalid")
    render_command_record = (
        "render_command: "
        + json.dumps(record.get("render_command"))
        + "\nrender_exit_code: "
        + render_exit_code
        + "\n"
    )
    if (
        not log_text.startswith(header)
        or render_command_record not in log_text
        or not log_text.endswith(trailer)
    ):
        raise ValueError("prior render attempt log identity/status is mismatched or tampered")
    return log_path, log_text, log_hash


def _validate_failed_render_attempt(
    project: Path,
    iteration: str,
    attempt: Path,
    record: dict[str, object],
) -> None:
    if (
        record.get("status") != "failed"
        or type(record.get("error")) is not str
        or not record["error"]
        or record.get("pages") != []
    ):
        raise ValueError("prior render attempt is incomplete, successful, or tampered")
    _render_attempt_log(project, iteration, attempt, record)


def _new_render_attempt(
    project: Path,
    paper: Path,
    iteration: str,
) -> tuple[str, Path]:
    root = paper / "render-attempts"
    if not root.exists() and not root.is_symlink():
        _mkdir_new(root, "render attempts root")
    root = _directory(root, "render attempts root")
    numbered = _load_render_attempts(project, paper, iteration)
    for _, attempt, _, record in numbered:
        _validate_failed_render_attempt(project, iteration, attempt, record)
    next_number = len(numbered) + 1
    attempt_id = f"attempt-{next_number:03d}"
    attempt = root / attempt_id
    _mkdir_new(attempt, "render attempt directory")
    return attempt_id, attempt


def _bound_render_attempt_command(
    *,
    attempt: Path,
    record: dict[str, object],
    expected_environment: dict[str, str],
    expected_candidate: dict[str, str],
    renderer_evidence: dict[str, object],
    executable: Path,
    pdf: Path,
) -> list[str]:
    if set(path.name for path in attempt.iterdir()) != {
        "pages",
        "render.log",
        "attempt.json",
    }:
        raise ValueError("render attempt contains unexpected top-level entries")
    candidate_record = _exact_keys(
        record.get("candidate"),
        {"manifest_sha256", "request_sha256", "pdf_sha256"},
        "render attempt candidate",
    )
    expected_command = [
        str(executable),
        "-r",
        str(_RENDER_DPI),
        "-png",
        str(pdf),
        str(attempt / "pages/page"),
    ]
    if (
        record.get("environment") != expected_environment
        or record.get("renderer") != renderer_evidence
        or candidate_record != expected_candidate
        or record.get("version_command") != [str(executable), "-v"]
        or record.get("render_command") != expected_command
    ):
        raise ValueError("render attempt binding is stale or tampered")
    return expected_command


def _recover_render_manifest(
    *,
    project: Path,
    paper: Path,
    iteration: str,
    render_manifest_path: Path,
    manifest_path: Path,
    candidate: dict[str, object],
    request_path: Path,
    environment_path: Path,
    environment_hash: str,
    renderer_evidence: dict[str, object],
    executable: Path,
    pdf: Path,
    immutable_hashes: dict[str, str],
) -> dict[str, object] | None:
    attempts = _load_render_attempts(project, paper, iteration)
    pass_indexes = [
        index
        for index, (_, _, _, record) in enumerate(attempts)
        if record.get("status") == "pass"
    ]
    if not pass_indexes:
        return None
    if len(pass_indexes) != 1 or pass_indexes[0] != len(attempts) - 1:
        raise ValueError("render recovery requires exactly one final successful attempt")
    expected_environment = {
        "path": environment_path.relative_to(project).as_posix(),
        "sha256": environment_hash,
    }
    expected_candidate = {
        "manifest_sha256": immutable_hashes["manifest"],
        "request_sha256": immutable_hashes["request"],
        "pdf_sha256": immutable_hashes["pdf"],
    }
    for _, prior_attempt, _, prior_record in attempts[:-1]:
        _bound_render_attempt_command(
            attempt=prior_attempt,
            record=prior_record,
            expected_environment=expected_environment,
            expected_candidate=expected_candidate,
            renderer_evidence=renderer_evidence,
            executable=executable,
            pdf=pdf,
        )
        _validate_failed_render_attempt(project, iteration, prior_attempt, prior_record)

    _, attempt, attempt_path, record = attempts[-1]
    expected_command = _bound_render_attempt_command(
        attempt=attempt,
        record=record,
        expected_environment=expected_environment,
        expected_candidate=expected_candidate,
        renderer_evidence=renderer_evidence,
        executable=executable,
        pdf=pdf,
    )
    if (
        record.get("status") != "pass"
        or record.get("error") is not None
        or record.get("exit_code") != 0
    ):
        raise ValueError("successful render attempt evidence is stale or tampered")
    log_path, log_text, log_hash = _render_attempt_log(
        project, iteration, attempt, record
    )
    version_output = renderer_evidence.get("version_output")
    if type(version_output) is not str:
        raise ValueError("successful render attempt version evidence is invalid")
    expected_log_prefix = (
        f"attempt_id: {record['attempt_id']}\n"
        f"created_at: {record['created_at']}\n"
        + "version_command: "
        + json.dumps([str(executable), "-v"])
        + "\nversion_exit_code: 0\n"
        + version_output
        + "render_command: "
        + json.dumps(expected_command)
        + "\nrender_exit_code: 0\n"
    )
    if not log_text.startswith(expected_log_prefix):
        raise ValueError("successful render attempt log/version evidence is mismatched")

    page_qa = candidate.get("page_qa")
    pdf_record = candidate.get("pdf")
    if (
        type(page_qa) is not dict
        or type(page_qa.get("total_pages")) is not int
        or type(pdf_record) is not dict
    ):
        raise ValueError("candidate page count is invalid for render recovery")
    total_pages = page_qa["total_pages"]
    pages_dir = _directory(attempt / "pages", "successful render attempt pages")
    pages = record.get("pages")
    if type(pages) is not list or len(pages) != total_pages:
        raise ValueError("successful render attempt page evidence is incomplete")
    normalized_pages: list[dict[str, object]] = []
    observed_pages: list[int] = []
    observed_paths: set[str] = set()
    observed_path_order: list[str] = []
    for index, entry in enumerate(pages):
        page = _exact_keys(
            entry,
            {"page", "path", "sha256", "width_px", "height_px"},
            f"successful render page {index}",
        )
        page_number = page.get("page")
        if type(page_number) is not int:
            raise ValueError("successful render page number must be an integer")
        image = _project_evidence_file(project, page.get("path"), "rendered page PNG")
        relative_image = image.relative_to(project).as_posix()
        if (
            image.parent != pages_dir
            or image.suffix.lower() != ".png"
            or relative_image in observed_paths
        ):
            raise ValueError("successful render page path is not unique/canonical")
        observed_paths.add(relative_image)
        observed_path_order.append(relative_image)
        if page.get("sha256") != sha256_file(image):
            raise ValueError("successful render page hash is stale or tampered")
        width, height = _render_png(image)
        if page.get("width_px") != width or page.get("height_px") != height:
            raise ValueError("successful render page dimensions are mismatched")
        observed_pages.append(page_number)
        normalized_pages.append(dict(page))
    directory_png_paths = sorted(
        _regular_file(path, "successful render attempt PNG")
        .relative_to(project)
        .as_posix()
        for path in pages_dir.iterdir()
        if path.suffix.lower() == ".png"
    )
    if (
        observed_pages != list(range(1, total_pages + 1))
        or observed_path_order != sorted(observed_path_order)
        or directory_png_paths != observed_path_order
    ):
        raise ValueError("successful render page coverage is not exact and consecutive")

    payload = {
        "schema_version": "1",
        "manifest_type": "paper_render",
        "iteration": iteration,
        "attempt": {
            "id": record["attempt_id"],
            "path": attempt.relative_to(project).as_posix(),
            "record_path": attempt_path.relative_to(project).as_posix(),
            "record_sha256": sha256_file(attempt_path),
        },
        "generator": {
            "name": "paper_production",
            "version": "1",
            "method": "controlled_renderer",
            "command": expected_command,
            "exit_code": 0,
            "log_path": log_path.relative_to(project).as_posix(),
            "log_sha256": log_hash,
        },
        "environment": expected_environment,
        "renderer": renderer_evidence,
        "pdf_path": pdf_record["path"],
        "pdf_sha256": pdf_record["sha256"],
        "candidate_manifest_path": manifest_path.relative_to(project).as_posix(),
        "candidate_manifest_sha256": immutable_hashes["manifest"],
        "review_request_path": request_path.relative_to(project).as_posix(),
        "review_request_sha256": immutable_hashes["request"],
        "total_pages": total_pages,
        "pages": normalized_pages,
    }
    _write_new_json(render_manifest_path, payload)
    return payload


def render_paper_pages(
    project_root: Path,
    iteration: str,
    *,
    renderer: Path,
) -> dict[str, object]:
    """Render once, or recover one exact unpublished success without rerendering."""

    project = _directory(project_root, "project root")
    if type(iteration) is not str or _ITERATION_RE.fullmatch(iteration) is None:
        raise ValueError("iteration must use canonical vNNN form")
    manifest_path, candidate, request_path, _ = _validate_candidate_for_finalization(
        project, iteration
    )
    paper = _directory(project / f"iterations/{iteration}/paper", "active paper directory")
    render_manifest_path = paper / "paper_render_manifest.json"
    if render_manifest_path.exists() or render_manifest_path.is_symlink():
        raise FileExistsError(f"render manifest already exists: {render_manifest_path}")
    environment_path, environment_hash, renderer_evidence, executable = (
        _candidate_renderer_evidence(project, iteration, candidate, Path(renderer))
    )
    pdf_record = candidate["pdf"]
    page_qa = candidate["page_qa"]
    assert type(pdf_record) is dict and type(page_qa) is dict
    pdf = _project_evidence_file(project, pdf_record["path"], "candidate PDF")
    before = {
        "manifest": sha256_file(manifest_path),
        "request": sha256_file(request_path),
        "pdf": sha256_file(pdf),
    }
    recovered = _recover_render_manifest(
        project=project,
        paper=paper,
        iteration=iteration,
        render_manifest_path=render_manifest_path,
        manifest_path=manifest_path,
        candidate=candidate,
        request_path=request_path,
        environment_path=environment_path,
        environment_hash=environment_hash,
        renderer_evidence=renderer_evidence,
        executable=executable,
        pdf=pdf,
        immutable_hashes=before,
    )
    if recovered is not None:
        return recovered
    attempt_id, attempt = _new_render_attempt(project, paper, iteration)
    pages_dir = attempt / "pages"
    _mkdir_new(pages_dir, "render attempt pages directory")
    output_prefix = pages_dir / "page"
    command = [
        str(executable),
        "-r",
        str(_RENDER_DPI),
        "-png",
        str(pdf),
        str(output_prefix),
    ]
    created_at = utc_now()
    log_path = attempt / "render.log"
    attempt_path = attempt / "attempt.json"
    version: subprocess.CompletedProcess[str] | None = None
    completed: subprocess.CompletedProcess[str] | None = None

    def immutable_hashes() -> dict[str, str]:
        return {
            "manifest": sha256_file(manifest_path),
            "request": sha256_file(request_path),
            "pdf": sha256_file(pdf),
        }

    def finish_attempt(
        status: str,
        error: str | None,
        pages: list[dict[str, object]],
    ) -> dict[str, object]:
        version_stdout = version.stdout if version is not None else ""
        version_stderr = version.stderr if version is not None else ""
        render_stdout = completed.stdout if completed is not None else ""
        render_stderr = completed.stderr if completed is not None else ""
        log_text = (
            "attempt_id: " + attempt_id + "\n"
            + "created_at: " + created_at + "\n"
            + "version_command: " + json.dumps([str(executable), "-v"]) + "\n"
            + "version_exit_code: "
            + (str(version.returncode) if version is not None else "not_started")
            + "\n"
            + version_stdout
            + version_stderr
            + "render_command: " + json.dumps(command) + "\n"
            + "render_exit_code: "
            + (str(completed.returncode) if completed is not None else "not_started")
            + "\n"
            + render_stdout
            + render_stderr
            + "attempt_status: " + status + "\n"
            + "error: " + (error or "") + "\n"
        )
        _write_new_bytes(log_path, log_text.encode("utf-8"), "render attempt log")
        record = {
            "schema_version": "1",
            "manifest_type": "paper_render_attempt",
            "iteration": iteration,
            "attempt_id": attempt_id,
            "created_at": created_at,
            "status": status,
            "error": error,
            "environment": {
                "path": environment_path.relative_to(project).as_posix(),
                "sha256": environment_hash,
            },
            "renderer": renderer_evidence,
            "candidate": {
                "manifest_sha256": before["manifest"],
                "request_sha256": before["request"],
                "pdf_sha256": before["pdf"],
            },
            "version_command": [str(executable), "-v"],
            "render_command": command,
            "exit_code": completed.returncode if completed is not None else None,
            "log": {
                "path": log_path.relative_to(project).as_posix(),
                "sha256": sha256_file(log_path),
            },
            "pages": pages,
        }
        _write_new_json(attempt_path, record)
        return record

    try:
        version = _run_renderer_version(executable)
        _validate_renderer_version(version, executable, renderer_evidence)
        _candidate_renderer_evidence(project, iteration, candidate, executable)
        if immutable_hashes() != before:
            raise ValueError(
                "candidate manifest, request, or PDF changed during version probe"
            )
        _candidate_renderer_evidence(project, iteration, candidate, executable)
    except ValueError as error:
        finish_attempt("failed", str(error), [])
        raise

    try:
        completed = subprocess.run(
            command,
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_RENDER_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        failure = ValueError(f"controlled PDF renderer failed: {error}")
        finish_attempt("failed", str(failure), [])
        raise failure from error

    pages: list[dict[str, object]] = []
    try:
        _candidate_renderer_evidence(project, iteration, candidate, executable)
        if immutable_hashes() != before:
            raise ValueError("candidate manifest, request, or PDF changed during rendering")
        if completed.returncode != 0:
            raise ValueError("controlled PDF renderer exited nonzero")
        total_pages = page_qa["total_pages"]
        pngs = sorted(
            path for path in pages_dir.iterdir() if path.suffix.lower() == ".png"
        )
        if len(pngs) != total_pages:
            raise ValueError("controlled PDF renderer did not produce exactly one PNG per page")
        for page_number, image in enumerate(pngs, start=1):
            width, height = _render_png(image)
            pages.append(
                {
                    "page": page_number,
                    "path": image.relative_to(project).as_posix(),
                    "sha256": sha256_file(image),
                    "width_px": width,
                    "height_px": height,
                }
            )
    except ValueError as error:
        finish_attempt("failed", str(error), [])
        raise

    attempt_record = finish_attempt("pass", None, pages)
    payload = {
        "schema_version": "1",
        "manifest_type": "paper_render",
        "iteration": iteration,
        "attempt": {
            "id": attempt_id,
            "path": attempt.relative_to(project).as_posix(),
            "record_path": attempt_path.relative_to(project).as_posix(),
            "record_sha256": sha256_file(attempt_path),
        },
        "generator": {
            "name": "paper_production",
            "version": "1",
            "method": "controlled_renderer",
            "command": command,
            "exit_code": completed.returncode,
            "log_path": log_path.relative_to(project).as_posix(),
            "log_sha256": sha256_file(log_path),
        },
        "environment": {
            "path": environment_path.relative_to(project).as_posix(),
            "sha256": environment_hash,
        },
        "renderer": renderer_evidence,
        "pdf_path": pdf_record["path"],
        "pdf_sha256": pdf_record["sha256"],
        "candidate_manifest_path": manifest_path.relative_to(project).as_posix(),
        "candidate_manifest_sha256": before["manifest"],
        "review_request_path": request_path.relative_to(project).as_posix(),
        "review_request_sha256": before["request"],
        "total_pages": page_qa["total_pages"],
        "pages": attempt_record["pages"],
    }
    _write_new_json(render_manifest_path, payload)
    return payload


def _validate_candidate_for_finalization(
    project: Path, iteration: str
) -> tuple[Path, dict[str, object], Path, dict[str, object]]:
    current = load_current(project)
    if current["active_iteration"] != iteration:
        raise ValueError("paper finalization iteration must be active")
    if current.get("status") == "stale":
        raise ValueError("current project state is stale")
    gates = current.get("gates")
    if type(gates) is not dict or gates.get("gate3") != "confirmed":
        raise ValueError("Gate 3 must remain confirmed for finalization")
    iteration_root = _directory(project / "iterations" / iteration, "active iteration")
    _current_validation(iteration_root)
    _staleness_check(project)
    paper = _directory(iteration_root / "paper", "active paper directory")
    finalization = paper / "paper_finalization.json"
    if finalization.exists() or finalization.is_symlink():
        raise FileExistsError(f"paper finalization already exists: {finalization}")
    _, _, publication = _load_publication_receipt(
        project, paper, iteration, require_public=True
    )
    manifest_path, manifest, _ = publication["paper_manifest"]
    _exact_keys(
        manifest,
        {
            "schema_version",
            "manifest_type",
            "iteration",
            "created_at",
            "template",
            "template_status",
            "content",
            "environment",
            "compiler",
            "submission_ready",
            "status",
            "failed_checks",
            "pdf",
            "page_qa",
            "readiness",
        },
        "candidate manifest",
    )
    if (
        manifest.get("schema_version") != "1"
        or manifest.get("manifest_type") != "paper"
        or manifest.get("iteration") != iteration
        or manifest.get("submission_ready") is not False
        or manifest.get("status") != "pass"
        or manifest.get("failed_checks") != []
    ):
        raise ValueError("candidate manifest is not an immutable passing non-ready candidate")
    template = manifest.get("template")
    if type(template) is not dict or template.get("submission_ready_eligible") is not True:
        raise ValueError("candidate template is not submission-ready eligible")
    copied_root = safe_relative_path(template.get("copied_root"), "candidate template root")
    template_root = _directory(project / copied_root, "candidate template root")
    expected_hashes = template.get("assembled_hashes")
    if type(expected_hashes) is not dict or any(
        type(name) is not str
        or type(digest) is not str
        or _HASH_RE.fullmatch(digest) is None
        for name, digest in expected_hashes.items()
    ):
        raise ValueError("candidate template hash manifest is invalid")
    observed_hashes = {
        relative.as_posix(): sha256_file(template_root / relative)
        for relative in relative_regular_files(template_root)
    }
    if observed_hashes != expected_hashes:
        raise ValueError("candidate template tree changed after compilation")
    page_qa = manifest.get("page_qa")
    if (
        type(page_qa) is not dict
        or page_qa.get("status") != "pass"
        or page_qa.get("failed_checks") != []
        or type(page_qa.get("total_pages")) is not int
        or page_qa["total_pages"] < 1
        or type(page_qa.get("visual_qa")) is not dict
        or page_qa["visual_qa"].get("status") != "needs_review"
    ):
        raise ValueError("candidate page/reference/structure gate is not a passing review request")
    pdf_record = _exact_keys(
        manifest.get("pdf"),
        {
            "path",
            "sha256",
            "byte_size",
            "compiled_candidate_path",
            "compiled_candidate_sha256",
        },
        "candidate PDF record",
    )
    expected_pdf_path = f"iterations/{iteration}/paper/paper.pdf"
    if pdf_record.get("path") != expected_pdf_path:
        raise ValueError("candidate PDF path is not the immutable published PDF")
    pdf = _project_evidence_file(project, pdf_record["path"], "candidate PDF")
    if (
        pdf_record.get("sha256") != sha256_file(pdf)
        or pdf_record.get("byte_size") != pdf.stat(follow_symlinks=False).st_size
        or page_qa.get("pdf_sha256") != pdf_record.get("sha256")
    ):
        raise ValueError("candidate PDF no longer matches its manifest")
    readiness = _exact_keys(
        manifest.get("readiness"),
        {"status", "authority", "review_request"},
        "candidate readiness record",
    )
    request_relative = f"iterations/{iteration}/paper/visual_review_request.json"
    if (
        readiness.get("status") != "pending_visual_review"
        or readiness.get("authority") != f"iterations/{iteration}/paper/paper_finalization.json"
        or readiness.get("review_request") != request_relative
    ):
        raise ValueError("candidate readiness authority/request is invalid")
    request_path, request, _ = publication["visual_review_request"]
    _exact_keys(
        request,
        {
            "schema_version",
            "manifest_type",
            "iteration",
            "created_at",
            "status",
            "candidate_manifest",
            "candidate_pdf",
            "required_page_coverage",
            "finalization_authority",
        },
        "visual review request",
    )
    manifest_record = _exact_keys(
        request.get("candidate_manifest"), {"path", "sha256"}, "request manifest record"
    )
    request_pdf = _exact_keys(
        request.get("candidate_pdf"),
        {"path", "sha256", "total_pages"},
        "request PDF record",
    )
    total_pages = page_qa["total_pages"]
    expected_coverage = {"start": 1, "end": total_pages, "pages": total_pages}
    if (
        request.get("schema_version") != "1"
        or request.get("manifest_type") != "paper_visual_review_request"
        or request.get("iteration") != iteration
        or request.get("status") != "pending"
        or manifest_record
        != {"path": f"iterations/{iteration}/paper/paper_manifest.json", "sha256": sha256_file(manifest_path)}
        or request_pdf
        != {"path": pdf_record["path"], "sha256": pdf_record["sha256"], "total_pages": total_pages}
        or request.get("required_page_coverage") != expected_coverage
        or request.get("finalization_authority") != readiness["authority"]
    ):
        raise ValueError("visual review request is stale or not bound to the candidate")
    return manifest_path, manifest, request_path, request


def finalize_paper(
    project_root: Path,
    iteration: str,
    review_path: Path,
) -> dict[str, object]:
    """Create the immutable readiness authority from post-compile render/review evidence."""

    project = _directory(project_root, "project root")
    if type(iteration) is not str or _ITERATION_RE.fullmatch(iteration) is None:
        raise ValueError("iteration must use canonical vNNN form")
    manifest_path, candidate, request_path, request = _validate_candidate_for_finalization(
        project, iteration
    )
    review_file = _regular_file(Path(review_path), "visual review manifest")
    if not review_file.is_relative_to(project):
        raise ValueError("visual review manifest must belong to the current project")
    review = _strict_json(review_file, "visual review manifest")
    _exact_keys(
        review,
        {
            "schema_version",
            "manifest_type",
            "iteration",
            "status",
            "pdf_sha256",
            "render_manifest_sha256",
            "page_coverage",
            "checklist",
            "reviewer",
            "reviewed_at",
        },
        "visual review manifest",
    )
    if (
        review.get("schema_version") != "1"
        or review.get("manifest_type") != "paper_visual_review"
        or review.get("iteration") != iteration
        or review.get("status") != "pass"
    ):
        raise ValueError("visual review manifest status/schema is not an exact pass")
    pdf_record = candidate["pdf"]
    page_qa = candidate["page_qa"]
    assert type(pdf_record) is dict and type(page_qa) is dict
    total_pages = page_qa["total_pages"]
    expected_coverage = {"start": 1, "end": total_pages, "pages": total_pages}
    if review.get("pdf_sha256") != pdf_record["sha256"] or review.get("page_coverage") != expected_coverage:
        raise ValueError("visual review does not cover the exact candidate PDF")
    reviewer = review.get("reviewer")
    if type(reviewer) is not str or not reviewer.strip():
        raise ValueError("visual review reviewer must be nonempty")
    _utc_timestamp(review.get("reviewed_at"), "visual review reviewed_at")
    checklist = _exact_keys(
        review.get("checklist"),
        {
            "blank_pages",
            "cropping",
            "garbled_text",
            "overlap",
            "abnormal_font_or_hidden_padding",
        },
        "visual review checklist",
    )
    if any(value != "pass" for value in checklist.values()):
        raise ValueError("every visual review checklist item must explicitly pass")
    render_file = _project_evidence_file(
        project,
        f"iterations/{iteration}/paper/paper_render_manifest.json",
        "canonical render manifest",
    )
    if review.get("render_manifest_sha256") != sha256_file(render_file):
        raise ValueError("visual review render-manifest hash is stale")
    render = _strict_json(render_file, "render manifest")
    _exact_keys(
        render,
        {
            "schema_version",
            "manifest_type",
            "iteration",
            "attempt",
            "generator",
            "environment",
            "renderer",
            "pdf_path",
            "pdf_sha256",
            "candidate_manifest_path",
            "candidate_manifest_sha256",
            "review_request_path",
            "review_request_sha256",
            "total_pages",
            "renderer",
            "pages",
        },
        "render manifest",
    )
    if (
        render.get("schema_version") != "1"
        or render.get("manifest_type") != "paper_render"
        or render.get("iteration") != iteration
        or render.get("candidate_manifest_path")
        != f"iterations/{iteration}/paper/paper_manifest.json"
        or render.get("candidate_manifest_sha256") != sha256_file(manifest_path)
        or render.get("pdf_path") != pdf_record["path"]
        or render.get("pdf_sha256") != pdf_record["sha256"]
        or render.get("review_request_path")
        != f"iterations/{iteration}/paper/visual_review_request.json"
        or render.get("review_request_sha256") != sha256_file(request_path)
        or render.get("total_pages") != total_pages
    ):
        raise ValueError("render manifest is stale or not bound to the review request/PDF")
    attempt_meta = _exact_keys(
        render.get("attempt"),
        {"id", "path", "record_path", "record_sha256"},
        "render attempt reference",
    )
    attempt_id = attempt_meta.get("id")
    if type(attempt_id) is not str or _RENDER_ATTEMPT_RE.fullmatch(attempt_id) is None:
        raise ValueError("render attempt id is invalid")
    expected_attempt_path = f"iterations/{iteration}/paper/render-attempts/{attempt_id}"
    expected_attempt_record = expected_attempt_path + "/attempt.json"
    if (
        attempt_meta.get("path") != expected_attempt_path
        or attempt_meta.get("record_path") != expected_attempt_record
    ):
        raise ValueError("render attempt reference is not canonical")
    attempt_dir = _directory(project / expected_attempt_path, "successful render attempt")
    attempt_record_path = _project_evidence_file(
        project, attempt_meta.get("record_path"), "render attempt record"
    )
    if attempt_meta.get("record_sha256") != sha256_file(attempt_record_path):
        raise ValueError("render attempt record hash is stale")
    attempt_record_bytes = attempt_record_path.read_bytes()
    attempt_record = _strict_json(attempt_record_path, "render attempt record")
    if attempt_record_bytes != _canonical_json_bytes(attempt_record):
        raise ValueError("render attempt record is not canonical")
    _exact_keys(
        attempt_record,
        {
            "schema_version",
            "manifest_type",
            "iteration",
            "attempt_id",
            "created_at",
            "status",
            "error",
            "environment",
            "renderer",
            "candidate",
            "version_command",
            "render_command",
            "exit_code",
            "log",
            "pages",
        },
        "render attempt record",
    )
    _utc_timestamp(attempt_record.get("created_at"), "render attempt created_at")
    if (
        attempt_record.get("schema_version") != "1"
        or attempt_record.get("manifest_type") != "paper_render_attempt"
        or attempt_record.get("iteration") != iteration
        or attempt_record.get("attempt_id") != attempt_id
        or attempt_record.get("status") != "pass"
        or attempt_record.get("error") is not None
        or attempt_record.get("exit_code") != 0
    ):
        raise ValueError("canonical render attempt is not an exact validated success")
    generator = _exact_keys(
        render.get("generator"),
        {"name", "version", "method", "command", "exit_code", "log_path", "log_sha256"},
        "render generator",
    )
    if (
        generator.get("name") != "paper_production"
        or generator.get("version") != "1"
        or generator.get("method") != "controlled_renderer"
    ):
        raise ValueError("render manifest generator is not production-controlled")
    if generator.get("exit_code") != 0:
        raise ValueError("render generator exit code must be zero")
    command = generator.get("command")
    if type(command) is not list or not command or any(
        type(item) is not str or not item for item in command
    ):
        raise ValueError("render generator command must be an auditable string array")
    log_file = _project_evidence_file(project, generator.get("log_path"), "render log")
    if generator.get("log_sha256") != sha256_file(log_file):
        raise ValueError("render log hash is stale")
    attempt_log = _exact_keys(
        attempt_record.get("log"), {"path", "sha256"}, "render attempt log record"
    )
    expected_log_path = expected_attempt_path + "/render.log"
    if (
        generator.get("log_path") != expected_log_path
        or attempt_log
        != {"path": expected_log_path, "sha256": generator.get("log_sha256")}
    ):
        raise ValueError("render log is not bound to the canonical attempt")
    renderer = _exact_keys(
        render.get("renderer"),
        {
            "name",
            "status",
            "path",
            "sha256",
            "version_command",
            "version_exit_code",
            "version_signature",
            "version_output",
            "version_output_sha256",
            "trust_basis",
        },
        "renderer",
    )
    renderer_path_value = renderer.get("path")
    if (
        type(renderer_path_value) is not str
        or not renderer_path_value.strip()
        or not Path(renderer_path_value).is_absolute()
    ):
        raise ValueError("renderer path must be exact and absolute")
    renderer_path = Path(renderer_path_value)
    environment_path, environment_hash, current_renderer, renderer_executable = (
        _candidate_renderer_evidence(
            project, iteration, candidate, renderer_path
        )
    )
    expected_environment = {
        "path": environment_path.relative_to(project).as_posix(),
        "sha256": environment_hash,
    }
    if render.get("environment") != expected_environment or renderer != current_renderer:
        raise ValueError("render manifest environment/renderer evidence is stale")
    attempt_candidate = _exact_keys(
        attempt_record.get("candidate"),
        {"manifest_sha256", "request_sha256", "pdf_sha256"},
        "render attempt candidate record",
    )
    if (
        attempt_record.get("environment") != expected_environment
        or attempt_record.get("renderer") != current_renderer
        or attempt_candidate
        != {
            "manifest_sha256": sha256_file(manifest_path),
            "request_sha256": sha256_file(request_path),
            "pdf_sha256": sha256_file(
                _project_evidence_file(project, pdf_record["path"], "candidate PDF")
            ),
        }
        or attempt_record.get("version_command") != [str(renderer_executable), "-v"]
        or attempt_record.get("render_command") != command
    ):
        raise ValueError("render attempt evidence is stale or mismatched")
    _probe_registered_renderer(renderer_executable, current_renderer)
    pdf = _project_evidence_file(project, pdf_record["path"], "candidate PDF")
    output_prefix = attempt_dir / "pages/page"
    expected_command = [
        str(renderer_executable),
        "-r",
        str(_RENDER_DPI),
        "-png",
        str(pdf),
        str(output_prefix),
    ]
    if command != expected_command:
        raise ValueError("render generator command is not the canonical expected command")
    pages = render.get("pages")
    if type(pages) is not list or len(pages) != total_pages:
        raise ValueError("render manifest must contain exactly one PNG per PDF page")
    observed_pages: list[int] = []
    observed_paths: set[str] = set()
    normalized_pages: list[dict[str, object]] = []
    for index, entry in enumerate(pages):
        page = _exact_keys(
            entry,
            {"page", "path", "sha256", "width_px", "height_px"},
            f"render page {index}",
        )
        page_number = page.get("page")
        if type(page_number) is not int:
            raise ValueError("render page number must be an integer")
        image = _project_evidence_file(project, page.get("path"), "rendered page PNG")
        if image.parent != attempt_dir / "pages":
            raise ValueError("rendered page PNG is outside the canonical attempt pages")
        relative_image = image.relative_to(project).as_posix()
        if relative_image in observed_paths:
            raise ValueError("rendered page PNG paths must be unique")
        observed_paths.add(relative_image)
        if page.get("sha256") != sha256_file(image):
            raise ValueError("rendered page PNG hash is stale")
        width, height = _render_png(image)
        if page.get("width_px") != width or page.get("height_px") != height:
            raise ValueError("rendered page PNG dimensions disagree with the manifest")
        observed_pages.append(page_number)
        normalized_pages.append(dict(page))
    if observed_pages != list(range(1, total_pages + 1)):
        raise ValueError("rendered page numbers must be unique, consecutive, and complete")
    if attempt_record.get("pages") != normalized_pages:
        raise ValueError("render attempt page evidence differs from the canonical manifest")
    finalization_path = project / f"iterations/{iteration}/paper/paper_finalization.json"
    finalization = {
        "schema_version": "1",
        "manifest_type": "paper_finalization",
        "iteration": iteration,
        "created_at": utc_now(),
        "status": "pass",
        "submission_ready": True,
        "readiness_authority": True,
        "candidate_manifest": {
            "path": manifest_path.relative_to(project).as_posix(),
            "sha256": sha256_file(manifest_path),
        },
        "candidate_pdf": {
            "path": str(pdf_record["path"]),
            "sha256": str(pdf_record["sha256"]),
        },
        "review_request": {
            "path": request_path.relative_to(project).as_posix(),
            "sha256": sha256_file(request_path),
        },
        "render_manifest": {
            "path": render_file.relative_to(project).as_posix(),
            "sha256": sha256_file(render_file),
            "renderer": dict(renderer),
            "pages": normalized_pages,
        },
        "visual_review": {
            "path": review_file.relative_to(project).as_posix(),
            "sha256": sha256_file(review_file),
            "reviewer": reviewer.strip(),
            "reviewed_at": review["reviewed_at"],
            "checklist": dict(checklist),
        },
    }
    _write_new_json(finalization_path, finalization)
    return finalization


def recover_paper_publication(project_root: Path, iteration: str) -> dict[str, object]:
    """Reconcile the exact receipt-bound candidate pair without recompiling."""

    project = _directory(project_root, "project root")
    if type(iteration) is not str or _ITERATION_RE.fullmatch(iteration) is None:
        raise ValueError("iteration must use canonical vNNN form")
    current = load_current(project)
    if current.get("active_iteration") != iteration or current.get("status") == "stale":
        raise ValueError("paper publication recovery requires the active non-stale iteration")
    gates = current.get("gates")
    if type(gates) is not dict or gates.get("gate3") != "confirmed":
        raise ValueError("Gate 3 must remain confirmed for publication recovery")
    iteration_root = _directory(project / "iterations" / iteration, "active iteration")
    _current_validation(iteration_root)
    _staleness_check(project)
    paper = _directory(iteration_root / "paper", "active paper directory")
    _, receipt, publication = _load_publication_receipt(
        project, paper, iteration, require_public=False
    )
    manifest_path, manifest, manifest_bytes = publication["paper_manifest"]
    request_path, request, request_bytes = publication["visual_review_request"]
    _exact_keys(
        manifest,
        {
            "schema_version",
            "manifest_type",
            "iteration",
            "created_at",
            "template",
            "template_status",
            "content",
            "environment",
            "compiler",
            "submission_ready",
            "status",
            "failed_checks",
            "pdf",
            "page_qa",
            "readiness",
        },
        "receipt candidate manifest",
    )
    status = manifest.get("status")
    page_qa = manifest.get("page_qa")
    if (
        manifest.get("schema_version") != "1"
        or manifest.get("manifest_type") != "paper"
        or manifest.get("iteration") != iteration
        or status not in ("pass", "needs_revision")
        or manifest.get("submission_ready") is not False
        or manifest.get("failed_checks") != []
        or type(page_qa) is not dict
        or page_qa.get("status") != status
        or page_qa.get("failed_checks") != []
        or type(page_qa.get("total_pages")) is not int
        or page_qa["total_pages"] < 1
    ):
        raise ValueError("receipt does not describe a recoverable candidate")
    pdf_record = _exact_keys(
        manifest.get("pdf"),
        {
            "path",
            "sha256",
            "byte_size",
            "compiled_candidate_path",
            "compiled_candidate_sha256",
        },
        "receipt candidate PDF",
    )
    expected_pdf_path = f"iterations/{iteration}/paper/paper.pdf"
    pdf = _project_evidence_file(project, pdf_record.get("path"), "candidate PDF")
    if (
        pdf_record.get("path") != expected_pdf_path
        or pdf_record.get("sha256") != sha256_file(pdf)
        or pdf_record.get("byte_size") != pdf.stat(follow_symlinks=False).st_size
        or page_qa.get("pdf_sha256") != pdf_record.get("sha256")
    ):
        raise ValueError("receipt candidate PDF is stale or tampered")
    request_relative = f"iterations/{iteration}/paper/visual_review_request.json"
    authority_relative = f"iterations/{iteration}/paper/paper_finalization.json"
    readiness = _exact_keys(
        manifest.get("readiness"),
        {"status", "authority", "review_request"},
        "receipt candidate readiness",
    )
    if readiness != {
        "status": "pending_visual_review",
        "authority": authority_relative,
        "review_request": request_relative,
    }:
        raise ValueError("receipt candidate readiness record is invalid")
    created_at = receipt["created_at"]
    expected_request = {
        "schema_version": "1",
        "manifest_type": "paper_visual_review_request",
        "iteration": iteration,
        "created_at": created_at,
        "status": "pending",
        "candidate_manifest": {
            "path": f"iterations/{iteration}/paper/paper_manifest.json",
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        },
        "candidate_pdf": {
            "path": pdf_record["path"],
            "sha256": pdf_record["sha256"],
            "total_pages": page_qa["total_pages"],
        },
        "required_page_coverage": {
            "start": 1,
            "end": page_qa["total_pages"],
            "pages": page_qa["total_pages"],
        },
        "finalization_authority": authority_relative,
    }
    if request != expected_request or request_bytes != _canonical_json_bytes(expected_request):
        raise ValueError("receipt visual review request is mismatched or tampered")

    missing: list[tuple[Path, bytes, str]] = []
    for target, content, label in (
        (manifest_path, manifest_bytes, "candidate manifest"),
        (request_path, request_bytes, "visual review request"),
    ):
        if target.exists() or target.is_symlink():
            existing = _regular_file(target, label)
            try:
                existing_bytes = existing.read_bytes()
            except OSError as error:
                raise ValueError(f"existing {label} cannot be read") from error
            if existing_bytes != content:
                raise ValueError(f"existing {label} is mismatched or tampered")
        else:
            missing.append((target, content, label))
    for target, content, label in missing:
        _write_new_bytes(target, content, label)
    return dict(request)


def produce_paper(
    project_root: Path,
    iteration: str,
    content_path: Path,
    environment_manifest_path: Path,
    template_path: Path | None = None,
    compiler: Path | None = None,
    *,
    official_template: Path | None = None,
    locally_verified_template: Path | None = None,
    visual_review_path: Path | None = None,
) -> dict[str, object]:
    """Produce one immutable paper attempt from current confirmed evidence."""

    project = _directory(project_root, "project root")
    if type(iteration) is not str or _ITERATION_RE.fullmatch(iteration) is None:
        raise ValueError("iteration must use canonical vNNN form")
    current = load_current(project)
    if current["active_iteration"] != iteration:
        raise ValueError("paper production iteration must be the active iteration")
    gates = current["gates"]
    if type(gates) is not dict or gates.get("gate3") != "confirmed":
        raise ValueError("Gate 3 must be confirmed before paper production")
    if current.get("status") == "stale":
        raise ValueError("current project state is stale")
    iteration_root = _directory(project / "iterations" / iteration, "active iteration")
    paper = _directory(iteration_root / "paper", "active paper directory")
    handoff = _current_validation(iteration_root)
    _staleness_check(project)
    content, content_hash = _frozen_content(Path(content_path), iteration_root)
    _, tools, environment_hash = _environment(
        Path(environment_manifest_path),
        project,
        handoff,
        Path(compiler) if compiler is not None else None,
    )
    if visual_review_path is not None:
        raise ValueError(
            "visual review evidence is accepted only by finalize_paper after compilation"
        )
    _preflight_output_paths(paper)

    fallback = _directory(_BUILTIN_FALLBACK, "built-in fallback template")
    selection = select_template(
        user_template=Path(template_path) if template_path is not None else None,
        fallback_dir=fallback,
        official_template=official_template,
        locally_verified_template=locally_verified_template,
    )
    tools = _engine_tools(tools, selection["engine"])
    template = paper / "template"
    build = paper / "build"
    logs = paper / "logs"
    _copy_selected_template(selection, template)
    _validate_template_integration(template, str(selection["main_entry"]))
    assembly = _write_assembly(template, content)
    template_hashes = _template_hashes(template, selection, assembly)
    _mkdir_new(build, "paper build directory")
    _mkdir_new(logs, "paper logs directory")

    attempts, candidate, aux, all_logs = _attempt_compilation(
        project=project,
        template=template,
        main_entry=str(selection["main_entry"]),
        tools=tools,
        build=build,
        logs=logs,
    )
    manifest_path = paper / "paper_manifest.json"
    created_at = utc_now()
    common: dict[str, object] = {
        "schema_version": "1",
        "manifest_type": "paper",
        "iteration": iteration,
        "created_at": created_at,
        "template": {
            **selection,
            "copied_root": _project_relative(project, template),
            "assembled_hashes": template_hashes,
        },
        "template_status": selection["template_status"],
        "content": {
            "path": _project_relative(project, _regular_file(Path(content_path), "frozen paper content")),
            "sha256": content_hash,
            "assembly": [
                {
                    "path": _project_relative(project, template / entry["path"]),
                    "sha256": entry["sha256"],
                }
                for entry in assembly
            ],
        },
        "environment": {
            "path": _project_relative(
                project,
                _regular_file(Path(environment_manifest_path), "environment manifest"),
            ),
            "sha256": environment_hash,
        },
        "compiler": {"attempts": attempts},
        "submission_ready": False,
    }

    integrity_error: str | None = None
    try:
        if _template_hashes(template, selection, assembly) != template_hashes:
            integrity_error = "template integrity changed during compilation"
    except ValueError as error:
        integrity_error = f"template integrity changed during compilation: {error}"
    if integrity_error is not None:
        report = {
            **common,
            "status": "fail",
            "failed_checks": [integrity_error],
            "pdf": None,
            "page_qa": None,
        }
        _write_new_json(manifest_path, report)
        return report

    successful_exit = bool(attempts and attempts[-1]["exit_code"] == 0)
    if candidate is None:
        failed = []
        failed.extend(
            str(attempt["candidate_error"])
            for attempt in attempts
            if attempt.get("candidate_error") is not None
        )
        if not successful_exit:
            failed.append("all diagnosed compiler attempts failed")
        elif not failed:
            failed.append("compiler exited zero but produced no PDF")
        report = {
            **common,
            "status": "fail",
            "failed_checks": failed,
            "pdf": None,
            "page_qa": None,
        }
        _write_new_json(manifest_path, report)
        return report

    final_attempt = attempts[-1]
    final_log_paths = {str(final_attempt["log_path"])}
    if final_attempt.get("build_log_path") is not None:
        final_log_paths.add(str(final_attempt["build_log_path"]))
    final_log = [
        path
        for path in all_logs
        if _project_relative(project, path) in final_log_paths
    ]
    page_qa = inspect_pdf(
        candidate,
        aux_path=aux,
        log_paths=final_log,
    )
    pdf_record = {
        "path": _project_relative(project, candidate),
        "sha256": sha256_file(candidate),
        "byte_size": candidate.stat(follow_symlinks=False).st_size,
    }
    if page_qa["status"] in ("pass", "needs_revision"):
        published = paper / "paper.pdf"
        _copy_new_file(candidate, published, "published paper PDF")
        pdf_record = {
            "path": _project_relative(project, published),
            "sha256": sha256_file(published),
            "byte_size": published.stat(follow_symlinks=False).st_size,
            "compiled_candidate_path": _project_relative(project, candidate),
            "compiled_candidate_sha256": sha256_file(candidate),
        }

    status = str(page_qa["status"])
    review_request_path = paper / "visual_review_request.json"
    finalization_path = paper / "paper_finalization.json"
    report = {
        **common,
        "status": status,
        "failed_checks": list(page_qa["failed_checks"]),
        "pdf": pdf_record,
        "page_qa": page_qa,
        "submission_ready": False,
        "readiness": {
            "status": "pending_visual_review",
            "authority": _project_relative(project, finalization_path),
            "review_request": _project_relative(project, review_request_path),
        },
    }
    manifest_relative = _project_relative(project, manifest_path)
    manifest_bytes = _canonical_json_bytes(report)
    request = {
        "schema_version": "1",
        "manifest_type": "paper_visual_review_request",
        "iteration": iteration,
        "created_at": created_at,
        "status": "pending",
        "candidate_manifest": {
            "path": manifest_relative,
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        },
        "candidate_pdf": {
            "path": str(pdf_record["path"]),
            "sha256": str(pdf_record["sha256"]),
            "total_pages": page_qa["total_pages"],
        },
        "required_page_coverage": {
            "start": 1,
            "end": page_qa["total_pages"],
            "pages": page_qa["total_pages"],
        },
        "finalization_authority": _project_relative(project, finalization_path),
    }
    receipt, expected_manifest_bytes, expected_request_bytes = _publication_receipt(
        iteration=iteration,
        created_at=created_at,
        manifest_path=manifest_relative,
        manifest=report,
        request_path=_project_relative(project, review_request_path),
        request=request,
    )
    if manifest_bytes != expected_manifest_bytes:
        raise ValueError("candidate manifest canonical bytes changed during transaction setup")
    receipt_path = paper / "paper_publication_receipt.json"
    _write_new_json(receipt_path, receipt)
    _write_new_json(manifest_path, report)
    _write_new_json(review_request_path, request)
    if (
        manifest_path.read_bytes() != expected_manifest_bytes
        or review_request_path.read_bytes() != expected_request_bytes
    ):
        raise ValueError("published candidate bytes differ from the transaction receipt")
    return report


__all__ = [
    "finalize_paper",
    "produce_paper",
    "recover_paper_publication",
    "render_paper_pages",
    "select_template",
]
