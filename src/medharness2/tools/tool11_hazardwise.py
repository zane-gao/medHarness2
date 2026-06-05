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
        item = dict(row)
        error_type = str(item.get("error_type") or "unknown")
        level = str(int(float(item.get("hazard_level") or 1)))
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


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
