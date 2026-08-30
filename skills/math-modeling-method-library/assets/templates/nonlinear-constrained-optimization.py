from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _project(values: list[float], bounds: list[tuple[float, float]], limit: float) -> list[float]:
    clipped = [min(high, max(low, value)) for value, (low, high) in zip(values, bounds)]
    if sum(clipped) <= limit:
        return clipped
    left, right = 0.0, max(value - low for value, (low, _) in zip(clipped, bounds))
    for _ in range(80):
        shift = (left + right) / 2.0
        projected = [min(high, max(low, value - shift)) for value, (low, high) in zip(clipped, bounds)]
        if sum(projected) > limit:
            left = shift
        else:
            right = shift
    return [min(high, max(low, value - right)) for value, (low, high) in zip(clipped, bounds)]


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
    """Maximize a separable concave quadratic over box and sum constraints."""
    linear = [float(value) for value in data["linear"]]
    quadratic = [float(value) for value in data["quadratic"]]
    bounds = [(float(pair[0]), float(pair[1])) for pair in data["bounds"]]
    limit = float(data["sum_limit"])
    step_size = float(data.get("step_size", 0.05))
    iterations = int(data.get("iterations", 500))
    if not linear or len(linear) != len(quadratic) or len(linear) != len(bounds):
        raise ValueError("linear, quadratic, and bounds must have equal nonzero length")
    if any(q <= 0 for q in quadratic) or any(low > high for low, high in bounds):
        raise ValueError("quadratic coefficients must be positive and bounds ordered")
    if sum(low for low, _ in bounds) > limit or step_size <= 0 or not 1 <= iterations <= 100000:
        raise ValueError("sum constraint, step size, or iteration count is invalid")
    values = _project([(low + high) / 2.0 for low, high in bounds], bounds, limit)
    used = 0
    for used in range(1, iterations + 1):
        gradient = [a - 2.0 * q * value for a, q, value in zip(linear, quadratic, values)]
        updated = _project(
            [value + step_size * change for value, change in zip(values, gradient)],
            bounds,
            limit,
        )
        if max(abs(new - old) for new, old in zip(updated, values)) < 1e-10:
            values = updated
            break
        values = updated
    objective = sum(a * value - q * value * value for a, q, value in zip(linear, quadratic, values))
    violation = max(0.0, sum(values) - limit, *(low - value for value, (low, _) in zip(values, bounds)), *(value - high for value, (_, high) in zip(values, bounds)))
    return {
        "values": values,
        "metrics": {"objective": objective, "iterations": used, "max_constraint_violation": violation},
        "assumptions": ["strictly concave separable objective", "box and total-allocation constraints"],
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
