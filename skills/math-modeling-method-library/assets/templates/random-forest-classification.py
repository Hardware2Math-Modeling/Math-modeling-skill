from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any


def _majority(labels: list[Any]) -> Any:
    counts = Counter(labels)
    return min(counts, key=lambda label: (-counts[label], repr(label)))


def _gini(labels: list[Any]) -> float:
    if not labels:
        return 0.0
    counts = Counter(labels)
    return 1.0 - sum((count / len(labels)) ** 2 for count in counts.values())


def _fit_stump(features: list[list[float]], labels: list[Any], candidates: list[int]) -> tuple[int, float, Any, Any] | tuple[None, None, Any, Any]:
    parent = _majority(labels)
    best: tuple[float, int, float, Any, Any] | None = None
    for column in candidates:
        distinct = sorted({row[column] for row in features})
        for left_value, right_value in zip(distinct, distinct[1:]):
            threshold = (left_value + right_value) / 2.0
            left = [label for row, label in zip(features, labels) if row[column] <= threshold]
            right = [label for row, label in zip(features, labels) if row[column] > threshold]
            if not left or not right:
                continue
            impurity = (len(left) * _gini(left) + len(right) * _gini(right)) / len(labels)
            candidate = (impurity, column, threshold, _majority(left), _majority(right))
            if best is None or candidate[:3] < best[:3]:
                best = candidate
    if best is None:
        return (None, None, parent, parent)
    _, column, threshold, left_label, right_label = best
    return (column, threshold, left_label, right_label)


def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Fit a seeded bootstrap forest of randomized decision stumps."""
    features = [[float(value) for value in row] for row in data["X"]]
    labels = list(data["y"])
    trees = int(data.get("n_trees", 25))
    if not features or len(features) != len(labels) or not 1 <= trees <= 1000:
        raise ValueError("forest X/y dimensions or n_trees are invalid")
    columns = len(features[0])
    if columns == 0 or any(len(row) != columns for row in features):
        raise ValueError("forest X must be a nonempty rectangular matrix")
    if any(not isinstance(label, (str, int, bool)) for label in labels):
        raise ValueError("classification labels must be JSON scalar categories")
    generator = random.Random(int(config.get("seed", 0)))
    fitted = []
    candidate_count = max(1, int(math.sqrt(columns)))
    for _ in range(trees):
        indices = [generator.randrange(len(features)) for _ in features]
        sampled_features = [features[index] for index in indices]
        sampled_labels = [labels[index] for index in indices]
        candidate_columns = generator.sample(range(columns), candidate_count)
        fitted.append(_fit_stump(sampled_features, sampled_labels, candidate_columns))
    predictions: list[Any] = []
    for row in features:
        votes = []
        for column, threshold, left_label, right_label in fitted:
            votes.append(left_label if column is None or row[column] <= threshold else right_label)
        predictions.append(_majority(votes))
    accuracy = sum(predicted == actual for predicted, actual in zip(predictions, labels)) / len(labels)
    return {
        "values": predictions,
        "metrics": {"training_accuracy": accuracy, "n_trees": trees, "seed": int(config.get("seed", 0)), "tree_depth": 1},
        "assumptions": ["labeled rows are comparable", "forest consists of depth-one trees", "seed fixes bootstrap and feature sampling"],
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
