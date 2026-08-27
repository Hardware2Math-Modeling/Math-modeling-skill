from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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
        updated = [max(0.0, share + dt * share * (value - average)) for share, value in zip(shares, fitness)]
        total = sum(updated)
        if total <= 0:
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
