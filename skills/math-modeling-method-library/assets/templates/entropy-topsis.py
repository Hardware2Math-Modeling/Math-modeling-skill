from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def _finite_json_io(function: Any) -> Any:
    def checked(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps({"data": data, "config": config}, allow_nan=False)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"solve input must be finite JSON: {error}") from error
        result = function(data, config)
        try:
            json.dumps(result, allow_nan=False)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"solve result must be finite JSON: {error}") from error
        return result

    return checked


@_finite_json_io
def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Rank feasible alternatives with entropy weights and TOPSIS closeness."""
    matrix = [[float(value) for value in row] for row in data["matrix"]]
    directions = list(data["directions"])
    if len(matrix) < 2 or not matrix or not matrix[0]:
        raise ValueError("TOPSIS needs at least two alternatives and one criterion")
    columns = len(matrix[0])
    if any(len(row) != columns for row in matrix) or len(directions) != columns:
        raise ValueError("matrix and directions dimensions do not match")
    if any(direction not in {"benefit", "cost"} for direction in directions):
        raise ValueError("directions must contain only benefit or cost")
    oriented = [[0.0] * columns for _ in matrix]
    for column in range(columns):
        values = [row[column] for row in matrix]
        low, high = min(values), max(values)
        for row_index, value in enumerate(values):
            directed = value if directions[column] == "benefit" else high + low - value
            oriented[row_index][column] = directed
    diversities: list[float] = []
    for column in range(columns):
        values = [row[column] for row in oriented]
        low = min(values)
        positive = [value - low for value in values]
        total = sum(positive)
        if total <= 1e-15:
            diversities.append(0.0)
            continue
        probabilities = [value / total for value in positive]
        entropy = -sum(p * math.log(p) for p in probabilities if p > 0) / math.log(len(matrix))
        diversities.append(max(0.0, 1.0 - entropy))
    diversity_total = sum(diversities)
    if diversity_total <= 1e-15:
        raise ValueError("all TOPSIS criteria are constant")
    weights = [value / diversity_total for value in diversities]
    normalized = [[0.0] * columns for _ in matrix]
    for column in range(columns):
        norm = math.sqrt(sum(row[column] ** 2 for row in oriented))
        if norm <= 1e-15:
            raise ValueError("a directed TOPSIS criterion has zero norm")
        for row_index in range(len(matrix)):
            normalized[row_index][column] = weights[column] * oriented[row_index][column] / norm
    ideal = [max(row[column] for row in normalized) for column in range(columns)]
    anti = [min(row[column] for row in normalized) for column in range(columns)]
    closeness: list[float] = []
    for row in normalized:
        positive_distance = math.sqrt(sum((value - target) ** 2 for value, target in zip(row, ideal)))
        negative_distance = math.sqrt(sum((value - target) ** 2 for value, target in zip(row, anti)))
        denominator = positive_distance + negative_distance
        closeness.append(negative_distance / denominator if denominator > 0 else 0.5)
    return {
        "values": closeness,
        "metrics": {"weights": weights, "alternatives": len(matrix), "criteria": columns},
        "assumptions": ["alternatives are already feasible", "criteria directions are declared", "entropy weights reflect dispersion only"],
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
