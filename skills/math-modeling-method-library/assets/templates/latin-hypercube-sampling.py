from __future__ import annotations

import argparse
import json
import random
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
    """Generate a seeded Latin hypercube over finite rectangular bounds."""
    bounds = [(float(pair[0]), float(pair[1])) for pair in data["bounds"]]
    samples = int(data["samples"])
    if not bounds or any(low >= high for low, high in bounds) or not 1 <= samples <= 1000000:
        raise ValueError("Latin hypercube bounds or sample count is invalid")
    generator = random.Random(int(config.get("seed", 0)))
    columns: list[list[float]] = []
    for low, high in bounds:
        unit = [(stratum + generator.random()) / samples for stratum in range(samples)]
        generator.shuffle(unit)
        columns.append([low + value * (high - low) for value in unit])
    rows = [[columns[column][row] for column in range(len(bounds))] for row in range(samples)]
    return {
        "values": rows,
        "metrics": {"samples": samples, "dimensions": len(bounds), "seed": int(config.get("seed", 0))},
        "assumptions": ["finite rectangular bounds", "independent per-dimension permutations", "one point in every marginal stratum"],
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
