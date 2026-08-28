from __future__ import annotations

import copy
import importlib.util
import json
import math
import shutil
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
LIBRARY = ROOT / "skills" / "math-modeling-method-library"
TEMPLATES = LIBRARY / "assets" / "templates"
METHODS = LIBRARY / "references" / "methods"
sys.path.insert(0, str(SCRIPTS))

from method_catalog import (  # noqa: E402
    EXPECTED_FAMILIES,
    REQUIRED_FIELDS,
    load_catalog,
    run_smoke,
    validate_catalog,
)
from python_runner import RunFailed  # noqa: E402


EXPECTED_METHODS = {
    "优化与决策": {
        "linear-programming",
        "mixed-integer-programming",
        "nonlinear-constrained-optimization",
    },
    "预测、回归与时间序列": {
        "ols-ridge-regression",
        "exponential-smoothing",
        "arima-forecasting",
    },
    "综合评价与多指标决策": {
        "entropy-topsis",
        "ahp-weighted-score",
        "dea-efficiency",
    },
    "统计分析与数据处理": {
        "bootstrap-confidence",
        "hypothesis-test",
        "robust-outlier-detection",
    },
    "机器学习、分类、聚类与降维": {
        "random-forest-classification",
        "kmeans-clustering",
        "pca-reduction",
    },
    "图论与网络": {
        "shortest-path",
        "max-flow-min-cut",
        "pagerank-centrality",
    },
    "机理模型与数值分析": {
        "ode-integration",
        "nonlinear-least-squares",
        "finite-difference-heat",
    },
    "随机模拟与不确定性": {
        "monte-carlo-propagation",
        "latin-hypercube-sampling",
        "markov-chain-simulation",
    },
    "博弈与多主体决策": {
        "normal-form-nash",
        "evolutionary-replicator",
        "best-response-dynamics",
    },
    "几何、空间与信号": {
        "linear-interpolation",
        "convex-hull-geometry",
        "fft-denoising",
    },
}
ALLOWED_FIGURE_ROLES = {"evidence", "validation", "diagnostic", "conceptual"}


def _strict_json(path: Path) -> object:
    def reject_constant(value: str) -> object:
        raise ValueError(f"non-finite JSON constant: {value}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)


def _assert_finite_tree(test: unittest.TestCase, value: object) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _assert_finite_tree(test, item)
    elif isinstance(value, list):
        for item in value:
            _assert_finite_tree(test, item)
    elif isinstance(value, float):
        test.assertTrue(math.isfinite(value), value)


def _load_template(method_id: str, template: str | None = None) -> object:
    path = TEMPLATES / (template or f"{method_id}.py")
    spec = importlib.util.spec_from_file_location(method_id.replace("-", "_"), path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"unable to load template: {method_id}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MethodLibraryTests(unittest.TestCase):
    def test_catalog_contains_the_approved_thirty_methods_three_per_family(self) -> None:
        catalog = load_catalog()
        self.assertEqual(30, len(catalog))
        counts = Counter(item["family"] for item in catalog)
        self.assertEqual(set(EXPECTED_FAMILIES), set(counts))
        self.assertTrue(all(counts[family] == 3 for family in EXPECTED_FAMILIES))
        actual = {
            family: {item["id"] for item in catalog if item["family"] == family}
            for family in EXPECTED_FAMILIES
        }
        self.assertEqual(EXPECTED_METHODS, actual)

    def test_entries_have_complete_method_metadata_and_original_source_boundaries(self) -> None:
        for item in load_catalog():
            with self.subTest(method=item["id"]):
                self.assertEqual(set(REQUIRED_FIELDS), set(item))
                self.assertTrue(
                    all(item[field] for field in REQUIRED_FIELDS if field != "dependencies")
                )
                self.assertIsInstance(item["dependencies"], list)
                self.assertTrue(all(entry.get("units") for entry in item["inputs"]))
                self.assertTrue(all(entry.get("meaning") for entry in item["inputs"]))
                self.assertTrue(item["trigger_conditions"])
                self.assertTrue(item["assumptions"])
                self.assertTrue(item["failure_signals"])
                self.assertTrue(item["validation"])
                roles = {figure["role"] for figure in item["figure_roles"]}
                self.assertTrue(roles <= ALLOWED_FIGURE_ROLES)
                self.assertTrue(roles)
                self.assertTrue(
                    all(type(figure.get("claim_supporting")) is bool for figure in item["figure_roles"])
                )
                notes = item["license_notes"]
                self.assertRegex(notes["source_url"], r"^https://github\.com/")
                self.assertNotEqual("unknown", notes["source_license"].casefold())
                self.assertEqual("MIT", notes["template_license"])
                self.assertIn("original", notes["copy_policy"].casefold())

    def test_every_entry_has_one_safe_reference_and_executable_template(self) -> None:
        catalog = load_catalog()
        self.assertEqual([], validate_catalog())
        self.assertEqual(30, len(list(TEMPLATES.glob("*.py"))))
        self.assertEqual(30, len(list(METHODS.glob("*.md"))))
        for item in catalog:
            template = TEMPLATES / item["template"]
            reference = METHODS / f"{item['id']}.md"
            with self.subTest(method=item["id"]):
                self.assertEqual(f"{item['id']}.py", item["template"])
                self.assertTrue(template.is_file())
                source = template.read_text(encoding="utf-8")
                self.assertIn("def solve(", source)
                self.assertIn("--input", source)
                self.assertIn("--output", source)
                self.assertIn("--seed", source)
                self.assertNotIn("T" + "ODO", source)
                self.assertTrue(reference.is_file())
                self.assertIn(item["name_zh"], reference.read_text(encoding="utf-8"))

    def test_validator_rejects_catalog_and_template_contract_mutations(self) -> None:
        cases = (
            ("duplicate id", lambda catalog, root: catalog.__setitem__(1, copy.deepcopy(catalog[0]))),
            ("unknown family", lambda catalog, root: catalog[0].__setitem__("family", "未知方法族")),
            ("missing fields: formula", lambda catalog, root: catalog[0].pop("formula")),
            ("unsafe template path", lambda catalog, root: catalog[0].__setitem__("template", "../escape.py")),
            (
                "undeclared dependency: numpy",
                lambda catalog, root: (root / "skills/math-modeling-method-library/assets/templates" / catalog[0]["template"]).write_text(
                    "import numpy\n" + (root / "skills/math-modeling-method-library/assets/templates" / catalog[0]["template"]).read_text(encoding="utf-8"),
                    encoding="utf-8",
                ),
            ),
        )
        for expected, mutate in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "suite"
                shutil.copytree(LIBRARY, root / "skills" / LIBRARY.name)
                catalog_path = root / "skills/math-modeling-method-library/references/catalog.json"
                catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
                mutate(catalog, root)
                catalog_path.write_text(
                    json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                errors = validate_catalog(root)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_all_templates_smoke_through_the_explicit_interpreter_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            python = Path(sys.executable).resolve()
            first = run_smoke(
                ROOT,
                python_executable=python,
                work_dir=Path(first_dir),
                seed=17,
            )
            second = run_smoke(
                ROOT,
                python_executable=python,
                work_dir=Path(second_dir),
                seed=17,
            )

        self.assertEqual(30, len(first))
        self.assertEqual(
            [entry["method_id"] for entry in first],
            [entry["method_id"] for entry in second],
        )
        self.assertEqual(
            [entry["result"] for entry in first],
            [entry["result"] for entry in second],
        )
        for entry in first:
            with self.subTest(method=entry["method_id"]):
                self.assertEqual(str(python), entry["run"]["python_executable"])
                self.assertIs(entry["run"]["shell"], False)
                self.assertEqual({"values", "metrics", "assumptions"}, set(entry["result"]))
                self.assertIsInstance(entry["result"]["values"], list)
                self.assertIsInstance(entry["result"]["metrics"], dict)
                self.assertIsInstance(entry["result"]["assumptions"], list)
                _assert_finite_tree(self, entry["result"])

    def test_smoke_fixture_has_one_labeled_case_for_every_method(self) -> None:
        payload = _strict_json(LIBRARY / "assets/fixtures/method-smoke.json")
        self.assertEqual("1", payload["schema_version"])
        fixtures = payload["fixtures"]
        self.assertEqual(30, len(fixtures))
        self.assertEqual(
            {item["id"] for item in load_catalog()},
            {fixture["method_id"] for fixture in fixtures},
        )
        self.assertTrue(all(fixture["label"] == "test data" for fixture in fixtures))
        self.assertTrue(all(isinstance(fixture["data"], dict) for fixture in fixtures))

    def test_nonzero_template_exit_is_not_hidden_or_substituted(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as work:
            root = Path(directory) / "suite"
            shutil.copytree(LIBRARY, root / "skills" / LIBRARY.name)
            catalog = load_catalog(root)
            target = root / "skills/math-modeling-method-library/assets/templates" / catalog[0]["template"]
            source = target.read_text(encoding="utf-8")
            target.write_text(source.replace("    main()", "    raise SystemExit(9)"), encoding="utf-8")

            with self.assertRaises(RunFailed) as raised:
                run_smoke(
                    root,
                    python_executable=Path(sys.executable).resolve(),
                    work_dir=Path(work),
                    method_ids=[catalog[0]["id"]],
                )

        self.assertEqual(9, raised.exception.result["exit_code"])

    def test_smoke_rejects_invalid_selection_before_materializing_inputs(self) -> None:
        cases = (
            ([1], "method_ids must contain catalog id strings"),
            (["not-a-maintained-id"], "unknown method id"),
            (["linear-programming", "linear-programming"], "must not contain duplicates"),
        )
        for method_ids, message in cases:
            with self.subTest(method_ids=method_ids), tempfile.TemporaryDirectory() as work:
                workspace = Path(work)
                with self.assertRaisesRegex(ValueError, message):
                    run_smoke(
                        ROOT,
                        python_executable=Path(sys.executable).resolve(),
                        work_dir=workspace,
                        method_ids=method_ids,
                    )
                self.assertEqual([], list(workspace.iterdir()))

    def test_smoke_rejects_relative_interpreter_before_materializing_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as work:
            workspace = Path(work)
            with self.assertRaisesRegex(ValueError, "Python executable must be an absolute path"):
                run_smoke(
                    ROOT,
                    python_executable=Path("python3"),
                    work_dir=workspace,
                    method_ids=["linear-programming"],
                )
            self.assertEqual([], list(workspace.iterdir()))

    def test_templates_expose_callable_solve_for_direct_use(self) -> None:
        fixture_payload = _strict_json(LIBRARY / "assets/fixtures/method-smoke.json")
        fixtures = {fixture["method_id"]: fixture for fixture in fixture_payload["fixtures"]}
        for item in load_catalog():
            with self.subTest(method=item["id"]):
                module = _load_template(item["id"], item["template"])
                result = module.solve(fixtures[item["id"]]["data"], {"seed": 17})
                self.assertEqual({"values", "metrics", "assumptions"}, set(result))
                _assert_finite_tree(self, result)
                json.dumps(result, ensure_ascii=False, allow_nan=False)

    def test_pca_accepts_nonzero_covariance_when_all_ones_is_a_null_direction(self) -> None:
        module = _load_template("pca-reduction")

        result = module.solve(
            {"matrix": [[-1, 1], [0, 0], [1, -1]], "iterations": 30},
            {"seed": 0},
        )

        self.assertAlmostEqual(1.0, result["metrics"]["explained_variance_ratio"])
        self.assertAlmostEqual(2 ** -0.5, result["metrics"]["loadings"][0])
        self.assertAlmostEqual(-(2 ** -0.5), result["metrics"]["loadings"][1])
        self.assertAlmostEqual(-(2 ** 0.5), result["values"][0])
        self.assertAlmostEqual(2 ** 0.5, result["values"][2])

    def test_every_direct_solve_rejects_nonfinite_input_even_when_unused(self) -> None:
        fixture_payload = _strict_json(LIBRARY / "assets/fixtures/method-smoke.json")
        fixtures = {fixture["method_id"]: fixture for fixture in fixture_payload["fixtures"]}
        for item in load_catalog():
            with self.subTest(method=item["id"]):
                data = copy.deepcopy(fixtures[item["id"]]["data"])
                data["nonfinite_probe"] = float("inf")
                module = _load_template(item["id"], item["template"])
                with self.assertRaisesRegex(ValueError, "finite JSON"):
                    module.solve(data, {"seed": 17})

    def test_direct_solve_rejects_a_nonfinite_derived_metric(self) -> None:
        module = _load_template("exponential-smoothing")

        with self.assertRaisesRegex(ValueError, "finite JSON"):
            module.solve(
                {"values": [1e308, -1e308], "alpha": 1.0, "horizon": 1},
                {"seed": 0},
            )

    def test_nonlinear_optimizer_catalogs_the_controls_its_template_consumes(self) -> None:
        item = next(
            entry for entry in load_catalog()
            if entry["id"] == "nonlinear-constrained-optimization"
        )
        inputs = {entry["name"]: entry for entry in item["inputs"]}
        self.assertTrue({"step_size", "iterations"} <= set(inputs))
        self.assertTrue(inputs["step_size"]["meaning"])
        self.assertTrue(inputs["step_size"]["units"])
        self.assertTrue(inputs["iterations"]["meaning"])
        self.assertTrue(inputs["iterations"]["units"])

        module = _load_template(item["id"], item["template"])
        base = {
            "linear": [4, 2],
            "quadratic": [1, 0.5],
            "bounds": [[0, 3], [0, 3]],
            "sum_limit": 3,
            "iterations": 1,
        }
        slow = module.solve({**base, "step_size": 0.01}, {"seed": 0})
        fast = module.solve({**base, "step_size": 0.2}, {"seed": 0})
        self.assertEqual(1, slow["metrics"]["iterations"])
        self.assertEqual(1, fast["metrics"]["iterations"])
        self.assertNotEqual(slow["values"], fast["values"])

    def test_replicator_rejects_a_materially_negative_euler_update(self) -> None:
        module = _load_template("evolutionary-replicator")

        with self.assertRaisesRegex(ValueError, "probability simplex"):
            module.solve(
                {
                    "payoff": [[-100, -100], [100, 100]],
                    "initial": [0.5, 0.5],
                    "dt": 0.1,
                    "steps": 1,
                },
                {"seed": 0},
            )

    def test_random_forest_scale_metadata_matches_depth_one_split_scanning(self) -> None:
        item = next(
            entry for entry in load_catalog()
            if entry["id"] == "random-forest-classification"
        )
        module = _load_template(item["id"], item["template"])
        result = module.solve(
            {"X": [[0], [1], [2], [3]], "y": [0, 0, 1, 1], "n_trees": 3},
            {"seed": 7},
        )

        self.assertEqual(1, result["metrics"]["tree_depth"])
        self.assertIn("O(T sqrt(p) n^2)", item["scale_limit"])
        self.assertIn("n<=500", item["scale_limit"])


if __name__ == "__main__":
    unittest.main()
