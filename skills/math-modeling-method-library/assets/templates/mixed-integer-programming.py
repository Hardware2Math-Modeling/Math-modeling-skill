from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Solve a small all-binary linear integer program by complete enumeration."""
    c = [float(value) for value in data["c"]]
    matrix = [[float(value) for value in row] for row in data["A"]]
    bounds = [float(value) for value in data["b"]]
    variables = len(c)
    if not 1 <= variables <= 22 or len(matrix) != len(bounds):
        raise ValueError("binary template requires 1..22 variables and one bound per row")
    if any(len(row) != variables for row in matrix):
        raise ValueError("each A row must match c")
    best: list[float] | None = None
    best_objective = float("-inf")
    feasible_count = 0
    for mask in range(1 << variables):
        candidate = [float((mask >> index) & 1) for index in range(variables)]
        if any(sum(a * x for a, x in zip(row, candidate)) > bound + 1e-12 for row, bound in zip(matrix, bounds)):
            continue
        feasible_count += 1
        objective = sum(coefficient * value for coefficient, value in zip(c, candidate))
        if objective > best_objective + 1e-12:
            best, best_objective = candidate, objective
    if best is None:
        raise ValueError("binary program has no feasible assignment")
    return {
        "values": best,
        "metrics": {
            "objective": best_objective,
            "enumerated": 1 << variables,
            "feasible_assignments": feasible_count,
        },
        "assumptions": ["all decision variables are binary", "complete enumeration is tractable"],
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
