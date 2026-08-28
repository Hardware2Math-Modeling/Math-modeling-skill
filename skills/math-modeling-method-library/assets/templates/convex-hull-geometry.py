from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _cross(origin: tuple[float, float], left: tuple[float, float], right: tuple[float, float]) -> float:
    return (left[0] - origin[0]) * (right[1] - origin[1]) - (left[1] - origin[1]) * (right[0] - origin[0])


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
    """Return the counterclockwise two-dimensional convex hull vertices."""
    points = sorted({(float(point[0]), float(point[1])) for point in data["points"]})
    if not points:
        raise ValueError("convex hull needs at least one point")
    if len(points) <= 2:
        hull = points
    else:
        lower: list[tuple[float, float]] = []
        for point in points:
            while len(lower) >= 2 and _cross(lower[-2], lower[-1], point) <= 0:
                lower.pop()
            lower.append(point)
        upper: list[tuple[float, float]] = []
        for point in reversed(points):
            while len(upper) >= 2 and _cross(upper[-2], upper[-1], point) <= 0:
                upper.pop()
            upper.append(point)
        hull = lower[:-1] + upper[:-1]
    area = 0.0
    if len(hull) >= 3:
        area = abs(sum(hull[index][0] * hull[(index + 1) % len(hull)][1] - hull[(index + 1) % len(hull)][0] * hull[index][1] for index in range(len(hull)))) / 2.0
    return {
        "values": [[point[0], point[1]] for point in hull],
        "metrics": {"unique_points": len(points), "hull_vertices": len(hull), "area": area},
        "assumptions": ["finite planar coordinates", "Euclidean geometry", "collinear interior boundary points are omitted"],
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
