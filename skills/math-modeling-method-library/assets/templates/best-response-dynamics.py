from __future__ import annotations

import argparse
import json
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
    """Run alternating deterministic pure best responses for two players."""
    row_payoffs = [[float(value) for value in row] for row in data["row_payoffs"]]
    column_payoffs = [[float(value) for value in row] for row in data["column_payoffs"]]
    initial = [int(value) for value in data["initial"]]
    steps = int(data["steps"])
    if not row_payoffs or not row_payoffs[0] or len(row_payoffs) != len(column_payoffs) or len(initial) != 2:
        raise ValueError("best-response payoff matrices or initial strategy is invalid")
    columns = len(row_payoffs[0])
    if any(len(row) != columns for row in row_payoffs + column_payoffs):
        raise ValueError("best-response payoff matrices must have equal rectangular shape")
    row_strategy, column_strategy = initial
    if not 0 <= row_strategy < len(row_payoffs) or not 0 <= column_strategy < columns or not 1 <= steps <= 1000000:
        raise ValueError("best-response initial strategy or steps is invalid")
    path = [[row_strategy, column_strategy]]
    seen = {(row_strategy, column_strategy): 0}
    cycle_length = 0
    for step in range(1, steps + 1):
        row_strategy = min(range(len(row_payoffs)), key=lambda candidate: (-row_payoffs[candidate][column_strategy], candidate))
        column_strategy = min(range(columns), key=lambda candidate: (-column_payoffs[row_strategy][candidate], candidate))
        state = (row_strategy, column_strategy)
        path.append([row_strategy, column_strategy])
        if state in seen and cycle_length == 0:
            cycle_length = step - seen[state]
        seen.setdefault(state, step)
    return {
        "values": path,
        "metrics": {"final_strategy": path[-1], "cycle_length": cycle_length, "steps": steps},
        "assumptions": ["alternating row-then-column updates", "fixed complete-information payoffs", "smallest-index tie break"],
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
