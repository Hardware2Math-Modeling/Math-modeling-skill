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
    """Integrate dy/dt = rate*y + forcing with classical RK4."""
    state = float(data["y0"])
    rate = float(data["rate"])
    forcing = float(data["forcing"])
    step_size = float(data["dt"])
    steps = int(data["steps"])
    if step_size <= 0 or not 1 <= steps <= 1000000:
        raise ValueError("ODE dt and steps must be positive and bounded")
    trajectory = [state]
    for _ in range(steps):
        derivative = lambda value: rate * value + forcing
        k1 = derivative(state)
        k2 = derivative(state + step_size * k1 / 2.0)
        k3 = derivative(state + step_size * k2 / 2.0)
        k4 = derivative(state + step_size * k3)
        state += step_size * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0
        trajectory.append(state)
    if rate == 0:
        exact_final = float(data["y0"]) + forcing * step_size * steps
    else:
        import math

        elapsed = step_size * steps
        exact_final = (float(data["y0"]) + forcing / rate) * math.exp(rate * elapsed) - forcing / rate
    return {
        "values": trajectory,
        "metrics": {"final_time": step_size * steps, "absolute_error_against_linear_exact": abs(state - exact_final), "steps": steps},
        "assumptions": ["scalar non-stiff linear ODE", "constant rate and forcing", "fixed positive RK4 step"],
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
