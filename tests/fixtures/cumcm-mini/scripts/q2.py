#!/usr/bin/env python3
"""Deterministic offline allocation adapter for fixture/test-data."""

import argparse
import csv
import json
import math
import random
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--seed", required=True, type=int)
args = parser.parse_args()
random.seed(args.seed)
row = list(csv.DictReader(Path(args.input).read_text(encoding="utf-8").splitlines()))[-1]
demand = int(row["demand"])
capacity_a, capacity_b = int(row["capacity_a"]), int(row["capacity_b"])
cost_a, cost_b = float(row["cost_a"]), float(row["cost_b"])
feasible = [
    (cost_a * a + cost_b * b, a, b)
    for a in range(capacity_a + 1)
    for b in range(capacity_b + 1)
    if a + b >= demand
]
total_cost, allocation_a, allocation_b = min(feasible)
payload = {
    "fixture_label": "fixture/test-data",
    "seed": args.seed,
    "metrics": {
        "allocation_a": {"value": allocation_a, "unit": "items"},
        "allocation_b": {"value": allocation_b, "unit": "items"},
        "total_cost": {"value": total_cost, "unit": "CNY"},
        "unmet_demand": {"value": max(0, demand - allocation_a - allocation_b), "unit": "items"},
    },
}
assert all(math.isfinite(metric["value"]) for metric in payload["metrics"].values())
Path(args.output).write_text(
    json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n",
    encoding="utf-8",
)
