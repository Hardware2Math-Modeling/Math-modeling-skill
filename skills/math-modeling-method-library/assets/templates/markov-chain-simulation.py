from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Simulate one finite-state time-homogeneous Markov path."""
    transition = [[float(value) for value in row] for row in data["transition"]]
    initial = int(data["initial"])
    steps = int(data["steps"])
    states = len(transition)
    if not states or any(len(row) != states for row in transition) or not 0 <= initial < states or not 0 <= steps <= 1000000:
        raise ValueError("Markov transition, initial state, or steps is invalid")
    for row in transition:
        if any(value < 0 for value in row) or abs(sum(row) - 1.0) > 1e-9:
            raise ValueError("every Markov transition row must be nonnegative and sum to one")
    generator = random.Random(int(config.get("seed", 0)))
    current = initial
    path = [current]
    for _ in range(steps):
        draw = generator.random()
        cumulative = 0.0
        next_state = states - 1
        for state, probability in enumerate(transition[current]):
            cumulative += probability
            if draw < cumulative:
                next_state = state
                break
        current = next_state
        path.append(current)
    counts = [path.count(state) for state in range(states)]
    return {
        "values": path,
        "metrics": {"state_frequencies": [count / len(path) for count in counts], "steps": steps, "seed": int(config.get("seed", 0))},
        "assumptions": ["time-homogeneous first-order Markov property", "row-stochastic transition matrix", "seed fixes the simulated path"],
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
