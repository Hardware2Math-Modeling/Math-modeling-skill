import json
import subprocess
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


EXPECTED_WORKFLOW_STAGE_SKILLS = (
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
EXPECTED_SUPPORT_SKILLS = ("math-modeling-method-library",)
EXPECTED_ALL_SKILLS = (
    "math-modeling-orchestrator",
    *EXPECTED_WORKFLOW_STAGE_SKILLS,
    *EXPECTED_SUPPORT_SKILLS,
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

    for skill in EXPECTED_ALL_SKILLS:
        skill_dir = root / "skills" / skill
        skill_dir.mkdir(parents=True, exist_ok=True)
        body = "\n".join(f"- {stage}" for stage in EXPECTED_WORKFLOW_STAGE_SKILLS)
        if skill in EXPECTED_SUPPORT_SKILLS:
            body = "Read-only catalog/reference support. Do not write project state."
        elif skill != "math-modeling-orchestrator":
            body = "See ../math-modeling-orchestrator/references/handoff-contract.md."
        skill_dir.joinpath("SKILL.md").write_text(
            "---\n"
            f"name: {skill}\n"
            f"description: Use when {skill} is needed for its bounded stage.\n"
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
    contract.write_text(
        "schema_version: \"1\"\n"
        "task:\n"
        "  statement: \"required\"\n"
        "  objectives: []\n"
        "  constraints: []\n"
        "state:\n"
        "  current_stage: \"problem-analysis\"\n"
        "  status: \"complete\"\n"
        "  validation_status: \"pending\"\n"
        "  completed_stages: []\n"
        "  invalidated_stages: []\n"
        "result:\n"
        "  summary: \"required\"\n"
        "next:\n"
        "  rationale: \"required\"\n"
        "  alternatives: []\n"
        "quality:\n"
        "  warnings: []\n"
        "  confidence: \"medium\"\n",
        encoding="utf-8",
    )

    workflow = {
        "schema_version": "2",
        "orchestrator": "math-modeling-orchestrator",
        "stages": [
            {
                "id": skill.removeprefix("math-modeling-"),
                "skill": skill,
                "optional": skill
                in {
                    "math-modeling-data-analysis",
                    "math-modeling-visualization",
                    "math-modeling-paper-writing",
                    "math-modeling-paper-production",
                },
            }
            for skill in EXPECTED_WORKFLOW_STAGE_SKILLS
        ],
        "transitions": {
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
        },
        "guards": {
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
        },
        "handoff": {
            "required_fields": list(HANDOFF_REQUIRED_FIELDS),
            "statuses": ["pending", "in_progress", "complete", "needs_revision", "skipped"],
            "state_fields": [
                "current_stage",
                "status",
                "validation_status",
                "completed_stages",
                "invalidated_stages",
            ],
            "validation_statuses": ["pending", "pass", "needs_revision", "stale"],
        },
    }
    write_json(root / "skills" / "math-modeling-orchestrator" / "references" / "workflow.json", workflow)


class SuiteValidationTests(unittest.TestCase):
    def test_complete_skill_registry_has_routed_and_support_boundaries(self):
        self.assertEqual(EXPECTED_WORKFLOW_STAGE_SKILLS, STAGE_SKILLS)
        self.assertEqual(EXPECTED_ALL_SKILLS, ALL_SKILLS)
        self.assertNotIn("math-modeling-method-library", STAGE_SKILLS)

    def test_rejects_malformed_suite_root(self):
        self.assertIn(
            "suite root must be a valid path",
            validate_suite(Path("\x00")),
        )

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "suite"
            link = base / "suite-link"
            make_valid_suite(root)
            try:
                link.symlink_to(root, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlinks unavailable: {error}")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_suite.py"), str(link)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("suite root must not be a symbolic link", result.stdout)

    def test_valid_suite_has_no_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            self.assertEqual([], validate_suite(root))

    def test_missing_or_symlinked_metadata_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            errors = validate_suite(Path(directory))
            self.assertIn("missing .codex-plugin/plugin.json", errors)

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "suite"
            make_valid_suite(root)
            manifest = root / ".codex-plugin" / "plugin.json"
            external_manifest = base / "external-plugin.json"
            manifest.replace(external_manifest)
            try:
                manifest.symlink_to(external_manifest)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symlinks unavailable: {error}")

            self.assertIn(
                ".codex-plugin/plugin.json must not use symbolic links",
                validate_suite(root),
            )

            manifest.unlink()
            external_manifest.replace(manifest)
            skill = root / "skills" / "math-modeling-validation"
            external_skill = base / "external-validation-skill"
            skill.replace(external_skill)
            skill.symlink_to(external_skill, target_is_directory=True)
            self.assertTrue(
                any(
                    "skills/math-modeling-validation/SKILL.md must not use symbolic links"
                    in error
                    for error in validate_suite(root)
                )
            )

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

    def test_missing_new_required_skill_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            preflight_dir = root / "skills" / "math-modeling-preflight"
            for path in sorted(preflight_dir.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                else:
                    path.rmdir()
            preflight_dir.rmdir()
            self.assertTrue(
                any(
                    "math-modeling-preflight" in error
                    for error in validate_suite(root)
                )
            )

    def test_support_skill_uses_read_only_catalog_boundary_not_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            method_library = (
                root / "skills" / "math-modeling-method-library" / "SKILL.md"
            )
            errors = validate_suite(root)
            self.assertFalse(
                any(
                    "math-modeling-method-library/SKILL.md must reference shared handoff"
                    in error
                    for error in errors
                )
            )
            method_library.write_text(
                method_library.read_text(encoding="utf-8").replace(
                    "Read-only catalog/reference support. Do not write project state.",
                    "Reusable modeling methods.",
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any(
                    "read-only catalog/reference" in error
                    for error in validate_suite(root)
                )
            )

    def test_invalid_validation_fail_route_is_reported_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            workflow_path = root / "skills" / "math-modeling-orchestrator" / "references" / "workflow.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            workflow["transitions"]["validation-fail"].append("paper-writing")
            write_json(workflow_path, workflow)
            self.assertIn(
                "workflow validation-fail must route only to upstream modeling stages",
                validate_suite(root),
            )

    def test_manifest_rejects_unknown_nested_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            manifest_path = root / ".codex-plugin" / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["author"]["typo"] = "value"
            manifest["interface"]["typo"] = "value"
            write_json(manifest_path, manifest)
            errors = validate_suite(root)
            self.assertIn("manifest author contains unsupported keys: typo", errors)
            self.assertIn("manifest interface contains unsupported keys: typo", errors)

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

    def test_manifest_optional_id_must_be_nonempty_string(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            manifest_path = root / ".codex-plugin" / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["id"] = []
            write_json(manifest_path, manifest)
            self.assertIn(
                "manifest id must be a non-empty string when present",
                validate_suite(root),
            )

    def test_manifest_optional_metadata_has_supported_types(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            manifest_path = root / ".codex-plugin" / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["homepage"] = []
            manifest["keywords"] = ["math", 1]
            manifest["author"]["email"] = []
            manifest["interface"]["screenshots"] = [1]
            write_json(manifest_path, manifest)
            errors = validate_suite(root)
            self.assertIn("manifest homepage must be a non-empty string when present", errors)
            self.assertIn("manifest keywords must be a non-empty string array when present", errors)
            self.assertIn("manifest author.email must be a non-empty string when present", errors)
            self.assertIn("manifest interface.screenshots must be a string array when present", errors)

    def test_manifest_rejects_invalid_optional_urls_color_and_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            manifest_path = root / ".codex-plugin" / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["author"]["url"] = "http://example.invalid"
            manifest["interface"].update(
                {
                    "websiteURL": "javascript:alert(1)",
                    "brandColor": "red",
                    "composerIcon": "../../outside.png",
                    "screenshots": ["assets/missing.png"],
                }
            )
            write_json(manifest_path, manifest)
            errors = validate_suite(root)
            self.assertIn("manifest author.url must be an absolute https URL", errors)
            self.assertIn(
                "manifest interface.websiteURL must be an absolute https URL",
                errors,
            )
            self.assertIn("manifest interface.brandColor must use #RRGGBB", errors)
            self.assertIn(
                "manifest interface.composerIcon must stay inside the plugin root",
                errors,
            )
            self.assertIn(
                "manifest interface.screenshots[0] points to a missing file",
                errors,
            )

    def test_guards_must_not_contain_extra_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            workflow_path = root / "skills" / "math-modeling-orchestrator" / "references" / "workflow.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            workflow["guards"]["unexpected"] = {"allowed": True}
            write_json(workflow_path, workflow)
            self.assertTrue(any("guards" in error for error in validate_suite(root)))

            workflow["unexpected"] = True
            workflow["stages"][0]["unexpected"] = "value"
            workflow["handoff"]["unexpected"] = []
            write_json(workflow_path, workflow)
            errors = validate_suite(root)
            self.assertIn("workflow contains unsupported keys: unexpected", errors)
            self.assertIn(
                "workflow stage entries must contain only id, skill, optional",
                errors,
            )
            self.assertIn(
                "workflow handoff contains unsupported keys: unexpected", errors
            )

    def test_each_guard_rejects_unknown_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            workflow_path = root / "skills" / "math-modeling-orchestrator" / "references" / "workflow.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            for guard_name in workflow["guards"]:
                with self.subTest(guard=guard_name):
                    mutated = json.loads(json.dumps(workflow))
                    mutated["guards"][guard_name]["unexpected"] = True
                    write_json(workflow_path, mutated)
                    self.assertIn(
                        f"workflow guard {guard_name} contains unsupported keys: unexpected",
                        validate_suite(root),
                    )

    def test_skill_description_must_be_trigger_oriented(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            skill_path = root / "skills" / "math-modeling-validation" / "SKILL.md"
            skill_path.write_text(
                skill_path.read_text(encoding="utf-8").replace(
                    "description: Use when math-modeling-validation is needed for its bounded stage.",
                    "description: Validation helper.",
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("description must start with 'Use when'" in error for error in validate_suite(root))
            )

    def test_skill_frontmatter_rejects_unsupported_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            skill_path = root / "skills" / "math-modeling-validation" / "SKILL.md"
            skill_path.write_text(
                skill_path.read_text(encoding="utf-8").replace(
                    "name: math-modeling-validation\n",
                    "name: math-modeling-validation\nunexpected: value\n",
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("unsupported frontmatter keys: unexpected" in error for error in validate_suite(root))
            )

    def test_skill_description_rejects_angle_brackets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            skill_path = root / "skills" / "math-modeling-validation" / "SKILL.md"
            skill_path.write_text(
                skill_path.read_text(encoding="utf-8").replace(
                    "Use when math-modeling-validation is needed for its bounded stage.",
                    "Use when <validation> is needed for its bounded stage.",
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("description must not contain angle brackets" in error for error in validate_suite(root))
            )

    def test_frontmatter_rejects_ambiguous_unquoted_yaml_scalar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            skill_path = root / "skills" / "math-modeling-validation" / "SKILL.md"
            skill_path.write_text(
                skill_path.read_text(encoding="utf-8").replace(
                    "Use when math-modeling-validation is needed for its bounded stage.",
                    "Use when validation has a key: value ambiguity.",
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("invalid frontmatter" in error for error in validate_suite(root))
            )

    def test_frontmatter_requires_exact_delimiters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            skill_path = root / "skills" / "math-modeling-validation" / "SKILL.md"
            content = skill_path.read_text(encoding="utf-8")
            skill_path.write_text(" " + content, encoding="utf-8")
            self.assertTrue(
                any("invalid frontmatter" in error for error in validate_suite(root))
            )

    def test_frontmatter_rejects_malformed_single_quoted_scalar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            skill_path = root / "skills" / "math-modeling-validation" / "SKILL.md"
            skill_path.write_text(
                skill_path.read_text(encoding="utf-8").replace(
                    "description: Use when math-modeling-validation is needed for its bounded stage.",
                    "description: 'Use when validation' trailing '",
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("invalid frontmatter" in error for error in validate_suite(root))
            )

    def test_workflow_stage_id_must_match_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            workflow_path = root / "skills" / "math-modeling-orchestrator" / "references" / "workflow.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            workflow["stages"][0]["id"] = "wrong-id"
            write_json(workflow_path, workflow)
            self.assertTrue(
                any("workflow stage id" in error for error in validate_suite(root))
            )

    def test_workflow_stage_optionality_must_be_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            workflow_path = root / "skills" / "math-modeling-orchestrator" / "references" / "workflow.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            workflow["stages"][1]["optional"] = True
            workflow["stages"][2]["optional"] = False
            write_json(workflow_path, workflow)
            errors = validate_suite(root)
            self.assertIn(
                "workflow stage math-modeling-problem-analysis optional must be false",
                errors,
            )
            self.assertIn(
                "workflow stage math-modeling-data-analysis optional must be true",
                errors,
            )

    def test_workflow_handoff_revision_state_must_be_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            workflow_path = root / "skills" / "math-modeling-orchestrator" / "references" / "workflow.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            workflow["handoff"]["validation_statuses"].remove("stale")
            workflow["handoff"]["state_fields"].remove("invalidated_stages")
            write_json(workflow_path, workflow)
            errors = validate_suite(root)
            self.assertIn(
                "workflow handoff.state_fields must match required state fields",
                errors,
            )
            self.assertIn(
                "workflow handoff.validation_statuses must match required validation statuses",
                errors,
            )

    def test_frontmatter_rejects_unstructured_yaml_line(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            skill_path = root / "skills" / "math-modeling-validation" / "SKILL.md"
            skill_path.write_text(
                skill_path.read_text(encoding="utf-8").replace(
                    "description: Use when math-modeling-validation is needed for its bounded stage.",
                    "not valid yaml\ndescription: Validation helper.",
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("invalid frontmatter" in error for error in validate_suite(root))
            )

    def test_agent_yaml_rejects_unstructured_yaml_line(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            agent_path = root / "skills" / "math-modeling-validation" / "agents" / "openai.yaml"
            agent_path.write_text(
                agent_path.read_text(encoding="utf-8") + "broken: [\n",
                encoding="utf-8",
            )
            self.assertTrue(
                any("invalid YAML" in error for error in validate_suite(root))
            )

    def test_handoff_contract_requires_canonical_nested_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_valid_suite(root)
            contract_path = root / "skills" / "math-modeling-orchestrator" / "references" / "handoff-contract.md"
            contract = contract_path.read_text(encoding="utf-8")
            contract = contract.replace('  statement: "required"\n', "")
            contract_path.write_text(contract, encoding="utf-8")
            self.assertTrue(
                any("handoff contract must show task.statement" in error for error in validate_suite(root))
            )


if __name__ == "__main__":
    unittest.main()
