from __future__ import annotations

import argparse
import heapq
import json
from pathlib import Path
from typing import Any


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Find one deterministic nonnegative shortest path with Dijkstra's method."""
    nodes = [str(value) for value in data["nodes"]]
    source, target = str(data["source"]), str(data["target"])
    if len(nodes) != len(set(nodes)) or source not in nodes or target not in nodes:
        raise ValueError("shortest-path nodes must be unique and contain source/target")
    adjacency: dict[str, list[tuple[str, float]]] = {node: [] for node in nodes}
    for edge in data["edges"]:
        start, end, weight = str(edge[0]), str(edge[1]), float(edge[2])
        if start not in adjacency or end not in adjacency or weight < 0:
            raise ValueError("Dijkstra edges require known nodes and nonnegative weights")
        adjacency[start].append((end, weight))
    for edges in adjacency.values():
        edges.sort()
    distances = {node: float("inf") for node in nodes}
    distances[source] = 0.0
    previous: dict[str, str] = {}
    queue = [(0.0, source)]
    settled = 0
    while queue:
        distance, node = heapq.heappop(queue)
        if distance != distances[node]:
            continue
        settled += 1
        if node == target:
            break
        for neighbor, weight in adjacency[node]:
            candidate = distance + weight
            if candidate < distances[neighbor] - 1e-12:
                distances[neighbor] = candidate
                previous[neighbor] = node
                heapq.heappush(queue, (candidate, neighbor))
    if distances[target] == float("inf"):
        raise ValueError("shortest-path target is unreachable")
    path = [target]
    while path[-1] != source:
        path.append(previous[path[-1]])
    path.reverse()
    return {
        "values": path,
        "metrics": {"distance": distances[target], "settled_nodes": settled},
        "assumptions": ["directed graph", "additive nonnegative edge weights", "one declared weight unit"],
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
