from __future__ import annotations

import argparse
import cmath
import json
import math
from pathlib import Path
from typing import Any


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Denoise an equally spaced real signal by low-frequency DFT truncation."""
    signal = [float(value) for value in data["values"]]
    keep = int(data["keep_frequencies"])
    size = len(signal)
    if size < 2 or size > 2048 or not 1 <= keep <= size // 2 + 1:
        raise ValueError("DFT signal length or keep_frequencies is invalid")
    spectrum = [sum(value * cmath.exp(-2j * math.pi * frequency * index / size) for index, value in enumerate(signal)) for frequency in range(size)]
    retained = {0}
    for frequency in range(1, keep):
        retained.add(frequency)
        retained.add((-frequency) % size)
    filtered = [value if index in retained else 0j for index, value in enumerate(spectrum)]
    reconstructed = [sum(value * cmath.exp(2j * math.pi * frequency * index / size) for frequency, value in enumerate(filtered)).real / size for index in range(size)]
    removed_power = sum(abs(value) ** 2 for index, value in enumerate(spectrum) if index not in retained) / (size * size)
    mse = sum((actual - estimate) ** 2 for actual, estimate in zip(signal, reconstructed)) / size
    return {
        "values": [0.0 if abs(value) < 1e-12 else value for value in reconstructed],
        "metrics": {"kept_nonnegative_frequencies": keep, "removed_power": removed_power, "reconstruction_mse": mse, "samples": size},
        "assumptions": ["equally spaced real samples", "periodic boundary approximation", "signal energy is concentrated in retained low frequencies"],
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
