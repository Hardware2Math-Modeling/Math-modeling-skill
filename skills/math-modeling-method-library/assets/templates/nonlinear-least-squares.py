from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def _two_by_two(a: float, b: float, c: float, d: float, first: float, second: float) -> tuple[float, float]:
    determinant = a * d - b * c
    if abs(determinant) < 1e-14:
        raise ValueError("nonlinear least-squares Jacobian is singular")
    return ((first * d - b * second) / determinant, (a * second - first * c) / determinant)


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Fit y = a*exp(b*x) with a deterministic Gauss-Newton iteration."""
    predictors = [float(value) for value in data["x"]]
    response = [float(value) for value in data["y"]]
    initial = [float(value) for value in data.get("initial", [1.0, 0.0])]
    iterations = int(data.get("iterations", 50))
    if len(predictors) < 2 or len(predictors) != len(response) or len(initial) != 2 or not 1 <= iterations <= 10000:
        raise ValueError("nonlinear fit x/y, initial, or iterations is invalid")
    a, b = initial
    used = 0
    for used in range(1, iterations + 1):
        exponentials = [math.exp(b * value) for value in predictors]
        predictions = [a * value for value in exponentials]
        residuals = [actual - predicted for actual, predicted in zip(response, predictions)]
        first_column = exponentials
        second_column = [a * x_value * exponential for x_value, exponential in zip(predictors, exponentials)]
        jt_j_00 = sum(value * value for value in first_column)
        jt_j_01 = sum(left * right for left, right in zip(first_column, second_column))
        jt_j_11 = sum(value * value for value in second_column)
        jt_r_0 = sum(value * residual for value, residual in zip(first_column, residuals))
        jt_r_1 = sum(value * residual for value, residual in zip(second_column, residuals))
        delta_a, delta_b = _two_by_two(jt_j_00, jt_j_01, jt_j_01, jt_j_11, jt_r_0, jt_r_1)
        a += delta_a
        b += delta_b
        if max(abs(delta_a), abs(delta_b)) < 1e-12:
            break
        if not math.isfinite(a) or not math.isfinite(b):
            raise ValueError("nonlinear least-squares parameters diverged")
    predictions = [a * math.exp(b * value) for value in predictors]
    sse = sum((actual - predicted) ** 2 for actual, predicted in zip(response, predictions))
    return {
        "values": [a, b],
        "metrics": {"sse": sse, "iterations": used},
        "assumptions": ["two-parameter exponential response", "independent equal-variance errors on the response scale", "initial parameters identify the local basin"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = solve(data, {"seed": args.seed})
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
