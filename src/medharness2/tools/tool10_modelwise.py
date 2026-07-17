from __future__ import annotations

import math
from typing import Any


def modelwise_weighted(rows: list[dict[str, Any]], weights: dict[str, float] | None = None) -> dict[str, Any]:
    normalized_weights = _strict_weights(weights)
    weighted: dict[str, float] = {}
    totals: dict[str, float] = {}
    eligible_count = 0
    fallback_count = 0
    for index, row in enumerate(rows):
        if not _eligible(row):
            fallback_count += 1
            continue
        eligible_count += 1
        model = str(row.get("model") or row.get("model_key") or index)
        weight = normalized_weights.get(model, normalized_weights.get(str(index), 1.0))
        metrics = _numeric_metrics(row)
        for key, value in metrics.items():
            weighted[key] = weighted.get(key, 0.0) + value * weight
            totals[key] = totals.get(key, 0.0) + weight
    result = {key: round(value / totals[key], 6) for key, value in weighted.items() if totals.get(key, 0.0) > 0}
    result["_provenance"] = {
        "eligible_count": eligible_count,
        "fallback_count": fallback_count,
        "input_count": len(rows),
    }
    return result


def _numeric_metrics(row: dict[str, Any]) -> dict[str, float]:
    if not isinstance(row, dict):
        raise ValueError("modelwise row must be an object")
    if "metrics" in row and row["metrics"] is not None:
        payload = row["metrics"]
        label = "metrics"
    elif "composite_inputs" in row and row["composite_inputs"] is not None:
        payload = row["composite_inputs"]
        label = "composite_inputs"
    else:
        payload = row
        label = "row"
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object")
    result: dict[str, float] = {}
    for key, value in payload.items():
        if key in {"model", "model_key", "source", "warnings", "metadata", "provenance", "evidence_tier"}:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            number = float(value)
            if math.isfinite(number):
                result[key] = number
    return result


def _eligible(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata") or row.get("provenance") or {}
    fallback_used = metadata.get("fallback_used")
    if fallback_used is not None and not isinstance(fallback_used, bool):
        return False
    if fallback_used is True:
        return False
    if str(row.get("evidence_tier") or "").lower() in {"debug_fallback", "mock"}:
        return False
    return str(row.get("source") or "").lower() not in {"local_vlm_fallback", "mock", "fallback", "mock_fallback", "mock_judge"}


def _strict_weights(value: dict[str, float] | None) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("weights must be a mapping")
    result: dict[str, float] = {}
    for key, weight in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("weights keys must be non-empty strings")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise ValueError("weights values must be finite non-negative numbers")
        number = float(weight)
        if not math.isfinite(number) or number < 0:
            raise ValueError("weights values must be finite non-negative numbers")
        result[key] = number
    return result
