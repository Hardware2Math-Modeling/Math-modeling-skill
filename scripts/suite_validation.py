"""Validation helpers for the Math Modeling Codex plugin suite."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


PLUGIN_NAME = "math-modeling-suite"
ORCHESTRATOR_SKILL = "math-modeling-orchestrator"
STAGE_SKILLS = (
    "math-modeling-problem-analysis",
    "math-modeling-data-analysis",
    "math-modeling-model-construction",
    "math-modeling-model-solving",
    "math-modeling-validation",
    "math-modeling-paper-writing",
)
ALL_SKILLS = (ORCHESTRATOR_SKILL, *STAGE_SKILLS)
HANDOFF_REQUIRED_FIELDS = ("schema_version", "state", "result", "next")
HANDOFF_STATUSES = ("pending", "in_progress", "complete", "needs_revision", "skipped")

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
SKILL_NAME_RE = re.compile(r"^[a-z](?:[a-z0-9]*(?:-[a-z0-9]+)*)?$")
SCAFFOLD_RE = re.compile(r"\[(?:TODO|TBD):", re.IGNORECASE)

_MANIFEST_KEYS = {
    "id", "name", "version", "description", "author", "homepage", "repository",
    "license", "keywords", "skills", "interface",
}
_INTERFACE_STRING_FIELDS = (
    "displayName", "shortDescription", "longDescription", "developerName", "category",
)
_EXPECTED_TRANSITIONS = {
    "problem-analysis": ["data-analysis", "model-construction"],
    "data-analysis": ["model-construction"],
    "model-construction": ["model-solving"],
    "model-solving": ["validation"],
    "validation-pass": ["paper-writing", "complete"],
    "validation-fail": ["model-construction", "model-solving"],
    "paper-writing": ["complete"],
}


def _contains_marker(text: str) -> bool:
    return bool(SCAFFOLD_RE.search(text))


def _read_text(path: Path, errors: list[str], label: str) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        errors.append(f"missing {label}")
    except UnicodeDecodeError:
        errors.append(f"unreadable {label}")
    return None


def _read_json_object(path: Path, errors: list[str], label: str) -> tuple[dict[str, Any] | None, str | None]:
    text = _read_text(path, errors, label)
    if text is None:
        return None, None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        errors.append(f"invalid JSON in {label}")
        return None, text
    if not isinstance(value, dict):
        errors.append(f"{label} must be a JSON object")
        return None, text
    return value, text


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_manifest(root: Path, errors: list[str]) -> None:
    path = root / ".codex-plugin" / "plugin.json"
    manifest, raw = _read_json_object(path, errors, ".codex-plugin/plugin.json")
    if manifest is None:
        return
    if raw is not None and _contains_marker(raw):
        errors.append("manifest contains scaffold marker")
    unexpected = sorted(set(manifest) - _MANIFEST_KEYS)
    if unexpected:
        errors.append("manifest contains unsupported keys: " + ", ".join(unexpected))
    forbidden = sorted(set(manifest) & {"hooks", "apps", "mcpServers"})
    if forbidden:
        errors.append("manifest must not declare " + ", ".join(forbidden))
    if manifest.get("name") != PLUGIN_NAME:
        errors.append(f"manifest name must be {PLUGIN_NAME}")
    version = manifest.get("version")
    if not isinstance(version, str) or not SEMVER_RE.fullmatch(version):
        errors.append("manifest version must be strict SemVer")
    if not _is_nonempty_string(manifest.get("description")):
        errors.append("manifest description must be a non-empty string")
    if manifest.get("skills") != "./skills/":
        errors.append('manifest skills must be "./skills/"')
    author = manifest.get("author")
    if not isinstance(author, dict) or not _is_nonempty_string(author.get("name")):
        errors.append("manifest author.name must be a non-empty string")
    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        errors.append("manifest interface must be an object")
        return
    for field in _INTERFACE_STRING_FIELDS:
        if not _is_nonempty_string(interface.get(field)):
            errors.append(f"manifest interface.{field} must be a non-empty string")
    capabilities = interface.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities or not all(_is_nonempty_string(item) for item in capabilities):
        errors.append("manifest interface.capabilities must be a non-empty string array")
    prompts = interface.get("defaultPrompt")
    if not isinstance(prompts, list) or not prompts or not all(_is_nonempty_string(item) for item in prompts):
        errors.append("manifest interface.defaultPrompt must be a non-empty string array")
    elif not any(f"${ORCHESTRATOR_SKILL}" in prompt for prompt in prompts):
        errors.append(f"manifest interface.defaultPrompt must mention ${ORCHESTRATOR_SKILL}")


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        closing = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return None
    values: dict[str, str] = {}
    for line in lines[1:closing]:
        if not line.strip() or line.startswith((" ", "\t", "#")) or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if value.startswith('"'):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return None
            if not isinstance(decoded, str):
                return None
            value = decoded
        values[key] = value
    return values


def _validate_agent(path: Path, skill: str, errors: list[str]) -> None:
    label = f"skills/{skill}/agents/openai.yaml"
    text = _read_text(path, errors, label)
    if text is None:
        return
    if _contains_marker(text):
        errors.append(f"{label} contains scaffold marker")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        section = re.fullmatch(r"([a-z_]+):\s*", line)
        if section:
            current = section.group(1)
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    interface_lines = "\n".join(sections.get("interface", []))
    fields: dict[str, str] = {}
    for field in ("display_name", "short_description", "default_prompt"):
        match = re.search(rf'(?m)^  {re.escape(field)}:\s*("(?:[^"\\]|\\.)*")\s*$', interface_lines)
        if not match:
            errors.append(f"{label} requires quoted {field}")
            continue
        try:
            fields[field] = json.loads(match.group(1))
        except json.JSONDecodeError:
            errors.append(f"{label} has invalid quoted {field}")
    prompt = fields.get("default_prompt")
    if prompt is not None and f"${skill}" not in prompt:
        errors.append(f"{label} default_prompt must mention ${skill}")
    policy_lines = "\n".join(sections.get("policy", []))
    if not re.search(r"(?m)^  allow_implicit_invocation:\s*true\s*$", policy_lines):
        errors.append(f"{label} allow_implicit_invocation must be true")


def _validate_skills(root: Path, errors: list[str]) -> None:
    skills_root = root / "skills"
    existing_dirs = sorted((path for path in skills_root.iterdir() if path.is_dir()), key=lambda path: path.name) if skills_root.is_dir() else []
    missing = [skill for skill in ALL_SKILLS if not (skills_root / skill).is_dir()]
    if missing:
        errors.append("missing required skills: " + ", ".join(missing))
    seen_names: dict[str, str] = {}
    for skill_dir in existing_dirs:
        skill = skill_dir.name
        skill_path = skill_dir / "SKILL.md"
        label = f"skills/{skill}/SKILL.md"
        text = _read_text(skill_path, errors, label)
        if text is not None:
            if _contains_marker(text):
                errors.append(f"{label} contains scaffold marker")
            frontmatter = _parse_frontmatter(text)
            if frontmatter is None:
                errors.append(f"{label} has invalid frontmatter")
            else:
                name = frontmatter.get("name")
                description = frontmatter.get("description")
                if not _is_nonempty_string(name) or not SKILL_NAME_RE.fullmatch(name) or len(name) > 64:
                    errors.append(f"{label} frontmatter name must be lower hyphen-case and at most 64 characters")
                else:
                    if name in seen_names:
                        errors.append(f"duplicate skill frontmatter name: {name}")
                    else:
                        seen_names[name] = skill
                    if name != skill:
                        errors.append(f"{label} frontmatter name must match directory")
                if not _is_nonempty_string(description) or not 1 <= len(description) <= 1024:
                    errors.append(f"{label} frontmatter description must be 1-1024 characters")
            if skill == ORCHESTRATOR_SKILL:
                for stage in STAGE_SKILLS:
                    if stage not in text:
                        errors.append(f"{label} must mention {stage}")
            elif "../math-modeling-orchestrator/references/handoff-contract.md" not in text:
                errors.append(f"{label} must reference shared handoff contract")
        _validate_agent(skill_dir / "agents" / "openai.yaml", skill, errors)


def _validate_workflow(root: Path, errors: list[str]) -> None:
    workflow_path = root / "skills" / ORCHESTRATOR_SKILL / "references" / "workflow.json"
    workflow, raw = _read_json_object(workflow_path, errors, "skills/math-modeling-orchestrator/references/workflow.json")
    if workflow is None:
        return
    if raw is not None and _contains_marker(raw):
        errors.append("workflow contains scaffold marker")
    if workflow.get("schema_version") != "1":
        errors.append('workflow schema_version must be "1"')
    if workflow.get("orchestrator") != ORCHESTRATOR_SKILL:
        errors.append(f"workflow orchestrator must be {ORCHESTRATOR_SKILL}")
    stages = workflow.get("stages")
    if not isinstance(stages, list) or not all(isinstance(stage, dict) for stage in stages):
        errors.append("workflow stages must be an array of objects")
    else:
        registered = [stage.get("skill") for stage in stages]
        if not all(isinstance(skill, str) for skill in registered):
            errors.append("workflow stages must contain string skill values")
        elif registered != list(STAGE_SKILLS):
            errors.append("workflow stages must register required skills in order")
        for stage in stages:
            skill = stage.get("skill")
            if isinstance(skill, str) and skill not in ALL_SKILLS:
                errors.append(f"workflow stage references unknown skill: {skill}")
        required_optional = {
            "math-modeling-data-analysis": True,
            "math-modeling-paper-writing": True,
        }
        for skill, expected in required_optional.items():
            stage = next((item for item in stages if item.get("skill") == skill), None)
            if stage is not None and stage.get("optional") is not expected:
                errors.append(f"workflow stage {skill} optional must be true")

    transitions = workflow.get("transitions")
    if not isinstance(transitions, dict):
        errors.append("workflow transitions must be an object")
    else:
        if set(transitions) != set(_EXPECTED_TRANSITIONS):
            errors.append("workflow transitions must define the required routes")
        for source, expected in _EXPECTED_TRANSITIONS.items():
            actual = transitions.get(source)
            if source == "validation-fail":
                if actual != expected:
                    errors.append("workflow validation-fail must route only to model-construction or model-solving")
            elif actual != expected:
                errors.append(f"workflow transition {source} must be {expected}")

    guards = workflow.get("guards")
    if not isinstance(guards, dict):
        errors.append("workflow guards must be an object")
    else:
        if set(guards) != {"data-analysis-skip", "paper-writing"}:
            errors.append("workflow guards must contain only data-analysis-skip and paper-writing")
        if guards.get("data-analysis-skip") != {"allowed": True, "requires_reason": True}:
            errors.append("workflow data-analysis-skip guard must require allowed and requires_reason")
        if guards.get("paper-writing") != {"optional": True, "requires_validation_pass": True}:
            errors.append("workflow paper-writing guard must require optional and requires_validation_pass")

    handoff = workflow.get("handoff")
    if not isinstance(handoff, dict):
        errors.append("workflow handoff must be an object")
    else:
        if handoff.get("required_fields") != list(HANDOFF_REQUIRED_FIELDS):
            errors.append("workflow handoff.required_fields must match required contract fields")
        if handoff.get("statuses") != list(HANDOFF_STATUSES):
            errors.append("workflow handoff.statuses must match required statuses")

    contract_path = root / "skills" / ORCHESTRATOR_SKILL / "references" / "handoff-contract.md"
    contract = _read_text(contract_path, errors, "skills/math-modeling-orchestrator/references/handoff-contract.md")
    if contract is not None:
        for field in HANDOFF_REQUIRED_FIELDS:
            if not re.search(rf"(?m)^\s*{re.escape(field)}\s*:", contract):
                errors.append(f"handoff contract must show {field}:")


def validate_suite(root: Path) -> list[str]:
    """Return deterministic, human-readable contract errors for a suite root."""
    root = Path(root)
    errors: list[str] = []
    _validate_manifest(root, errors)
    _validate_skills(root, errors)
    _validate_workflow(root, errors)
    return errors
