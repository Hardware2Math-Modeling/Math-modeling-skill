#!/usr/bin/env python3
"""Validate and freeze evidence-backed Chinese paper content."""

from __future__ import annotations

import copy
import json
import re
import stat
from pathlib import Path

from figure_qa import validate_figure_manifest
from handoff_schema import strict_json_tree_errors
from manifest import atomic_write_json, safe_relative_path, sha256_file
from result_contract import validate_result_payload
from suite_validation import ensure_no_symlink_components


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_QUESTION_RE = re.compile(r"^Q[1-9][0-9]*$")
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.])[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:%|％)?")
_BOLD_RE = re.compile(r"\\textbf\{([^{}]+)\}")
_ROOT_FIELDS = {
    "schema_version",
    "language",
    "requirement_manifests",
    "abstract",
    "keywords",
    "sections",
    "symbols",
    "claims",
    "figure_references",
    "table_references",
    "references",
    "code_appendix",
    "ai_use_disclosure",
    "human_review_records",
    "supplemental_appendix",
    "english_abstract",
}
_REQUIRED_ROOT_FIELDS = _ROOT_FIELDS - {"english_abstract"}
_SECTION_TITLES = {
    "1": "问题背景与重述",
    "2": "问题分析",
    "3": "模型假设",
    "4": "符号说明",
    "5": "模型的建立与求解",
    "6": "模型检验",
    "7": "模型评价与推广/改进",
    "8": "结论",
}


def _nonempty(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _unknown_keys(value: dict[object, object], allowed: set[str], label: str) -> list[str]:
    keys = sorted(
        (key for key in value if key not in allowed),
        key=lambda item: (type(item).__name__, repr(item)),
    )
    return [f"{label}.{key} is unsupported" for key in keys]


def _required_keys(
    value: dict[object, object], required: set[str], label: str
) -> list[str]:
    return [f"{label}.{key} is required" for key in sorted(required) if key not in value]


def _safe_root(value: Path) -> Path:
    root = Path(value)
    if not root.is_absolute():
        raise ValueError("evidence_root must be an absolute path")
    root = ensure_no_symlink_components(root, "evidence_root")
    try:
        mode = root.lstat().st_mode
    except OSError as error:
        raise ValueError("evidence_root must be an existing directory") from error
    if not stat.S_ISDIR(mode):
        raise ValueError("evidence_root must be an existing directory")
    return root


def _evidence_path(root: Path, value: object, label: str) -> Path:
    relative = safe_relative_path(value, label)
    target = ensure_no_symlink_components(root / relative, label)
    if not target.is_relative_to(root):
        raise ValueError(f"{label} must remain within evidence_root")
    try:
        mode = target.lstat().st_mode
    except OSError as error:
        raise ValueError(f"{label} must be an existing regular file") from error
    if not stat.S_ISREG(mode):
        raise ValueError(f"{label} must be an existing regular non-symlink file")
    return target


def _strict_json(path: Path, label: str) -> dict[str, object]:
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
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"{label} must contain strict JSON: {error}") from error
    if type(payload) is not dict:
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def question_ids(content: object) -> list[str]:
    """Return section-five question identifiers in declared order."""

    if type(content) is not dict:
        return []
    sections = content.get("sections")
    if type(sections) is not dict or type(sections.get("5")) is not dict:
        return []
    questions = sections["5"].get("questions")
    if type(questions) is not list:
        return []
    return [
        question["question_id"]
        for question in questions
        if type(question) is dict and type(question.get("question_id")) is str
    ]


def _reference_ids(content: object, field: str, id_field: str) -> list[str]:
    if type(content) is not dict or type(content.get(field)) is not list:
        return []
    return [
        entry[id_field]
        for entry in content[field]
        if type(entry) is dict and type(entry.get(id_field)) is str
    ]


def referenced_figures(content: object) -> list[str]:
    """Return registered figure identifiers in paper order."""

    return _reference_ids(content, "figure_references", "figure_id")


def referenced_tables(content: object) -> list[str]:
    """Return registered table identifiers in paper order."""

    return _reference_ids(content, "table_references", "table_id")


def _validate_abstract(content: dict[str, object], questions: list[str], errors: list[str]) -> None:
    abstract = content.get("abstract")
    if type(abstract) is not dict:
        errors.append("abstract must be an object")
        return
    errors.extend(
        _required_keys(abstract, {"intro_sentences", "question_paragraphs"}, "abstract")
    )
    errors.extend(
        _unknown_keys(abstract, {"intro_sentences", "question_paragraphs"}, "abstract")
    )
    intro = abstract.get("intro_sentences")
    if (
        type(intro) is not list
        or len(intro) != 2
        or any(not _nonempty(sentence) for sentence in intro)
    ):
        errors.append(
            "abstract.intro_sentences must contain exactly two ordered non-empty sentences"
        )

    paragraphs = abstract.get("question_paragraphs")
    if type(paragraphs) is not list:
        errors.append("abstract.question_paragraphs must be a list")
        return
    paragraph_ids: list[str] = []
    allowed = {"question_id", "leading_summary", "modeling_steps", "answer"}
    for index, paragraph in enumerate(paragraphs):
        label = f"abstract.question_paragraphs[{index}]"
        if type(paragraph) is not dict:
            errors.append(f"{label} must be an object")
            continue
        errors.extend(_required_keys(paragraph, allowed, label))
        errors.extend(_unknown_keys(paragraph, allowed, label))
        question_id = paragraph.get("question_id")
        if not _nonempty(question_id) or _QUESTION_RE.fullmatch(question_id) is None:
            errors.append(f"{label}.question_id must use canonical Qn form")
        else:
            paragraph_ids.append(question_id)
        for field in ("leading_summary", "modeling_steps", "answer"):
            if not _nonempty(paragraph.get(field)):
                errors.append(f"{label}.{field} must be a non-empty string")
    for question_id in questions:
        if paragraph_ids.count(question_id) != 1:
            errors.append(
                f"abstract.question_paragraphs must contain exactly one paragraph for {question_id}"
            )
    for question_id in paragraph_ids:
        if question_id not in questions:
            errors.append(
                f"abstract.question_paragraphs contains unsupported question {question_id}"
            )
    if len(paragraphs) != len(questions):
        errors.append("abstract.question_paragraphs count must match section 5 questions")


def _validate_subsection(
    value: object,
    *,
    label: str,
    expected_title: str,
    errors: list[str],
) -> None:
    if type(value) is not dict:
        errors.append(f"{label} must be an object")
        return
    errors.extend(_required_keys(value, {"title", "content"}, label))
    errors.extend(_unknown_keys(value, {"title", "content"}, label))
    if value.get("title") != expected_title:
        errors.append(f"{label}.title must be {expected_title!r}")
    if not _nonempty(value.get("content")):
        errors.append(f"{label}.content must be a non-empty string")


def _validate_sections(content: dict[str, object], errors: list[str]) -> list[str]:
    sections = content.get("sections")
    expected_keys = set(_SECTION_TITLES)
    if type(sections) is not dict:
        errors.append("sections must be an object containing sections 1 through 8")
        return []
    errors.extend(_required_keys(sections, expected_keys, "sections"))
    errors.extend(_unknown_keys(sections, expected_keys, "sections"))
    for key, expected_title in _SECTION_TITLES.items():
        section = sections.get(key)
        if type(section) is not dict:
            errors.append(f"sections.{key} must be an object")
            continue
        if section.get("title") != expected_title:
            errors.append(f"sections.{key}.title must be {expected_title!r}")

    background = sections.get("1")
    if type(background) is dict:
        errors.extend(_required_keys(background, {"title", "subsections"}, "sections.1"))
        errors.extend(_unknown_keys(background, {"title", "subsections"}, "sections.1"))
        subsections = background.get("subsections")
        if type(subsections) is not dict:
            errors.append("sections.1.subsections must contain 1.1 and 1.2")
        else:
            errors.extend(
                _required_keys(subsections, {"1.1", "1.2"}, "sections.1.subsections")
            )
            errors.extend(
                _unknown_keys(subsections, {"1.1", "1.2"}, "sections.1.subsections")
            )
            _validate_subsection(
                subsections.get("1.1"),
                label="sections.1.subsections.1.1",
                expected_title="问题背景",
                errors=errors,
            )
            _validate_subsection(
                subsections.get("1.2"),
                label="sections.1.subsections.1.2",
                expected_title="问题重述",
                errors=errors,
            )

    for key in ("2", "3", "4", "6", "7", "8"):
        section = sections.get(key)
        if type(section) is not dict:
            continue
        errors.extend(_required_keys(section, {"title", "content"}, f"sections.{key}"))
        errors.extend(_unknown_keys(section, {"title", "content"}, f"sections.{key}"))
        if not _nonempty(section.get("content")):
            errors.append(f"sections.{key}.content must be a non-empty string")

    model_section = sections.get("5")
    if type(model_section) is not dict:
        return []
    errors.extend(_required_keys(model_section, {"title", "questions"}, "sections.5"))
    errors.extend(_unknown_keys(model_section, {"title", "questions"}, "sections.5"))
    questions = model_section.get("questions")
    if type(questions) is not list or not questions:
        errors.append("sections.5.questions must be a non-empty list")
        return []

    identifiers: list[str] = []
    for index, question in enumerate(questions, start=1):
        label = f"sections.5.questions[{index - 1}]"
        expected_id = f"Q{index}"
        if type(question) is not dict:
            errors.append(f"{label} must be an object for {expected_id}")
            continue
        allowed = {"question_id", "title", "subsections"}
        errors.extend(_required_keys(question, allowed, label))
        errors.extend(_unknown_keys(question, allowed, label))
        question_id = question.get("question_id")
        if question_id != expected_id:
            errors.append(
                f"{label}.question_id must be contiguous canonical identifier {expected_id}"
            )
        if _nonempty(question_id) and _QUESTION_RE.fullmatch(question_id):
            identifiers.append(question_id)
        if not _nonempty(question.get("title")):
            errors.append(f"{label}.title must be a non-empty string")
        subsections = question.get("subsections")
        expected = {
            f"5.{index}.1": "建模",
            f"5.{index}.2": "计算",
        }
        if type(subsections) is not dict:
            errors.append(f"{label}.subsections must contain modeling and calculation for {expected_id}")
            continue
        for key in expected:
            if key not in subsections:
                errors.append(f"{expected_id} requires subsection {key}")
        for key in sorted(subsections):
            if key not in expected:
                errors.append(f"{key} is unsupported in {expected_id}; use only 5.{index}.1 and 5.{index}.2")
        for key, title in expected.items():
            if key in subsections:
                _validate_subsection(
                    subsections[key],
                    label=f"{label}.subsections.{key}",
                    expected_title=title,
                    errors=errors,
                )
    if len(set(identifiers)) != len(identifiers):
        errors.append("sections.5 question_id values must be unique")
    return identifiers


def _validate_symbols(content: dict[str, object], errors: list[str]) -> None:
    symbols = content.get("symbols")
    if type(symbols) is not list or not symbols:
        errors.append("symbols must be a non-empty three-column list")
        return
    columns = {"symbol", "description", "unit"}
    for index, symbol in enumerate(symbols):
        label = f"symbols[{index}]"
        if type(symbol) is not dict:
            errors.append(f"{label} must be an object")
            continue
        errors.extend(_required_keys(symbol, columns, label))
        errors.extend(_unknown_keys(symbol, columns, label))
        for field in sorted(columns):
            if not _nonempty(symbol.get(field)):
                errors.append(f"{label}.{field} must be a non-empty string")


def _reference_target(
    entry: dict[str, object],
    *,
    path_field: str,
    hash_field: str,
    label: str,
    root: Path | None,
    errors: list[str],
) -> Path | None:
    try:
        safe_relative_path(entry.get(path_field), f"{label}.{path_field}")
    except ValueError:
        errors.append(f"{label}.{path_field} must be a safe relative path")
        return None
    expected_hash = entry.get(hash_field)
    if type(expected_hash) is not str or _HASH_RE.fullmatch(expected_hash) is None:
        errors.append(f"{label}.{hash_field} must be a lowercase SHA-256 hash")
        return None
    if root is None:
        return None
    try:
        target = _evidence_path(root, entry[path_field], f"{label}.{path_field}")
        observed = sha256_file(target)
    except ValueError as error:
        errors.append(str(error))
        return None
    if observed != expected_hash:
        errors.append(f"{label}.{hash_field} does not match the current evidence hash")
        return None
    return target


def _validate_claims(
    content: dict[str, object],
    questions: list[str],
    root: Path | None,
    errors: list[str],
) -> list[dict[str, object]]:
    claims = content.get("claims")
    if type(claims) is not list or not claims:
        errors.append("claims must contain evidence-backed claims")
        return []
    allowed = {"question_id", "claim_id", "statement", "source_path", "source_hash", "important"}
    valid_claims: list[dict[str, object]] = []
    seen: set[str] = set()
    counts = {question_id: 0 for question_id in questions}
    for index, claim in enumerate(claims):
        label = f"claims[{index}]"
        if type(claim) is not dict:
            errors.append(f"{label} must be an object")
            continue
        errors.extend(_required_keys(claim, allowed, label))
        errors.extend(_unknown_keys(claim, allowed, label))
        question_id = claim.get("question_id")
        if question_id not in questions:
            errors.append(f"{label}.question_id must reference a section 5 question")
        else:
            counts[question_id] += 1
        claim_id = claim.get("claim_id")
        if not _nonempty(claim_id):
            errors.append(f"{label}.claim_id must be a non-empty string")
        elif claim_id in seen:
            errors.append(f"{label}.claim_id must be unique")
        else:
            seen.add(claim_id)
        if not _nonempty(claim.get("statement")):
            errors.append(f"{label}.statement must be a non-empty string")
        if type(claim.get("important")) is not bool:
            errors.append(f"{label}.important must be boolean")
        target = _reference_target(
            claim,
            path_field="source_path",
            hash_field="source_hash",
            label=label,
            root=root,
            errors=errors,
        )
        if target is not None:
            try:
                result = _strict_json(target, f"{label} result contract")
            except ValueError as error:
                errors.append(str(error))
            else:
                result_errors = validate_result_payload(result)
                if result_errors:
                    errors.append(f"{label} result contract is invalid: {result_errors[0]}")
                if result.get("freeze_status") != "confirmed":
                    errors.append(f"{label} result contract must have freeze_status confirmed")
                if result.get("question_id") != question_id:
                    errors.append(f"{label}.question_id does not match the frozen result contract")
                result_claims = result.get("claims")
                result_ids = {
                    item.get("claim_id")
                    for item in result_claims
                    if type(item) is dict
                } if type(result_claims) is list else set()
                if claim_id not in result_ids:
                    errors.append(f"{label}.claim_id does not resolve in the frozen result contract")
        valid_claims.append(claim)
    for question_id, count in counts.items():
        if count == 0:
            errors.append(f"claims must include at least one frozen result claim for {question_id}")
    return valid_claims


def _validate_fresh_sources(
    manifest: dict[str, object], root: Path, label: str, errors: list[str]
) -> None:
    sources = manifest.get("sources")
    if type(sources) is not list or not sources:
        errors.append(f"{label}.sources must be a non-empty list")
        return
    for index, source in enumerate(sources):
        source_label = f"{label}.sources[{index}]"
        if type(source) is not dict:
            errors.append(f"{source_label} must be an object")
            continue
        target = _reference_target(
            source,
            path_field="path",
            hash_field="sha256",
            label=source_label,
            root=root,
            errors=errors,
        )
        if target is None:
            continue


def _validate_artifact_references(
    content: dict[str, object], root: Path | None, errors: list[str]
) -> None:
    specifications = (
        ("figure_references", "figure_id", "figure"),
        ("table_references", "table_id", "table"),
    )
    for field, id_field, kind in specifications:
        entries = content.get(field)
        if type(entries) is not list:
            errors.append(f"{field} must be an explicit list")
            continue
        seen: set[str] = set()
        allowed = {id_field, "manifest_path", "manifest_hash"}
        for index, entry in enumerate(entries):
            label = f"{field}[{index}]"
            if type(entry) is not dict:
                errors.append(f"{label} must be an object")
                continue
            errors.extend(_required_keys(entry, allowed, label))
            errors.extend(_unknown_keys(entry, allowed, label))
            identifier = entry.get(id_field)
            if not _nonempty(identifier):
                errors.append(f"{label}.{id_field} must be a non-empty string")
            elif identifier in seen:
                errors.append(f"{label}.{id_field} must be unique")
            else:
                seen.add(identifier)
            target = _reference_target(
                entry,
                path_field="manifest_path",
                hash_field="manifest_hash",
                label=label,
                root=root,
                errors=errors,
            )
            if target is None:
                continue
            try:
                manifest = _strict_json(target, f"{label} {kind} manifest")
            except ValueError as error:
                errors.append(str(error))
                continue
            if manifest.get("status") != "verified":
                errors.append(f"{label} {kind} manifest status must be verified")
            if manifest.get(id_field) != identifier:
                errors.append(f"{label}.{id_field} does not match the {kind} manifest")
            if kind == "figure":
                figure_errors = validate_figure_manifest(manifest, project_root=root)
                for figure_error in figure_errors:
                    errors.append(f"{label} figure manifest: {figure_error}")
            else:
                _validate_fresh_sources(manifest, root, label, errors)


def _validate_requirement_manifests(
    content: dict[str, object], root: Path | None, errors: list[str]
) -> bool:
    entries = content.get("requirement_manifests")
    if type(entries) is not list:
        errors.append("requirement_manifests must be an explicit list")
        return False
    english_required = False
    allowed = {"kind", "path", "sha256"}
    for index, entry in enumerate(entries):
        label = f"requirement_manifests[{index}]"
        if type(entry) is not dict:
            errors.append(f"{label} must be an object")
            continue
        errors.extend(_required_keys(entry, allowed, label))
        errors.extend(_unknown_keys(entry, allowed, label))
        kind = entry.get("kind")
        if kind not in ("template", "competition"):
            errors.append(f"{label}.kind must be template or competition")
        target = _reference_target(
            entry,
            path_field="path",
            hash_field="sha256",
            label=label,
            root=root,
            errors=errors,
        )
        if target is None:
            continue
        try:
            manifest = _strict_json(target, f"{label} requirement manifest")
        except ValueError as error:
            errors.append(str(error))
            continue
        if manifest.get("status") != "verified":
            errors.append(f"{label} requirement manifest status must be verified")
            continue
        if manifest.get("manifest_type") != kind:
            errors.append(f"{label}.kind does not match requirement manifest_type")
            continue
        required_sections = manifest.get("required_sections")
        if type(required_sections) is list and "english_abstract" in required_sections:
            english_required = True
    return english_required


def _validate_english(content: dict[str, object], allowed: bool, errors: list[str]) -> None:
    if "english_abstract" not in content:
        return
    english = content["english_abstract"]
    if not allowed:
        errors.append(
            "English abstract requires a current verified template or competition manifest"
        )
    if type(english) is not dict:
        errors.append("english_abstract must be an object")
        return
    fields = {"text", "keywords"}
    errors.extend(_required_keys(english, fields, "english_abstract"))
    errors.extend(_unknown_keys(english, fields, "english_abstract"))
    if not _nonempty(english.get("text")):
        errors.append("english_abstract.text must be a non-empty string")
    keywords = english.get("keywords")
    if type(keywords) is not list or not keywords or any(not _nonempty(item) for item in keywords):
        errors.append("english_abstract.keywords must be a non-empty string list")


def _validate_simple_arrays(content: dict[str, object], errors: list[str]) -> None:
    specifications = {
        "references": ({"citation_id", "entry"}, {"citation_id", "entry"}),
        "code_appendix": ({"path", "sha256", "description"}, {"path", "sha256", "description"}),
        "ai_use_disclosure": (
            {"tool", "purpose", "output_used", "human_verified"},
            {"tool", "purpose", "output_used"},
        ),
        "human_review_records": (
            {"review_id", "scope", "status", "reviewed_by"},
            {"review_id", "scope", "status", "reviewed_by"},
        ),
        "supplemental_appendix": ({"title", "content"}, {"title", "content"}),
    }
    for field, (allowed, string_fields) in specifications.items():
        entries = content.get(field)
        if type(entries) is not list:
            errors.append(f"{field} must be an explicit list")
            continue
        for index, entry in enumerate(entries):
            label = f"{field}[{index}]"
            if type(entry) is not dict:
                errors.append(f"{label} must be an object")
                continue
            errors.extend(_required_keys(entry, allowed, label))
            errors.extend(_unknown_keys(entry, allowed, label))
            for name in sorted(string_fields):
                if not _nonempty(entry.get(name)):
                    errors.append(f"{label}.{name} must be a non-empty string")
            if field == "code_appendix":
                try:
                    safe_relative_path(entry.get("path"), f"{label}.path")
                except ValueError:
                    errors.append(f"{label}.path must be a safe relative path")
                digest = entry.get("sha256")
                if type(digest) is not str or _HASH_RE.fullmatch(digest) is None:
                    errors.append(f"{label}.sha256 must be a lowercase SHA-256 hash")
            if field == "ai_use_disclosure" and type(entry.get("human_verified")) is not bool:
                errors.append(f"{label}.human_verified must be boolean")
            if field == "human_review_records" and entry.get("status") not in (
                "pending", "confirmed", "rejected"
            ):
                errors.append(f"{label}.status must be pending, confirmed, or rejected")


def _narrative_strings(content: dict[str, object]) -> tuple[list[str], list[str]]:
    abstract_strings: list[str] = []
    body_strings: list[str] = []
    abstract = content.get("abstract")
    if type(abstract) is dict:
        intro = abstract.get("intro_sentences")
        if type(intro) is list:
            abstract_strings.extend(item for item in intro if type(item) is str)
        paragraphs = abstract.get("question_paragraphs")
        if type(paragraphs) is list:
            for paragraph in paragraphs:
                if type(paragraph) is dict:
                    abstract_strings.extend(
                        paragraph[field]
                        for field in ("leading_summary", "modeling_steps", "answer")
                        if type(paragraph.get(field)) is str
                    )
    sections = content.get("sections")
    if type(sections) is dict:
        for section in sections.values():
            if type(section) is not dict:
                continue
            if type(section.get("content")) is str:
                body_strings.append(section["content"])
            subsections = section.get("subsections")
            if type(subsections) is dict:
                for subsection in subsections.values():
                    if type(subsection) is dict and type(subsection.get("content")) is str:
                        body_strings.append(subsection["content"])
            questions = section.get("questions")
            if type(questions) is list:
                for question in questions:
                    if type(question) is not dict or type(question.get("subsections")) is not dict:
                        continue
                    for subsection in question["subsections"].values():
                        if type(subsection) is dict and type(subsection.get("content")) is str:
                            body_strings.append(subsection["content"])
    return abstract_strings, body_strings


def _validate_narrative(
    content: dict[str, object], claims: list[dict[str, object]], errors: list[str]
) -> None:
    abstract_strings, body_strings = _narrative_strings(content)
    supported_numbers = {
        match.group(0)
        for claim in claims
        for match in _NUMBER_RE.finditer(str(claim.get("statement", "")))
    }
    for text in abstract_strings + body_strings:
        for match in _NUMBER_RE.finditer(text):
            number = match.group(0)
            if number not in supported_numbers:
                errors.append(f"unsupported numerical claim in paper narrative: {number}")

    important_statements = [
        str(claim.get("statement", ""))
        for claim in claims
        if claim.get("important") is True
    ]
    for text in body_strings:
        for match in _BOLD_RE.finditer(text):
            emphasized = match.group(1)
            if not any(emphasized in statement for statement in important_statements):
                errors.append(
                    "textbf is allowed only in the abstract or an evidence-backed important claim"
                )


def validate_paper_content(
    content: object,
    *,
    evidence_root: Path | None = None,
) -> list[str]:
    """Return deterministic content, structure, and evidence errors."""

    if type(content) is not dict:
        return ["paper content must be an object"]
    strict_errors = strict_json_tree_errors(content)
    if strict_errors:
        return [f"paper content must be strict JSON: {strict_errors[0]}"]

    errors: list[str] = []
    root: Path | None = None
    if evidence_root is not None:
        try:
            root = _safe_root(evidence_root)
        except ValueError as error:
            return [str(error)]

    errors.extend(_required_keys(content, _REQUIRED_ROOT_FIELDS, "paper_content"))
    errors.extend(_unknown_keys(content, _ROOT_FIELDS, "paper_content"))
    if content.get("schema_version") != "1":
        errors.append('schema_version must be exactly "1"')
    if content.get("language") != "zh-CN":
        errors.append("language must be exactly zh-CN")

    questions = _validate_sections(content, errors)
    _validate_abstract(content, questions, errors)
    keywords = content.get("keywords")
    if type(keywords) is not list or not keywords or any(not _nonempty(item) for item in keywords):
        errors.append("keywords must be a non-empty string list")
    elif len(set(keywords)) != len(keywords):
        errors.append("keywords must be unique")
    _validate_symbols(content, errors)
    claims = _validate_claims(content, questions, root, errors)
    _validate_artifact_references(content, root, errors)
    english_allowed = _validate_requirement_manifests(content, root, errors)
    _validate_english(content, english_allowed, errors)
    _validate_simple_arrays(content, errors)
    _validate_narrative(content, claims, errors)
    return errors


def freeze_content(
    content: object,
    *,
    output_path: Path,
    evidence_root: Path,
) -> dict[str, object]:
    """Write canonical complete content only after current evidence validates."""

    errors = validate_paper_content(content, evidence_root=evidence_root)
    if errors:
        raise ValueError("paper content validation failed:\n- " + "\n- ".join(errors))
    if type(content) is not dict:  # Kept explicit for static type narrowing.
        raise ValueError("paper content validation failed: content must be an object")

    evidence: dict[str, str] = {}
    sources: list[tuple[object, object]] = []
    for claim in content["claims"]:
        sources.append((claim["source_path"], claim["source_hash"]))
    for field in ("figure_references", "table_references"):
        for reference in content[field]:
            sources.append((reference["manifest_path"], reference["manifest_hash"]))
    for reference in content["requirement_manifests"]:
        sources.append((reference["path"], reference["sha256"]))
    for path, digest in sources:
        if path in evidence and evidence[path] != digest:
            raise ValueError(f"paper content validation failed: conflicting hashes for {path}")
        evidence[path] = digest

    frozen: dict[str, object] = {
        "schema_version": "1",
        "status": "complete",
        "content": copy.deepcopy(content),
        "evidence": [
            {"path": path, "sha256": evidence[path]}
            for path in sorted(evidence)
        ],
    }
    atomic_write_json(Path(output_path), frozen)
    return frozen


__all__ = [
    "freeze_content",
    "question_ids",
    "referenced_figures",
    "referenced_tables",
    "validate_paper_content",
]
