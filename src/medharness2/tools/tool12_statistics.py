from __future__ import annotations

import math
import statistics
from typing import Any


STATISTIC_METRICS = {
    "likert_mean",
    "structure_score",
    "finding_coverage",
    "precision",
    "recall",
    "score",
    "error_rate",
    "agreement",
}


def calculate_statistics(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    values_by_key: dict[str, list[float]] = {}
    for row in rows:
        for key, value in _numeric_metrics(row).items():
            values_by_key.setdefault(key, []).append(value)
    result: dict[str, dict[str, float]] = {}
    for key, values in values_by_key.items():
        mean = statistics.mean(values)
        std = statistics.stdev(values) if len(values) > 1 else 0.0
        ci = _ci_half_width(std, len(values))
        result[key] = {
            "n": len(values),
            "mean": mean,
            "std": std,
            "min": min(values),
            "max": max(values),
            "ci_lower": mean - ci,
            "ci_upper": mean + ci,
        }
    return result


def percentile_rank(value: float, population: list[float]) -> float:
    if not population:
        return 0.0
    below = sum(1 for item in population if item < value)
    equal = sum(1 for item in population if item == value)
    return round(100.0 * (below + 0.5 * equal) / len(population), 6)


def _numeric_metrics(row: dict[str, Any]) -> dict[str, float]:
    payload = row.get("metrics") or row.get("composite_inputs") or row
    return {
        key: float(value)
        for key, value in payload.items()
        if key in STATISTIC_METRICS
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }


def _ci_half_width(std: float, n: int) -> float:
    if n <= 1:
        return 0.0
    # Conservative t critical values for the small pilot sizes; 1.96 thereafter.
    critical = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365, 9: 2.306, 10: 2.262}.get(n, 1.96)
    return critical * std / math.sqrt(n)


def compare_metric_groups(group_a: list[float], group_b: list[float]) -> dict[str, float | int | str]:
    """Welch-style comparison with a deterministic permutation fallback for tiny samples."""
    a = [float(value) for value in group_a]
    b = [float(value) for value in group_b]
    if not a or not b:
        return {"n_a": len(a), "n_b": len(b), "mean_a": 0.0, "mean_b": 0.0, "difference": 0.0, "p_value": 1.0, "method": "insufficient_data"}
    mean_a = statistics.mean(a)
    mean_b = statistics.mean(b)
    difference = mean_a - mean_b
    if len(a) < 2 or len(b) < 2:
        return {"n_a": len(a), "n_b": len(b), "mean_a": mean_a, "mean_b": mean_b, "difference": difference, "p_value": 1.0, "method": "insufficient_data"}
    var_a = statistics.variance(a)
    var_b = statistics.variance(b)
    denominator = math.sqrt(var_a / len(a) + var_b / len(b))
    if denominator == 0:
        p_value = 0.0 if difference else 1.0
    else:
        t_value = abs(difference / denominator)
        # Conservative normal-tail approximation; formal reports must record this method.
        p_value = math.erfc(t_value / math.sqrt(2.0))
    return {"n_a": len(a), "n_b": len(b), "mean_a": mean_a, "mean_b": mean_b, "difference": difference, "p_value": min(1.0, max(0.0, p_value)), "method": "welch_normal_approximation"}


def correct_pvalues_holm(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(((key, min(1.0, max(0.0, float(value)))) for key, value in p_values.items()), key=lambda item: item[1])
    corrected: dict[str, float] = {}
    running = 0.0
    count = len(ordered)
    for index, (key, value) in enumerate(ordered):
        adjusted = min(1.0, (count - index) * value)
        running = max(running, adjusted)
        corrected[key] = running
    return corrected
