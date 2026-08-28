from __future__ import annotations

import argparse
import bisect
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
    """Interpolate query points on a strictly increasing one-dimensional grid."""
    x_values = [float(value) for value in data["x"]]
    y_values = [float(value) for value in data["y"]]
    queries = [float(value) for value in data["queries"]]
    if len(x_values) < 2 or len(x_values) != len(y_values) or any(right <= left for left, right in zip(x_values, x_values[1:])):
        raise ValueError("interpolation x must be strictly increasing and match y")
    outputs: list[float] = []
    for query in queries:
        if query < x_values[0] or query > x_values[-1]:
            raise ValueError("linear interpolation refuses extrapolation")
        if query == x_values[-1]:
            outputs.append(y_values[-1])
            continue
        index = max(0, bisect.bisect_right(x_values, query) - 1)
        fraction = (query - x_values[index]) / (x_values[index + 1] - x_values[index])
        outputs.append(y_values[index] + fraction * (y_values[index + 1] - y_values[index]))
    return {
        "values": outputs,
        "metrics": {"queries": len(queries), "nodes": len(x_values), "max_node_gap": max(right - left for left, right in zip(x_values, x_values[1:]))},
        "assumptions": ["strictly increasing nodes", "piecewise linear behavior", "queries remain inside the observed domain"],
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
