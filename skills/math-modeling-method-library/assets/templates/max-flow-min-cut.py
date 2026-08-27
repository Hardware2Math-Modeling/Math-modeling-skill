from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path
from typing import Any


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Compute a directed maximum flow and source-side minimum cut."""
    nodes = [str(value) for value in data["nodes"]]
    source, sink = str(data["source"]), str(data["sink"])
    if len(nodes) != len(set(nodes)) or source not in nodes or sink not in nodes or source == sink:
        raise ValueError("flow nodes must be unique and contain distinct source/sink")
    capacity = {(left, right): 0.0 for left in nodes for right in nodes}
    neighbors = {node: set() for node in nodes}
    for edge in data["edges"]:
        start, end, value = str(edge[0]), str(edge[1]), float(edge[2])
        if start not in neighbors or end not in neighbors or value < 0:
            raise ValueError("flow edges require known nodes and nonnegative capacities")
        capacity[start, end] += value
        neighbors[start].add(end)
        neighbors[end].add(start)
    residual = capacity.copy()
    maximum = 0.0
    augmentations = 0
    while True:
        parent = {source: ""}
        queue = deque([source])
        while queue and sink not in parent:
            node = queue.popleft()
            for neighbor in sorted(neighbors[node]):
                if neighbor not in parent and residual[node, neighbor] > 1e-12:
                    parent[neighbor] = node
                    queue.append(neighbor)
        if sink not in parent:
            break
        bottleneck = float("inf")
        node = sink
        while node != source:
            previous = parent[node]
            bottleneck = min(bottleneck, residual[previous, node])
            node = previous
        node = sink
        while node != source:
            previous = parent[node]
            residual[previous, node] -= bottleneck
            residual[node, previous] += bottleneck
            node = previous
        maximum += bottleneck
        augmentations += 1
    reachable = {source}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        for neighbor in sorted(neighbors[node]):
            if neighbor not in reachable and residual[node, neighbor] > 1e-12:
                reachable.add(neighbor)
                queue.append(neighbor)
    cut_capacity = sum(capacity[left, right] for left in reachable for right in nodes if right not in reachable)
    return {
        "values": [maximum],
        "metrics": {"min_cut_capacity": cut_capacity, "source_side": sorted(reachable), "augmentations": augmentations},
        "assumptions": ["directed nonnegative capacities", "single source and sink", "flow conservation at intermediate nodes"],
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
