#!/usr/bin/env python3
"""Diagnose one user-supplied modeling environment without changing it."""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Sequence

from suite_validation import ensure_no_symlink_components, ensure_outside_plugin_root


_PYTHON_PROBE = "import sys; print(sys.executable); print(sys.version)"
_LATEX_TOOLS = ("tectonic", "latexmk", "xelatex", "pdflatex")
_PACKAGE_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_PROBE_TIMEOUT_SECONDS = 15


def _absolute_path(path: Path, label: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    if any(part == ".." for part in candidate.parts):
        raise ValueError(f"{label} must not contain '..' components")
    return ensure_no_symlink_components(candidate, label)


def _directory(path: Path, label: str) -> Path:
    safe = _absolute_path(path, label)
    try:
        mode = safe.lstat().st_mode
    except OSError as error:
        raise ValueError(f"{label} must be an existing directory: {safe}") from error
    if not stat.S_ISDIR(mode):
        raise ValueError(f"{label} must be a directory: {safe}")
    return safe


def _regular_file(path: Path, label: str) -> Path:
    safe = _absolute_path(path, label)
    try:
        mode = safe.lstat().st_mode
    except OSError as error:
        raise ValueError(f"{label} must be an existing regular file: {safe}") from error
    if not stat.S_ISREG(mode):
        raise ValueError(f"{label} must be a regular non-symlink file: {safe}")
    return safe


def _run_probe(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_PROBE_TIMEOUT_SECONDS,
    )


def _python_report(python: Path) -> dict[str, object]:
    command = [str(python), "-c", _PYTHON_PROBE]
    try:
        completed = _run_probe(command)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "status": "error",
            "path": str(python),
            "resolved_path": str(python.resolve(strict=True)),
            "reported_executable": None,
            "version": None,
            "platform": platform.platform(),
            "error": str(error),
        }

    lines = completed.stdout.splitlines()
    reported = lines[0].strip() if lines else ""
    version = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    identity_matches = False
    if reported:
        try:
            identity_matches = Path(reported).resolve(strict=True) == python.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            identity_matches = False
    status = "pass" if completed.returncode == 0 and reported and version and identity_matches else "error"
    error = None
    if status == "error":
        error = completed.stderr.strip() or "supplied interpreter did not report the same executable identity"
    return {
        "status": status,
        "path": str(python),
        "resolved_path": str(python.resolve(strict=True)),
        "reported_executable": reported or None,
        "version": version or None,
        "platform": platform.platform(),
        "error": error,
    }


def _package_reports(python: Path, packages: Sequence[str]) -> list[dict[str, object]]:
    reports: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, package in enumerate(packages):
        if type(package) is not str or not _PACKAGE_RE.fullmatch(package):
            raise ValueError(f"required package {index} must be a distribution name")
        normalized = package.casefold()
        if normalized in seen:
            raise ValueError(f"duplicate required package: {package}")
        seen.add(normalized)
        code = f"import importlib.metadata as m; print(m.version({json.dumps(package)}))"
        try:
            completed = _run_probe([str(python), "-c", code])
        except (OSError, subprocess.TimeoutExpired) as error:
            completed = None
            probe_error = str(error)
        else:
            probe_error = completed.stderr.strip()
        if completed is not None and completed.returncode == 0 and completed.stdout.strip():
            reports.append(
                {
                    "name": package,
                    "status": "available",
                    "version": completed.stdout.strip(),
                    "install_command": None,
                    "error": None,
                }
            )
        elif (
            completed is not None
            and "importlib.metadata.PackageNotFoundError" in completed.stderr
        ):
            reports.append(
                {
                    "name": package,
                    "status": "missing",
                    "version": None,
                    "install_command": shlex.join(
                        [str(python), "-m", "pip", "install", package]
                    ),
                    "error": probe_error or "distribution metadata was not found",
                }
            )
        else:
            reports.append(
                {
                    "name": package,
                    "status": "error",
                    "version": None,
                    "install_command": None,
                    "error": probe_error or "package metadata probe failed without an error message",
                }
            )
    return reports


def _tool_version(path: Path) -> tuple[str | None, str | None]:
    try:
        completed = _run_probe([str(path), "--version"])
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, str(error)
    output = completed.stdout.strip() or completed.stderr.strip()
    first_line = output.splitlines()[0] if output else None
    if completed.returncode != 0:
        return first_line, f"version probe exited {completed.returncode}"
    return first_line, None


def _latex_report(paper_production: bool) -> dict[str, object]:
    tools: list[dict[str, object]] = []
    selected: str | None = None
    for name in _LATEX_TOOLS:
        discovered = shutil.which(name)
        if discovered is None:
            tools.append({"name": name, "status": "missing", "path": None, "version": None})
            continue
        try:
            path = Path(discovered).resolve(strict=True)
            mode = path.stat(follow_symlinks=False).st_mode
            if not stat.S_ISREG(mode) or not os.access(path, os.X_OK):
                raise OSError("discovered path is not an executable regular file")
            version, error = _tool_version(path)
        except (OSError, RuntimeError, ValueError) as probe_error:
            tools.append(
                {
                    "name": name,
                    "status": "error",
                    "path": discovered,
                    "version": None,
                    "error": str(probe_error),
                }
            )
            continue
        status = "available" if error is None else "error"
        tool: dict[str, object] = {
            "name": name,
            "status": status,
            "path": str(path),
            "version": version,
        }
        if error is not None:
            tool["error"] = error
        tools.append(tool)
        if selected is None and status == "available":
            selected = name

    if selected is not None:
        status = "pass"
        message = f"selected the first available LaTeX tool: {selected}"
    elif paper_production:
        status = "blocking"
        message = "paper production requires one available LaTeX tool"
    else:
        status = "warning"
        message = "no LaTeX tool is available; result-only work may continue"
    return {"status": status, "selected": selected, "tools": tools, "message": message}


def _template_report(template_path: Path | None) -> dict[str, object]:
    if template_path is None:
        return {
            "status": "fallback_non_submission",
            "requested_path": None,
            "resolved_path": None,
            "message": "no user template was supplied; use an explicit non-submission fallback",
        }
    safe = _absolute_path(template_path, "template path")
    try:
        mode = safe.lstat().st_mode
    except FileNotFoundError:
        return {
            "status": "fallback_non_submission",
            "requested_path": str(safe),
            "resolved_path": None,
            "message": "the requested user template is missing; use an explicit non-submission fallback",
        }
    except OSError as error:
        raise ValueError(f"template path cannot be inspected: {safe}") from error
    if not stat.S_ISREG(mode):
        raise ValueError(f"template path must be a regular non-symlink file: {safe}")
    return {
        "status": "user_provided",
        "requested_path": str(safe),
        "resolved_path": str(safe.resolve(strict=True)),
        "message": "user template is available",
    }


def diagnose_environment(
    *,
    project_root: Path,
    python_executable: Path,
    required_packages: Sequence[str],
    template_path: Path | None,
    paper_production: bool = False,
) -> dict[str, object]:
    """Inspect exactly one supplied Python environment and return diagnostics."""

    if type(paper_production) is not bool:
        raise ValueError("paper_production must be a boolean")
    project = ensure_outside_plugin_root(
        _directory(project_root, "project root"),
        "project root",
    )
    python = _regular_file(python_executable, "Python executable")
    if not os.access(python, os.X_OK):
        raise ValueError(f"Python executable is not executable: {python}")
    if isinstance(required_packages, (str, bytes)):
        raise ValueError("required_packages must be a sequence of distribution names")

    python_report = _python_report(python)
    packages = _package_reports(python, required_packages) if python_report["status"] == "pass" else []
    latex = _latex_report(paper_production)
    template = _template_report(template_path)

    blockers: list[str] = []
    warnings: list[str] = []
    if python_report["status"] != "pass":
        blockers.append("the supplied Python interpreter failed its identity/version probe")
    for package in packages:
        if package["status"] == "missing":
            blockers.append(f"required Python package is missing: {package['name']}")
        elif package["status"] == "error":
            blockers.append(f"required Python package diagnostic failed: {package['name']}")
    if latex["status"] == "blocking":
        blockers.append(str(latex["message"]))
    elif latex["status"] == "warning":
        warnings.append(str(latex["message"]))
    if template["status"] == "fallback_non_submission":
        warnings.append(str(template["message"]))

    status = "blocking" if blockers else "warning" if warnings else "pass"
    return {
        "status": status,
        "project_root": str(project),
        "python": python_report,
        "packages": packages,
        "latex": latex,
        "template": template,
        "blockers": blockers,
        "warnings": warnings,
    }
