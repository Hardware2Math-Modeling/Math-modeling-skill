import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from result_contract import validate_result_payload  # noqa: E402


def valid_result() -> dict[str, object]:
    return {
        "question_id": "Q1",
        "model_id": "logistic-growth-v1",
        "assumptions": ["The carrying capacity is constant over the run."],
        "baseline": {
            "model_id": "constant-mean-v1",
            "metric": "score",
            "value": 0.60,
            "unit": "dimensionless",
        },
        "parameters": {"growth_rate": {"value": 0.2, "unit": "1/day"}},
        "metrics": {
            "score": {
                "value": 0.75,
                "unit": "dimensionless",
                "source_path": "results/q1.json",
                "source_hash": "a" * 64,
                "finite": True,
            }
        },
        "units": {"time": "day", "population": "individuals"},
        "run_manifest": {
            "run_id": "run-q1-001",
            "status": "current",
            "seed": 1729,
        },
        "validation_plan": {
            "validation_cycle_id": "validation-q1-001",
            "threshold": 0.70,
            "split": "holdout",
            "scope": "Q1 test observations",
            "seed": 1729,
            "method": "blocked holdout",
        },
        "validation_history": [],
        "validation_manifest": {
            "validation_cycle_id": "validation-q1-001",
            "status": "current",
        },
        "figure_manifests": [
            {"figure_id": "q1-main", "status": "verified"},
        ],
        "claims": [
            {
                "claim_id": "claim-q1-01",
                "statement": "The accepted model exceeds the baseline score.",
                "metric": "score",
                "source_path": "results/q1.json",
                "source_hash": "a" * 64,
            }
        ],
        "freeze_status": "draft",
    }


class ResultContractTests(unittest.TestCase):
    def test_valid_result_is_accepted(self) -> None:
        self.assertEqual([], validate_result_payload(valid_result()))

    def test_result_requires_question_model_baseline_metrics_and_seed(self) -> None:
        errors = validate_result_payload({"question_id": "Q1"})
        for field in ("model_id", "baseline", "metrics", "run_manifest", "validation_plan"):
            with self.subTest(field=field):
                self.assertTrue(any(field in error for error in errors))

    def test_each_top_level_contract_field_is_required(self) -> None:
        required = (
            "question_id",
            "model_id",
            "assumptions",
            "baseline",
            "parameters",
            "metrics",
            "units",
            "run_manifest",
            "validation_plan",
            "claims",
            "freeze_status",
        )
        for field in required:
            with self.subTest(field=field):
                payload = valid_result()
                del payload[field]
                errors = validate_result_payload(payload)
                self.assertTrue(any(field in error for error in errors))

    def test_metric_requires_value_unit_source_hash_and_finite_status(self) -> None:
        required = ("value", "unit", "source_path", "source_hash", "finite")
        for field in required:
            with self.subTest(field=field):
                payload = valid_result()
                del payload["metrics"]["score"][field]
                errors = validate_result_payload(payload)
                self.assertTrue(any(f"metrics.score.{field}" in error for error in errors))

    def test_metric_rejects_nonfinite_values_and_false_finite_status(self) -> None:
        mutations = (
            (float("nan"), True),
            (float("inf"), True),
            ("NaN", True),
            (0.75, False),
        )
        for value, finite in mutations:
            with self.subTest(value=value, finite=finite):
                payload = valid_result()
                payload["metrics"]["score"]["value"] = value
                payload["metrics"]["score"]["finite"] = finite
                errors = validate_result_payload(payload)
                self.assertTrue(any("finite" in error for error in errors))

    def test_metric_rejects_unsafe_source_path_and_invalid_hash(self) -> None:
        mutations = (("../q1.json", "a" * 64), ("results/q1.json", "not-a-hash"))
        for source_path, source_hash in mutations:
            with self.subTest(source_path=source_path, source_hash=source_hash):
                payload = valid_result()
                payload["metrics"]["score"]["source_path"] = source_path
                payload["metrics"]["score"]["source_hash"] = source_hash
                errors = validate_result_payload(payload)
                self.assertTrue(any("metrics.score.source" in error for error in errors))

    def test_metric_errors_are_independent_of_mapping_insertion_order(self) -> None:
        expected = [
            "metrics.alpha must be an object with a finite numeric value",
            "metrics.zeta must be an object with a finite numeric value",
        ]
        for metrics in (
            {"zeta": "NaN", "alpha": "NaN"},
            {"alpha": "NaN", "zeta": "NaN"},
        ):
            with self.subTest(metrics=metrics):
                payload = valid_result()
                payload["metrics"] = metrics
                errors = validate_result_payload(payload)
                self.assertEqual(expected, [error for error in errors if error.startswith("metrics.")])

    def test_validation_plan_requires_threshold_split_scope_seed_and_method(self) -> None:
        for field in ("threshold", "split", "scope", "seed", "method"):
            with self.subTest(field=field):
                payload = valid_result()
                del payload["validation_plan"][field]
                errors = validate_result_payload(payload)
                self.assertTrue(any(f"validation_plan.{field}" in error for error in errors))

    def test_validation_threshold_change_is_recorded_as_new_cycle(self) -> None:
        payload = valid_result()
        payload["validation_plan"]["threshold"] = 0.99
        payload["validation_history"] = [{"threshold": 0.90, "status": "fail"}]
        errors = validate_result_payload(payload)
        self.assertTrue(any("threshold" in error for error in errors))

    def test_new_threshold_cycle_preserves_previous_outcome(self) -> None:
        payload = valid_result()
        payload["validation_plan"]["validation_cycle_id"] = "validation-q1-002"
        payload["validation_plan"]["threshold"] = 0.80
        payload["validation_history"] = [
            {
                "validation_cycle_id": "validation-q1-001",
                "threshold": 0.70,
                "status": "fail",
            }
        ]
        self.assertEqual([], validate_result_payload(payload))

    def test_changed_threshold_requires_previous_cycle_id_and_outcome(self) -> None:
        for missing_field in ("validation_cycle_id", "status"):
            with self.subTest(missing_field=missing_field):
                payload = valid_result()
                payload["validation_plan"]["validation_cycle_id"] = "validation-q1-002"
                payload["validation_plan"]["threshold"] = 0.80
                prior = {
                    "validation_cycle_id": "validation-q1-001",
                    "threshold": 0.70,
                    "status": "fail",
                }
                del prior[missing_field]
                payload["validation_history"] = [prior]
                errors = validate_result_payload(payload)
                self.assertTrue(any(missing_field in error for error in errors))

    def test_nan_or_unverified_number_cannot_be_frozen(self) -> None:
        payload = valid_result()
        payload["metrics"]["score"] = "NaN"
        payload["freeze_status"] = "confirmed"
        errors = validate_result_payload(payload)
        self.assertTrue(any("finite" in error or "freeze" in error for error in errors))

    def test_confirmed_result_requires_current_run_validation_and_figures(self) -> None:
        mutations = (
            ("run_manifest", "stale"),
            ("validation_manifest", "stale"),
            ("figure_manifests", "stale"),
        )
        for field, status in mutations:
            with self.subTest(field=field):
                payload = valid_result()
                payload["freeze_status"] = "confirmed"
                if field == "figure_manifests":
                    payload[field][0]["status"] = status
                else:
                    payload[field]["status"] = status
                errors = validate_result_payload(payload)
                self.assertTrue(any("freeze" in error and field in error for error in errors))

    def test_confirmed_result_accepts_current_evidence(self) -> None:
        payload = valid_result()
        payload["freeze_status"] = "confirmed"
        self.assertEqual([], validate_result_payload(payload))


if __name__ == "__main__":
    unittest.main()
