import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from suite_validation import (  # noqa: E402
    ALL_SKILLS,
    HANDOFF_REQUIRED_FIELDS,
    STAGE_SKILLS,
    validate_suite,
)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def make_valid_suite(root):
    manifest = {
        "name": "math-modeling-suite",
        "version": "0.1.0",
        "description": "A reusable mathematical modeling skill suite.",
        "author": {"name": "Math Modeling Team"},
        "license": "MIT",
        "keywords": ["math", "modeling"],
        "skills": "./skills/",
        "interface": {
            "displayName": "Math Modeling Suite",
            "shortDescription": "Modeling workflows",
            "longDescription": "A staged mathematical modeling workflow.",
            "developerName": "Math Modeling Team",
            "category": "education",
            "capabilities": ["workflow", "validation"],
            "defaultPrompt": ["Use $math-modeling-orchestrator to guide the work."],
        },
    }
    write_json(root / ".codex-plugin" / "plugin.json", manifest)

    for skill in ALL_SKILLS:
        skill_dir = root / "skills" / skill
        skill_dir.mkdir(parents=True, exist_ok=True)
        body = "\n".join(f"- {stage}" for stage in STAGE_SKILLS)
        if skill != "math-modeling-orchestrator":
            body = "See ../math-modeling-orchestrator/references/handoff-contract.md."
        skill_dir.joinpath("SKILL.md").write_text(
            "---\n"
            f"name: {skill}\n"
            f"description: {skill} stage instructions.\n"
            "---\n\n"
            f"{body}\n",
            encoding="utf-8",
        )
        agent_dir = skill_dir / "agents"
        agent_dir.mkdir()
        agent_dir.joinpath("openai.yaml").write_text(
            "interface:\n"
            f'  display_name: "{skill}"\n'
            f'  short_description: "Run {skill}."\n'
            f'  default_prompt: "Use ${skill} for this stage."\n'
            "policy:\n"
            "  allow_implicit_invocation: true\n",
            encoding="utf-8",
        )

    contract = root / "skills" / "math-modeling-orchestrator" / "references" / "handoff-contract.md"
    contract.parent.mkdir()
    contract.write_text("\n".join(f"{field}: required" for field in HANDOFF_REQUIRED_FIELDS), encoding="utf-8")

    workflow = {
        "schema_version": "1",
        "orchestrator": "math-modeling-orchestrator",
        "stages": [{"skill": skill, "optional": skill in {"math-modeling-data-analysis", "math-modeling-paper-writing"}} for skill in STAGE_SKILLS],
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
            "data-analysis-skip": {"allowed": True, "requires_reason": True},
            "paper-writing": {"optional": True, "requires_validation_pass": True},
        },
        "handoff": {
            "required_fields": list(HANDOFF_REQUIRED_FIELDS),
            "statuses": ["pending", "in_progress", "complete", "needs_revision", "skipped"],
        },
    }
    write_json(root / "skills" / "math-modeling-orchestrator" / "references" / "workflow.json", workflow)


class SuiteValidationTests(unittest.TestCase):
    def test_valid_suite_has_no_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            self.assertEqual([], validate_suite(root))

    def test_missing_manifest_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            errors = validate_suite(Path(directory))
            self.assertIn("missing .codex-plugin/plugin.json", errors)

    def test_missing_required_skill_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            validation_dir = root / "skills" / "math-modeling-validation"
            for path in sorted(validation_dir.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                else:
                    path.rmdir()
            validation_dir.rmdir()
            errors = validate_suite(root)
            self.assertTrue(any("missing required skills" in error for error in errors))

    def test_invalid_validation_fail_route_is_reported_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            workflow_path = root / "skills" / "math-modeling-orchestrator" / "references" / "workflow.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            workflow["transitions"]["validation-fail"].append("paper-writing")
            write_json(workflow_path, workflow)
            self.assertIn(
                "workflow validation-fail must route only to model-construction or model-solving",
                validate_suite(root),
            )

    def test_agent_default_prompt_must_mention_its_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            agent = root / "skills" / "math-modeling-data-analysis" / "agents" / "openai.yaml"
            agent.write_text(
                agent.read_text(encoding="utf-8").replace(
                    "$math-modeling-data-analysis", "$wrong-skill"
                ),
                encoding="utf-8",
            )
            errors = validate_suite(root)
            self.assertTrue(any("default_prompt must mention" in error for error in errors))

    def test_extra_skill_is_validated_and_duplicate_name_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            extra = root / "skills" / "extra-skill"
            extra.mkdir()
            extra.joinpath("SKILL.md").write_text(
                "---\nname: math-modeling-data-analysis\ndescription: extra\n---\n",
                encoding="utf-8",
            )
            (extra / "agents").mkdir()
            (extra / "agents" / "openai.yaml").write_text(
                'interface:\n  display_name: "extra"\n  short_description: "extra"\n  default_prompt: "Use $extra-skill."\npolicy:\n  allow_implicit_invocation: true\n',
                encoding="utf-8",
            )
            self.assertTrue(any("duplicate skill frontmatter name" in error for error in validate_suite(root)))

    def test_capabilities_must_be_nonempty_strings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            manifest_path = root / ".codex-plugin" / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["interface"]["capabilities"] = [""]
            write_json(manifest_path, manifest)
            self.assertTrue(any("capabilities" in error for error in validate_suite(root)))

    def test_guards_must_not_contain_extra_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            workflow_path = root / "skills" / "math-modeling-orchestrator" / "references" / "workflow.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            workflow["guards"]["unexpected"] = {"allowed": True}
            write_json(workflow_path, workflow)
            self.assertTrue(any("guards" in error for error in validate_suite(root)))


if __name__ == "__main__":
    unittest.main()
