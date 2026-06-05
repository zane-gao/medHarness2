from __future__ import annotations

import math
import statistics
from typing import Any


def calculate_statistics(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    values_by_key: dict[str, list[float]] = {}
    for row in rows:
        for key, value in _numeric_metrics(row).items():
            values_by_key.setdefault(key, []).append(value)
    result: dict[str, dict[str, float]] = {}
    for key, values in values_by_key.items():
        mean = statistics.mean(values)
        std = statistics.stdev(values) if len(values) > 1 else 0.0
        ci = 1.96 * std / math.sqrt(len(values)) if values else 0.0
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
    at_or_below = sum(1 for item in population if item <= value)
    return round(100.0 * at_or_below / len(population), 6)


def _numeric_metrics(row: dict[str, Any]) -> dict[str, float]:
    payload = row.get("metrics") or row.get("composite_inputs") or row
    return {
        key: float(value)
        for key, value in payload.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
