from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _distance_squared(left: list[float], right: list[float]) -> float:
    return sum((a - b) ** 2 for a, b in zip(left, right))


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Cluster points with deterministic seeded farthest-first K-means."""
    points = [[float(value) for value in row] for row in data["points"]]
    clusters = int(data["k"])
    max_iter = int(data.get("max_iter", 100))
    if not points or not 1 <= clusters <= len(points) or not 1 <= max_iter <= 10000:
        raise ValueError("K-means points, k, or max_iter is invalid")
    dimensions = len(points[0])
    if dimensions == 0 or any(len(point) != dimensions for point in points):
        raise ValueError("K-means points must be rectangular")
    first = int(config.get("seed", 0)) % len(points)
    centroids = [points[first][:]]
    while len(centroids) < clusters:
        index = max(
            range(len(points)),
            key=lambda row: (min(_distance_squared(points[row], center) for center in centroids), -row),
        )
        if any(points[index] == center for center in centroids):
            raise ValueError("K-means needs at least k distinct points")
        centroids.append(points[index][:])
    labels = [-1] * len(points)
    used = 0
    for used in range(1, max_iter + 1):
        new_labels = [min(range(clusters), key=lambda cluster: (_distance_squared(point, centroids[cluster]), cluster)) for point in points]
        if new_labels == labels:
            break
        labels = new_labels
        for cluster in range(clusters):
            members = [point for point, label in zip(points, labels) if label == cluster]
            if members:
                centroids[cluster] = [sum(point[column] for point in members) / len(members) for column in range(dimensions)]
    inertia = sum(_distance_squared(point, centroids[label]) for point, label in zip(points, labels))
    return {
        "values": [int(value) for value in labels],
        "metrics": {"centroids": centroids, "inertia": inertia, "iterations": used, "k": clusters},
        "assumptions": ["Euclidean geometry after declared scaling", "approximately spherical clusters", "seed selects the first farthest-first center"],
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
