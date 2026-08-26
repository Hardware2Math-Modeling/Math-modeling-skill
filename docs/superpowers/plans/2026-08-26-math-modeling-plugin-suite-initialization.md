# Math Modeling Plugin Suite Initialization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Initialize this repository as an installable Codex plugin containing one orchestrator skill and six stage skills, with deterministic validation, bundle creation, local installation, cachebuster updates, and contributor documentation.

**Architecture:** The repository root is the `math-modeling-suite` plugin source. `skills/math-modeling-orchestrator/references/workflow.json` is the machine-readable stage registry, while `handoff-contract.md` is the human-readable cross-stage contract. Python standard-library scripts validate the source, build and validate a marketplace bundle, preview/apply local installation, and update the plugin cachebuster; all behavior is covered by `unittest` without network or model API calls.

**Tech Stack:** Codex plugin/skill manifests, Markdown, JSON, YAML-shaped metadata, Python 3.10+ standard library, `unittest`, Codex CLI.

---

## Scope and file map

This plan implements one cohesive initialization slice. It does not add mathematical algorithms, external data integrations, MCP servers, solver dependencies, or publication templates.

| Path | Responsibility |
| --- | --- |
| `.codex-plugin/plugin.json` | Plugin identity, version, discovery path, and Codex UI metadata |
| `skills/math-modeling-orchestrator/SKILL.md` | End-to-end routing, stopping, skip, and rollback rules |
| `skills/math-modeling-orchestrator/references/workflow.json` | Machine-readable stage registry and routing invariants |
| `skills/math-modeling-orchestrator/references/handoff-contract.md` | Shared Modeling Handoff schema and field semantics |
| `skills/math-modeling-*/SKILL.md` | One bounded stage contract per modeling phase |
| `skills/*/agents/openai.yaml` | UI name, discoverability, and explicit default invocation prompt |
| `scripts/suite_validation.py` | Reusable source-tree and workflow validation library |
| `scripts/validate_suite.py` | Source validation CLI |
| `scripts/build_bundle.py` | Safe marketplace bundle builder |
| `scripts/validate_bundle.py` | Marketplace-to-plugin path and bundled source validator |
| `scripts/update_cachebuster.py` | Preview/apply SemVer build-metadata cachebuster replacement |
| `scripts/install_local.py` | Dry-run/apply wrapper around bundle build and Codex CLI install |
| `tests/` | Standard-library unit, contract, bundle, installer, and cachebuster tests |
| `docs/architecture.md` | Maintainer-facing architecture and extension boundaries |
| `README.md` | User-facing validation, installation, invocation, and development workflow |

Preserve the existing uncommitted blank-line change in `README.md`; the documentation task incorporates it instead of reverting it.

### Task 1: Build the reusable source validator with TDD

**Files:**

- Create: `scripts/suite_validation.py`
- Create: `scripts/validate_suite.py`
- Create: `tests/test_suite_validation.py`

- [ ] **Step 1: Write the failing validator tests**

Create `tests/test_suite_validation.py` with this complete content:

```python
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from suite_validation import (  # noqa: E402
    ALL_SKILLS,
    HANDOFF_REQUIRED_FIELDS,
    STAGE_SKILLS,
    validate_suite,
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def make_valid_suite(root: Path) -> None:
    write_json(
        root / ".codex-plugin" / "plugin.json",
        {
            "name": "math-modeling-suite",
            "version": "0.1.0",
            "description": "A staged Codex skill suite for mathematical modeling.",
            "author": {"name": "Test Author"},
            "license": "MIT",
            "keywords": ["mathematical-modeling"],
            "skills": "./skills/",
            "interface": {
                "displayName": "Math Modeling Suite",
                "shortDescription": "Solve modeling problems in explicit stages",
                "longDescription": "Route mathematical modeling work through verified stages.",
                "developerName": "Test Author",
                "category": "Education & Research",
                "capabilities": ["Interactive", "Read", "Write"],
                "defaultPrompt": [
                    "Use $math-modeling-orchestrator to solve this problem."
                ],
            },
        },
    )

    for skill_name in ALL_SKILLS:
        skill_root = root / "skills" / skill_name
        skill_root.mkdir(parents=True, exist_ok=True)
        references = ""
        if skill_name == "math-modeling-orchestrator":
            references = "\n".join(STAGE_SKILLS)
        else:
            references = (
                "../math-modeling-orchestrator/references/handoff-contract.md"
            )
        (skill_root / "SKILL.md").write_text(
            "---\n"
            f'name: {skill_name}\n'
            f'description: "Use {skill_name} for its bounded modeling stage."\n'
            "---\n\n"
            f"# {skill_name}\n\n{references}\n",
            encoding="utf-8",
        )
        agents = skill_root / "agents"
        agents.mkdir(parents=True, exist_ok=True)
        (agents / "openai.yaml").write_text(
            "interface:\n"
            f'  display_name: "{skill_name}"\n'
            '  short_description: "Perform one verified modeling workflow stage"\n'
            f'  default_prompt: "Use ${skill_name} for this modeling task."\n\n'
            "policy:\n"
            "  allow_implicit_invocation: true\n",
            encoding="utf-8",
        )

    references_root = (
        root / "skills" / "math-modeling-orchestrator" / "references"
    )
    references_root.mkdir(parents=True, exist_ok=True)
    (references_root / "handoff-contract.md").write_text(
        "# Modeling Handoff\n\n"
        + "\n".join(f"{field}:" for field in HANDOFF_REQUIRED_FIELDS)
        + "\n",
        encoding="utf-8",
    )
    write_json(
        references_root / "workflow.json",
        {
            "schema_version": "1",
            "orchestrator": "math-modeling-orchestrator",
            "stages": [
                {
                    "id": skill.removeprefix("math-modeling-"),
                    "skill": skill,
                    "optional": skill
                    in {"math-modeling-data-analysis", "math-modeling-paper-writing"},
                }
                for skill in STAGE_SKILLS
            ],
            "transitions": {
                "problem-analysis": ["data-analysis", "model-construction"],
                "data-analysis": ["model-construction"],
                "model-construction": ["model-solving"],
                "model-solving": ["validation"],
                "validation-pass": ["paper-writing", "complete"],
                "validation-fail": ["model-construction", "model-solving"],
                "paper-writing": ["complete"],
            },
            "guards": {
                "data-analysis-skip": {
                    "allowed": True,
                    "requires_reason": True,
                },
                "paper-writing": {
                    "optional": True,
                    "requires_validation_pass": True,
                },
            },
            "handoff": {
                "required_fields": list(HANDOFF_REQUIRED_FIELDS),
                "statuses": [
                    "pending",
                    "in_progress",
                    "complete",
                    "needs_revision",
                    "skipped",
                ],
            },
        },
    )


class SuiteValidationTests(unittest.TestCase):
    def test_valid_suite_has_no_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            self.assertEqual(validate_suite(root), [])

    def test_missing_manifest_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            errors = validate_suite(Path(directory))
            self.assertIn("missing .codex-plugin/plugin.json", errors)

    def test_missing_registered_skill_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            skill_root = root / "skills" / "math-modeling-validation"
            for path in sorted(skill_root.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                else:
                    path.rmdir()
            skill_root.rmdir()
            errors = validate_suite(root)
            self.assertTrue(
                any("missing required skills" in error for error in errors), errors
            )

    def test_validation_failure_cannot_route_to_paper_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            workflow_path = (
                root
                / "skills"
                / "math-modeling-orchestrator"
                / "references"
                / "workflow.json"
            )
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            workflow["transitions"]["validation-fail"].append("paper-writing")
            write_json(workflow_path, workflow)
            errors = validate_suite(root)
            self.assertIn(
                "workflow validation-fail must route only to model-construction or model-solving",
                errors,
            )

    def test_openai_prompt_must_name_its_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            yaml_path = (
                root
                / "skills"
                / "math-modeling-data-analysis"
                / "agents"
                / "openai.yaml"
            )
            yaml_path.write_text(
                yaml_path.read_text(encoding="utf-8").replace(
                    "$math-modeling-data-analysis", "$wrong-skill"
                ),
                encoding="utf-8",
            )
            errors = validate_suite(root)
            self.assertTrue(
                any("default_prompt must mention" in error for error in errors), errors
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and confirm the import failure**

Run:

```bash
python3 -m unittest tests/test_suite_validation.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'suite_validation'`.

- [ ] **Step 3: Implement the validation library**

Create `scripts/suite_validation.py` with this complete content:

```python
#!/usr/bin/env python3
"""Shared validation for the math-modeling Codex plugin suite."""

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
HANDOFF_STATUSES = (
    "pending",
    "in_progress",
    "complete",
    "needs_revision",
    "skipped",
)
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONTMATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---(?:\n|\Z)", re.DOTALL)
PLACEHOLDER_MARKERS = ("[TODO:", "[TBD:")


def _load_json_object(
    path: Path, label: str, errors: list[str]
) -> dict[str, Any] | None:
    if not path.is_file():
        errors.append(f"missing {label}")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.append(f"{label} must be readable valid JSON")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{label} must contain a JSON object")
        return None
    return payload


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _contains_placeholder(text: str) -> bool:
    return any(marker in text for marker in PLACEHOLDER_MARKERS)


def _parse_frontmatter(path: Path, errors: list[str]) -> dict[str, str] | None:
    if not path.is_file():
        errors.append(f"missing {path.relative_to(path.parents[2])}")
        return None
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if match is None:
        errors.append(f"{path} must start with YAML frontmatter")
        return None
    if _contains_placeholder(text):
        errors.append(f"{path} contains an unfinished scaffold placeholder")
    parsed: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if not line.strip() or line.startswith((" ", "\t")):
            continue
        if ":" not in line:
            errors.append(f"{path} has invalid frontmatter line: {line}")
            continue
        key, raw_value = line.split(":", 1)
        value = raw_value.strip()
        if value.startswith('"'):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                errors.append(f"{path} has invalid quoted frontmatter value for {key}")
                continue
            if isinstance(decoded, str):
                value = decoded
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        parsed[key.strip()] = value
    return parsed


def _validate_manifest(root: Path, errors: list[str]) -> None:
    manifest = _load_json_object(
        root / ".codex-plugin" / "plugin.json",
        ".codex-plugin/plugin.json",
        errors,
    )
    if manifest is None:
        return
    allowed_fields = {
        "id",
        "name",
        "version",
        "description",
        "author",
        "homepage",
        "repository",
        "license",
        "keywords",
        "skills",
        "interface",
    }
    for field in sorted(set(manifest) - allowed_fields):
        errors.append(f"plugin.json field {field} is not supported by this suite")
    if _contains_placeholder(json.dumps(manifest, ensure_ascii=False)):
        errors.append("plugin.json contains an unfinished scaffold placeholder")
    if manifest.get("name") != PLUGIN_NAME:
        errors.append(f"plugin.json name must be {PLUGIN_NAME}")
    version = manifest.get("version")
    if not _non_empty_string(version) or SEMVER_RE.fullmatch(str(version)) is None:
        errors.append("plugin.json version must be strict SemVer")
    if not _non_empty_string(manifest.get("description")):
        errors.append("plugin.json description must be a non-empty string")
    if manifest.get("skills") != "./skills/":
        errors.append("plugin.json skills must be ./skills/")
    author = manifest.get("author")
    if not isinstance(author, dict) or not _non_empty_string(author.get("name")):
        errors.append("plugin.json author.name must be a non-empty string")
    for unsupported in ("hooks", "apps", "mcpServers"):
        if unsupported in manifest:
            errors.append(f"plugin.json must not declare uncreated component {unsupported}")
    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        errors.append("plugin.json interface must be an object")
        return
    for field in (
        "displayName",
        "shortDescription",
        "longDescription",
        "developerName",
        "category",
    ):
        if not _non_empty_string(interface.get(field)):
            errors.append(f"plugin.json interface.{field} must be a non-empty string")
    capabilities = interface.get("capabilities")
    if not isinstance(capabilities, list) or not all(
        _non_empty_string(value) for value in capabilities
    ):
        errors.append("plugin.json interface.capabilities must be an array of strings")
    prompts = interface.get("defaultPrompt")
    if not isinstance(prompts, list) or not prompts or not all(
        _non_empty_string(value) for value in prompts
    ):
        errors.append("plugin.json interface.defaultPrompt must be a non-empty string array")
    elif not any("$math-modeling-orchestrator" in prompt for prompt in prompts):
        errors.append("plugin.json defaultPrompt must mention $math-modeling-orchestrator")


def _validate_openai_yaml(path: Path, skill_name: str, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"missing {skill_name}/agents/openai.yaml")
        return
    text = path.read_text(encoding="utf-8")
    if _contains_placeholder(text):
        errors.append(f"{path} contains an unfinished scaffold placeholder")
    for field in ("display_name", "short_description"):
        if re.search(
            rf'^\s{{2}}{field}:\s*"[^"]+"\s*$', text, re.MULTILINE
        ) is None:
            errors.append(f"{skill_name} interface.{field} must be a quoted string")
    prompt_match = re.search(
        r'^\s{2}default_prompt:\s*"(?P<prompt>[^"]+)"\s*$', text, re.MULTILINE
    )
    if prompt_match is None or f"${skill_name}" not in prompt_match.group("prompt"):
        errors.append(f"{skill_name} default_prompt must mention ${skill_name}")
    if not re.search(
        r"^\s{2}allow_implicit_invocation:\s*true\s*$", text, re.MULTILINE
    ):
        errors.append(f"{skill_name} must allow implicit invocation")


def _validate_skills(root: Path, errors: list[str]) -> set[str]:
    skills_root = root / "skills"
    if not skills_root.is_dir():
        errors.append("missing skills directory")
        return set()
    names: set[str] = set()
    for skill_root in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        skill_md = skill_root / "SKILL.md"
        frontmatter = _parse_frontmatter(skill_md, errors)
        if frontmatter is None:
            continue
        name = frontmatter.get("name", "")
        description = frontmatter.get("description", "")
        if SKILL_NAME_RE.fullmatch(name) is None or len(name) > 64:
            errors.append(f"invalid skill name {name!r} in {skill_md}")
        if name != skill_root.name:
            errors.append(f"skill directory {skill_root.name} must match frontmatter name {name}")
        if not description or len(description) > 1024:
            errors.append(f"{name or skill_root.name} description must contain 1-1024 characters")
        if name in names:
            errors.append(f"duplicate skill name {name}")
        names.add(name)
        _validate_openai_yaml(skill_root / "agents" / "openai.yaml", name, errors)
        if name in STAGE_SKILLS:
            skill_text = skill_md.read_text(encoding="utf-8")
            contract_reference = (
                "../math-modeling-orchestrator/references/handoff-contract.md"
            )
            if contract_reference not in skill_text:
                errors.append(f"{name} does not reference the shared handoff contract")

    missing = sorted(set(ALL_SKILLS) - names)
    if missing:
        errors.append(f"missing required skills: {', '.join(missing)}")
    orchestrator_path = skills_root / ORCHESTRATOR_SKILL / "SKILL.md"
    if orchestrator_path.is_file():
        orchestrator_text = orchestrator_path.read_text(encoding="utf-8")
        for stage_skill in STAGE_SKILLS:
            if stage_skill not in orchestrator_text:
                errors.append(f"orchestrator does not reference {stage_skill}")
    return names


def _validate_workflow(root: Path, skill_names: set[str], errors: list[str]) -> None:
    references_root = root / "skills" / ORCHESTRATOR_SKILL / "references"
    workflow = _load_json_object(
        references_root / "workflow.json", "orchestrator workflow.json", errors
    )
    if workflow is None:
        return
    if workflow.get("schema_version") != "1":
        errors.append("workflow schema_version must be 1")
    if workflow.get("orchestrator") != ORCHESTRATOR_SKILL:
        errors.append(f"workflow orchestrator must be {ORCHESTRATOR_SKILL}")
    stages = workflow.get("stages")
    if not isinstance(stages, list):
        errors.append("workflow stages must be an array")
        return
    if not all(isinstance(stage, dict) for stage in stages):
        errors.append("every workflow stage must be an object")
        return
    registered = [stage.get("skill") for stage in stages]
    if not all(isinstance(skill, str) for skill in registered):
        errors.append("every workflow stage skill must be a string")
        return
    if registered != list(STAGE_SKILLS):
        errors.append("workflow stages must register the six standard skills in order")
    unknown = sorted(set(registered) - skill_names)
    if unknown:
        errors.append(f"workflow references unknown skills: {', '.join(unknown)}")

    transitions = workflow.get("transitions")
    if not isinstance(transitions, dict):
        errors.append("workflow transitions must be an object")
        return
    expected_transitions = {
        "problem-analysis": ["data-analysis", "model-construction"],
        "data-analysis": ["model-construction"],
        "model-construction": ["model-solving"],
        "model-solving": ["validation"],
        "validation-pass": ["paper-writing", "complete"],
        "paper-writing": ["complete"],
    }
    for route, destinations in expected_transitions.items():
        if transitions.get(route) != destinations:
            errors.append(f"workflow {route} route must be {destinations}")
    if transitions.get("validation-fail") != [
        "model-construction",
        "model-solving",
    ]:
        errors.append(
            "workflow validation-fail must route only to model-construction or model-solving"
        )

    guards = workflow.get("guards")
    if not isinstance(guards, dict):
        errors.append("workflow guards must be an object")
    else:
        skip_guard = guards.get("data-analysis-skip")
        if skip_guard != {"allowed": True, "requires_reason": True}:
            errors.append("data-analysis skip must be allowed and require a reason")
        writing_guard = guards.get("paper-writing")
        if writing_guard != {"optional": True, "requires_validation_pass": True}:
            errors.append("paper-writing must be optional and require validation pass")

    handoff = workflow.get("handoff")
    if not isinstance(handoff, dict):
        errors.append("workflow handoff must be an object")
    else:
        if handoff.get("required_fields") != list(HANDOFF_REQUIRED_FIELDS):
            errors.append("workflow handoff required_fields do not match the contract")
        if handoff.get("statuses") != list(HANDOFF_STATUSES):
            errors.append("workflow handoff statuses do not match the contract")

    contract_path = references_root / "handoff-contract.md"
    if not contract_path.is_file():
        errors.append("missing orchestrator handoff-contract.md")
    else:
        contract = contract_path.read_text(encoding="utf-8")
        for field in HANDOFF_REQUIRED_FIELDS:
            if f"{field}:" not in contract:
                errors.append(f"handoff contract does not show required field {field}")


def validate_suite(root: Path) -> list[str]:
    """Return deterministic validation errors for a plugin source root."""
    root = root.expanduser().resolve()
    errors: list[str] = []
    _validate_manifest(root, errors)
    skill_names = _validate_skills(root, errors)
    _validate_workflow(root, skill_names, errors)
    return errors
```

- [ ] **Step 4: Add the source-validation CLI**

Create `scripts/validate_suite.py` with this complete content:

```python
#!/usr/bin/env python3
"""Validate a math-modeling plugin source tree."""

from __future__ import annotations

import argparse
from pathlib import Path

from suite_validation import validate_suite


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        default=str(Path(__file__).resolve().parents[1]),
        help="Plugin source root; defaults to this repository.",
    )
    return parser.parse_args()


def main() -> None:
    root = Path(parse_args().root).expanduser().resolve()
    errors = validate_suite(root)
    if errors:
        print("Suite validation failed:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print(f"Suite validation passed: {root}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the focused validator tests**

Run:

```bash
python3 -m unittest tests/test_suite_validation.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 6: Commit the validator foundation**

```bash
git add scripts/suite_validation.py scripts/validate_suite.py tests/test_suite_validation.py
git commit -m "test: add plugin suite contract validator"
```

### Task 2: Add the plugin manifest, orchestrator, and six stage skills

**Files:**

- Create: `.codex-plugin/plugin.json`
- Create: `skills/math-modeling-orchestrator/SKILL.md`
- Create: `skills/math-modeling-orchestrator/agents/openai.yaml`
- Create: `skills/math-modeling-orchestrator/references/workflow.json`
- Create: `skills/math-modeling-orchestrator/references/handoff-contract.md`
- Create: `skills/math-modeling-problem-analysis/SKILL.md`
- Create: `skills/math-modeling-problem-analysis/agents/openai.yaml`
- Create: `skills/math-modeling-data-analysis/SKILL.md`
- Create: `skills/math-modeling-data-analysis/agents/openai.yaml`
- Create: `skills/math-modeling-model-construction/SKILL.md`
- Create: `skills/math-modeling-model-construction/agents/openai.yaml`
- Create: `skills/math-modeling-model-solving/SKILL.md`
- Create: `skills/math-modeling-model-solving/agents/openai.yaml`
- Create: `skills/math-modeling-validation/SKILL.md`
- Create: `skills/math-modeling-validation/agents/openai.yaml`
- Create: `skills/math-modeling-paper-writing/SKILL.md`
- Create: `skills/math-modeling-paper-writing/agents/openai.yaml`
- Create: `tests/test_repository_contract.py`

- [ ] **Step 1: Write the failing repository contract test**

Create `tests/test_repository_contract.py` with this complete content:

```python
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from suite_validation import STAGE_SKILLS, validate_suite  # noqa: E402


class RepositoryContractTests(unittest.TestCase):
    def test_repository_is_a_valid_suite(self) -> None:
        self.assertEqual(validate_suite(ROOT), [])

    def test_workflow_registers_each_stage_once(self) -> None:
        workflow_path = (
            ROOT
            / "skills"
            / "math-modeling-orchestrator"
            / "references"
            / "workflow.json"
        )
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        registered = [stage["skill"] for stage in workflow["stages"]]
        self.assertEqual(registered, list(STAGE_SKILLS))
        self.assertEqual(len(registered), len(set(registered)))

    def test_validation_gate_blocks_paper_writing(self) -> None:
        workflow_path = (
            ROOT
            / "skills"
            / "math-modeling-orchestrator"
            / "references"
            / "workflow.json"
        )
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        self.assertNotIn("paper-writing", workflow["transitions"]["validation-fail"])
        self.assertTrue(
            workflow["guards"]["paper-writing"]["requires_validation_pass"]
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the repository contract test and confirm the missing-plugin failure**

Run:

```bash
python3 -m unittest tests/test_repository_contract.py -v
```

Expected: FAIL because `.codex-plugin/plugin.json` and `skills/` do not exist.

- [ ] **Step 3: Add the plugin manifest**

Create `.codex-plugin/plugin.json` with this complete content:

```json
{
  "name": "math-modeling-suite",
  "version": "0.1.0",
  "description": "A staged Codex skill suite for mathematical modeling problems.",
  "author": {
    "name": "硬件重组之打数模"
  },
  "license": "MIT",
  "keywords": [
    "mathematical-modeling",
    "CUMCM",
    "research"
  ],
  "skills": "./skills/",
  "interface": {
    "displayName": "Math Modeling Suite",
    "shortDescription": "Solve modeling problems in explicit stages",
    "longDescription": "Routes mathematical modeling work through problem analysis, data analysis, model construction, solving, validation, and paper writing.",
    "developerName": "硬件重组之打数模",
    "category": "Education & Research",
    "capabilities": [
      "Interactive",
      "Read",
      "Write"
    ],
    "defaultPrompt": [
      "Use $math-modeling-orchestrator to work through this modeling problem."
    ]
  }
}
```

- [ ] **Step 4: Add the machine-readable workflow registry**

Create `skills/math-modeling-orchestrator/references/workflow.json` with this complete content:

```json
{
  "schema_version": "1",
  "orchestrator": "math-modeling-orchestrator",
  "stages": [
    {
      "id": "problem-analysis",
      "skill": "math-modeling-problem-analysis",
      "optional": false
    },
    {
      "id": "data-analysis",
      "skill": "math-modeling-data-analysis",
      "optional": true
    },
    {
      "id": "model-construction",
      "skill": "math-modeling-model-construction",
      "optional": false
    },
    {
      "id": "model-solving",
      "skill": "math-modeling-model-solving",
      "optional": false
    },
    {
      "id": "validation",
      "skill": "math-modeling-validation",
      "optional": false
    },
    {
      "id": "paper-writing",
      "skill": "math-modeling-paper-writing",
      "optional": true
    }
  ],
  "transitions": {
    "problem-analysis": [
      "data-analysis",
      "model-construction"
    ],
    "data-analysis": [
      "model-construction"
    ],
    "model-construction": [
      "model-solving"
    ],
    "model-solving": [
      "validation"
    ],
    "validation-pass": [
      "paper-writing",
      "complete"
    ],
    "validation-fail": [
      "model-construction",
      "model-solving"
    ],
    "paper-writing": [
      "complete"
    ]
  },
  "guards": {
    "data-analysis-skip": {
      "allowed": true,
      "requires_reason": true
    },
    "paper-writing": {
      "optional": true,
      "requires_validation_pass": true
    }
  },
  "handoff": {
    "required_fields": [
      "schema_version",
      "state",
      "result",
      "next"
    ],
    "statuses": [
      "pending",
      "in_progress",
      "complete",
      "needs_revision",
      "skipped"
    ]
  }
}
```

- [ ] **Step 5: Add the Modeling Handoff reference**

Create `skills/math-modeling-orchestrator/references/handoff-contract.md` with this complete content:

````markdown
# Modeling Handoff Contract

Use this contract to transfer state between the orchestrator and every stage skill. It is a structured model output, not a required database or on-disk state file. Preserve exact formulas, units, data provenance, assumptions, and artifact paths between stages.

## Schema

```yaml
schema_version: "1"
task:
  statement: "Original problem or a faithful summary"
  objectives: []
  constraints: []
state:
  current_stage: "problem-analysis"
  status: "complete"
context:
  assumptions: []
  variables: []
  data: []
  methods: []
  decisions: []
artifacts:
  - path: "relative/path/to/artifact"
    kind: "table|figure|code|report"
    description: "What this artifact proves or contains"
quality:
  checks: []
  warnings: []
  confidence: "high|medium|low"
result:
  summary: "Stage conclusion"
  details: []
next:
  recommended_stage: "data-analysis"
  rationale: "Why this is the correct next stage"
  alternatives: []
```

## Required semantics

- `schema_version`, `state`, `result`, and `next` are required.
- `state.status` is one of `pending`, `in_progress`, `complete`, `needs_revision`, or `skipped`.
- Use empty arrays for inapplicable collections. Never invent measurements, provenance, citations, computed values, or artifacts.
- A skipped stage records its reason in `result.summary` and `next.rationale`.
- A revision request identifies the failed check and recommends either model construction or model solving.
- Artifact paths are relative to the user's active project unless the user explicitly chooses another location.
- A stage result states what was completed, where its evidence lives, and what the next stage still needs.
````

- [ ] **Step 6: Add the orchestrator skill and UI metadata**

Create `skills/math-modeling-orchestrator/SKILL.md` with this complete content:

```markdown
---
name: math-modeling-orchestrator
description: "Orchestrate end-to-end mathematical modeling work across problem analysis, data analysis, model construction, solving, validation, and paper writing. Use when a user provides a modeling problem or asks to coordinate several modeling stages; do not use for a narrowly scoped request that clearly belongs to one stage skill."
---

# Math Modeling Orchestrator

Coordinate the modeling process while keeping each stage independently checkable.

## Required references

Before routing, read [references/workflow.json](references/workflow.json) and [references/handoff-contract.md](references/handoff-contract.md). Treat `workflow.json` as the routing source of truth and preserve the handoff schema across every stage.

## Start and resume

1. Convert the user's request and any existing work into a Modeling Handoff.
2. If a handoff already exists, resume from its state instead of restarting completed stages.
3. Ask the user only when missing information would materially change objectives, constraints, or model choice. Record ordinary assumptions explicitly.
4. Select the next stage from the workflow registry and invoke the corresponding skill.

## Stage routing

- Invoke `$math-modeling-problem-analysis` first for a new problem.
- Invoke `$math-modeling-data-analysis` when supplied or discoverable data must be audited, transformed, estimated, or explored. A data-free analytical problem may skip it only with a recorded reason.
- Invoke `$math-modeling-model-construction` once objectives, constraints, and available evidence are clear enough to compare candidate models.
- Invoke `$math-modeling-model-solving` only after selecting a model and specifying its variables, assumptions, constraints, and evaluation criteria.
- Invoke `$math-modeling-validation` for every computed or analytical result before declaring the model complete.
- Invoke `$math-modeling-paper-writing` only after validation passes and only when the user wants a paper, report, or section draft.

Stage skills return a handoff and recommendation; they do not choose the final cross-stage route. Do not let one stage silently perform another stage's work.

## Quality gates

- Do not route failed validation to paper writing. Return to model construction when assumptions or structure are wrong; return to model solving when implementation, parameters, or numerical work is wrong.
- Preserve equations, variable definitions, units, data provenance, accepted and rejected models, artifact paths, and validation evidence.
- A stage is complete only when its handoff states what changed, what evidence supports it, and what the next stage requires.
- Do not claim the whole problem is complete until validation passes. If paper writing is skipped, explain that the validated modeling result is complete but no manuscript was requested.

## Final response

Summarize the chosen model, strongest evidence, validation status, material limitations, generated artifacts, and any unresolved decisions. Distinguish verified results from assumptions and recommendations.
```

Create `skills/math-modeling-orchestrator/agents/openai.yaml` with this complete content:

```yaml
interface:
  display_name: "Math Modeling Orchestrator"
  short_description: "Route modeling work through verified stages"
  default_prompt: "Use $math-modeling-orchestrator to coordinate this mathematical modeling problem."

policy:
  allow_implicit_invocation: true
```

- [ ] **Step 7: Add the problem-analysis skill and UI metadata**

Create `skills/math-modeling-problem-analysis/SKILL.md` with this complete content:

```markdown
---
name: math-modeling-problem-analysis
description: "Translate a mathematical modeling prompt into explicit objectives, constraints, variables, evaluation criteria, ambiguities, and information needs. Use for problem formulation and decomposition before choosing a model; do not perform full model construction or numerical solving."
---

# Problem Analysis

Turn the prompt into a precise modeling specification.

## Input

Accept the original problem and any current Modeling Handoff. When invoked independently, read `../math-modeling-orchestrator/references/handoff-contract.md` before returning results.

## Work

1. Separate requested outputs from background narrative and identify each subproblem.
2. State objectives, decision variables, constraints, evaluation metrics, time/space scales, and required units.
3. Classify supplied facts as data, assumptions, definitions, or claims that need evidence.
4. Identify ambiguities that would materially change the model. Ask only for those; record reasonable ordinary assumptions.
5. Describe what evidence or data the next stage needs without selecting a final model.

## Output

Return an updated Modeling Handoff with `state.current_stage: problem-analysis`, a concise problem definition, the constraint and metric lists, warnings, and a recommendation for data analysis or model construction. Use `complete` only when the problem is precise enough to continue.

Do not invent data, lock in a model family, solve equations, or claim the entire task is complete.
```

Create `skills/math-modeling-problem-analysis/agents/openai.yaml` with this complete content:

```yaml
interface:
  display_name: "Modeling Problem Analysis"
  short_description: "Turn a prompt into a precise modeling specification"
  default_prompt: "Use $math-modeling-problem-analysis to formulate this modeling problem."

policy:
  allow_implicit_invocation: true
```

- [ ] **Step 8: Add the data-analysis skill and UI metadata**

Create `skills/math-modeling-data-analysis/SKILL.md` with this complete content:

```markdown
---
name: math-modeling-data-analysis
description: "Audit and analyze data for mathematical modeling, including provenance, units, missingness, anomalies, transformations, exploratory evidence, and modeling implications. Use when a modeling task supplies or requires data; do not choose the final model or present unvalidated conclusions."
---

# Data Analysis

Produce an evidence-based data assessment for downstream modeling.

## Input

Accept data locations, problem objectives, constraints, and the current Modeling Handoff. When invoked independently, read `../math-modeling-orchestrator/references/handoff-contract.md` before returning results.

## Work

1. Inventory sources, fields, units, time ranges, sampling, provenance, and access limitations.
2. Check types, missingness, duplicates, impossible values, anomalies, leakage risks, and inconsistent units.
3. Perform only transformations and exploratory analyses justified by the objective; retain the original data and document every transformation.
4. Report patterns with appropriate uncertainty and distinguish observations from causal claims.
5. Explain which findings constrain model construction and which data limitations remain material.

## Output

Return an updated Modeling Handoff with `state.current_stage: data-analysis`, data-quality checks, artifact paths, evidence summaries, warnings, and a recommendation for model construction. If the stage is unnecessary, return `skipped` with a concrete reason instead of manufacturing an analysis.

Do not invent sources or measurements, silently repair data, select the final model, or claim the whole task is complete.
```

Create `skills/math-modeling-data-analysis/agents/openai.yaml` with this complete content:

```yaml
interface:
  display_name: "Modeling Data Analysis"
  short_description: "Audit data and extract modeling evidence"
  default_prompt: "Use $math-modeling-data-analysis to audit and analyze this modeling data."

policy:
  allow_implicit_invocation: true
```

- [ ] **Step 9: Add the model-construction skill and UI metadata**

Create `skills/math-modeling-model-construction/SKILL.md` with this complete content:

```markdown
---
name: math-modeling-model-construction
description: "Construct and compare mathematical models from a defined problem and available evidence, including assumptions, symbols, equations, constraints, identifiability, and selection rationale. Use after problem and data analysis; do not run the full solution or bypass validation."
---

# Model Construction

Convert the problem specification into an explicit, defensible model.

## Input

Accept the completed problem definition, relevant data evidence, and current Modeling Handoff. When invoked independently, read `../math-modeling-orchestrator/references/handoff-contract.md` before returning results.

## Work

1. Define symbols, units, domains, decision variables, state variables, parameters, objectives, and constraints.
2. Propose the smallest useful set of candidate model families and state the assumptions each requires.
3. Check dimensional consistency, boundary behavior, identifiability, computational feasibility, and alignment with evaluation metrics.
4. Compare candidates using explicit criteria and record both the selected model and rejected alternatives with reasons.
5. Specify the equations, estimation target, solution interface, and validation tests needed downstream.

## Output

Return an updated Modeling Handoff with `state.current_stage: model-construction`, the selected model specification, accepted assumptions, rejected alternatives, risks, and a recommendation for model solving. Use `needs_revision` when the problem or evidence cannot support a defensible model.

Do not hide assumptions, conflate correlation with mechanism, fabricate parameter values, execute the full solution, or claim the whole task is complete.
```

Create `skills/math-modeling-model-construction/agents/openai.yaml` with this complete content:

```yaml
interface:
  display_name: "Mathematical Model Construction"
  short_description: "Build and compare defensible mathematical models"
  default_prompt: "Use $math-modeling-model-construction to construct a model for this problem."

policy:
  allow_implicit_invocation: true
```

- [ ] **Step 10: Add the model-solving skill and UI metadata**

Create `skills/math-modeling-model-solving/SKILL.md` with this complete content:

```markdown
---
name: math-modeling-model-solving
description: "Solve a specified mathematical model analytically or computationally while recording algorithms, parameters, convergence, reproducibility, and artifacts. Use after model construction has fixed equations and evaluation criteria; do not change the model silently or declare unvalidated results final."
---

# Model Solving

Produce reproducible results from an explicit model specification.

## Input

Accept equations, variables, constraints, parameter sources, evaluation criteria, and the current Modeling Handoff. When invoked independently, read `../math-modeling-orchestrator/references/handoff-contract.md` before returning results.

## Work

1. Choose an analytical, numerical, optimization, simulation, or estimation method justified by the model structure.
2. Record algorithms, software assumptions, parameter values and sources, initial/boundary conditions, tolerances, seeds, and stopping criteria.
3. Keep implementation artifacts focused and reproducible; preserve commands and relative output paths.
4. Check convergence, feasibility, numerical stability, and basic sanity bounds before reporting results.
5. If solving exposes a structural flaw, return `needs_revision` and identify whether model construction or implementation must change.

## Output

Return an updated Modeling Handoff with `state.current_stage: model-solving`, methods, parameters, computed results, commands, artifact paths, warnings, and a recommendation for validation.

Do not silently alter equations or constraints, conceal failed runs, invent numerical output, or claim results are final before validation.
```

Create `skills/math-modeling-model-solving/agents/openai.yaml` with this complete content:

```yaml
interface:
  display_name: "Mathematical Model Solving"
  short_description: "Solve a specified model reproducibly"
  default_prompt: "Use $math-modeling-model-solving to solve this specified mathematical model."

policy:
  allow_implicit_invocation: true
```

- [ ] **Step 11: Add the validation skill and UI metadata**

Create `skills/math-modeling-validation/SKILL.md` with this complete content:

```markdown
---
name: math-modeling-validation
description: "Validate mathematical modeling results using fit, residual, sensitivity, robustness, boundary, feasibility, and limitation checks. Use after a model has produced analytical or computational results; do not rewrite failed validation as success or draft a final paper before the gate passes."
---

# Model Validation

Decide whether the evidence supports the model's intended use.

## Input

Accept the model specification, solution results, evaluation criteria, artifacts, and current Modeling Handoff. When invoked independently, read `../math-modeling-orchestrator/references/handoff-contract.md` before returning results.

## Work

1. Select checks appropriate to the objective: fit or residual diagnostics, held-out evidence, sensitivity, uncertainty, robustness, feasibility, dimensional consistency, boundary behavior, or baseline comparison.
2. State acceptance thresholds before interpreting results whenever the task supplies enough information.
3. Trace every validation claim to a calculation, source, or artifact and distinguish internal checks from external evidence.
4. Identify limitations, failure modes, extrapolation boundaries, and conclusions that the evidence cannot support.
5. On failure, identify the smallest justified rollback: model construction for structural/assumption failures, or model solving for implementation/parameter failures.

## Output

Return an updated Modeling Handoff with `state.current_stage: validation`, checks, evidence, warnings, confidence, and an explicit pass or `needs_revision` conclusion. Recommend paper writing or completion only after passing; otherwise recommend model construction or model solving.

Never route failed validation to paper writing, suppress adverse evidence, or claim the entire task is complete without a recorded validation decision.
```

Create `skills/math-modeling-validation/agents/openai.yaml` with this complete content:

```yaml
interface:
  display_name: "Mathematical Model Validation"
  short_description: "Test model fit, robustness, and limitations"
  default_prompt: "Use $math-modeling-validation to validate these modeling results."

policy:
  allow_implicit_invocation: true
```

- [ ] **Step 12: Add the paper-writing skill and UI metadata**

Create `skills/math-modeling-paper-writing/SKILL.md` with this complete content:

```markdown
---
name: math-modeling-paper-writing
description: "Turn validated mathematical modeling work into a clear paper, report, or requested section with traceable equations, figures, results, assumptions, and limitations. Use only after validation passes or when editing already validated material; do not manufacture evidence or conceal unresolved model failures."
---

# Modeling Paper Writing

Present validated modeling work accurately and coherently.

## Input

Accept the validated handoff, equations, results, artifact paths, target format, audience, and any competition or publication constraints. When invoked independently, read `../math-modeling-orchestrator/references/handoff-contract.md` before returning results.

## Work

1. Confirm that validation passed and identify the requested deliverable, language, length, and formatting constraints.
2. Build a traceable narrative from problem restatement through assumptions, notation, model, solution, validation, strengths, and limitations.
3. Keep symbols, units, terminology, numerical precision, figure/table references, and citations consistent with source artifacts.
4. State assumptions and limitations where readers need them; distinguish verified findings from interpretation and recommendations.
5. Report missing evidence or unresolved failures instead of smoothing them over in prose.

## Output

Return the requested draft or section plus an updated Modeling Handoff with `state.current_stage: paper-writing`, artifact paths, remaining editorial warnings, and `next.recommended_stage: complete` when the deliverable is ready.

Do not invent citations, data, equations, figures, or validation evidence, and do not write around a failed validation gate.
```

Create `skills/math-modeling-paper-writing/agents/openai.yaml` with this complete content:

```yaml
interface:
  display_name: "Mathematical Modeling Paper Writing"
  short_description: "Write traceable reports from validated models"
  default_prompt: "Use $math-modeling-paper-writing to draft this validated modeling report."

policy:
  allow_implicit_invocation: true
```

- [ ] **Step 13: Run repository and validator tests**

Run:

```bash
python3 -m unittest tests/test_suite_validation.py tests/test_repository_contract.py -v
python3 scripts/validate_suite.py
```

Expected: 8 tests PASS and `Suite validation passed`.

- [ ] **Step 14: Run the bundled Codex validators when their optional YAML dependency is available**

Run:

```bash
if python3 -c 'import yaml' 2>/dev/null; then
  python3 /Users/jinana/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
  for skill in skills/*; do
    python3 /Users/jinana/.codex/skills/.system/skill-creator/scripts/quick_validate.py "$skill"
  done
else
  printf '%s\n' 'Bundled Codex validators skipped: optional PyYAML is not installed.'
fi
```

Expected on this machine: the explicit PyYAML skip message. If PyYAML is already available in the execution environment, plugin validation passes and all seven skills print `Skill is valid!`. Do not install a dependency or use network access only for this redundant compatibility check.

- [ ] **Step 15: Commit the plugin and skill contracts**

```bash
git add .codex-plugin skills tests/test_repository_contract.py
git commit -m "feat: scaffold math modeling skill suite"
```

### Task 3: Build and validate a standard local marketplace bundle

**Files:**

- Create: `scripts/build_bundle.py`
- Create: `scripts/validate_bundle.py`
- Create: `tests/test_bundle.py`

- [ ] **Step 1: Write the failing bundle tests**

Create `tests/test_bundle.py` with this complete content:

```python
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from build_bundle import build_bundle  # noqa: E402
from test_suite_validation import make_valid_suite, write_json  # noqa: E402
from validate_bundle import validate_bundle  # noqa: E402


class BundleTests(unittest.TestCase):
    def test_builds_valid_marketplace_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            (source / ".git").mkdir()
            (source / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

            plugin_root = build_bundle(source, output)

            self.assertEqual(
                plugin_root, output / "plugins" / "math-modeling-suite"
            )
            self.assertFalse((plugin_root / ".git").exists())
            self.assertEqual(validate_bundle(output), [])
            marketplace = json.loads(
                (output / ".agents" / "plugins" / "marketplace.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(marketplace["name"], "math-modeling-local")
            self.assertEqual(
                marketplace["plugins"][0]["source"]["path"],
                "./plugins/math-modeling-suite",
            )

    def test_refuses_non_empty_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            source.mkdir()
            output.mkdir()
            (output / "owned-by-user.txt").write_text("keep\n", encoding="utf-8")
            make_valid_suite(source)

            with self.assertRaisesRegex(FileExistsError, "non-empty"):
                build_bundle(source, output)

            self.assertEqual(
                (output / "owned-by-user.txt").read_text(encoding="utf-8"), "keep\n"
            )

    def test_refuses_output_inside_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            make_valid_suite(source)
            output = source / "generated-bundle"

            with self.assertRaisesRegex(ValueError, "outside the source tree"):
                build_bundle(source, output)

    def test_rejects_marketplace_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            output = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            build_bundle(source, output)
            marketplace_path = (
                output / ".agents" / "plugins" / "marketplace.json"
            )
            marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
            marketplace["plugins"][0]["source"]["path"] = "../../outside"
            write_json(marketplace_path, marketplace)

            errors = validate_bundle(output)

            self.assertIn("marketplace source.path escapes the bundle root", errors)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and confirm the missing-module failure**

Run:

```bash
python3 -m unittest tests/test_bundle.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'build_bundle'`.

- [ ] **Step 3: Implement the safe bundle builder**

Create `scripts/build_bundle.py` with this complete content:

```python
#!/usr/bin/env python3
"""Build a self-contained local Codex marketplace bundle."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from suite_validation import PLUGIN_NAME, validate_suite

MARKETPLACE_NAME = "math-modeling-local"
IGNORED_NAMES = {
    ".git",
    ".DS_Store",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
}


def marketplace_payload() -> dict[str, object]:
    return {
        "name": MARKETPLACE_NAME,
        "interface": {"displayName": "Local Math Modeling"},
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": {
                    "source": "local",
                    "path": f"./plugins/{PLUGIN_NAME}",
                },
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Education & Research",
            }
        ],
    }


def _ignore_copy_entries(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in IGNORED_NAMES or name.endswith(".pyc")}


def _require_output_outside_source(source_root: Path, output_root: Path) -> None:
    try:
        output_root.relative_to(source_root)
    except ValueError:
        return
    raise ValueError("bundle output must be outside the source tree")


def build_bundle(source_root: Path, output_root: Path) -> Path:
    source_root = source_root.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    _require_output_outside_source(source_root, output_root)
    errors = validate_suite(source_root)
    if errors:
        raise ValueError("source validation failed:\n- " + "\n- ".join(errors))
    if output_root.exists():
        if not output_root.is_dir() or any(output_root.iterdir()):
            raise FileExistsError(f"refusing to overwrite non-empty output: {output_root}")
    else:
        output_root.mkdir(parents=True)

    plugin_root = output_root / "plugins" / PLUGIN_NAME
    plugin_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_root, plugin_root, ignore=_ignore_copy_entries)

    marketplace_path = output_root / ".agents" / "plugins" / "marketplace.json"
    marketplace_path.parent.mkdir(parents=True, exist_ok=True)
    marketplace_path.write_text(
        json.dumps(marketplace_payload(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return plugin_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default=str(Path(__file__).resolve().parents[1]),
        help="Plugin source root; defaults to this repository.",
    )
    parser.add_argument("--output", required=True, help="Empty bundle output directory.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plugin_root = build_bundle(Path(args.source), Path(args.output))
    print(f"Bundle created: {plugin_root.parents[1]}")
    print(f"Plugin copy: {plugin_root}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Implement bundle validation**

Create `scripts/validate_bundle.py` with this complete content:

```python
#!/usr/bin/env python3
"""Validate a local Codex marketplace bundle and its plugin copy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_bundle import MARKETPLACE_NAME
from suite_validation import PLUGIN_NAME, validate_suite


def _load_marketplace(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file():
        errors.append("missing .agents/plugins/marketplace.json")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.append("marketplace.json must be readable valid JSON")
        return None
    if not isinstance(payload, dict):
        errors.append("marketplace.json must contain an object")
        return None
    return payload


def _resolve_plugin_root(
    bundle_root: Path, marketplace: dict[str, Any], errors: list[str]
) -> Path | None:
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list):
        errors.append("marketplace plugins must be an array")
        return None
    matches = [
        entry
        for entry in plugins
        if isinstance(entry, dict) and entry.get("name") == PLUGIN_NAME
    ]
    if len(matches) != 1:
        errors.append(f"marketplace must contain exactly one {PLUGIN_NAME} entry")
        return None
    source = matches[0].get("source")
    if not isinstance(source, dict) or source.get("source") != "local":
        errors.append("marketplace plugin source must be local")
        return None
    raw_path = source.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        errors.append("marketplace source.path must be a non-empty string")
        return None
    candidate = (bundle_root / raw_path).resolve()
    try:
        candidate.relative_to(bundle_root)
    except ValueError:
        errors.append("marketplace source.path escapes the bundle root")
        return None
    return candidate


def validate_bundle(bundle_root: Path) -> list[str]:
    bundle_root = bundle_root.expanduser().resolve()
    errors: list[str] = []
    marketplace = _load_marketplace(
        bundle_root / ".agents" / "plugins" / "marketplace.json", errors
    )
    if marketplace is None:
        return errors
    if marketplace.get("name") != MARKETPLACE_NAME:
        errors.append(f"marketplace name must be {MARKETPLACE_NAME}")
    plugin_root = _resolve_plugin_root(bundle_root, marketplace, errors)
    if plugin_root is None:
        return errors
    if not (plugin_root / ".codex-plugin" / "plugin.json").is_file():
        errors.append("marketplace source.path does not contain the plugin manifest")
        return errors
    errors.extend(f"plugin: {error}" for error in validate_suite(plugin_root))
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", help="Bundle root containing .agents and plugins.")
    return parser.parse_args()


def main() -> None:
    bundle_root = Path(parse_args().bundle).expanduser().resolve()
    errors = validate_bundle(bundle_root)
    if errors:
        print("Bundle validation failed:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print(f"Bundle validation passed: {bundle_root}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run bundle tests and an actual temporary bundle smoke test**

Run:

```bash
python3 -m unittest tests/test_bundle.py -v
bundle_dir="$(mktemp -d)/math-modeling-suite-bundle"
python3 scripts/build_bundle.py --output "$bundle_dir"
python3 scripts/validate_bundle.py "$bundle_dir"
```

Expected: 4 tests PASS, bundle creation succeeds, and bundle validation passes.

- [ ] **Step 6: Commit bundle tooling**

```bash
git add scripts/build_bundle.py scripts/validate_bundle.py tests/test_bundle.py
git commit -m "feat: add validated local plugin bundles"
```

### Task 4: Add safe cachebuster preview and update

**Files:**

- Create: `scripts/update_cachebuster.py`
- Create: `tests/test_update_cachebuster.py`

- [ ] **Step 1: Write the failing cachebuster tests**

Create `tests/test_update_cachebuster.py` with this complete content:

```python
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from update_cachebuster import replace_cachebuster, update_manifest  # noqa: E402


class CachebusterTests(unittest.TestCase):
    def test_replaces_existing_codex_suffix(self) -> None:
        self.assertEqual(
            replace_cachebuster(
                "0.1.0+codex.local-20260101-000000", "local-20260826-120000"
            ),
            "0.1.0+codex.local-20260826-120000",
        )

    def test_preserves_prerelease_base(self) -> None:
        self.assertEqual(
            replace_cachebuster("1.2.3-beta.1+old", "local-20260826-120000"),
            "1.2.3-beta.1+codex.local-20260826-120000",
        )

    def test_preview_does_not_write_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "plugin.json"
            manifest.write_text('{"version": "0.1.0"}\n', encoding="utf-8")

            old_version, new_version = update_manifest(
                manifest, "local-20260826-120000", apply=False
            )

            self.assertEqual(old_version, "0.1.0")
            self.assertEqual(new_version, "0.1.0+codex.local-20260826-120000")
            self.assertEqual(
                json.loads(manifest.read_text(encoding="utf-8"))["version"], "0.1.0"
            )

    def test_apply_writes_manifest_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "plugin.json"
            manifest.write_text('{"version": "0.1.0"}\n', encoding="utf-8")

            update_manifest(manifest, "local-20260826-120000", apply=True)

            self.assertEqual(
                json.loads(manifest.read_text(encoding="utf-8"))["version"],
                "0.1.0+codex.local-20260826-120000",
            )
            self.assertEqual(list(Path(directory).glob(".*.tmp")), [])

    def test_rejects_unsafe_token(self) -> None:
        with self.assertRaisesRegex(ValueError, "cachebuster token"):
            replace_cachebuster("0.1.0", "../../escape")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and confirm the missing-module failure**

Run:

```bash
python3 -m unittest tests/test_update_cachebuster.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'update_cachebuster'`.

- [ ] **Step 3: Implement cachebuster replacement and atomic writes**

Create `scripts/update_cachebuster.py` with this complete content:

```python
#!/usr/bin/env python3
"""Preview or apply a Codex cachebuster to the plugin version."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from suite_validation import SEMVER_RE

TOKEN_RE = re.compile(r"^[0-9A-Za-z-]+$")


def default_cachebuster() -> str:
    return datetime.now(timezone.utc).strftime("local-%Y%m%d-%H%M%S")


def replace_cachebuster(version: str, token: str) -> str:
    if SEMVER_RE.fullmatch(version) is None:
        raise ValueError(f"current version is not strict SemVer: {version}")
    if TOKEN_RE.fullmatch(token) is None:
        raise ValueError("cachebuster token must contain only letters, digits, and hyphens")
    base = version.split("+", 1)[0]
    return f"{base}+codex.{token}"


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"unable to read valid manifest JSON: {path}") from error
    if not isinstance(manifest, dict) or not isinstance(manifest.get("version"), str):
        raise ValueError("plugin manifest must contain a string version")
    return manifest


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temporary_path = Path(handle.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def update_manifest(path: Path, token: str, *, apply: bool) -> tuple[str, str]:
    path = path.expanduser().resolve()
    manifest = _load_manifest(path)
    old_version = manifest["version"]
    new_version = replace_cachebuster(old_version, token)
    if apply:
        manifest["version"] = new_version
        _write_json_atomically(path, manifest)
    return old_version, new_version


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=str(
            Path(__file__).resolve().parents[1]
            / ".codex-plugin"
            / "plugin.json"
        ),
        help="Plugin manifest path.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Cachebuster token; defaults to local-<UTC timestamp>.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the proposed version. Without this flag the command is a preview.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    token = args.token or default_cachebuster()
    old_version, new_version = update_manifest(
        Path(args.manifest), token, apply=args.apply
    )
    action = "Updated" if args.apply else "Preview"
    print(f"{action}: {old_version} -> {new_version}")
    if not args.apply:
        print("No file changed. Re-run with --apply to write the version.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run cachebuster tests and a no-write repository preview**

Run:

```bash
python3 -m unittest tests/test_update_cachebuster.py -v
before="$(git hash-object .codex-plugin/plugin.json)"
python3 scripts/update_cachebuster.py --token local-20260826-120000
after="$(git hash-object .codex-plugin/plugin.json)"
test "$before" = "$after"
```

Expected: 5 tests PASS, the CLI prints `Preview`, and the hash comparison succeeds.

- [ ] **Step 5: Commit cachebuster tooling**

```bash
git add scripts/update_cachebuster.py tests/test_update_cachebuster.py
git commit -m "feat: add safe plugin cachebuster updates"
```

### Task 5: Add dry-run-first local installation orchestration

**Files:**

- Create: `scripts/install_local.py`
- Create: `tests/test_install_local.py`

- [ ] **Step 1: Write the failing installer tests**

Create `tests/test_install_local.py` with this complete content:

```python
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from install_local import install_local  # noqa: E402
from test_suite_validation import make_valid_suite  # noqa: E402


class InstallLocalTests(unittest.TestCase):
    def test_dry_run_builds_bundle_without_running_codex(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            bundle = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            calls: list[tuple[list[str], bool]] = []

            def runner(command: list[str], *, check: bool) -> None:
                calls.append((command, check))

            commands = install_local(
                source,
                bundle,
                apply=False,
                codex_bin="/fake/codex",
                runner=runner,
            )

            self.assertEqual(calls, [])
            self.assertTrue(
                (bundle / ".agents" / "plugins" / "marketplace.json").is_file()
            )
            self.assertEqual(
                commands,
                [
                    ["/fake/codex", "plugin", "marketplace", "add", str(bundle)],
                    [
                        "/fake/codex",
                        "plugin",
                        "add",
                        "math-modeling-suite@math-modeling-local",
                    ],
                ],
            )

    def test_apply_runs_commands_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            bundle = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            calls: list[list[str]] = []

            def runner(command: list[str], *, check: bool) -> None:
                self.assertTrue(check)
                calls.append(command)

            commands = install_local(
                source,
                bundle,
                apply=True,
                codex_bin="/fake/codex",
                runner=runner,
            )

            self.assertEqual(calls, commands)

    def test_registered_marketplace_skips_marketplace_add(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            bundle = base / "bundle"
            source.mkdir()
            make_valid_suite(source)

            commands = install_local(
                source,
                bundle,
                apply=False,
                marketplace_registered=True,
                codex_bin="codex",
            )

            self.assertEqual(
                commands,
                [
                    [
                        "codex",
                        "plugin",
                        "add",
                        "math-modeling-suite@math-modeling-local",
                    ]
                ],
            )

    def test_apply_reuses_a_valid_dry_run_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            bundle = base / "bundle"
            source.mkdir()
            make_valid_suite(source)
            install_local(
                source,
                bundle,
                apply=False,
                codex_bin="/fake/codex",
            )
            calls: list[list[str]] = []

            def runner(command: list[str], *, check: bool) -> None:
                self.assertTrue(check)
                calls.append(command)

            commands = install_local(
                source,
                bundle,
                apply=True,
                codex_bin="/fake/codex",
                runner=runner,
            )

            self.assertEqual(calls, commands)

    def test_missing_codex_fails_before_creating_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            bundle = base / "bundle"
            source.mkdir()
            make_valid_suite(source)

            with patch("install_local.shutil.which", return_value=None):
                with self.assertRaisesRegex(FileNotFoundError, "Codex CLI"):
                    install_local(source, bundle, apply=True)

            self.assertFalse(bundle.exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and confirm the missing-module failure**

Run:

```bash
python3 -m unittest tests/test_install_local.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'install_local'`.

- [ ] **Step 3: Implement dry-run and apply installation paths**

Create `scripts/install_local.py` with this complete content:

```python
#!/usr/bin/env python3
"""Build and optionally install the local math-modeling Codex plugin."""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from build_bundle import MARKETPLACE_NAME, build_bundle
from suite_validation import PLUGIN_NAME
from validate_bundle import validate_bundle

Runner = Callable[..., object]


def _commands(
    codex_bin: str, bundle_root: Path, *, marketplace_registered: bool
) -> list[list[str]]:
    commands: list[list[str]] = []
    if not marketplace_registered:
        commands.append(
            [codex_bin, "plugin", "marketplace", "add", str(bundle_root)]
        )
    commands.append(
        [codex_bin, "plugin", "add", f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"]
    )
    return commands


def install_local(
    source_root: Path,
    bundle_root: Path,
    *,
    apply: bool,
    marketplace_registered: bool = False,
    codex_bin: str | None = None,
    runner: Runner = subprocess.run,
) -> list[list[str]]:
    source_root = source_root.expanduser().resolve()
    bundle_root = bundle_root.expanduser().resolve()
    resolved_codex = codex_bin or shutil.which("codex")
    if apply and resolved_codex is None:
        raise FileNotFoundError(
            "Codex CLI was not found; install it or pass --codex-bin before using --apply"
        )
    command_bin = resolved_codex or "codex"

    if bundle_root.is_dir() and any(bundle_root.iterdir()):
        errors = validate_bundle(bundle_root)
    else:
        build_bundle(source_root, bundle_root)
        errors = validate_bundle(bundle_root)
    if errors:
        raise ValueError("bundle validation failed:\n- " + "\n- ".join(errors))
    commands = _commands(
        command_bin,
        bundle_root,
        marketplace_registered=marketplace_registered,
    )
    if apply:
        for command in commands:
            runner(command, check=True)
    return commands


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default=str(Path(__file__).resolve().parents[1]),
        help="Plugin source root; defaults to this repository.",
    )
    parser.add_argument("--bundle", required=True, help="Empty bundle output directory.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Run Codex marketplace and plugin commands. The default is dry-run.",
    )
    parser.add_argument(
        "--marketplace-registered",
        action="store_true",
        help="Skip marketplace add and reinstall from the existing local marketplace.",
    )
    parser.add_argument(
        "--codex-bin",
        default=None,
        help="Explicit Codex CLI path; otherwise resolve codex from PATH.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    commands = install_local(
        Path(args.source),
        Path(args.bundle),
        apply=args.apply,
        marketplace_registered=args.marketplace_registered,
        codex_bin=args.codex_bin,
    )
    if args.apply:
        print("Local plugin installation commands completed.")
        print("Restart Codex if it is open, then test the plugin in a new thread.")
        return
    print("Dry run complete. Bundle validated; no Codex configuration changed.")
    print("Commands that --apply would run:")
    for command in commands:
        print(f"  {shlex.join(command)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run installer tests and a real dry run**

Run:

```bash
python3 -m unittest tests/test_install_local.py -v
bundle_dir="$(mktemp -d)/math-modeling-suite-bundle"
python3 scripts/install_local.py --bundle "$bundle_dir"
```

Expected: 5 tests PASS; the dry run validates a bundle, prints the two exact Codex commands, and says no Codex configuration changed.

- [ ] **Step 5: Commit installer tooling**

```bash
git add scripts/install_local.py tests/test_install_local.py
git commit -m "feat: add dry-run local plugin installer"
```

### Task 6: Document architecture, installation, invocation, and extension rules

**Files:**

- Modify: `README.md`
- Modify: `.gitignore`
- Create: `docs/architecture.md`

- [ ] **Step 1: Replace the minimal README with the user and developer workflow**

Replace `README.md` with this complete content (the blank line after the title preserves the user's existing uncommitted formatting change):

````markdown
# Math Modeling Skill Suite

A Codex plugin for staged mathematical modeling workflows, initially focused on CUMCM-style problems. One orchestrator routes work through six independently discoverable skills: problem analysis, data analysis, model construction, model solving, validation, and paper writing.

The repository currently provides the plugin architecture and development workflow. It deliberately does not claim a complete catalog of mathematical methods yet.

## Architecture

```text
math-modeling-orchestrator
  -> math-modeling-problem-analysis
  -> math-modeling-data-analysis       (optional)
  -> math-modeling-model-construction
  -> math-modeling-model-solving
  -> math-modeling-validation
       -> model construction/solving   (failed validation)
       -> math-modeling-paper-writing   (optional, passed validation)
```

The plugin is the installation and version boundary. Each directory under `skills/` is an independent Codex skill. The orchestrator owns cross-stage routing; stage skills return a structured Modeling Handoff but do not call one another or declare the whole problem complete.

See [docs/architecture.md](docs/architecture.md) for the stage registry, handoff contract, safety boundaries, and extension rules.

## Requirements

- Python 3.10 or newer for repository scripts and tests
- Codex CLI with plugin commands for local installation
- No Python packages, API keys, solver runtimes, or network access for validation and bundle creation

## Validate the source

```bash
python3 scripts/validate_suite.py
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The validator checks the plugin manifest, skill frontmatter, UI metadata, stage registry, handoff contract, skip/rollback rules, and unresolved scaffold markers.

## Build a local marketplace bundle

Codex local marketplaces resolve plugin paths from a standard bundle layout. Keep generated bundles outside this repository:

```bash
bundle_dir="$(mktemp -d)/math-modeling-suite-bundle"
python3 scripts/build_bundle.py --output "$bundle_dir"
python3 scripts/validate_bundle.py "$bundle_dir"
```

The bundle contains:

```text
<bundle>/
  .agents/plugins/marketplace.json
  plugins/math-modeling-suite/
```

The builder refuses to overwrite a non-empty directory and excludes Git metadata and local caches.

## Preview and install locally

Start with a dry run. It builds or reuses a valid bundle and prints the exact Codex commands without changing Codex configuration:

```bash
bundle_dir="$(mktemp -d)/math-modeling-suite-bundle"
python3 scripts/install_local.py --bundle "$bundle_dir"
```

After reviewing the output, install from the same validated bundle:

```bash
python3 scripts/install_local.py --bundle "$bundle_dir" --apply
```

This runs:

```bash
codex plugin marketplace add "$bundle_dir"
codex plugin add math-modeling-suite@math-modeling-local
```

Restart Codex if it is open, then use a new thread so the installed skill set is loaded cleanly.

## Invoke the skills

Use the orchestrator for an end-to-end problem:

```text
Use $math-modeling-orchestrator to work through this modeling problem: <problem>
```

Use a stage skill directly for bounded work:

```text
Use $math-modeling-validation to validate these model results and identify the correct rollback if a check fails.
```

All available skill names are listed in [docs/architecture.md](docs/architecture.md).

## Development update loop

Preview a cachebuster change:

```bash
python3 scripts/update_cachebuster.py
```

Apply it only when the source should move to a new local plugin cache key:

```bash
python3 scripts/update_cachebuster.py --apply
```

Then build a fresh bundle and reinstall from the already registered marketplace:

```bash
bundle_dir="$(mktemp -d)/math-modeling-suite-bundle"
python3 scripts/install_local.py \
  --bundle "$bundle_dir" \
  --marketplace-registered \
  --apply
```

Start a new Codex thread after reinstalling. Stable releases use SemVer; local iterations replace only the `+codex.local-<UTC timestamp>` build metadata.

## Safety boundaries

- Validation, tests, bundle creation, and installer dry runs do not modify Codex configuration.
- `install_local.py` requires `--apply` before it runs external Codex commands.
- `update_cachebuster.py` requires `--apply` before it edits the plugin manifest.
- The plugin does not install solver runtimes, TeX, Python packages, MCP servers, or credentials.
- Failed model validation cannot route to paper writing.

## License

MIT. See [LICENSE](LICENSE).
````

- [ ] **Step 2: Add the maintainer architecture guide**

Create `docs/architecture.md` with this complete content:

````markdown
# Math Modeling Suite Architecture

## System boundary

`math-modeling-suite` is one Codex plugin and one versioned distribution unit. The `skills/` children are independent discovery and invocation units. Installing the plugin makes every skill available; it does not create an automatic program pipeline. `$math-modeling-orchestrator` owns stage selection, state transfer, skip decisions, and rollback decisions at model runtime.

The initialization layer has no external runtime dependency. It provides contracts and deterministic tooling; future domain work adds mathematical methods behind the existing stage boundaries.

## Component map

| Skill | Owns | Must not own |
| --- | --- | --- |
| `math-modeling-orchestrator` | Cross-stage state, routing, gates, resume, final synthesis | Detailed work of a stage |
| `math-modeling-problem-analysis` | Objectives, constraints, metrics, variables, ambiguities | Final model selection or solving |
| `math-modeling-data-analysis` | Provenance, units, quality, transformations, exploratory evidence | Final model selection or causal invention |
| `math-modeling-model-construction` | Assumptions, notation, candidate models, equations, selection rationale | Full numerical execution |
| `math-modeling-model-solving` | Algorithms, parameters, reproducibility, computed artifacts | Silent model changes or final validation |
| `math-modeling-validation` | Fit, residuals, sensitivity, robustness, feasibility, limitations, rollback | Paper writing after a failed gate |
| `math-modeling-paper-writing` | Traceable presentation of validated work | New evidence, hidden failures, or invented citations |

## Routing source of truth

`skills/math-modeling-orchestrator/references/workflow.json` is the machine-readable stage registry. The suite validator enforces these invariants:

```text
problem-analysis -> data-analysis | model-construction
data-analysis -> model-construction
model-construction -> model-solving
model-solving -> validation
validation-pass -> paper-writing | complete
validation-fail -> model-construction | model-solving
paper-writing -> complete
```

Data analysis is optional and records a reason when skipped. Paper writing is optional and requires passed validation. No route from failed validation may reach paper writing.

## Modeling Handoff

`skills/math-modeling-orchestrator/references/handoff-contract.md` defines the shared stage output. The minimum stable interface is:

```yaml
schema_version: "1"
state:
  current_stage: "problem-analysis"
  status: "complete"
result:
  summary: "Stage result"
  details: []
next:
  recommended_stage: "data-analysis"
  rationale: "Why"
  alternatives: []
```

Stages also preserve objectives, constraints, assumptions, variables, data provenance, methods, decisions, artifacts, checks, warnings, and confidence when those fields apply. Empty collections are valid; fabricated values are not.

The handoff is a structured model-output contract. Users do not need a database or state file. Persist it only when the active modeling project benefits from an auditable artifact.

## Validation layers

1. `scripts/validate_suite.py` checks source structure, manifest fields, skill metadata, stage references, handoff fields, and routing invariants.
2. `python3 -m unittest discover -s tests -p 'test_*.py' -v` checks failures as well as the happy path without model APIs.
3. `scripts/build_bundle.py` creates a clean standard marketplace bundle outside the source tree.
4. `scripts/validate_bundle.py` proves that the marketplace path resolves inside the bundle and that the copied plugin still passes suite validation.
5. The bundled Codex plugin and skill validators provide an additional compatibility check during development.

## Installation boundary

The repository root is the plugin source. A generated bundle adapts it to Codex's local marketplace layout:

```text
bundle/.agents/plugins/marketplace.json
bundle/plugins/math-modeling-suite/.codex-plugin/plugin.json
```

`install_local.py` is dry-run by default. `--apply` is the authorization boundary for `codex plugin marketplace add` and `codex plugin add`. Reinstalling from an already configured marketplace uses `--marketplace-registered` and a fresh bundle after changing the cachebuster.

## Adding a stage or specialization

Add a new skill only when it has a distinct trigger, input/output boundary, and useful independent invocation. Then:

1. Create `skills/<prefixed-name>/SKILL.md` and `agents/openai.yaml`.
2. Add its entry, transitions, optionality, and gates to `workflow.json` if the orchestrator routes to it.
3. Define what it adds to the Modeling Handoff and what it must not change.
4. Extend validator constants and structural tests.
5. Add a behavior fixture that asserts a routing or quality invariant rather than exact prose.
6. Validate the source and a generated bundle before reinstalling.

Prefer references inside a stage for substantial method families. Do not grow the orchestrator into a catalog of algorithms.

## Contract evolution

Compatible additions may keep handoff `schema_version: "1"`. Removing a field, changing field meaning, narrowing an accepted value, or altering required routing semantics is incompatible: increment the schema version and document how an existing handoff resumes or migrates.

Stable plugin releases use SemVer. Local development changes only the `+codex.<cachebuster>` build metadata so Codex loads a new cache key without pretending a new public release exists.
````

- [ ] **Step 3: Ignore repository-local bundle output**

Append this exact block to `.gitignore`:

```gitignore

# Local Codex plugin bundles
.local-bundles/
```

- [ ] **Step 4: Verify every documented command and path exists**

Run:

```bash
python3 scripts/validate_suite.py
python3 scripts/build_bundle.py --help
python3 scripts/validate_bundle.py --help
python3 scripts/install_local.py --help
python3 scripts/update_cachebuster.py --help
rg -n 'scripts/(validate_suite|build_bundle|validate_bundle|install_local|update_cachebuster)\.py|math-modeling-(orchestrator|problem-analysis|data-analysis|model-construction|model-solving|validation|paper-writing)' README.md docs/architecture.md
```

Expected: suite validation passes, each help command exits 0, and every documented script and skill reference resolves to a real repository path/name.

- [ ] **Step 5: Commit documentation and the preserved README change**

```bash
git add README.md .gitignore docs/architecture.md
git commit -m "docs: document plugin development workflow"
```

### Task 7: Run end-to-end verification and record the initialized baseline

**Files:**

- Modify only if verification exposes a defect: files introduced in Tasks 1-6

- [ ] **Step 1: Compile Python sources**

Run:

```bash
python3 -m compileall -q scripts tests
```

Expected: exit 0 with no syntax errors.

- [ ] **Step 2: Run the complete deterministic test suite**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: exactly 62 tests PASS (25 validator + 8 repository + 16 bundle + 7 cachebuster + 6 installer).

- [ ] **Step 3: Run source validation and the optional bundled Codex validators**

Run:

```bash
python3 scripts/validate_suite.py
if python3 -c 'import yaml' 2>/dev/null; then
  python3 /Users/jinana/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
  for skill in skills/*; do
    python3 /Users/jinana/.codex/skills/.system/skill-creator/scripts/quick_validate.py "$skill"
  done
else
  printf '%s\n' 'Bundled Codex validators skipped: optional PyYAML is not installed.'
fi
```

Expected: source validation passes. On this machine the optional validators report the documented PyYAML skip; in an environment with PyYAML, plugin validation and all seven skill validations also pass.

- [ ] **Step 4: Prove bundle creation, validation, and installer dry-run**

Run:

```bash
verification_root="$(mktemp -d)"
bundle_dir="$verification_root/math-modeling-suite-bundle"
python3 scripts/install_local.py --bundle "$bundle_dir"
python3 scripts/validate_bundle.py "$bundle_dir"
test -f "$bundle_dir/.agents/plugins/marketplace.json"
test -f "$bundle_dir/plugins/math-modeling-suite/.codex-plugin/plugin.json"
```

Expected: dry run prints the exact marketplace/plugin commands, bundle validation passes, and both file checks succeed. This step does not modify Codex configuration.

- [ ] **Step 5: Check formatting, accidental placeholders, and repository state**

Run:

```bash
git diff --check
rg -n '\[(TODO|TBD):' .codex-plugin skills scripts tests README.md docs/architecture.md || true
git status --short --branch
git log --oneline --decorate -8
```

Expected: `git diff --check` is clean, the placeholder search returns no hits, the worktree has no unintended uncommitted files, commits are local and ahead of `origin/main`, and nothing has been pushed.

- [ ] **Step 6: Optionally exercise the real Codex installation after explicit filesystem approval**

Use the already validated bundle from Step 4. Because this writes outside the repository, request the environment's required approval immediately before running:

```bash
python3 scripts/install_local.py --bundle "$bundle_dir" --apply
codex plugin list
```

Expected: `math-modeling-suite@math-modeling-local` is installed/listed. Restart Codex if it is open and use a new thread for behavioral testing. If the user chooses not to modify local Codex state, report the verified dry-run boundary instead of claiming a real installation.

## Plan self-review record

The complete snippets in Tasks 1-6 record the original RED/GREEN implementation sequence. The final implementation supersedes them where review hardening expanded the contract: validation failure may roll back to problem analysis, data analysis, model construction, or model solving according to the earliest invalidated evidence; the handoff now tracks `validation_status`, `completed_stages`, and `invalidated_stages`; paper writing requires a current validation pass with no invalidated input stage; source and bundle validation reject symlinked metadata, Git submodules, known credential paths, private-key suffixes, unreadable directories, and special files; bundle publication is staged and atomic; and registered-marketplace reinstall verifies an existing bundle at the exact registered path. This is a filename/type archive policy, not a content-level secret scanner. Related regression assertions are consolidated into the 62-test baseline without removing coverage. The Task 7 commands and exact test count below are the authoritative final verification baseline.

- **Spec coverage:** Tasks 1-2 cover manifest, seven skills, registry, handoff, skip/rollback gates, and independent discovery. Tasks 3-5 cover source/bundle separation, safe build, validation, cachebuster, dry-run/apply install, missing CLI behavior, and new-thread guidance. Tasks 6-7 cover architecture, README command consistency, deterministic behavior tests, optional bundled-validator compatibility, and no-push verification.
- **Placeholder scan:** The plan contains no unfinished scaffold placeholders. Test fixtures intentionally search for the literal marker families through regular expressions rather than embedding unfinished content in generated plugin files.
- **Type consistency:** `validate_suite(Path) -> list[str]`, `build_bundle(Path, Path) -> Path`, `validate_bundle(Path) -> list[str]`, `update_manifest(Path, str, apply=bool) -> tuple[str, str]`, and `install_local(Path, Path, ...) -> list[list[str]]` are used consistently across production code and tests.
- **Test count:** Task 7 expects exactly 62 passing tests (25 validator + 8 repository + 16 bundle + 7 cachebuster + 6 installer). If implementation legitimately adds or removes a test, update the documented count in the same commit so the verification claim remains exact.
