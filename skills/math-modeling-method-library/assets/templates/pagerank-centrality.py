from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Compute PageRank with uniform teleportation and dangling redistribution."""
    nodes = [str(value) for value in data["nodes"]]
    damping = float(data.get("damping", 0.85))
    iterations = int(data.get("iterations", 100))
    if not nodes or len(nodes) != len(set(nodes)) or not 0 < damping < 1 or not 1 <= iterations <= 100000:
        raise ValueError("PageRank nodes, damping, or iterations is invalid")
    outgoing = {node: set() for node in nodes}
    for edge in data["edges"]:
        start, end = str(edge[0]), str(edge[1])
        if start not in outgoing or end not in outgoing:
            raise ValueError("PageRank edge contains an unknown node")
        outgoing[start].add(end)
    rank = {node: 1.0 / len(nodes) for node in nodes}
    residual = 0.0
    used = 0
    for used in range(1, iterations + 1):
        dangling = sum(rank[node] for node in nodes if not outgoing[node]) / len(nodes)
        updated = {node: (1.0 - damping) / len(nodes) + damping * dangling for node in nodes}
        for start in nodes:
            if outgoing[start]:
                share = damping * rank[start] / len(outgoing[start])
                for end in outgoing[start]:
                    updated[end] += share
        residual = sum(abs(updated[node] - rank[node]) for node in nodes)
        rank = updated
        if residual < 1e-12:
            break
    total = sum(rank.values())
    values = [rank[node] / total for node in nodes]
    return {
        "values": values,
        "metrics": {"nodes": nodes, "iterations": used, "l1_residual": residual, "damping": damping},
        "assumptions": ["directed unweighted edges", "uniform teleportation", "uniform dangling-node redistribution"],
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
