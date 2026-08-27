from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Score univariate observations with the median absolute deviation."""
    observations = [float(value) for value in data["values"]]
    threshold = float(data.get("threshold", 3.5))
    if len(observations) < 3 or threshold <= 0:
        raise ValueError("MAD detection needs at least three values and a positive threshold")
    median = float(statistics.median(observations))
    mad = float(statistics.median(abs(value - median) for value in observations))
    if mad <= 0:
        raise ValueError("MAD is zero; the maintained robust score is undefined")
    scores = [0.67448975 * (value - median) / mad for value in observations]
    flags = [abs(value) > threshold for value in scores]
    return {
        "values": scores,
        "metrics": {"median": median, "mad": mad, "threshold": threshold, "outlier_indices": [index for index, flagged in enumerate(flags) if flagged]},
        "assumptions": ["a majority of observations share one stable distribution", "flags require domain review before exclusion"],
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
