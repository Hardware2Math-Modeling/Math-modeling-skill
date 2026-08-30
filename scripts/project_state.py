#!/usr/bin/env python3
"""Create and evolve immutable mathematical-modeling project evidence."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from uuid import uuid4

try:
    from .authorization_capability import verify_user_event as verify_host_user_event
except ImportError:  # direct script/module fallback
    from authorization_capability import verify_user_event as verify_host_user_event
from handoff_schema import (
    GATE_REQUIRED_SCOPE_KINDS,
    GATE_SCOPE_KINDS,
    load_and_validate,
    load_json_strict,
    user_event_challenge_sha256,
    validate_document,
)
from manifest import (
    atomic_write_json,
    relative_regular_files,
    safe_relative_path,
    sha256_file,
    utc_now,
)
from suite_validation import ensure_no_symlink_components


SCHEMA_VERSION = "2"
GATE_IDS = ("gate1", "gate2", "gate3")
GATE_STATUSES = ("pending", "confirmed", "rejected")
ROLLBACK_STAGES = {
    "gate1": "problem-analysis",
    "gate2": "model-construction",
    "gate3": "validation",
}
ITERATION_DIRECTORIES = (
    "state",
    "code",
    "data",
    "results",
    "figures",
    "paper",
    "manifests",
)
STALE_ARTIFACTS = ("run", "figure", "validation", "paper")
_ITERATION_RE = re.compile(r"^v([0-9]{3,})$")
_QUESTION_RE = re.compile(r"\bQ([1-9][0-9]*)\b", re.IGNORECASE)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _absolute_path(path: Path, label: str, *, must_exist: bool = False) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    if any(part == ".." for part in candidate.parts):
        raise ValueError(f"{label} must not contain '..' components")
    safe = ensure_no_symlink_components(candidate, label)
    if must_exist and not safe.exists():
        raise ValueError(f"{label} does not exist: {safe}")
    return safe


def _directory(path: Path, label: str) -> Path:
    safe = _absolute_path(path, label, must_exist=True)
    try:
        mode = safe.lstat().st_mode
    except OSError as error:
        raise ValueError(f"{label} cannot be inspected: {safe}") from error
    if not stat.S_ISDIR(mode):
        raise ValueError(f"{label} must be a directory: {safe}")
    return safe


def _regular_file(path: Path, label: str) -> Path:
    safe = _absolute_path(path, label, must_exist=True)
    try:
        mode = safe.lstat().st_mode
    except OSError as error:
        raise ValueError(f"{label} cannot be inspected: {safe}") from error
    if not stat.S_ISREG(mode):
        raise ValueError(f"{label} must be a regular file: {safe}")
    return safe


def _output_file(path: Path, label: str) -> Path:
    """Preflight an output that may be absent or an existing regular file."""

    safe = _absolute_path(path, label)
    _directory(safe.parent, f"{label} parent")
    try:
        mode = safe.lstat().st_mode
    except FileNotFoundError:
        return safe
    except OSError as error:
        raise ValueError(f"{label} cannot be inspected: {safe}") from error
    if not stat.S_ISREG(mode):
        raise ValueError(
            f"{label} must be absent or an existing regular non-symlink file: {safe}"
        )
    return safe


def _validate_payload(payload: object, kind: str) -> dict[str, object]:
    errors = validate_document(payload, kind=kind)
    if errors:
        raise ValueError(f"invalid {kind} document:\n- " + "\n- ".join(errors))
    assert type(payload) is dict
    return payload


def _write_validated_json(path: Path, payload: object, kind: str) -> None:
    atomic_write_json(path, _validate_payload(payload, kind))


def _mtime_utc(path: Path) -> str:
    timestamp = path.stat(follow_symlinks=False).st_mtime
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _copy_regular_tree(source: Path, destination: Path) -> tuple[Path, ...]:
    source_files = relative_regular_files(source)
    destination.mkdir()
    for relative in source_files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target, follow_symlinks=False)
    return tuple(source_files)


def _question_ids(input_dir: Path, input_files: Sequence[Path]) -> list[str]:
    values: set[int] = set()
    for relative in input_files:
        try:
            text = (input_dir / relative).read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            continue
        values.update(int(match.group(1)) for match in _QUESTION_RE.finditer(text))
    return [f"Q{number}" for number in sorted(values)]


def _input_manifest(project_root: Path, input_files: Sequence[Path], created_at: str) -> dict[str, object]:
    entries = []
    for relative in input_files:
        copied = project_root / "input" / relative
        entries.append(
            {
                "path": f"input/{relative.as_posix()}",
                "byte_size": copied.stat(follow_symlinks=False).st_size,
                "modified_at": _mtime_utc(copied),
                "sha256": sha256_file(copied),
                "source_label": "input_dir",
                "read_only": True,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": "input",
        "created_at": created_at,
        "entries": entries,
    }


def _create_iteration_layout(path: Path) -> None:
    path.mkdir()
    for directory in ITERATION_DIRECTORIES:
        (path / directory).mkdir()


def _copy_iteration_evidence(source: Path, destination: Path) -> None:
    _directory(source, "parent iteration")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"iteration target already exists: {destination}")
    relative_regular_files(source)
    shutil.copytree(source, destination, symlinks=False)
    relative_regular_files(destination)


def _project_id(project_root: Path) -> str:
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", project_root.name).strip("-._")
    if not label:
        label = "modeling-project"
    return f"{label}-{uuid4().hex}"


def init_project(
    project_root: Path,
    *,
    python_executable: Path,
    input_dir: Path,
    template_path: Path | None,
    competition: str = "CUMCM",
) -> dict[str, object]:
    """Create a new project and return its canonical current.json payload."""

    project = _absolute_path(project_root, "project root")
    if project.exists() or project.is_symlink():
        raise FileExistsError(f"project root already exists: {project}")
    python = _regular_file(python_executable, "Python executable")
    if not os.access(python, os.X_OK):
        raise ValueError(f"Python executable is not executable: {python}")
    source_input = _directory(input_dir, "input directory")
    if project.is_relative_to(source_input):
        raise ValueError("project root must not be inside the input directory")
    if type(competition) is not str or not competition.strip():
        raise ValueError("competition must be a non-empty string")
    template = _regular_file(template_path, "template path") if template_path is not None else None
    template_name = (
        safe_relative_path(template.name, "template basename")
        if template is not None
        else None
    )

    input_files = relative_regular_files(source_input)
    if not input_files:
        raise ValueError("input directory must contain at least one regular file")
    questions = _question_ids(source_input, input_files)
    created_at = utc_now()

    project.mkdir()
    try:
        (project / "iterations").mkdir()
        (project / "qa").mkdir()
        (project / "archive").mkdir()
        copied_files = _copy_regular_tree(source_input, project / "input")
        iteration = project / "iterations/v001"
        _create_iteration_layout(iteration)

        if template is not None:
            assert template_name is not None
            template_dir = iteration / "paper/template-source"
            template_dir.mkdir()
            shutil.copyfile(template, template_dir / template_name, follow_symlinks=False)

        manifest = _input_manifest(project, copied_files, created_at)
        _write_validated_json(iteration / "manifests/input_manifest.json", manifest, "manifest")
        initialization = {
            "schema_version": SCHEMA_VERSION,
            "competition": competition.strip(),
            "python_executable": os.fspath(python),
            "template_path": (
                f"iterations/v001/paper/template-source/{template_name.as_posix()}"
                if template_name is not None
                else None
            ),
            "created_at": created_at,
        }
        _write_validated_json(
            iteration / "state/initialization.json",
            initialization,
            "initialization",
        )
        current: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "project_id": _project_id(project),
            "active_iteration": "v001",
            "question_sources": {question: "v001" for question in questions},
            "gates": {gate: "pending" for gate in GATE_IDS},
            "status": "in_progress",
            "updated_at": created_at,
        }
        _write_validated_json(project / "current.json", current, "iteration")
    except BaseException:
        shutil.rmtree(project)
        raise
    return current


def load_current(project_root: Path) -> dict[str, object]:
    """Load and validate the current pointer."""

    project = _directory(project_root, "project root")
    current_path = _regular_file(project / "current.json", "current pointer")
    current = load_and_validate(current_path, kind="iteration")
    iteration = _directory(
        project / "iterations" / str(current["active_iteration"]),
        "active iteration",
    )
    if not iteration.is_relative_to(project):
        raise ValueError("active iteration escapes the project root")
    sources = current["question_sources"]
    assert type(sources) is dict
    for source in sorted(set(sources.values())):
        _directory(project / "iterations" / str(source), "question source iteration")
    return current


def _next_iteration_name(iterations: Path) -> str:
    values = []
    for entry in iterations.iterdir():
        match = _ITERATION_RE.fullmatch(entry.name)
        if match:
            values.append(int(match.group(1)))
    next_value = max(values, default=0) + 1
    return f"v{next_value:03d}"


def _normalized_questions(values: Sequence[str], current: dict[str, object]) -> list[str]:
    if type(values) not in (list, tuple):
        raise ValueError("affected questions must be a sequence")
    normalized: set[int] = set()
    known = current["question_sources"]
    assert type(known) is dict
    for value in values:
        if type(value) is not str or re.fullmatch(r"Q[1-9][0-9]*", value) is None:
            raise ValueError(f"invalid question id: {value!r}")
        if value not in known:
            raise ValueError(f"unknown question id: {value}")
        normalized.add(int(value[1:]))
    if not normalized:
        raise ValueError("affected questions must not be empty")
    return [f"Q{number}" for number in sorted(normalized)]


def create_iteration(
    project_root: Path,
    *,
    reason: str,
    affected_questions: Sequence[str],
) -> str:
    """Create and return the next immutable vNNN directory name."""

    project = _directory(project_root, "project root")
    if type(reason) is not str or not reason.strip():
        raise ValueError("iteration reason must be a non-empty string")
    current = load_current(project)
    affected = _normalized_questions(affected_questions, current)
    iterations = _directory(project / "iterations", "iterations directory")
    parent_name = str(current["active_iteration"])
    parent = _directory(iterations / parent_name, "parent iteration")
    version = _next_iteration_name(iterations)
    destination = iterations / version
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"iteration target already exists: {destination}")

    _copy_iteration_evidence(parent, destination)
    try:
        created_at = utc_now()
        audit = {
            "schema_version": SCHEMA_VERSION,
            "iteration": version,
            "parent": parent_name,
            "reason": reason.strip(),
            "affected_questions": affected,
            "created_at": created_at,
        }
        atomic_write_json(destination / "state/iteration.json", audit)
        snapshot_files = [
            relative
            for relative in relative_regular_files(destination)
            if relative != Path("manifests/iteration_manifest.json")
        ]
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "manifest_type": "run",
            "created_at": created_at,
            "entries": [
                {
                    "path": f"iterations/{version}/{relative.as_posix()}",
                    "sha256": sha256_file(destination / relative),
                    "kind": "iteration-snapshot",
                    "description": "Immutable iteration snapshot evidence; not a model computation run.",
                }
                for relative in snapshot_files
            ],
        }
        _write_validated_json(destination / "manifests/iteration_manifest.json", manifest, "manifest")

        sources = dict(current["question_sources"])
        for question in affected:
            sources[question] = version
        updated = dict(current)
        updated.update(
            {
                "active_iteration": version,
                "question_sources": sources,
                "status": "in_progress",
                "updated_at": created_at,
            }
        )
        _write_validated_json(project / "current.json", updated, "iteration")
    except BaseException:
        shutil.rmtree(destination)
        raise
    return version


def record_gate(
    project_root: Path,
    *,
    gate_id: str,
    status: str,
    confirmer: str | None,
    artifact_hashes: Sequence[str] = (),
    note: str,
    artifact_scope: Sequence[dict[str, object]] | None = None,
    confirmation_event_id: str | None = None,
    host_capability: object | None = None,
    confirmation: dict[str, object] | None = None,
) -> dict[str, object]:
    """Append one auditable gate record and return the updated gate report."""

    project = _directory(project_root, "project root")
    current = load_current(project)
    if type(gate_id) is not str or gate_id not in GATE_IDS:
        raise ValueError(f"unknown gate id: {gate_id!r}")
    if type(status) is not str or status not in GATE_STATUSES:
        raise ValueError(f"unknown gate status: {status!r}")
    if confirmer is not None and type(confirmer) is not str:
        raise ValueError("confirmer must be a string or null")
    if type(note) is not str:
        raise ValueError("note must be a string")
    if type(artifact_hashes) not in (list, tuple):
        raise ValueError("artifact hashes must be a sequence")
    hashes = list(artifact_hashes)
    if any(type(item) is not str or _HASH_RE.fullmatch(item) is None for item in hashes):
        raise ValueError("artifact hashes must contain SHA-256 digests")
    if len(set(hashes)) != len(hashes):
        raise ValueError("artifact hashes must not contain duplicates")
    if confirmation is not None:
        raise ValueError("self-authored confirmation dictionaries are non-authorizing")
    raw_scope = [] if artifact_scope is None else artifact_scope
    if type(raw_scope) not in (list, tuple):
        raise ValueError("gate artifact scope must be a sequence")
    normalized_scope: list[dict[str, object]] = []
    for index, item in enumerate(raw_scope):
        if type(item) is not dict or set(item) != {"path", "kind", "sha256"}:
            raise ValueError(f"gate artifact scope[{index}] fields are not exact")
        path = safe_relative_path(item.get("path"), f"gate artifact scope[{index}] path")
        kind = item.get("kind")
        digest = item.get("sha256")
        if type(kind) is not str or kind not in GATE_SCOPE_KINDS[gate_id]:
            raise ValueError(f"gate artifact scope[{index}] kind is not relevant to {gate_id}")
        if type(digest) is not str or _HASH_RE.fullmatch(digest) is None:
            raise ValueError(f"gate artifact scope[{index}] hash is invalid")
        normalized_scope.append(
            {"path": path.as_posix(), "kind": kind, "sha256": digest}
        )
    normalized_scope.sort(key=lambda item: (str(item["kind"]), str(item["path"])))
    if len({item["path"] for item in normalized_scope}) != len(normalized_scope):
        raise ValueError("gate artifact scope paths must be unique")
    scope_hashes = [str(item["sha256"]) for item in normalized_scope]
    if hashes != scope_hashes:
        raise ValueError("artifact hashes must exactly match the normalized gate artifact scope")
    if status == "confirmed":
        if (
            type(confirmation_event_id) is not str
            or not confirmation_event_id.strip()
            or host_capability is None
        ):
            raise ValueError(
                "confirmed gates require a trusted user event id and host capability"
            )
        missing_kinds = GATE_REQUIRED_SCOPE_KINDS[gate_id] - {
            str(item["kind"]) for item in normalized_scope
        }
        if missing_kinds:
            raise ValueError(
                f"gate artifact scope is missing required {gate_id} kinds: "
                + ", ".join(sorted(missing_kinds))
            )
        challenge = user_event_challenge_sha256(
            "gate-confirmation",
            {
                "schema_version": SCHEMA_VERSION,
                "gate_id": gate_id,
                "artifact_scope": normalized_scope,
            },
        )
        try:
            verified = verify_host_user_event(
                host_capability,
                event_id=confirmation_event_id,
                event_type="gate-confirmation",
                challenge_sha256=challenge,
            )
        except Exception as error:
            raise ValueError(f"trusted user event verification failed: {error}") from error
        if type(verified) is not dict:
            raise ValueError("trusted user event was not verified")
        validated_confirmation = _validate_payload(verified, "gate-confirmation")
        if (
            validated_confirmation.get("event_id") != confirmation_event_id
            or validated_confirmation.get("challenge_sha256") != challenge
        ):
            raise ValueError("trusted user event receipt does not bind this gate challenge")
        confirmed_by = validated_confirmation["actor_id"]
        assert type(confirmed_by) is str
        if confirmer is not None and confirmer.strip() != confirmed_by:
            raise ValueError("confirmer must exactly match the verified event actor")
        confirmation = copy.deepcopy(validated_confirmation)
    elif any(
        value is not None
        for value in (confirmation, confirmation_event_id, host_capability)
    ):
        raise ValueError("confirmation evidence is allowed only for a confirmed gate")

    timestamp = utc_now()
    record = {
        "schema_version": SCHEMA_VERSION,
        "gate_id": gate_id,
        "status": status,
        "artifact_scope": normalized_scope,
        "artifact_hashes": hashes,
        "notes": note,
        "rollback_stage": ROLLBACK_STAGES[gate_id] if status == "rejected" else None,
    }
    if status == "confirmed":
        assert confirmation is not None
        record.update(
            {
                "confirmed_by": confirmation["actor_id"],
                "confirmed_at": confirmation["occurred_at"],
                "confirmation": copy.deepcopy(confirmation),
            }
        )
    _validate_payload(record, "gate")

    qa = _directory(project / "qa", "QA directory")
    report_path = _output_file(qa / "gates.json", "gate report output")
    current_path = _output_file(project / "current.json", "current pointer output")
    if report_path.exists() or report_path.is_symlink():
        report = load_json_strict(report_path)
        if type(report) is not dict or set(report) != {"schema_version", "records"}:
            raise ValueError("invalid gate report structure")
        records = report.get("records")
        if type(records) is not list:
            raise ValueError("invalid gate report records")
        for previous in records:
            _validate_payload(previous, "gate")
        updated_report: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "records": [*records, record],
        }
    else:
        updated_report = {"schema_version": SCHEMA_VERSION, "records": [record]}

    gates = dict(current["gates"])
    gates[gate_id] = status
    updated_current = dict(current)
    updated_current.update({"gates": gates, "updated_at": timestamp})
    _validate_payload(updated_current, "iteration")

    atomic_write_json(report_path, updated_report)
    _write_validated_json(current_path, updated_current, "iteration")
    return updated_report


def _staleness_markdown(report: dict[str, object]) -> str:
    changed = report["changed_paths"]
    invalidated = report["invalidated"]
    assert type(changed) is list and type(invalidated) is dict
    lines = [
        "# Staleness Report",
        "",
        f"Status: {report['status']}",
        f"Recorded at: {report['recorded_at']}",
        "",
        "## Changed paths",
        "",
        *[f"- `{item}`" for item in changed],
        "",
        "## Invalidated artifacts",
        "",
    ]
    for question in sorted(invalidated, key=lambda value: int(value[1:])):
        artifacts = invalidated[question]
        assert type(artifacts) is list
        lines.append(f"- {question}: {', '.join(artifacts)}")
    lines.append("")
    return "\n".join(lines)


def _write_staleness_markdown(path: Path, content: str) -> None:
    safe = _output_file(path, "staleness Markdown output")
    parent = safe.parent
    temporary = parent / f".{safe.name}.{uuid4().hex}.tmp"
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, safe)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def mark_stale(
    project_root: Path,
    *,
    changed_paths: Sequence[str],
    question_ids: Sequence[str],
) -> dict[str, object]:
    """Propagate stale status to dependent artifacts without deleting evidence."""

    project = _directory(project_root, "project root")
    current = load_current(project)
    if type(changed_paths) not in (list, tuple) or not changed_paths:
        raise ValueError("changed paths must be a non-empty sequence")
    paths = sorted(
        {
            safe_relative_path(value, "changed path").as_posix()
            for value in changed_paths
        }
    )
    questions = _normalized_questions(question_ids, current)
    timestamp = utc_now()
    report: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "status": "stale",
        "recorded_at": timestamp,
        "changed_paths": paths,
        "invalidated": {question: list(STALE_ARTIFACTS) for question in questions},
    }
    markdown = _staleness_markdown(report)

    gates = {
        gate: ("stale" if status == "confirmed" else status)
        for gate, status in dict(current["gates"]).items()
    }
    updated_current = dict(current)
    updated_current.update(
        {"gates": gates, "status": "stale", "updated_at": timestamp}
    )
    _validate_payload(updated_current, "iteration")

    qa = _directory(project / "qa", "QA directory")
    json_path = _output_file(qa / "staleness.json", "staleness JSON output")
    markdown_path = _output_file(qa / "staleness.md", "staleness Markdown output")
    current_path = _output_file(project / "current.json", "current pointer output")

    atomic_write_json(json_path, report)
    _write_staleness_markdown(markdown_path, markdown)
    _write_validated_json(current_path, updated_current, "iteration")
    return report


def _absolute_cli_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("path must be absolute")
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage immutable modeling project state.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    initialize = subparsers.add_parser("init")
    initialize.add_argument("project_root", type=_absolute_cli_path)
    initialize.add_argument("--python-executable", required=True, type=_absolute_cli_path)
    initialize.add_argument("--input-dir", required=True, type=_absolute_cli_path)
    initialize.add_argument("--template-path", type=_absolute_cli_path)
    initialize.add_argument("--competition", default="CUMCM")

    iteration = subparsers.add_parser("new-iteration")
    iteration.add_argument("project_root", type=_absolute_cli_path)
    iteration.add_argument("--reason", required=True)
    iteration.add_argument("--question", action="append", required=True)

    gate = subparsers.add_parser("gate")
    gate.add_argument("project_root", type=_absolute_cli_path)
    gate.add_argument("--gate-id", required=True)
    gate.add_argument("--status", required=True)
    gate.add_argument("--confirmer")
    gate.add_argument("--artifact-hash", action="append", default=[])
    gate.add_argument(
        "--artifact-scope-file",
        type=_absolute_cli_path,
        help="Gate scope only; confirmed status also requires a process-local host capability.",
    )
    gate.add_argument("--note", default="")

    stale = subparsers.add_parser("stale")
    stale.add_argument("project_root", type=_absolute_cli_path)
    stale.add_argument("--changed-path", action="append", required=True)
    stale.add_argument("--question", action="append", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        project = args.project_root
        if args.command == "init":
            init_project(
                project,
                python_executable=args.python_executable,
                input_dir=args.input_dir,
                template_path=args.template_path,
                competition=args.competition,
            )
            result = project / "current.json"
        elif args.command == "new-iteration":
            version = create_iteration(
                project,
                reason=args.reason,
                affected_questions=args.question,
            )
            result = project / "iterations" / version / "state/iteration.json"
        elif args.command == "gate":
            artifact_scope = None
            if args.artifact_scope_file is not None:
                raw_scope = load_json_strict(
                    _regular_file(args.artifact_scope_file, "gate artifact scope file")
                )
                if type(raw_scope) is not list:
                    raise ValueError("gate artifact scope file must contain an array")
                artifact_scope = raw_scope
            record_gate(
                project,
                gate_id=args.gate_id,
                status=args.status,
                confirmer=args.confirmer,
                artifact_hashes=args.artifact_hash,
                artifact_scope=artifact_scope,
                note=args.note,
            )
            result = project / "qa/gates.json"
        else:
            mark_stale(
                project,
                changed_paths=args.changed_path,
                question_ids=args.question,
            )
            result = project / "qa/staleness.json"
    except (OSError, TypeError, ValueError) as error:
        print(f"project state failed: {error}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
