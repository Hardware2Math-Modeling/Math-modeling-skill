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
    """Advance a one-dimensional heat equation with an explicit finite difference."""
    state = [float(value) for value in data["initial"]]
    diffusivity = float(data["alpha"])
    dx = float(data["dx"])
    dt = float(data["dt"])
    steps = int(data["steps"])
    if len(state) < 3 or diffusivity < 0 or dx <= 0 or dt <= 0 or not 1 <= steps <= 1000000:
        raise ValueError("heat grid, alpha, dx, dt, or steps is invalid")
    ratio = diffusivity * dt / (dx * dx)
    if ratio > 0.5 + 1e-15:
        raise ValueError("explicit heat scheme is unstable because alpha*dt/dx^2 exceeds 0.5")
    left_boundary, right_boundary = state[0], state[-1]
    for _ in range(steps):
        updated = state[:]
        for index in range(1, len(state) - 1):
            updated[index] = state[index] + ratio * (state[index - 1] - 2.0 * state[index] + state[index + 1])
        updated[0], updated[-1] = left_boundary, right_boundary
        state = updated
    return {
        "values": state,
        "metrics": {"stability_ratio": ratio, "steps": steps, "grid_points": len(state)},
        "assumptions": ["one-dimensional constant diffusivity", "uniform grid", "fixed Dirichlet boundaries"],
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
