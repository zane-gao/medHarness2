from __future__ import annotations

from typing import Any

from medharness2.alignment.scoring import finding_pair_score


def maximum_weight_finding_pairs(
    candidates: list[dict[str, Any]],
    references: list[dict[str, Any]],
    *,
    tolerance_mm: float,
) -> list[tuple[int, int]]:
    if not candidates or not references:
        return []
    scores = [
        [finding_pair_score(candidate, reference, tolerance_mm=tolerance_mm) for reference in references]
        for candidate in candidates
    ]
    assignments = _maximum_weight_assignment(scores)
    return [
        (candidate_index, reference_index)
        for candidate_index, reference_index in assignments
        if candidate_index < len(candidates)
        and reference_index < len(references)
        and scores[candidate_index][reference_index] is not None
    ]


def _maximum_weight_assignment(scores: list[list[float | None]]) -> list[tuple[int, int]]:
    row_count = len(scores)
    column_count = len(scores[0]) if scores else 0
    size = max(row_count, column_count)
    if size == 0:
        return []
    eligible = [score for row in scores for score in row if score is not None]
    maximum = max([0.0, *eligible])
    forbidden_weight = -1_000_000.0
    weights = [[0.0 for _ in range(size)] for _ in range(size)]
    for row_index in range(row_count):
        for column_index in range(column_count):
            score = scores[row_index][column_index]
            weights[row_index][column_index] = forbidden_weight if score is None else score
    costs = [[maximum - value for value in row] for row in weights]
    return _hungarian_minimize(costs)


def _hungarian_minimize(costs: list[list[float]]) -> list[tuple[int, int]]:
    size = len(costs)
    potentials_rows = [0.0] * (size + 1)
    potentials_columns = [0.0] * (size + 1)
    matched_row_by_column = [0] * (size + 1)
    previous_column = [0] * (size + 1)

    for row in range(1, size + 1):
        matched_row_by_column[0] = row
        min_cost = [float("inf")] * (size + 1)
        used = [False] * (size + 1)
        column = 0
        while True:
            used[column] = True
            current_row = matched_row_by_column[column]
            delta = float("inf")
            next_column = 0
            for candidate_column in range(1, size + 1):
                if used[candidate_column]:
                    continue
                reduced = (
                    costs[current_row - 1][candidate_column - 1]
                    - potentials_rows[current_row]
                    - potentials_columns[candidate_column]
                )
                if reduced < min_cost[candidate_column]:
                    min_cost[candidate_column] = reduced
                    previous_column[candidate_column] = column
                if min_cost[candidate_column] < delta:
                    delta = min_cost[candidate_column]
                    next_column = candidate_column
            for candidate_column in range(size + 1):
                if used[candidate_column]:
                    potentials_rows[matched_row_by_column[candidate_column]] += delta
                    potentials_columns[candidate_column] -= delta
                else:
                    min_cost[candidate_column] -= delta
            column = next_column
            if matched_row_by_column[column] == 0:
                break
        while True:
            prior = previous_column[column]
            matched_row_by_column[column] = matched_row_by_column[prior]
            column = prior
            if column == 0:
                break

    return [
        (matched_row_by_column[column] - 1, column - 1)
        for column in range(1, size + 1)
        if matched_row_by_column[column] != 0
    ]
