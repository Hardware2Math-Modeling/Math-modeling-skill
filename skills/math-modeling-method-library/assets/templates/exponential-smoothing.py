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
    """Produce simple-exponential-smoothing level forecasts."""
    observations = [float(value) for value in data["values"]]
    alpha = float(data["alpha"])
    horizon = int(data["horizon"])
    if not observations or not 0 < alpha <= 1 or not 1 <= horizon <= 100000:
        raise ValueError("values, alpha, or horizon is invalid")
    level = observations[0]
    fitted = [level]
    for observation in observations[1:]:
        level = alpha * observation + (1.0 - alpha) * level
        fitted.append(level)
    one_step_errors = [actual - previous for actual, previous in zip(observations[1:], fitted[:-1])]
    mae = sum(abs(value) for value in one_step_errors) / len(one_step_errors) if one_step_errors else 0.0
    return {
        "values": [level] * horizon,
        "metrics": {"final_level": level, "one_step_mae": mae, "alpha": alpha},
        "assumptions": ["equally spaced observations", "level-only process without trend or seasonality"],
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
