from __future__ import annotations

import math
from typing import Any


def modelwise_weighted(rows: list[dict[str, Any]], weights: dict[str, float] | None = None) -> dict[str, Any]:
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
        weight = float((weights or {}).get(model, (weights or {}).get(str(index), 1.0)))
        metrics = _numeric_metrics(row.get("metrics") or row.get("composite_inputs") or row)
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


def _numeric_metrics(payload: dict[str, Any]) -> dict[str, float]:
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
    if bool(metadata.get("fallback_used")):
        return False
    if str(row.get("evidence_tier") or "").lower() in {"debug_fallback", "mock"}:
        return False
    return str(row.get("source") or "").lower() not in {"local_vlm_fallback", "mock", "fallback", "mock_fallback", "mock_judge"}
