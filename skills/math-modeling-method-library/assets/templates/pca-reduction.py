from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


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


def _off_diagonal_frobenius(matrix: list[list[float]]) -> float:
    upper_triangle = (
        matrix[row][column]
        for row in range(len(matrix))
        for column in range(row + 1, len(matrix))
    )
    return math.sqrt(2.0) * math.hypot(*upper_triangle)


def _apply_jacobi_rotation(
    matrix: list[list[float]],
    eigenvectors: list[list[float]],
    row: int,
    column: int,
) -> None:
    off_diagonal = matrix[row][column]
    if off_diagonal == 0.0:
        return
    row_diagonal = matrix[row][row]
    column_diagonal = matrix[column][column]
    half_difference = (column_diagonal - row_diagonal) / 2.0
    if half_difference == 0.0:
        tangent = math.copysign(1.0, off_diagonal)
    else:
        magnitude = abs(off_diagonal) / (
            abs(half_difference) + math.hypot(half_difference, off_diagonal)
        )
        same_sign = (half_difference < 0.0) == (off_diagonal < 0.0)
        tangent = magnitude if same_sign else -magnitude
    cosine = 1.0 / math.hypot(1.0, tangent)
    sine = tangent * cosine

    for index in range(len(matrix)):
        if index in (row, column):
            continue
        row_value = matrix[index][row]
        column_value = matrix[index][column]
        rotated_row = cosine * row_value - sine * column_value
        rotated_column = sine * row_value + cosine * column_value
        matrix[index][row] = matrix[row][index] = rotated_row
        matrix[index][column] = matrix[column][index] = rotated_column
    matrix[row][row] = row_diagonal - tangent * off_diagonal
    matrix[column][column] = column_diagonal + tangent * off_diagonal
    matrix[row][column] = matrix[column][row] = 0.0

    for index in range(len(eigenvectors)):
        row_value = eigenvectors[index][row]
        column_value = eigenvectors[index][column]
        eigenvectors[index][row] = cosine * row_value - sine * column_value
        eigenvectors[index][column] = sine * row_value + cosine * column_value


@_finite_json_io
def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Extract the first principal component by symmetric Jacobi diagonalization."""
    matrix = [[float(value) for value in row] for row in data["matrix"]]
    iteration_input = data.get("iterations", 20)
    if type(iteration_input) is int:
        iterations = iteration_input
    elif type(iteration_input) is float and iteration_input.is_integer():
        iterations = int(iteration_input)
    else:
        raise ValueError("PCA iterations must be an integer Jacobi sweep budget")
    if len(matrix) < 2 or not 1 <= iterations <= 50:
        raise ValueError("PCA needs at least two rows and 1..50 Jacobi sweeps")
    columns = len(matrix[0])
    if not 1 <= columns <= 50 or any(len(row) != columns for row in matrix):
        raise ValueError("PCA matrix must be rectangular with 1..50 columns")
    means = [
        math.fsum(row[column] / len(matrix) for row in matrix)
        for column in range(columns)
    ]
    centered = [[value - mean for value, mean in zip(row, means)] for row in matrix]
    if any(not math.isfinite(value) for row in centered for value in row):
        raise ValueError("PCA must produce a finite centered matrix")
    covariance = [[0.0] * columns for _ in range(columns)]
    denominator = len(centered) - 1
    for row in range(columns):
        for column in range(row, columns):
            try:
                value = math.fsum(
                    sample[row] * (sample[column] / denominator)
                    for sample in centered
                )
            except (OverflowError, ValueError) as error:
                raise ValueError("PCA must produce a finite covariance matrix") from error
            covariance[row][column] = covariance[column][row] = value
    if any(not math.isfinite(value) for row in covariance for value in row):
        raise ValueError("PCA must produce a finite covariance matrix")
    total_variance = sum(covariance[index][index] for index in range(columns))
    if not math.isfinite(total_variance):
        raise ValueError("PCA must produce a finite covariance matrix")
    if total_variance <= 1e-15:
        raise ValueError("PCA requires total variance above 1e-15")
    convergence_tolerance = total_variance * 1e-12
    diagonalized = [row[:] for row in covariance]
    eigenvectors = [
        [1.0 if row == column else 0.0 for column in range(columns)]
        for row in range(columns)
    ]
    off_diagonal_norm = _off_diagonal_frobenius(diagonalized)
    sweeps_used = 0
    while off_diagonal_norm > convergence_tolerance and sweeps_used < iterations:
        sweeps_used += 1
        for row in range(columns - 1):
            for column in range(row + 1, columns):
                _apply_jacobi_rotation(diagonalized, eigenvectors, row, column)
        if any(not math.isfinite(value) for row in diagonalized for value in row):
            raise ValueError("PCA Jacobi rotations must remain finite")
        if any(not math.isfinite(value) for row in eigenvectors for value in row):
            raise ValueError("PCA Jacobi rotations must remain finite")
        off_diagonal_norm = _off_diagonal_frobenius(diagonalized)
    if off_diagonal_norm > convergence_tolerance:
        raise ValueError(
            f"PCA Jacobi diagonalization did not converge within {iterations} sweeps"
        )

    vectors = [
        [eigenvectors[row][column] for row in range(columns)]
        for column in range(columns)
    ]
    products = [
        [sum(value * component for value, component in zip(row, vector)) for row in covariance]
        for vector in vectors
    ]
    eigenvalues = [
        sum(value * component for value, component in zip(vector, product))
        for vector, product in zip(vectors, products)
    ]
    residuals = [
        math.hypot(
            *(value - eigenvalue * component for value, component in zip(product, vector))
        )
        for vector, product, eigenvalue in zip(vectors, products, eigenvalues)
    ]
    certified_off_diagonal_norm = math.hypot(*residuals)
    if certified_off_diagonal_norm > convergence_tolerance:
        raise ValueError(
            f"PCA Jacobi residual certification did not converge within {iterations} sweeps"
        )
    selected = max(range(columns), key=lambda index: (eigenvalues[index], -index))
    eigenvalue = eigenvalues[selected]
    vector = vectors[selected]
    convergence_residual = residuals[selected]
    anchor = max(range(columns), key=lambda index: abs(vector[index]))
    if vector[anchor] < 0:
        vector = [-value for value in vector]
    scores = [sum(value * loading for value, loading in zip(row, vector)) for row in centered]
    return {
        "values": scores,
        "metrics": {
            "loadings": vector,
            "explained_variance": eigenvalue,
            "explained_variance_ratio": eigenvalue / total_variance,
            "convergence_residual": convergence_residual,
            "convergence_tolerance": convergence_tolerance,
            "off_diagonal_norm": certified_off_diagonal_norm,
            "jacobi_sweeps": sweeps_used,
        },
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
