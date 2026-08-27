from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _solve_system(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    size = len(rhs)
    augmented = [row[:] + [value] for row, value in zip(matrix, rhs)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("ridge normal equations are singular; use positive alpha or revise features")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row != column:
                factor = augmented[row][column]
                augmented[row] = [value - factor * pivot_value for value, pivot_value in zip(augmented[row], augmented[column])]
    return [augmented[row][-1] for row in range(size)]


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Fit OLS (alpha zero) or ridge regression through normal equations."""
    features = [[float(value) for value in row] for row in data["X"]]
    response = [float(value) for value in data["y"]]
    alpha = float(data.get("alpha", 0.0))
    if not features or len(features) != len(response) or alpha < 0:
        raise ValueError("X/y dimensions or alpha are invalid")
    columns = len(features[0])
    if columns == 0 or columns > 50 or any(len(row) != columns for row in features):
        raise ValueError("X must be rectangular with 1..50 columns")
    gram = [[sum(row[i] * row[j] for row in features) + (alpha if i == j else 0.0) for j in range(columns)] for i in range(columns)]
    rhs = [sum(row[column] * value for row, value in zip(features, response)) for column in range(columns)]
    coefficients = _solve_system(gram, rhs)
    predictions = [sum(value * coefficient for value, coefficient in zip(row, coefficients)) for row in features]
    residuals = [actual - predicted for actual, predicted in zip(response, predictions)]
    mse = sum(value * value for value in residuals) / len(residuals)
    return {
        "values": coefficients,
        "metrics": {"mse": mse, "rows": len(features), "features": columns, "alpha": alpha},
        "assumptions": ["linear conditional mean", "independent rows", "fixed feature units"],
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
