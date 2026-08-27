from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Compute a two-sided one-sample t statistic with normal-tail approximation."""
    observations = [float(value) for value in data["values"]]
    null_mean = float(data["null_mean"])
    if len(observations) < 2:
        raise ValueError("one-sample test needs at least two observations")
    mean = sum(observations) / len(observations)
    variance = sum((value - mean) ** 2 for value in observations) / (len(observations) - 1)
    if variance <= 0:
        raise ValueError("one-sample statistic is undefined for zero sample variance")
    standard_error = math.sqrt(variance / len(observations))
    statistic = (mean - null_mean) / standard_error
    p_value = math.erfc(abs(statistic) / math.sqrt(2.0))
    return {
        "values": [statistic, p_value],
        "metrics": {"sample_mean": mean, "mean_difference": mean - null_mean, "standard_error": standard_error, "n": len(observations)},
        "assumptions": ["independent observations", "two-sided one-sample mean test", "normal approximation to the t tail"],
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
