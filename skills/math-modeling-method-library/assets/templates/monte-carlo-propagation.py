from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any


def _quantile(values: list[float], probability: float) -> float:
    position = probability * (len(values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] * (1.0 - fraction) + values[upper] * fraction


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
    """Propagate independent normal inputs through their product."""
    means = [float(value) for value in data["means"]]
    standard_deviations = [float(value) for value in data["stds"]]
    samples = int(data.get("samples", 10000))
    if not means or len(means) != len(standard_deviations) or any(value < 0 for value in standard_deviations) or not 1 <= samples <= 200000:
        raise ValueError("Monte Carlo means, stds, or samples is invalid")
    generator = random.Random(int(config.get("seed", 0)))
    outputs = []
    for _ in range(samples):
        factors = [generator.gauss(mean, deviation) for mean, deviation in zip(means, standard_deviations)]
        outputs.append(math.prod(factors))
    outputs.sort()
    mean_output = sum(outputs) / samples
    variance = sum((value - mean_output) ** 2 for value in outputs) / (samples - 1) if samples > 1 else 0.0
    return {
        "values": [mean_output, math.sqrt(variance), _quantile(outputs, 0.05), _quantile(outputs, 0.95)],
        "metrics": {"samples": samples, "seed": int(config.get("seed", 0)), "input_dimensions": len(means)},
        "assumptions": ["independent normal inputs", "output equals the product of inputs", "seed fixes the sample stream"],
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
