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
    """Derive AHP geometric-mean weights and apply them to normalized scores."""
    pairwise = [[float(value) for value in row] for row in data["pairwise"]]
    scores = [[float(value) for value in row] for row in data["scores"]]
    criteria = len(pairwise)
    if not 1 <= criteria <= 10 or any(len(row) != criteria for row in pairwise):
        raise ValueError("pairwise matrix must be square with 1..10 criteria")
    if not scores or any(len(row) != criteria for row in scores):
        raise ValueError("each score row must match the pairwise matrix")
    for row in range(criteria):
        for column in range(criteria):
            if pairwise[row][column] <= 0 or abs(pairwise[row][column] * pairwise[column][row] - 1.0) > 1e-6:
                raise ValueError("AHP pairwise matrix must be positive reciprocal")
    geometric = [math.prod(row) ** (1.0 / criteria) for row in pairwise]
    total = sum(geometric)
    weights = [value / total for value in geometric]
    weighted = [sum(value * weight for value, weight in zip(row, weights)) for row in scores]
    products = [sum(value * weight for value, weight in zip(row, weights)) for row in pairwise]
    lambda_max = sum(value / weight for value, weight in zip(products, weights)) / criteria
    consistency_index = (lambda_max - criteria) / (criteria - 1) if criteria > 1 else 0.0
    random_index = [0.0, 0.0, 0.0, 0.58, 0.90, 1.12, 1.24, 1.32, 1.41, 1.45, 1.49][criteria]
    consistency_ratio = consistency_index / random_index if random_index > 0 else 0.0
    return {
        "values": weighted,
        "metrics": {"weights": weights, "lambda_max": lambda_max, "consistency_ratio": consistency_ratio},
        "assumptions": ["positive reciprocal judgments", "normalized commensurable scores", "consistency ratio interpreted for the maintained RI table"],
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
