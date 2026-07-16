from __future__ import annotations

from typing import Any


DEFAULT_HAZARD_WEIGHTS = {
    "false_finding": {"1": 1.0, "2": 1.25, "3": 1.5, "4": 2.0, "5": 2.5},
    "omission_finding": {"1": 1.0, "2": 1.5, "3": 2.0, "4": 2.5, "5": 3.0},
    "incorrect_location": {"1": 1.0, "2": 1.25, "3": 1.5, "4": 2.0, "5": 2.5},
    "incorrect_severity": {"1": 1.0, "2": 1.25, "3": 1.5, "4": 2.0, "5": 2.5},
}


def hazardwise_weighted(
    rows: list[dict[str, Any]],
    hazard_weights: dict[str, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    weights = hazard_weights or DEFAULT_HAZARD_WEIGHTS
    result: list[dict[str, Any]] = []
    for row in rows:
        if not _eligible(row):
            continue
        item = dict(row)
        error_type = str(item.get("error_type") or "").strip()
        level_value = item.get("hazard_level")
        if not error_type or level_value is None or isinstance(level_value, bool):
            continue
        try:
            level_number = int(float(level_value))
        except (TypeError, ValueError):
            continue
        if level_number < 1 or level_number > 5:
            continue
        level = str(level_number)
        weight = float(weights.get(error_type, {}).get(level, 1.0))
        metrics = dict(item.get("metrics") or {})
        if metrics:
            item["metrics"] = {key: (value * weight if _is_number(value) else value) for key, value in metrics.items()}
        else:
            for key, value in list(item.items()):
                if key not in {"hazard_level", "hazard_weight"} and _is_number(value):
                    item[key] = value * weight
        item["hazard_weight"] = weight
        result.append(item)
    return result


def _eligible(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata") or row.get("provenance") or {}
    if bool(metadata.get("fallback_used")):
        return False
    if str(row.get("evidence_tier") or "").lower() in {"mock", "debug_fallback"}:
        return False
    return str(row.get("source") or "").lower() not in {
        "mock",
        "mock_fallback",
        "fallback",
        "local_vlm_fallback",
    }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
