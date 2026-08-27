from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Enumerate pure-strategy Nash equilibria in a two-player normal-form game."""
    row_payoffs = [[float(value) for value in row] for row in data["row_payoffs"]]
    column_payoffs = [[float(value) for value in row] for row in data["column_payoffs"]]
    if not row_payoffs or not row_payoffs[0] or len(row_payoffs) != len(column_payoffs):
        raise ValueError("payoff matrices must have equal nonzero shape")
    columns = len(row_payoffs[0])
    if any(len(row) != columns for row in row_payoffs + column_payoffs):
        raise ValueError("payoff matrices must be rectangular and equal-shaped")
    equilibria: list[list[int]] = []
    for row in range(len(row_payoffs)):
        for column in range(columns):
            row_best = max(row_payoffs[candidate][column] for candidate in range(len(row_payoffs)))
            column_best = max(column_payoffs[row][candidate] for candidate in range(columns))
            if row_payoffs[row][column] >= row_best - 1e-12 and column_payoffs[row][column] >= column_best - 1e-12:
                equilibria.append([row, column])
    return {
        "values": equilibria,
        "metrics": {"pure_equilibria": len(equilibria), "row_strategies": len(row_payoffs), "column_strategies": columns},
        "assumptions": ["two-player simultaneous complete-information game", "pure strategies only", "unilateral payoff maximization"],
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
