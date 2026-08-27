#!/usr/bin/env python3
"""Run one modeling script with reproducible process evidence."""

from __future__ import annotations

import math
import os
import stat
import subprocess
import time
from pathlib import Path
from typing import Sequence

from manifest import (
    atomic_write_json,
    relative_regular_files,
    safe_relative_path,
    sha256_file,
    sha256_paths,
    utc_now,
)
from suite_validation import ensure_no_symlink_components, ensure_outside_plugin_root


_CLI_MODES = ("json_io", "plain")
_RESERVED_OUTPUTS = {
    "command.json",
    "run_manifest.json",
    "stderr.log",
    "stdout.log",
}


class RunFailed(RuntimeError):
    """A completed or timed-out Python run that did not succeed."""

    def __init__(self, message: str, result: dict[str, object]) -> None:
        super().__init__(message)
        self.result = result


def _absolute_path(path: Path, label: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    if any(part == ".." for part in candidate.parts):
        raise ValueError(f"{label} must not contain '..' components")
    return ensure_no_symlink_components(candidate, label)


def _regular_file(path: Path, label: str) -> Path:
    safe = _absolute_path(path, label)
    try:
        mode = safe.lstat().st_mode
    except OSError as error:
        raise ValueError(f"{label} must be an existing regular file: {safe}") from error
    if not stat.S_ISREG(mode):
        raise ValueError(f"{label} must be a regular non-symlink file: {safe}")
    return safe


def _directory(path: Path, label: str) -> Path:
    safe = _absolute_path(path, label)
    try:
        mode = safe.lstat().st_mode
    except OSError as error:
        raise ValueError(f"{label} must be an existing directory: {safe}") from error
    if not stat.S_ISDIR(mode):
        raise ValueError(f"{label} must be a directory: {safe}")
    return safe


def _prepare_output_directory(path: Path, cwd: Path) -> Path:
    output = _absolute_path(path, "output directory")
    if not output.is_relative_to(cwd):
        raise ValueError("output directory must be inside cwd")
    if output == cwd:
        raise ValueError("output directory must not be cwd")
    try:
        mode = output.lstat().st_mode
    except FileNotFoundError:
        parent = output.parent
        while not parent.exists():
            parent = parent.parent
        _directory(parent, "output directory ancestor")
        return output
    except OSError as error:
        raise ValueError(f"output directory cannot be inspected: {output}") from error
    if not stat.S_ISDIR(mode):
        raise ValueError(f"output directory must be a directory: {output}")
    try:
        if any(output.iterdir()):
            raise ValueError(f"output directory must be empty: {output}")
    except OSError as error:
        raise ValueError(f"output directory cannot be inspected: {output}") from error
    return output


def _path_key(path: Path, cwd: Path) -> str:
    if path.is_relative_to(cwd):
        return safe_relative_path(path.relative_to(cwd).as_posix(), "evidence path").as_posix()
    return str(path)


def _timeout_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _write_text_evidence(path: Path, content: str) -> None:
    safe = _absolute_path(path, "log output")
    if safe.exists() or safe.is_symlink():
        raise ValueError(f"runner evidence path must be absent: {safe}")
    safe.write_text(content, encoding="utf-8")


def _persist_run(
    output_dir: Path,
    cwd: Path,
    command: list[str],
    controlled_environment: dict[str, str],
    stdout: str,
    stderr: str,
    result: dict[str, object],
) -> None:
    _directory(output_dir, "output directory")
    _write_text_evidence(output_dir / "stdout.log", stdout)
    _write_text_evidence(output_dir / "stderr.log", stderr)
    atomic_write_json(
        output_dir / "command.json",
        {
            "command": command,
            "cwd": str(cwd),
            "environment": controlled_environment,
            "shell": False,
        },
    )
    atomic_write_json(
        output_dir / "run_manifest.json",
        {
            "schema_version": "2",
            "manifest_type": "run",
            "created_at": utc_now(),
            "entries": [result],
        },
    )


def run_python(
    python_executable: Path,
    script: Path,
    *,
    cwd: Path,
    output_dir: Path,
    input_paths: Sequence[Path],
    seed: int,
    timeout_seconds: int | float,
    cli_mode: str = "plain",
    input_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, object]:
    """Run a script without a shell and return its run-manifest entry."""

    if cli_mode not in _CLI_MODES:
        raise ValueError("cli_mode must be 'json_io' or 'plain'")
    if type(seed) is not int or not 0 <= seed <= 4_294_967_295:
        raise ValueError("seed must be an integer from 0 through 4294967295")
    if (
        type(timeout_seconds) not in (int, float)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout_seconds must be a positive finite number")
    if isinstance(input_paths, (str, bytes)):
        raise ValueError("input_paths must be a sequence of paths")

    python = _regular_file(python_executable, "Python executable")
    if not os.access(python, os.X_OK):
        raise ValueError(f"Python executable is not executable: {python}")
    model_script = _regular_file(script, "Python script")
    project = ensure_outside_plugin_root(_directory(cwd, "cwd"), "cwd")
    output = _prepare_output_directory(output_dir, project)

    inputs: list[Path] = []
    seen_inputs: set[Path] = set()
    for index, path in enumerate(input_paths):
        item = _regular_file(path, f"input path {index}")
        if item in seen_inputs:
            raise ValueError(f"duplicate input path: {item}")
        seen_inputs.add(item)
        inputs.append(item)

    if cli_mode == "plain":
        if input_path is not None or output_path is not None:
            raise ValueError("plain mode does not accept input_path or output_path")
        command = [str(python), str(model_script)]
    else:
        if input_path is None:
            if len(inputs) != 1:
                raise ValueError("json_io mode requires input_path or exactly one input_paths entry")
            json_input = inputs[0]
        else:
            json_input = _regular_file(input_path, "json input path")
            if json_input not in seen_inputs:
                inputs.append(json_input)
                seen_inputs.add(json_input)
        json_output = (
            _absolute_path(output_path, "json output path")
            if output_path is not None
            else output / "output.json"
        )
        if not json_output.is_relative_to(output) or json_output == output:
            raise ValueError("json output path must be a file inside output_dir")
        if json_output.exists() or json_output.is_symlink():
            raise ValueError(f"json output path must be absent: {json_output}")
        command = [
            str(python),
            str(model_script),
            "--input",
            str(json_input),
            "--output",
            str(json_output),
            "--seed",
            str(seed),
        ]

    code_hash = sha256_file(model_script)
    input_hashes = {_path_key(path, project): sha256_file(path) for path in inputs}
    if output.exists():
        _directory(output, "output directory")
    else:
        output.mkdir(parents=True, exist_ok=False)
    controlled_environment = {"PYTHONHASHSEED": str(seed), "MPLBACKEND": "Agg"}
    environment = os.environ.copy()
    environment.update(controlled_environment)

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=str(project),
            env=environment,
            timeout=timeout_seconds,
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as error:
        exit_code: int | None = None
        status = "timeout"
        stdout = _timeout_text(error.stdout)
        stderr = _timeout_text(error.stderr)
    else:
        exit_code = completed.returncode
        status = "success" if completed.returncode == 0 else "failed"
        stdout = completed.stdout
        stderr = completed.stderr
    duration_seconds = round(time.monotonic() - started, 6)

    _directory(output, "output directory")
    failure_reason: str | None = None
    if cli_mode == "json_io" and status == "success":
        try:
            _regular_file(json_output, "declared JSON output")
        except ValueError as error:
            status = "failed"
            failure_reason = f"declared JSON output contract failed: {error}"
    try:
        produced = relative_regular_files(output)
        collisions = sorted(
            path.as_posix()
            for path in produced
            if path.as_posix() in _RESERVED_OUTPUTS
        )
        if collisions:
            raise ValueError(
                "script wrote reserved runner evidence paths: " + ", ".join(collisions)
            )
        output_hashes = sha256_paths(output, produced)
    except ValueError as error:
        if failure_reason is None:
            raise
        output_hashes = {}
        failure_reason += f"; output inspection failed: {error}"
    if cli_mode == "json_io" and status == "success":
        declared_key = safe_relative_path(
            json_output.relative_to(output).as_posix(),
            "declared JSON output",
        ).as_posix()
        if declared_key not in output_hashes:
            status = "failed"
            failure_reason = "declared JSON output is absent from output hashes"
    result: dict[str, object] = {
        "status": status,
        "python_executable": str(python),
        "script": _path_key(model_script, project),
        "cwd": str(project),
        "cli_mode": cli_mode,
        "command": command,
        "shell": False,
        "environment": controlled_environment,
        "code_hash": code_hash,
        "input_hashes": input_hashes,
        "output_hashes": output_hashes,
        "exit_code": exit_code,
        "seed": seed,
        "timeout_seconds": timeout_seconds,
        "duration_seconds": duration_seconds,
        "logs": {
            "stdout": _path_key(output / "stdout.log", project),
            "stderr": _path_key(output / "stderr.log", project),
        },
    }
    if failure_reason is not None:
        result["failure_reason"] = failure_reason
    _persist_run(
        output,
        project,
        command,
        controlled_environment,
        stdout,
        stderr,
        result,
    )
    if status == "timeout":
        raise RunFailed(f"Python run timed out after {timeout_seconds} seconds", result)
    if status == "failed":
        message = failure_reason or f"Python run exited with code {exit_code}"
        raise RunFailed(message, result)
    return result
