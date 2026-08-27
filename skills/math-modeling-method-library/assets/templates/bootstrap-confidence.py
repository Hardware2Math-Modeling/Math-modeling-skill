from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any


def _quantile(values: list[float], probability: float) -> float:
    position = probability * (len(values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] * (1.0 - fraction) + values[upper] * fraction


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Return a seeded percentile-bootstrap confidence interval for the mean."""
    observations = [float(value) for value in data["values"]]
    resamples = int(data.get("resamples", 2000))
    confidence = float(data.get("confidence", 0.95))
    if not observations or not 1 <= resamples <= 100000 or not 0 < confidence < 1:
        raise ValueError("bootstrap values, resamples, or confidence is invalid")
    generator = random.Random(int(config.get("seed", 0)))
    means = sorted(
        sum(observations[generator.randrange(len(observations))] for _ in observations) / len(observations)
        for _ in range(resamples)
    )
    tail = (1.0 - confidence) / 2.0
    sample_mean = sum(observations) / len(observations)
    return {
        "values": [sample_mean, _quantile(means, tail), _quantile(means, 1.0 - tail)],
        "metrics": {"resamples": resamples, "confidence": confidence, "seed": int(config.get("seed", 0))},
        "assumptions": ["iid exchangeable observations", "nonparametric resampling unit is one row"],
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
