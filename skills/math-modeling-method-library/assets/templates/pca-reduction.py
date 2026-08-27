from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Extract the first principal component by covariance power iteration."""
    matrix = [[float(value) for value in row] for row in data["matrix"]]
    iterations = int(data.get("iterations", 100))
    if len(matrix) < 2 or not 1 <= iterations <= 10000:
        raise ValueError("PCA needs at least two rows and a positive iteration count")
    columns = len(matrix[0])
    if not 1 <= columns <= 200 or any(len(row) != columns for row in matrix):
        raise ValueError("PCA matrix must be rectangular with 1..200 columns")
    means = [sum(row[column] for row in matrix) / len(matrix) for column in range(columns)]
    centered = [[value - mean for value, mean in zip(row, means)] for row in matrix]
    covariance = [[sum(row[i] * row[j] for row in centered) / (len(centered) - 1) for j in range(columns)] for i in range(columns)]
    total_variance = sum(covariance[index][index] for index in range(columns))
    if total_variance <= 1e-15:
        raise ValueError("PCA is undefined for zero total variance")
    vector = [1.0 / math.sqrt(columns)] * columns
    for _ in range(iterations):
        updated = [sum(value * component for value, component in zip(row, vector)) for row in covariance]
        norm = math.sqrt(sum(value * value for value in updated))
        if norm <= 1e-15:
            raise ValueError("PCA power iteration reached a zero direction")
        updated = [value / norm for value in updated]
        if max(abs(abs(a) - abs(b)) for a, b in zip(updated, vector)) < 1e-12:
            vector = updated
            break
        vector = updated
    anchor = max(range(columns), key=lambda index: abs(vector[index]))
    if vector[anchor] < 0:
        vector = [-value for value in vector]
    scores = [sum(value * loading for value, loading in zip(row, vector)) for row in centered]
    eigenvalue = sum(vector[i] * covariance[i][j] * vector[j] for i in range(columns) for j in range(columns))
    return {
        "values": scores,
        "metrics": {"loadings": vector, "explained_variance": eigenvalue, "explained_variance_ratio": eigenvalue / total_variance},
        "assumptions": ["centered continuous features", "linear first-component representation", "largest-loading sign fixed positive for determinism"],
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
