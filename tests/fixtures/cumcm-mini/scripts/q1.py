#!/usr/bin/env python3
"""Deterministic offline regression adapter for fixture/test-data."""

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
rows = list(csv.DictReader(Path(args.input).read_text(encoding="utf-8").splitlines()))
x = [float(row["month"]) for row in rows]
y = [float(row["demand"]) for row in rows]
x_bar, y_bar = sum(x) / len(x), sum(y) / len(y)
slope = sum((a - x_bar) * (b - y_bar) for a, b in zip(x, y)) / sum(
    (a - x_bar) ** 2 for a in x
)
intercept = y_bar - slope * x_bar
fitted = [intercept + slope * value for value in x]
sse = sum((actual - predicted) ** 2 for actual, predicted in zip(y, fitted))
sst = sum((actual - y_bar) ** 2 for actual in y)
payload = {
    "fixture_label": "fixture/test-data",
    "seed": args.seed,
    "metrics": {
        "slope": {"value": slope, "unit": "items/month"},
        "intercept": {"value": intercept, "unit": "items"},
        "r_squared": {"value": 1.0 - sse / sst, "unit": "dimensionless"},
    },
    "series": [
        {"month": month, "actual_items": actual, "fitted_items": predicted}
        for month, actual, predicted in zip(x, y, fitted)
    ],
}
assert all(math.isfinite(metric["value"]) for metric in payload["metrics"].values())
Path(args.output).write_text(
    json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n",
    encoding="utf-8",
)
