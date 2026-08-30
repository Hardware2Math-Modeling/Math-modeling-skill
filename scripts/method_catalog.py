#!/usr/bin/env python3
"""Validate and smoke-test the maintained mathematical-method catalog."""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import re
import stat
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse

from handoff_schema import strict_json_tree_errors
from manifest import atomic_write_json, safe_relative_path
from python_runner import run_python
from suite_validation import ensure_no_symlink_components, ensure_outside_plugin_root


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
LIBRARY_RELATIVE = Path("skills/math-modeling-method-library")
CATALOG_RELATIVE = LIBRARY_RELATIVE / "references/catalog.json"
FIXTURE_RELATIVE = LIBRARY_RELATIVE / "assets/fixtures/method-smoke.json"
TEMPLATES_RELATIVE = LIBRARY_RELATIVE / "assets/templates"
METHODS_RELATIVE = LIBRARY_RELATIVE / "references/methods"

EXPECTED_FAMILIES = (
    "优化与决策",
    "预测、回归与时间序列",
    "综合评价与多指标决策",
    "统计分析与数据处理",
    "机器学习、分类、聚类与降维",
    "图论与网络",
    "机理模型与数值分析",
    "随机模拟与不确定性",
    "博弈与多主体决策",
    "几何、空间与信号",
)
REQUIRED_FIELDS = (
    "id",
    "family",
    "name_zh",
    "trigger_conditions",
    "assumptions",
    "inputs",
    "formula",
    "scale_limit",
    "template",
    "dependencies",
    "failure_signals",
    "validation",
    "figure_roles",
    "paper_notes",
    "license_notes",
)
ALLOWED_DEPENDENCIES = {
    "numpy",
    "pandas",
    "scipy",
    "matplotlib",
    "scikit-learn",
    "statsmodels",
    "networkx",
    "openpyxl",
}
ALLOWED_FIGURE_ROLES = {"evidence", "validation", "diagnostic", "conceptual"}
_IMPORT_TO_DISTRIBUTION = {"sklearn": "scikit-learn"}
_METHOD_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_LICENSE_KEYS = {"source_url", "source_license", "template_license", "copy_policy"}
_FIGURE_KEYS = {"role", "description", "claim_supporting"}
_INPUT_KEYS = {"name", "meaning", "units"}


def _root_path(root: Path | None) -> Path:
    candidate = DEFAULT_ROOT if root is None else Path(root)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    safe = ensure_no_symlink_components(candidate, "suite root")
    try:
        mode = safe.lstat().st_mode
    except OSError as error:
        raise ValueError(f"suite root must be an existing directory: {safe}") from error
    if not stat.S_ISDIR(mode):
        raise ValueError(f"suite root must be a directory: {safe}")
    return safe


def _strict_json(path: Path, label: str) -> object:
    safe = ensure_no_symlink_components(path, label)
    try:
        mode = safe.lstat().st_mode
    except OSError as error:
        raise ValueError(f"missing {label}: {safe}") from error
    if not stat.S_ISREG(mode):
        raise ValueError(f"{label} must be a regular non-symlink file")

    def reject_constant(value: str) -> object:
        raise ValueError(f"{label} contains non-finite JSON constant: {value}")

    try:
        return json.loads(
            safe.read_text(encoding="utf-8"),
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid UTF-8 JSON in {label}: {error}") from error


def load_catalog(root: Path | None = None) -> list[dict[str, Any]]:
    """Load the catalog from ``root`` without modifying repository resources."""

    suite = _root_path(root)
    payload = _strict_json(suite / CATALOG_RELATIVE, "method catalog")
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("method catalog must be a JSON array of objects")
    return payload


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(_nonempty_string(item) for item in value)


def _template_imports(path: Path) -> tuple[set[str], str | None]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as error:
        return set(), str(error)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    return imports, None


def _validate_entry(
    suite: Path,
    item: dict[str, Any],
    index: int,
    errors: list[str],
) -> None:
    label = f"catalog entry {index}"
    missing = sorted(set(REQUIRED_FIELDS) - set(item))
    extra = sorted(set(item) - set(REQUIRED_FIELDS))
    if missing:
        errors.append(f"{label} missing fields: {', '.join(missing)}")
    if extra:
        errors.append(f"{label} unsupported fields: {', '.join(extra)}")

    method_id = item.get("id")
    if not _nonempty_string(method_id) or not _METHOD_ID_RE.fullmatch(method_id):
        errors.append(f"{label} id must be lower hyphen-case")
        method_id = f"entry-{index}"
    family = item.get("family")
    if family not in EXPECTED_FAMILIES:
        errors.append(f"{label} unknown family: {family!r}")
    if not _nonempty_string(item.get("name_zh")):
        errors.append(f"{label} name_zh must be a nonempty string")
    for field in ("trigger_conditions", "assumptions", "failure_signals", "validation"):
        if not _string_list(item.get(field)):
            errors.append(f"{label} {field} must be a nonempty string array")
    for field in ("formula", "scale_limit", "paper_notes"):
        if not _nonempty_string(item.get(field)):
            errors.append(f"{label} {field} must be a nonempty string")

    inputs = item.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        errors.append(f"{label} inputs must be a nonempty array")
    else:
        for input_index, input_item in enumerate(inputs):
            if not isinstance(input_item, dict) or set(input_item) != _INPUT_KEYS:
                errors.append(
                    f"{label} input {input_index} must contain name, meaning, and units"
                )
            elif not all(_nonempty_string(input_item[key]) for key in _INPUT_KEYS):
                errors.append(f"{label} input {input_index} values must be nonempty strings")

    dependencies = item.get("dependencies")
    if not isinstance(dependencies, list) or any(not _nonempty_string(value) for value in dependencies):
        errors.append(f"{label} dependencies must be a string array")
        declared: set[str] = set()
    else:
        declared = set(dependencies)
        if len(declared) != len(dependencies):
            errors.append(f"{label} dependencies must not contain duplicates")
        unsupported = sorted(declared - ALLOWED_DEPENDENCIES)
        if unsupported:
            errors.append(f"{label} unsupported dependencies: {', '.join(unsupported)}")

    figures = item.get("figure_roles")
    if not isinstance(figures, list) or not figures:
        errors.append(f"{label} figure_roles must be a nonempty array")
    else:
        for figure_index, figure in enumerate(figures):
            if not isinstance(figure, dict) or set(figure) != _FIGURE_KEYS:
                errors.append(
                    f"{label} figure role {figure_index} must contain role, description, and claim_supporting"
                )
                continue
            if figure["role"] not in ALLOWED_FIGURE_ROLES:
                errors.append(f"{label} figure role {figure_index} is outside the closed vocabulary")
            if not _nonempty_string(figure["description"]):
                errors.append(f"{label} figure role {figure_index} description must be nonempty")
            if type(figure["claim_supporting"]) is not bool:
                errors.append(f"{label} figure role {figure_index} claim_supporting must be boolean")

    notes = item.get("license_notes")
    if not isinstance(notes, dict) or set(notes) != _LICENSE_KEYS:
        errors.append(f"{label} license_notes must contain source and original-template terms")
    else:
        parsed = urlparse(notes.get("source_url", ""))
        if parsed.scheme != "https" or parsed.netloc != "github.com" or not parsed.path.strip("/"):
            errors.append(f"{label} license_notes source_url must be an HTTPS GitHub URL")
        if not _nonempty_string(notes.get("source_license")) or notes["source_license"].casefold() == "unknown":
            errors.append(f"{label} license_notes source_license must be known")
        if notes.get("template_license") != "MIT":
            errors.append(f"{label} license_notes template_license must be MIT")
        copy_policy = notes.get("copy_policy")
        if not _nonempty_string(copy_policy) or "original" not in copy_policy.casefold():
            errors.append(f"{label} license_notes copy_policy must require an original implementation")

    raw_template = item.get("template")
    try:
        relative = safe_relative_path(raw_template, f"{label} template")
    except ValueError:
        errors.append(f"{label} unsafe template path: {raw_template!r}")
        return
    if len(relative.parts) != 1 or relative.suffix != ".py":
        errors.append(f"{label} unsafe template path: {raw_template!r}")
        return
    if relative.name != f"{method_id}.py":
        errors.append(f"{label} template must be named {method_id}.py")
    template = suite / TEMPLATES_RELATIVE / relative
    try:
        safe_template = ensure_no_symlink_components(template, f"{label} template")
        mode = safe_template.lstat().st_mode
    except (OSError, ValueError) as error:
        errors.append(f"{label} template must be an existing safe regular file: {error}")
        return
    if not stat.S_ISREG(mode):
        errors.append(f"{label} template must be an existing safe regular file")
        return
    imports, syntax_error = _template_imports(safe_template)
    if syntax_error is not None:
        errors.append(f"{label} template is not valid Python: {syntax_error}")
        return
    external_imports = {
        _IMPORT_TO_DISTRIBUTION.get(name, name)
        for name in imports
        if name not in sys.stdlib_module_names and name != "__future__"
    }
    undeclared = sorted(external_imports - declared)
    if undeclared:
        errors.append(f"{label} undeclared dependency: {', '.join(undeclared)}")
    unused = sorted(declared - external_imports)
    if unused:
        errors.append(f"{label} declares dependencies not imported by its template: {', '.join(unused)}")

    reference = suite / METHODS_RELATIVE / f"{method_id}.md"
    try:
        reference_mode = ensure_no_symlink_components(
            reference, f"{label} method reference"
        ).lstat().st_mode
    except (OSError, ValueError) as error:
        errors.append(f"{label} method reference must be an existing safe regular file: {error}")
    else:
        if not stat.S_ISREG(reference_mode):
            errors.append(f"{label} method reference must be an existing safe regular file")


def _validate_fixture(suite: Path, ids: set[str], errors: list[str]) -> None:
    try:
        payload = _strict_json(suite / FIXTURE_RELATIVE, "method smoke fixture")
    except ValueError as error:
        errors.append(str(error))
        return
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "fixtures"}:
        errors.append("method smoke fixture must contain schema_version and fixtures")
        return
    if payload.get("schema_version") != "1":
        errors.append('method smoke fixture schema_version must be "1"')
    fixtures = payload.get("fixtures")
    if not isinstance(fixtures, list) or not all(isinstance(item, dict) for item in fixtures):
        errors.append("method smoke fixtures must be an array of objects")
        return
    fixture_ids: list[str] = []
    for index, fixture in enumerate(fixtures):
        if set(fixture) != {"method_id", "label", "data"}:
            errors.append(f"method smoke fixture {index} must contain method_id, label, and data")
            continue
        fixture_ids.append(fixture["method_id"])
        if fixture["label"] != "test data":
            errors.append(f"method smoke fixture {index} label must be test data")
        if not isinstance(fixture["data"], dict):
            errors.append(f"method smoke fixture {index} data must be an object")
    if len(fixture_ids) != len(set(fixture_ids)):
        errors.append("method smoke fixtures contain duplicate method ids")
    missing = sorted(ids - set(fixture_ids))
    unknown = sorted(set(fixture_ids) - ids)
    if missing:
        errors.append("method smoke fixtures missing ids: " + ", ".join(missing))
    if unknown:
        errors.append("method smoke fixtures contain unknown ids: " + ", ".join(unknown))


def validate_catalog(root: Path | None = None) -> list[str]:
    """Return all catalog, provenance, path, dependency, and fixture errors."""

    try:
        suite = _root_path(root)
        catalog = load_catalog(suite)
    except ValueError as error:
        return [str(error)]
    errors: list[str] = []
    for index, item in enumerate(catalog):
        _validate_entry(suite, item, index, errors)
    ids = [item.get("id") for item in catalog if isinstance(item.get("id"), str)]
    duplicates = sorted(method_id for method_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append("duplicate id: " + ", ".join(duplicates))
    families = Counter(item.get("family") for item in catalog)
    if len(catalog) != 30:
        errors.append(f"catalog must contain exactly 30 entries, found {len(catalog)}")
    for family in EXPECTED_FAMILIES:
        if families[family] != 3:
            errors.append(f"family {family} must contain exactly 3 entries")

    try:
        template_names = {
            path.name
            for path in (suite / TEMPLATES_RELATIVE).iterdir()
            if path.is_file() and path.suffix == ".py"
        }
        reference_names = {
            path.name
            for path in (suite / METHODS_RELATIVE).iterdir()
            if path.is_file() and path.suffix == ".md"
        }
    except OSError as error:
        errors.append(f"unable to enumerate method assets: {error}")
    else:
        expected_templates = {f"{method_id}.py" for method_id in ids}
        expected_references = {f"{method_id}.md" for method_id in ids}
        if template_names != expected_templates:
            errors.append("template file set must match catalog ids exactly")
        if reference_names != expected_references:
            errors.append("method reference file set must match catalog ids exactly")
    _validate_fixture(suite, set(ids), errors)
    return errors


def _load_fixtures(suite: Path) -> dict[str, dict[str, Any]]:
    payload = _strict_json(suite / FIXTURE_RELATIVE, "method smoke fixture")
    return {item["method_id"]: item for item in payload["fixtures"]}


def _python_path(path: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError("Python executable must be an absolute path")
    if any(part == ".." for part in candidate.parts):
        raise ValueError("Python executable must not contain '..' components")
    safe = ensure_no_symlink_components(candidate, "Python executable")
    try:
        mode = safe.lstat().st_mode
    except OSError as error:
        raise ValueError(f"Python executable must be an existing regular file: {safe}") from error
    if not stat.S_ISREG(mode):
        raise ValueError(f"Python executable must be a regular non-symlink file: {safe}")
    if not os.access(safe, os.X_OK):
        raise ValueError(f"Python executable is not executable: {safe}")
    return safe


def _validate_result(method_id: str, result: object) -> dict[str, Any]:
    if not isinstance(result, dict) or set(result) != {"values", "metrics", "assumptions"}:
        raise ValueError(
            f"smoke output for {method_id} must contain exactly values, metrics, and assumptions"
        )
    if not isinstance(result["values"], list):
        raise ValueError(f"smoke output for {method_id} values must be an array")
    if not isinstance(result["metrics"], dict):
        raise ValueError(f"smoke output for {method_id} metrics must be an object")
    if not isinstance(result["assumptions"], list) or not all(
        isinstance(item, str) for item in result["assumptions"]
    ):
        raise ValueError(f"smoke output for {method_id} assumptions must be a string array")
    tree_errors = strict_json_tree_errors(result)
    if tree_errors:
        raise ValueError(
            f"smoke output for {method_id} is not strict finite JSON:\n- "
            + "\n- ".join(tree_errors)
        )
    return result


def run_smoke(
    root: Path | None = None,
    *,
    python_executable: Path,
    work_dir: Path,
    method_ids: Sequence[str] | None = None,
    seed: int = 0,
    timeout_seconds: int | float = 30,
) -> list[dict[str, Any]]:
    """Execute selected fixtures through ``python_runner`` and preserve evidence."""

    errors = validate_catalog(root)
    if errors:
        raise ValueError("invalid method catalog:\n- " + "\n- ".join(errors))
    suite = _root_path(root)
    python = _python_path(python_executable)
    workspace_candidate = Path(work_dir)
    if not workspace_candidate.is_absolute():
        raise ValueError("smoke work_dir must be an absolute path")
    workspace = ensure_outside_plugin_root(
        ensure_no_symlink_components(workspace_candidate, "smoke work_dir"),
        "smoke work_dir",
    )
    try:
        mode = workspace.lstat().st_mode
    except OSError as error:
        raise ValueError(f"smoke work_dir must be an existing directory: {workspace}") from error
    if not stat.S_ISDIR(mode):
        raise ValueError(f"smoke work_dir must be a directory: {workspace}")
    if any(workspace.iterdir()):
        raise ValueError(f"smoke work_dir must be empty: {workspace}")

    catalog = load_catalog(suite)
    by_id = {item["id"]: item for item in catalog}
    if method_ids is None:
        selected = [item["id"] for item in catalog]
    else:
        if isinstance(method_ids, (str, bytes)):
            raise ValueError("method_ids must be a sequence of catalog ids")
        selected = list(method_ids)
        if any(type(method_id) is not str for method_id in selected):
            raise ValueError("method_ids must contain catalog id strings")
        if len(selected) != len(set(selected)):
            raise ValueError("method_ids must not contain duplicates")
        unknown = sorted(set(selected) - set(by_id))
        if unknown:
            raise ValueError("unknown method id: " + ", ".join(unknown))
    fixtures = _load_fixtures(suite)
    records: list[dict[str, Any]] = []
    for method_id in selected:
        input_path = workspace / f"{method_id}.input.json"
        atomic_write_json(input_path, fixtures[method_id]["data"])
        output_dir = workspace / f"{method_id}.run"
        output_path = output_dir / "output.json"
        run = run_python(
            python,
            suite / TEMPLATES_RELATIVE / by_id[method_id]["template"],
            cwd=workspace,
            output_dir=output_dir,
            input_paths=[input_path],
            seed=seed,
            timeout_seconds=timeout_seconds,
            cli_mode="json_io",
            input_path=input_path,
            output_path=output_path,
        )
        result = _strict_json(output_path, f"smoke output for {method_id}")
        records.append(
            {
                "method_id": method_id,
                "result": _validate_result(method_id, result),
                "run": run,
            }
        )
    return records


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--python", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--method", action="append", dest="method_ids")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=30)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if not args.check and not args.smoke:
        parser.error("choose --check and/or --smoke")
    if args.check:
        errors = validate_catalog(args.root)
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            raise SystemExit(1)
        print(f"method catalog valid: {len(load_catalog(args.root))} entries")
    if args.smoke:
        if args.python is None or args.work_dir is None:
            parser.error("--smoke requires --python and --work-dir")
        records = run_smoke(
            args.root,
            python_executable=args.python,
            work_dir=args.work_dir,
            method_ids=args.method_ids,
            seed=args.seed,
            timeout_seconds=args.timeout,
        )
        print(json.dumps(records, ensure_ascii=False, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
