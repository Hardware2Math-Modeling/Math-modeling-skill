#!/usr/bin/env python3
"""Select, assemble, compile, and audit immutable LaTeX paper outputs."""

from __future__ import annotations

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
_ITERATION_RE = re.compile(r"^v[0-9]{3,}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
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


def _write_new_json(path: Path, payload: object) -> None:
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
    _write_new_bytes(path, content.encode("utf-8"), "paper manifest")


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


def _environment(
    path: Path,
    project: Path,
    handoff: dict[str, object],
    requested_compiler: Path | None,
) -> tuple[dict[str, object], list[dict[str, object]], str]:
    safe = _regular_file(path, "environment manifest")
    if not safe.is_relative_to(project):
        raise ValueError("environment manifest must belong to the current project")
    report = _strict_json(safe, "environment manifest")
    environment_hash = sha256_file(safe)
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
    manifest_path = _regular_file(paper / "paper_manifest.json", "candidate manifest")
    manifest = _strict_json(manifest_path, "candidate manifest")
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
    request_path = _project_evidence_file(project, request_relative, "visual review request")
    request = _strict_json(request_path, "visual review request")
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
            "render_manifest_path",
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
        project, review.get("render_manifest_path"), "render manifest"
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
            "pdf_path",
            "pdf_sha256",
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
        or render.get("pdf_path") != pdf_record["path"]
        or render.get("pdf_sha256") != pdf_record["sha256"]
        or render.get("review_request_path")
        != f"iterations/{iteration}/paper/visual_review_request.json"
        or render.get("review_request_sha256") != sha256_file(request_path)
        or render.get("total_pages") != total_pages
    ):
        raise ValueError("render manifest is stale or not bound to the review request/PDF")
    renderer = _exact_keys(
        render.get("renderer"), {"name", "version", "method", "command"}, "renderer"
    )
    if any(
        type(renderer.get(field)) is not str or not str(renderer[field]).strip()
        for field in ("name", "version", "method")
    ):
        raise ValueError("renderer identity/method must be nonempty")
    command = renderer.get("command")
    if type(command) is not list or not command or any(
        type(item) is not str or not item for item in command
    ):
        raise ValueError("renderer command must be an auditable string array")
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
    _write_new_json(manifest_path, report)
    request = {
        "schema_version": "1",
        "manifest_type": "paper_visual_review_request",
        "iteration": iteration,
        "created_at": utc_now(),
        "status": "pending",
        "candidate_manifest": {
            "path": _project_relative(project, manifest_path),
            "sha256": sha256_file(manifest_path),
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
    _write_new_json(review_request_path, request)
    return report


__all__ = ["finalize_paper", "produce_paper", "select_template"]
