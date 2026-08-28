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
    """Integrate symmetric-game replicator dynamics with explicit Euler steps."""
    payoff = [[float(value) for value in row] for row in data["payoff"]]
    shares = [float(value) for value in data["initial"]]
    dt = float(data["dt"])
    steps = int(data["steps"])
    strategies = len(payoff)
    if not strategies or any(len(row) != strategies for row in payoff) or len(shares) != strategies:
        raise ValueError("replicator payoff and initial shares have incompatible shape")
    if any(value < 0 for value in shares) or abs(sum(shares) - 1.0) > 1e-9 or dt <= 0 or not 1 <= steps <= 1000000:
        raise ValueError("replicator initial simplex, dt, or steps is invalid")
    trajectory = [shares[:]]
    for _ in range(steps):
        fitness = [sum(value * share for value, share in zip(row, shares)) for row in payoff]
        average = sum(share * value for share, value in zip(shares, fitness))
        raw_updated = [share + dt * share * (value - average) for share, value in zip(shares, fitness)]
        if any(not math.isfinite(value) for value in raw_updated):
            raise ValueError("replicator step must produce a finite Euler update")
        scale = max(1.0, *(abs(value) for value in raw_updated))
        roundoff = 64.0 * math.ulp(scale)
        if any(value < -roundoff or value > 1.0 + roundoff for value in raw_updated):
            raise ValueError("replicator Euler step left the probability simplex")
        updated = [min(1.0, max(0.0, value)) for value in raw_updated]
        total = sum(updated)
        if total <= 0 or abs(total - 1.0) > roundoff * len(updated):
            raise ValueError("replicator Euler step left the probability simplex")
        shares = [value / total for value in updated]
        trajectory.append(shares[:])
    simplex_error = abs(sum(shares) - 1.0)
    return {
        "values": shares,
        "metrics": {"trajectory": trajectory, "steps": steps, "dt": dt, "simplex_error": simplex_error},
        "assumptions": ["large well-mixed population", "fixed symmetric payoff matrix", "Euler step is small enough"],
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
