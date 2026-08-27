from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Fit and forecast the maintained ARIMA(1,1,0) minimal model."""
    observations = [float(value) for value in data["values"]]
    horizon = int(data["horizon"])
    if len(observations) < 4 or not 1 <= horizon <= 100000:
        raise ValueError("ARIMA(1,1,0) template needs at least four values and positive horizon")
    differences = [current - previous for previous, current in zip(observations, observations[1:])]
    denominator = sum(value * value for value in differences[:-1])
    if denominator <= 1e-15:
        raise ValueError("AR coefficient is not identifiable from constant lagged differences")
    phi = sum(previous * current for previous, current in zip(differences[:-1], differences[1:])) / denominator
    if abs(phi) >= 1:
        raise ValueError("estimated differenced AR(1) is not stationary")
    forecasts: list[float] = []
    level = observations[-1]
    difference = differences[-1]
    for _ in range(horizon):
        difference *= phi
        level += difference
        forecasts.append(level)
    residuals = [current - phi * previous for previous, current in zip(differences[:-1], differences[1:])]
    mse = sum(value * value for value in residuals) / len(residuals)
    return {
        "values": forecasts,
        "metrics": {"phi": phi, "difference_residual_mse": mse, "horizon": horizon},
        "assumptions": ["ARIMA(1,1,0)", "equally spaced series", "stationary differenced AR component"],
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
