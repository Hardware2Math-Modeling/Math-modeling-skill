from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path
from typing import Any


def _linear_system(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    size = len(rhs)
    augmented = [row[:] + [value] for row, value in zip(matrix, rhs)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[column])
            ]
    return [augmented[row][-1] for row in range(size)]


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Solve a small bounded nonnegative LP by enumerating feasible vertices."""
    c = [float(value) for value in data["c"]]
    matrix = [[float(value) for value in row] for row in data["A"]]
    bounds = [float(value) for value in data["b"]]
    variables = len(c)
    if not 1 <= variables <= 6 or len(matrix) != len(bounds):
        raise ValueError("LP template requires 1..6 variables and one bound per row")
    if any(len(row) != variables for row in matrix):
        raise ValueError("each A row must match c")
    if any(c[index] > 0 and not any(row[index] > 0 for row in matrix) for index in range(variables)):
        raise ValueError("LP appears unbounded along a positive objective axis")
    active_rows = matrix + [
        [1.0 if index == column else 0.0 for index in range(variables)]
        for column in range(variables)
    ]
    active_rhs = bounds + [0.0] * variables
    best: list[float] | None = None
    best_objective = float("-inf")
    feasible_count = 0
    for selected in combinations(range(len(active_rows)), variables):
        candidate = _linear_system(
            [active_rows[index] for index in selected],
            [active_rhs[index] for index in selected],
        )
        if candidate is None:
            continue
        if any(value < -1e-9 for value in candidate):
            continue
        if any(sum(a * x for a, x in zip(row, candidate)) > bound + 1e-9 for row, bound in zip(matrix, bounds)):
            continue
        feasible_count += 1
        objective = sum(coefficient * value for coefficient, value in zip(c, candidate))
        if objective > best_objective + 1e-12:
            best, best_objective = candidate, objective
    if best is None:
        raise ValueError("LP has no feasible enumerated vertex")
    return {
        "values": [0.0 if abs(value) < 1e-12 else value for value in best],
        "metrics": {"objective": best_objective, "feasible_vertices": feasible_count},
        "assumptions": ["continuous nonnegative variables", "bounded linear feasible region"],
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
