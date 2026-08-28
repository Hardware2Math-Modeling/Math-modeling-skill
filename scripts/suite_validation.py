"""Validation helpers for the Math Modeling Codex plugin suite."""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse


PLUGIN_NAME = "math-modeling-suite"
ORCHESTRATOR_SKILL = "math-modeling-orchestrator"
WORKFLOW_STAGE_SKILLS = (
    "math-modeling-preflight",
    "math-modeling-problem-analysis",
    "math-modeling-data-analysis",
    "math-modeling-model-construction",
    "math-modeling-model-solving",
    "math-modeling-visualization",
    "math-modeling-validation",
    "math-modeling-paper-writing",
    "math-modeling-paper-production",
)
SUPPORT_SKILLS = ("math-modeling-method-library",)
STAGE_SKILLS = WORKFLOW_STAGE_SKILLS
ALL_SKILLS = (ORCHESTRATOR_SKILL, *WORKFLOW_STAGE_SKILLS, *SUPPORT_SKILLS)
HANDOFF_REQUIRED_FIELDS = ("schema_version", "state", "result", "next")
HANDOFF_STATUSES = ("pending", "in_progress", "complete", "needs_revision", "skipped")
HANDOFF_STATE_FIELDS = (
    "current_stage",
    "status",
    "validation_status",
    "completed_stages",
    "invalidated_stages",
)
HANDOFF_VALIDATION_STATUSES = ("pending", "pass", "needs_revision", "stale")
HANDOFF_CANONICAL_PATHS = (
    ("task", "statement"),
    ("task", "objectives"),
    ("task", "constraints"),
    ("state", "current_stage"),
    ("state", "status"),
    ("state", "validation_status"),
    ("state", "completed_stages"),
    ("state", "invalidated_stages"),
    ("quality", "warnings"),
    ("quality", "confidence"),
    ("next", "rationale"),
    ("next", "alternatives"),
)

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
SKILL_NAME_RE = re.compile(r"^[a-z](?:[a-z0-9]*(?:-[a-z0-9]+)*)?$")
SCAFFOLD_RE = re.compile(r"\[(?:TODO|TBD):", re.IGNORECASE)
HEX_COLOR_RE = re.compile(r"^#[0-9A-F]{6}$", re.IGNORECASE)

ARCHIVE_IGNORED_NAMES = {
    ".DS_Store",
    ".git",
    ".local-bundles",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".worktrees",
    "__pycache__",
}

# macOS exposes these stable aliases for temporary paths. They are safe to
# normalize, while user-controlled symlink components remain rejected.
_SAFE_SYSTEM_ALIASES = {
    Path("/tmp"): Path("/private/tmp"),
    Path("/var"): Path("/private/var"),
}

SENSITIVE_ENV_NAMES = {".env", ".envrc"}
SENSITIVE_FILE_NAMES = {
    "credentials",
    "credential",
    "credentials.json",
    "credential.json",
    "secrets",
    "secret",
    "secrets.json",
    "secret.json",
    "token",
    "tokens",
    "token.json",
    "tokens.json",
    "api_key",
    "api-key",
    "apikey",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
SENSITIVE_FILE_SUFFIXES = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
)

_MANIFEST_KEYS = {
    "id", "name", "version", "description", "author", "homepage", "repository",
    "license", "keywords", "skills", "interface",
}
_AUTHOR_KEYS = {"name", "email", "url"}
_SKILL_FRONTMATTER_KEYS = {"name", "description"}
_INTERFACE_STRING_FIELDS = (
    "displayName", "shortDescription", "longDescription", "developerName", "category",
)
_INTERFACE_KEYS = {
    *_INTERFACE_STRING_FIELDS,
    "capabilities",
    "defaultPrompt",
    "default_prompt",
    "websiteURL",
    "privacyPolicyURL",
    "termsOfServiceURL",
    "brandColor",
    "composerIcon",
    "logo",
    "logoDark",
    "screenshots",
}
_EXPECTED_TRANSITIONS = {
    "preflight": ["problem-analysis"],
    "problem-analysis": ["data-analysis", "model-construction"],
    "data-analysis": ["model-construction"],
    "model-construction": ["model-solving"],
    "model-solving": ["visualization", "validation"],
    "visualization": ["validation"],
    "validation-pass": ["paper-writing", "complete"],
    "validation-fail": [
        "problem-analysis",
        "data-analysis",
        "model-construction",
        "model-solving",
    ],
    "paper-writing": ["paper-production"],
    "paper-production": ["complete"],
}

_WORKFLOW_KEYS = {
    "schema_version",
    "orchestrator",
    "stages",
    "transitions",
    "guards",
    "authorization_policy",
    "handoff",
}
_WORKFLOW_STAGE_KEYS = {"id", "skill", "optional"}
_EXPECTED_GUARDS = {
    "data-analysis-skip": {"allowed": True, "requires_reason": True},
    "visualization-skip": {
        "allowed": True,
        "requires_reason": True,
        "requires_no_figure_claim": True,
    },
    "paper-writing": {
        "optional": True,
        "requires_validation_pass": True,
        "requires_gate3": True,
        "requires_no_invalidated_inputs": True,
    },
    "paper-production": {
        "optional": True,
        "requires_paper_request": True,
        "requires_paper_writing": True,
    },
}
_WORKFLOW_GUARD_KEYS = set(_EXPECTED_GUARDS)
_EXPECTED_AUTHORIZATION_POLICY = {
    "evaluator": "scripts/orchestrator_policy.py:authorization_errors",
    "workflow_guards_exhaustive": False,
}
_EXPECTED_SUPPORT_CONTRACT = {
    "schema_version": "1",
    "skill": "math-modeling-method-library",
    "workflow_role": "support",
    "resource_access": "read_only",
    "project_state_access": "none",
}
_WORKFLOW_HANDOFF_KEYS = {
    "required_fields",
    "statuses",
    "state_fields",
    "validation_statuses",
}


def _contains_marker(text: str) -> bool:
    return bool(SCAFFOLD_RE.search(text))


def _read_text(path: Path, errors: list[str], label: str) -> str | None:
    try:
        safe_path = ensure_no_symlink_components(path, label)
        if not stat.S_ISREG(safe_path.lstat().st_mode):
            errors.append(f"{label} must be a regular file")
            return None
        return safe_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        errors.append(f"missing {label}")
    except ValueError as error:
        if "symbolic link" in str(error):
            errors.append(f"{label} must not use symbolic links")
        else:
            errors.append(f"missing {label}")
    except OSError:
        errors.append(f"unreadable {label}")
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


def _exact_value_equal(actual: Any, expected: Any) -> bool:
    """Compare JSON-like values without treating booleans as integers."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            _exact_value_equal(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _exact_value_equal(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected)
        )
    return actual == expected


def _lexical_absolute(path: Path) -> Path:
    """Return an absolute path without dereferencing symlinks."""
    expanded = os.path.expanduser(os.fspath(path))
    if not os.path.isabs(expanded):
        expanded = os.path.join(os.getcwd(), expanded)
    # Do not call abspath/normpath here: collapsing ``..`` before checking
    # components would let a symlinked ancestor disappear from the audit.
    return Path(expanded)


def _is_safe_system_alias(path: Path) -> bool:
    """Allow only known OS aliases that are outside user-controlled roots."""
    expected = _SAFE_SYSTEM_ALIASES.get(path)
    if expected is None:
        return False
    try:
        return path.resolve(strict=True) == expected
    except (OSError, RuntimeError, ValueError):
        return False


def ensure_no_symlink_components(path: Path, label: str) -> Path:
    """Reject symlink components in an input path before it is resolved.

    Nonexistent trailing components are allowed so callers can create a new
    output directory. Existing components are inspected with ``lstat`` and
    failures are treated as unsafe rather than silently followed.
    """
    lexical = _lexical_absolute(path)
    absolute = Path(os.path.normpath(os.fspath(lexical)))
    current = Path(lexical.anchor) if lexical.anchor else Path()
    parts = lexical.parts[1:] if lexical.anchor else lexical.parts
    for part in parts:
        if part in {"", "."}:
            continue
        if part == "..":
            current = current.parent
            continue
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            # No later component can exist through a missing path component.
            break
        except OSError as error:
            raise ValueError(
                f"{label} path component cannot be inspected: {current}"
            ) from error
        if stat.S_ISLNK(mode) and not _is_safe_system_alias(current):
            if current == absolute:
                raise ValueError(f"{label} must not be a symbolic link: {current}")
            raise ValueError(f"{label} must not contain a symbolic link: {current}")
    return absolute


def ensure_outside_plugin_root(path: Path, label: str) -> Path:
    """Reject runtime paths at or below a directory containing a plugin manifest."""

    safe = ensure_no_symlink_components(path, label)
    for ancestor in (safe, *safe.parents):
        marker = ancestor / ".codex-plugin" / "plugin.json"
        try:
            mode = marker.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ValueError(f"{label} plugin boundary cannot be inspected: {marker}") from error
        if stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            raise ValueError(f"{label} must not be at or below a plugin root: {ancestor}")
    return safe


def is_sensitive_relative_path(path: Path) -> bool:
    """Return whether a relative archive path resembles credential material."""
    for component in path.parts:
        name = component.casefold()
        if name in SENSITIVE_ENV_NAMES or name.startswith(".env."):
            return True
        if name in SENSITIVE_FILE_NAMES or name.endswith(SENSITIVE_FILE_SUFFIXES):
            return True
    return False


def is_ignored_relative_path(path: Path) -> bool:
    """Return whether a path is repository metadata or generated cache output."""
    return any(
        component in ARCHIVE_IGNORED_NAMES
        or component.endswith((".pyc", ".pyo"))
        for component in path.parts
    )


def _is_absolute_https_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _validate_asset_path(
    root: Path, raw_path: Any, label: str, errors: list[str]
) -> None:
    if not _is_nonempty_string(raw_path):
        errors.append(f"{label} must be a non-empty relative path")
        return
    candidate = PurePosixPath(raw_path.replace("\\", "/"))
    if candidate.is_absolute() or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        errors.append(f"{label} must stay inside the plugin root")
        return
    try:
        asset_path = ensure_no_symlink_components(
            root / candidate.as_posix(), label
        )
        resolved = asset_path.resolve()
        resolved.relative_to(root.resolve())
    except ValueError as error:
        if "symbolic link" in str(error):
            errors.append(f"{label} must not use symbolic links")
        else:
            errors.append(f"{label} must stay inside the plugin root")
        return
    except (OSError, RuntimeError):
        errors.append(f"{label} must stay inside the plugin root")
        return
    try:
        is_regular = stat.S_ISREG(asset_path.lstat().st_mode)
    except OSError:
        is_regular = False
    if not is_regular:
        errors.append(f"{label} points to a missing file")


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
    if "id" in manifest and not _is_nonempty_string(manifest.get("id")):
        errors.append("manifest id must be a non-empty string when present")
    for field in ("homepage", "repository", "license"):
        if field in manifest and not _is_nonempty_string(manifest.get(field)):
            errors.append(f"manifest {field} must be a non-empty string when present")
    if "keywords" in manifest:
        keywords = manifest.get("keywords")
        if (
            not isinstance(keywords, list)
            or not keywords
            or not all(_is_nonempty_string(item) for item in keywords)
        ):
            errors.append(
                "manifest keywords must be a non-empty string array when present"
            )
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
    if isinstance(author, dict):
        unexpected_author = sorted(set(author) - _AUTHOR_KEYS)
        if unexpected_author:
            errors.append(
                "manifest author contains unsupported keys: "
                + ", ".join(unexpected_author)
            )
        for field in ("email", "url"):
            if field in author and not _is_nonempty_string(author.get(field)):
                errors.append(
                    f"manifest author.{field} must be a non-empty string when present"
                )
        if "url" in author and not _is_absolute_https_url(author.get("url")):
            errors.append("manifest author.url must be an absolute https URL")
    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        errors.append("manifest interface must be an object")
        return
    unexpected_interface = sorted(set(interface) - _INTERFACE_KEYS)
    if unexpected_interface:
        errors.append(
            "manifest interface contains unsupported keys: "
            + ", ".join(unexpected_interface)
        )
    for field in _INTERFACE_STRING_FIELDS:
        if not _is_nonempty_string(interface.get(field)):
            errors.append(f"manifest interface.{field} must be a non-empty string")
    capabilities = interface.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities or not all(_is_nonempty_string(item) for item in capabilities):
        errors.append("manifest interface.capabilities must be a non-empty string array")
    prompts = interface.get("defaultPrompt", interface.get("default_prompt"))
    if not isinstance(prompts, list) or not prompts or not all(_is_nonempty_string(item) for item in prompts):
        errors.append(
            "manifest interface.defaultPrompt must be a non-empty string array"
        )
    elif not any(f"${ORCHESTRATOR_SKILL}" in prompt for prompt in prompts):
        errors.append(f"manifest interface.defaultPrompt must mention ${ORCHESTRATOR_SKILL}")
    for field in (
        "websiteURL",
        "privacyPolicyURL",
        "termsOfServiceURL",
        "brandColor",
        "composerIcon",
        "logo",
        "logoDark",
    ):
        if field in interface and not _is_nonempty_string(interface.get(field)):
            errors.append(
                f"manifest interface.{field} must be a non-empty string when present"
            )
    for field in ("websiteURL", "privacyPolicyURL", "termsOfServiceURL"):
        if field in interface and not _is_absolute_https_url(interface.get(field)):
            errors.append(
                f"manifest interface.{field} must be an absolute https URL"
            )
    if "brandColor" in interface and (
        not isinstance(interface.get("brandColor"), str)
        or HEX_COLOR_RE.fullmatch(interface["brandColor"]) is None
    ):
        errors.append("manifest interface.brandColor must use #RRGGBB")
    for field in ("composerIcon", "logo", "logoDark"):
        if field in interface:
            _validate_asset_path(
                root,
                interface.get(field),
                f"manifest interface.{field}",
                errors,
            )
    if "screenshots" in interface:
        screenshots = interface.get("screenshots")
        if not isinstance(screenshots, list) or not all(
            _is_nonempty_string(item) for item in screenshots
        ):
            errors.append(
                "manifest interface.screenshots must be a string array when present"
            )
        if isinstance(screenshots, list):
            for index, raw_path in enumerate(screenshots):
                _validate_asset_path(
                    root,
                    raw_path,
                    f"manifest interface.screenshots[{index}]",
                    errors,
                )


def _parse_scalar(value: str, *, quoted_only: bool = False) -> str | None:
    """Parse the small scalar subset supported by skill metadata YAML."""
    value = value.strip()
    if not value:
        return None
    if value.startswith('"'):
        if len(value) < 2 or not value.endswith('"'):
            return None
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return None
        return decoded if isinstance(decoded, str) else None
    if value.startswith("'"):
        if re.fullmatch(r"'(?:[^']|'')*'", value) is None:
            return None
        return value[1:-1].replace("''", "'")
    if quoted_only:
        return None
    if value in {"true", "false", "null", "~"}:
        return None
    if value.startswith(("[", "{", "&", "*", "!", "|", ">")):
        return None
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", value):
        return None
    if re.search(r":(?:[ \t]|$)|(?:^|[ \t])#", value):
        return None
    return value


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return None
    try:
        closing = next(index for index, line in enumerate(lines[1:], 1) if line == "---")
    except StopIteration:
        return None
    values: dict[str, str] = {}
    for line in lines[1:closing]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")) or ":" not in line:
            return None
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", key) or key in values:
            return None
        parsed = _parse_scalar(value)
        if parsed is None:
            return None
        values[key] = parsed
    return values


def _parse_agent_yaml(text: str, label: str, errors: list[str]) -> dict[str, dict[str, str]]:
    """Parse the intentionally narrow, strict openai.yaml metadata subset."""
    sections: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("\t") or line.startswith(" ") and not line.startswith("  "):
            errors.append(f"{label} invalid YAML at line {line_number}")
            continue
        if line.startswith("  "):
            if current is None or line.startswith("   "):
                errors.append(f"{label} invalid YAML at line {line_number}")
                continue
            match = re.fullmatch(r"  ([a-z_][a-z0-9_]*):[ \t]*(.*)", line)
            if match is None:
                errors.append(f"{label} invalid YAML at line {line_number}")
                continue
            key, raw_value = match.groups()
            section = sections[current]
            if key in section:
                errors.append(f"{label} invalid YAML duplicate key {key}")
                continue
            quoted_only = current == "interface"
            if current == "policy" and key == "allow_implicit_invocation":
                parsed = raw_value.strip() if raw_value.strip() in {"true", "false"} else None
            else:
                parsed = _parse_scalar(raw_value, quoted_only=quoted_only)
            if parsed is None:
                errors.append(f"{label} invalid YAML at line {line_number}")
                continue
            section[key] = parsed
            continue
        match = re.fullmatch(r"([a-z_][a-z0-9_]*):[ \t]*(.*)", line)
        if match is None:
            errors.append(f"{label} invalid YAML at line {line_number}")
            continue
        section, raw_value = match.groups()
        if raw_value.strip() or section in sections:
            errors.append(f"{label} invalid YAML at line {line_number}")
            continue
        sections[section] = {}
        current = section
    return sections


def _validate_agent(path: Path, skill: str, errors: list[str]) -> None:
    label = f"skills/{skill}/agents/openai.yaml"
    text = _read_text(path, errors, label)
    if text is None:
        return
    if _contains_marker(text):
        errors.append(f"{label} contains scaffold marker")
    sections = _parse_agent_yaml(text, label, errors)
    interface = sections.get("interface", {})
    fields: dict[str, str] = {}
    for field in ("display_name", "short_description", "default_prompt"):
        value = interface.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label} requires quoted {field}")
            continue
        fields[field] = value
    unexpected_sections = sorted(set(sections) - {"interface", "policy"})
    if unexpected_sections:
        errors.append(f"{label} contains unsupported sections: {', '.join(unexpected_sections)}")
    unexpected_interface = sorted(set(interface) - {"display_name", "short_description", "default_prompt"})
    if unexpected_interface:
        errors.append(f"{label} interface contains unsupported keys: {', '.join(unexpected_interface)}")
    prompt = fields.get("default_prompt")
    if prompt is not None and f"${skill}" not in prompt:
        errors.append(f"{label} default_prompt must mention ${skill}")
    policy = sections.get("policy", {})
    if policy.get("allow_implicit_invocation") != "true":
        errors.append(f"{label} allow_implicit_invocation must be true")
    unexpected_policy = sorted(set(policy) - {"allow_implicit_invocation"})
    if unexpected_policy:
        errors.append(f"{label} policy contains unsupported keys: {', '.join(unexpected_policy)}")


def _validate_skills(root: Path, errors: list[str]) -> None:
    skills_root = root / "skills"
    try:
        existing_dirs = (
            sorted(
                (path for path in skills_root.iterdir() if path.is_dir()),
                key=lambda path: path.name,
            )
            if skills_root.is_dir()
            else []
        )
    except (OSError, ValueError, RuntimeError):
        existing_dirs = []
    missing = []
    for skill in ALL_SKILLS:
        try:
            present = (skills_root / skill).is_dir()
        except (OSError, ValueError, RuntimeError):
            present = False
        if not present:
            missing.append(skill)
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
                unexpected_frontmatter = sorted(
                    set(frontmatter) - _SKILL_FRONTMATTER_KEYS
                )
                if unexpected_frontmatter:
                    errors.append(
                        f"{label} unsupported frontmatter keys: "
                        + ", ".join(unexpected_frontmatter)
                    )
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
                elif not description.startswith("Use when"):
                    errors.append(
                        f"{label} frontmatter description must start with 'Use when'"
                    )
                elif "<" in description or ">" in description:
                    errors.append(
                        f"{label} frontmatter description must not contain angle brackets"
                    )
            if skill == ORCHESTRATOR_SKILL:
                for stage in WORKFLOW_STAGE_SKILLS:
                    if stage not in text:
                        errors.append(f"{label} must mention {stage}")
            elif skill in SUPPORT_SKILLS:
                if "references/support-contract.json" not in text:
                    errors.append(
                        f"{label} must reference references/support-contract.json"
                    )
            elif "../math-modeling-orchestrator/references/handoff-contract.md" not in text:
                errors.append(f"{label} must reference shared handoff contract")
        _validate_agent(skill_dir / "agents" / "openai.yaml", skill, errors)


def _validate_support_contract(root: Path, errors: list[str]) -> None:
    label = "skills/math-modeling-method-library/references/support-contract.json"
    contract_path = root / label
    contract, _ = _read_json_object(contract_path, errors, label)
    if contract is None:
        return

    expected_keys = set(_EXPECTED_SUPPORT_CONTRACT)
    unexpected = sorted(set(contract) - expected_keys)
    missing = sorted(expected_keys - set(contract))
    if unexpected:
        errors.append(
            "method-library support contract contains unsupported keys: "
            + ", ".join(unexpected)
        )
    if missing:
        errors.append(
            "method-library support contract is missing keys: " + ", ".join(missing)
        )

    expected_labels = {
        "schema_version": '"1"',
        "skill": "math-modeling-method-library",
        "workflow_role": "support",
        "resource_access": "read_only",
        "project_state_access": "none",
    }
    for field, expected_value in _EXPECTED_SUPPORT_CONTRACT.items():
        if field in contract and not _exact_value_equal(
            contract[field], expected_value
        ):
            errors.append(
                f"method-library support contract {field} must be "
                f"{expected_labels[field]}"
            )


def _validate_workflow(root: Path, errors: list[str]) -> None:
    workflow_path = root / "skills" / ORCHESTRATOR_SKILL / "references" / "workflow.json"
    workflow, raw = _read_json_object(workflow_path, errors, "skills/math-modeling-orchestrator/references/workflow.json")
    if workflow is None:
        return
    if raw is not None and _contains_marker(raw):
        errors.append("workflow contains scaffold marker")
    unexpected_workflow = sorted(set(workflow) - _WORKFLOW_KEYS)
    missing_workflow = sorted(_WORKFLOW_KEYS - set(workflow))
    if unexpected_workflow:
        errors.append(
            "workflow contains unsupported keys: " + ", ".join(unexpected_workflow)
        )
    if missing_workflow:
        errors.append("workflow is missing keys: " + ", ".join(missing_workflow))
    if workflow.get("schema_version") != "2":
        errors.append('workflow schema_version must be "2"')
    if workflow.get("orchestrator") != ORCHESTRATOR_SKILL:
        errors.append(f"workflow orchestrator must be {ORCHESTRATOR_SKILL}")
    stages = workflow.get("stages")
    if not isinstance(stages, list) or not all(isinstance(stage, dict) for stage in stages):
        errors.append("workflow stages must be an array of objects")
    else:
        registered = [stage.get("skill") for stage in stages]
        if not all(isinstance(skill, str) for skill in registered):
            errors.append("workflow stages must contain string skill values")
        elif registered != list(WORKFLOW_STAGE_SKILLS):
            errors.append("workflow stages must register required skills in order")
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            unexpected_stage = sorted(set(stage) - _WORKFLOW_STAGE_KEYS)
            missing_stage = sorted(_WORKFLOW_STAGE_KEYS - set(stage))
            if unexpected_stage:
                errors.append(
                    "workflow stage entries must contain only id, skill, optional"
                )
            if missing_stage:
                errors.append(
                    "workflow stage entries are missing: " + ", ".join(missing_stage)
                )
            skill = stage.get("skill")
            if isinstance(skill, str) and skill not in ALL_SKILLS:
                errors.append(f"workflow stage references unknown skill: {skill}")
        required_optional = {
            "math-modeling-preflight": False,
            "math-modeling-problem-analysis": False,
            "math-modeling-data-analysis": True,
            "math-modeling-model-construction": False,
            "math-modeling-model-solving": False,
            "math-modeling-visualization": True,
            "math-modeling-validation": False,
            "math-modeling-paper-writing": True,
            "math-modeling-paper-production": True,
        }
        for stage in stages:
            skill = stage.get("skill")
            if not isinstance(skill, str):
                continue
            expected_id = skill.removeprefix("math-modeling-")
            if stage.get("id") != expected_id:
                errors.append(
                    f"workflow stage id for {skill} must be {expected_id}"
                )
            if skill in required_optional:
                expected_optional = required_optional[skill]
                if stage.get("optional") is not expected_optional:
                    expected_word = "true" if expected_optional else "false"
                    errors.append(
                        f"workflow stage {skill} optional must be {expected_word}"
                    )
            if not isinstance(stage.get("id"), str):
                errors.append("workflow stage id must be a string")
            if type(stage.get("optional")) is not bool:
                errors.append("workflow stage optional must be a boolean")

    transitions = workflow.get("transitions")
    if not isinstance(transitions, dict):
        errors.append("workflow transitions must be an object")
    else:
        if set(transitions) != set(_EXPECTED_TRANSITIONS):
            errors.append("workflow transitions must define the required routes")
        for source, expected in _EXPECTED_TRANSITIONS.items():
            actual = transitions.get(source)
            if source in transitions and (
                not isinstance(actual, list)
                or not all(isinstance(destination, str) for destination in actual)
            ):
                errors.append(
                    f"workflow transition {source} must be a string array"
                )
                continue
            if source == "validation-fail":
                if actual != expected:
                    errors.append(
                        "workflow validation-fail must route only to upstream modeling stages"
                    )
            elif actual != expected:
                errors.append(f"workflow transition {source} must be {expected}")

    guards = workflow.get("guards")
    if not isinstance(guards, dict):
        errors.append("workflow guards must be an object")
    else:
        if set(guards) != _WORKFLOW_GUARD_KEYS:
            errors.append("workflow guards must define the required guard set")
        for guard_name, expected_guard in _EXPECTED_GUARDS.items():
            guard = guards.get(guard_name)
            if not isinstance(guard, dict):
                errors.append(f"workflow guard {guard_name} must be an object")
                continue
            unexpected_guard = sorted(set(guard) - set(expected_guard))
            if unexpected_guard:
                errors.append(
                    f"workflow guard {guard_name} contains unsupported keys: "
                    + ", ".join(unexpected_guard)
                )
            if not _exact_value_equal(guard, expected_guard):
                errors.append(f"workflow guard {guard_name} must match its required contract")

    authorization_policy = workflow.get("authorization_policy")
    if not isinstance(authorization_policy, dict) or not _exact_value_equal(
        authorization_policy,
        _EXPECTED_AUTHORIZATION_POLICY,
    ):
        errors.append(
            "workflow authorization_policy must name the authoritative evaluator "
            "and mark guards non-exhaustive"
        )
    else:
        _read_text(
            root / "scripts" / "orchestrator_policy.py",
            errors,
            "workflow authorization evaluator",
        )

    handoff = workflow.get("handoff")
    if not isinstance(handoff, dict):
        errors.append("workflow handoff must be an object")
    else:
        unexpected_handoff = sorted(set(handoff) - _WORKFLOW_HANDOFF_KEYS)
        missing_handoff = sorted(_WORKFLOW_HANDOFF_KEYS - set(handoff))
        if unexpected_handoff:
            errors.append(
                "workflow handoff contains unsupported keys: "
                + ", ".join(unexpected_handoff)
            )
        if missing_handoff:
            errors.append(
                "workflow handoff is missing keys: " + ", ".join(missing_handoff)
            )
        if handoff.get("required_fields") != list(HANDOFF_REQUIRED_FIELDS):
            errors.append("workflow handoff.required_fields must match required contract fields")
        if handoff.get("statuses") != list(HANDOFF_STATUSES):
            errors.append("workflow handoff.statuses must match required statuses")
        if handoff.get("state_fields") != list(HANDOFF_STATE_FIELDS):
            errors.append(
                "workflow handoff.state_fields must match required state fields"
            )
        if handoff.get("validation_statuses") != list(HANDOFF_VALIDATION_STATUSES):
            errors.append(
                "workflow handoff.validation_statuses must match required validation statuses"
            )

    contract_path = root / "skills" / ORCHESTRATOR_SKILL / "references" / "handoff-contract.md"
    contract = _read_text(contract_path, errors, "skills/math-modeling-orchestrator/references/handoff-contract.md")
    if contract is not None:
        for field in HANDOFF_REQUIRED_FIELDS:
            if not re.search(rf"(?m)^\s*{re.escape(field)}\s*:", contract):
                errors.append(f"handoff contract must show {field}:")
        for parent, child in HANDOFF_CANONICAL_PATHS:
            parent_match = re.search(rf"(?m)^{re.escape(parent)}\s*:\s*$", contract)
            if parent_match is None:
                errors.append(f"handoff contract must show {parent}.{child}")
                continue
            remainder = contract[parent_match.end():]
            next_parent = re.search(r"(?m)^[A-Za-z][A-Za-z0-9_-]*\s*:\s*$", remainder)
            section = remainder if next_parent is None else remainder[: next_parent.start()]
            if not re.search(rf"(?m)^  {re.escape(child)}\s*:", section):
                errors.append(f"handoff contract must show {parent}.{child}")


def validate_suite(root: Path) -> list[str]:
    """Return deterministic, human-readable contract errors for a suite root."""
    try:
        root = ensure_no_symlink_components(Path(root), "suite root").resolve()
    except ValueError as error:
        if "symbolic link" in str(error):
            return [str(error)]
        return ["suite root must be a valid path"]
    except (OSError, RuntimeError, TypeError):
        return ["suite root must be a valid path"]
    errors: list[str] = []
    _validate_manifest(root, errors)
    _validate_skills(root, errors)
    _validate_support_contract(root, errors)
    _validate_workflow(root, errors)
    return errors
