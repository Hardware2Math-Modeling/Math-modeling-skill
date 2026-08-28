#!/usr/bin/env python3
"""Select, assemble, compile, and audit immutable LaTeX paper outputs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
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
    target = _absolute(path, "paper manifest output")
    _directory(target.parent, "paper manifest parent")
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"paper manifest already exists: {target}")
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.link(temporary_name, target)
    except FileExistsError as error:
        raise FileExistsError(f"paper manifest already exists: {target}") from error
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass


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
) -> dict[str, object]:
    """Choose and hash a template without copying or mutating any destination."""

    selected: Path
    status: str
    eligible: bool
    selected_role: str
    if user_template is not None and Path(user_template).exists():
        selected = Path(user_template)
        status = "user_provided"
        eligible = True
        selected_role = "user"
    elif official_template is not None and Path(official_template).exists():
        selected = Path(official_template)
        status = "official_unverified"
        eligible = False
        selected_role = "official"
    else:
        selected = Path(fallback_dir)
        status = "fallback_non_submission"
        eligible = False
        selected_role = "fallback"

    root, files, source_kind = _template_files(selected, "selected template")
    metadata = _template_metadata(root, files)
    if selected_role == "official":
        required = ("source_url", "license", "verification_date")
        verified = metadata.get("status") == "verified" and all(
            type(metadata.get(field)) is str and bool(str(metadata[field]).strip())
            for field in required
        )
        if verified:
            status = "official_verified"
            eligible = True
    main_entry = _template_entry(root, files, metadata)
    engine = metadata.get("engine", "xelatex")
    if type(engine) is not str or not engine.strip():
        raise ValueError("template engine metadata must be a non-empty string")

    source = _absolute(selected, "selected template")
    return {
        "template_status": status,
        "source": str(source),
        "source_kind": source_kind,
        "sha256": _tree_hash(root, files),
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
    for relative in ("template", "build", "logs", "paper_manifest.json", "paper.pdf"):
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
    requested_compiler: Path | None,
) -> tuple[dict[str, object], list[dict[str, object]], str]:
    safe = _regular_file(path, "environment manifest")
    if not safe.is_relative_to(project):
        raise ValueError("environment manifest must belong to the current project")
    report = _strict_json(safe, "environment manifest")
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
    return report, ordered, sha256_file(safe)


def _copy_selected_template(selection: dict[str, object], destination: Path) -> None:
    source = _absolute(Path(str(selection["source"])), "selected template source")
    source_kind = selection["source_kind"]
    root = source.parent if source_kind == "file" else source
    destination.mkdir()
    files = selection["files"]
    assert type(files) is list
    for entry in files:
        assert type(entry) is dict
        relative = safe_relative_path(entry["path"], "selected template file")
        source_file = _regular_file(root / relative, "selected template file")
        if sha256_file(source_file) != entry["sha256"]:
            raise ValueError(f"selected template changed before copy: {relative.as_posix()}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, target, follow_symlinks=False)
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
    return (
        "\\begin{abstract}\n"
        + "\n\n\\par\n".join(_latex_text(item) for item in paragraphs)
        + "\n\\end{abstract}\n"
        + f"\\noindent\\textbf{{关键词：}}{keywords}\n"
    )


def _body(content: dict[str, object]) -> str:
    sections = content["sections"]
    assert type(sections) is dict
    lines: list[str] = []
    for number in range(1, 9):
        section = sections[str(number)]
        assert type(section) is dict
        lines.append(f"\\section{{{section['title']}}}")
        if number == 1:
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
    return "\n\n".join(lines) + "\n"


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
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"template reserves generated assembly path: {path}")
        path.write_text(value, encoding="utf-8", newline="\n")
        entries.append({"path": name, "sha256": sha256_file(path)})
    return entries


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
        attempt_build.mkdir()
        command = _command(tool, template / main_entry, attempt_build)
        log_path = logs / f"attempt-{index:02d}-{tool['name']}.log"
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
        log_path.write_text(
            json.dumps({"command": command}, ensure_ascii=False, allow_nan=False)
            + "\n\n[stdout]\n"
            + str(stdout)
            + "\n[stderr]\n"
            + str(stderr)
            + (f"\n[execution_error]\n{execution_error}\n" if execution_error else ""),
            encoding="utf-8",
        )
        all_logs.append(log_path)
        stem = Path(main_entry).stem
        produced_pdf = attempt_build / f"{stem}.pdf"
        produced_aux = attempt_build / f"{stem}.aux"
        candidate_error: str | None = None
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
        attempt = {
            "tool": tool["name"],
            "path": tool["path"],
            "compiler_sha256": sha256_file(Path(str(tool["path"]))),
            "version": tool.get("version"),
            "command": command,
            "exit_code": exit_code,
            "log_path": _project_relative(project, log_path),
            "log_sha256": sha256_file(log_path),
            "candidate_pdf": (
                _project_relative(project, produced_pdf) if candidate_is_regular else None
            ),
            "candidate_pdf_sha256": (
                sha256_file(produced_pdf) if candidate_is_regular else None
            ),
            "candidate_error": candidate_error,
        }
        build_log = attempt_build / f"{stem}.log"
        if build_log.is_file() and not build_log.is_symlink():
            all_logs.append(build_log)
            attempt["build_log_path"] = _project_relative(project, build_log)
            attempt["build_log_sha256"] = sha256_file(build_log)
        attempts.append(attempt)
        if exit_code == 0 and candidate_is_regular:
            candidate = produced_pdf
            aux = produced_aux if produced_aux.is_file() else None
            break
    return attempts, candidate, aux, all_logs


def produce_paper(
    project_root: Path,
    iteration: str,
    content_path: Path,
    environment_manifest_path: Path,
    template_path: Path | None = None,
    compiler: Path | None = None,
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
    _current_validation(iteration_root)
    _staleness_check(project)
    content, content_hash = _frozen_content(Path(content_path), iteration_root)
    _, tools, environment_hash = _environment(
        Path(environment_manifest_path),
        project,
        Path(compiler) if compiler is not None else None,
    )
    _preflight_output_paths(paper)

    fallback = _directory(_BUILTIN_FALLBACK, "built-in fallback template")
    selection = select_template(
        user_template=Path(template_path) if template_path is not None else None,
        fallback_dir=fallback,
    )
    template = paper / "template"
    build = paper / "build"
    logs = paper / "logs"
    _copy_selected_template(selection, template)
    assembly = _write_assembly(template, content)
    build.mkdir()
    logs.mkdir()

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
    page_qa = inspect_pdf(candidate, aux_path=aux, log_paths=final_log)
    pdf_record = {
        "path": _project_relative(project, candidate),
        "sha256": sha256_file(candidate),
        "byte_size": candidate.stat(follow_symlinks=False).st_size,
    }
    if page_qa["status"] in ("pass", "needs_revision"):
        published = paper / "paper.pdf"
        if published.exists() or published.is_symlink():
            raise FileExistsError(f"paper PDF already exists: {published}")
        shutil.copyfile(candidate, published, follow_symlinks=False)
        pdf_record = {
            "path": _project_relative(project, published),
            "sha256": sha256_file(published),
            "byte_size": published.stat(follow_symlinks=False).st_size,
            "compiled_candidate_path": _project_relative(project, candidate),
            "compiled_candidate_sha256": sha256_file(candidate),
        }

    status = str(page_qa["status"])
    submission_ready = bool(
        status == "pass"
        and selection["submission_ready_eligible"] is True
        and page_qa["visual_qa"]["status"] == "pass"
    )
    report = {
        **common,
        "status": status,
        "failed_checks": list(page_qa["failed_checks"]),
        "pdf": pdf_record,
        "page_qa": page_qa,
        "submission_ready": submission_ready,
    }
    _write_new_json(manifest_path, report)
    return report


__all__ = ["produce_paper", "select_template"]
