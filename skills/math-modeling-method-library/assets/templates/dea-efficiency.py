from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Compute the single-input, single-output CCR efficiency special case."""
    inputs = [float(value) for value in data["inputs"]]
    outputs = [float(value) for value in data["outputs"]]
    if not inputs or len(inputs) != len(outputs):
        raise ValueError("DEA inputs and outputs must have equal nonzero length")
    if any(value <= 0 for value in inputs) or any(value < 0 for value in outputs):
        raise ValueError("DEA inputs must be positive and outputs nonnegative")
    ratios = [output / input_value for input_value, output in zip(inputs, outputs)]
    frontier = max(ratios)
    if frontier <= 0:
        raise ValueError("DEA frontier is undefined when every output is zero")
    efficiencies = [ratio / frontier for ratio in ratios]
    return {
        "values": efficiencies,
        "metrics": {"frontier_ratio": frontier, "efficient_units": sum(abs(value - 1.0) <= 1e-12 for value in efficiencies)},
        "assumptions": ["single input and single output", "CCR constant returns to scale", "comparable decision units"],
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
