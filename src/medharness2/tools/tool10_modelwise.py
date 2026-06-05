from __future__ import annotations

from typing import Any


def modelwise_weighted(rows: list[dict[str, Any]], weights: dict[str, float] | None = None) -> dict[str, float]:
    weighted: dict[str, float] = {}
    totals: dict[str, float] = {}
    for index, row in enumerate(rows):
        model = str(row.get("model") or row.get("model_key") or index)
        weight = float((weights or {}).get(model, (weights or {}).get(str(index), 1.0)))
        metrics = _numeric_metrics(row.get("metrics") or row.get("composite_inputs") or row)
        for key, value in metrics.items():
            weighted[key] = weighted.get(key, 0.0) + value * weight
            totals[key] = totals.get(key, 0.0) + weight
    result = {key: round(value / totals[key], 6) for key, value in weighted.items() if totals.get(key, 0.0) > 0}
    result["model_count"] = len(rows)
    return result


def _numeric_metrics(payload: dict[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in payload.items():
        if key in {"model", "model_key", "source", "warnings", "metadata"}:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            result[key] = float(value)
    return result
