from __future__ import annotations

import math
from typing import Any


def select_top_k(
    evaluations: list[dict[str, Any]],
    weights: dict[str, float] | None = None,
    top_k: int = 3,
    *,
    near_cutoff_tolerance: float = 0.01,
) -> list[dict[str, Any]]:
    metric_weights = weights or {"likert_mean": 0.4, "structure_score": 0.3, "finding_coverage": 0.3}
    rows: list[dict[str, Any]] = []
    for index, evaluation in enumerate(evaluations):
        if not _eligible_for_statistics(evaluation):
            continue
        metrics = _numeric_metrics(evaluation)
        if any(key not in metrics for key, weight in metric_weights.items() if float(weight) > 0):
            # A missing metric is not a zero score.  Exclude incomplete
            # candidates rather than silently changing the ranking semantics.
            continue
        score = sum(metric_weights.get(key, 0.0) * metrics.get(key, 0.0) for key in metric_weights)
        total = sum(metric_weights.values()) or 1.0
        score = score / total
        score_interval = _score_interval(evaluation, metric_weights, total, metrics)
        rows.append(
            {
                "index": index,
                "model": evaluation.get("model"),
                "score": round(score, 4),
                "metrics": metrics,
                "score_ci_lower": None if score_interval is None else round(score_interval[0], 4),
                "score_ci_upper": None if score_interval is None else round(score_interval[1], 4),
                "uncertainty_status": "available" if score_interval is not None else "unavailable",
            }
        )
    ranked = sorted(rows, key=lambda row: row["score"], reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank
        row["selected_top_n"] = rank <= top_k
    selected = ranked[:top_k]
    if selected and top_k < len(ranked):
        cutoff = selected[-1]["score"]
        selected = [row for row in ranked if cutoff - row["score"] <= near_cutoff_tolerance]
        for row in selected:
            row["near_cutoff"] = True
            row["near_cutoff_review"] = not row["selected_top_n"]
            row["near_cutoff_tolerance"] = near_cutoff_tolerance
        cutoff_row = ranked[top_k - 1]
        if cutoff_row["score_ci_lower"] is not None:
            cutoff_interval = (cutoff_row["score_ci_lower"], cutoff_row["score_ci_upper"])
            for row in ranked:
                if row["score_ci_lower"] is None:
                    continue
                if _intervals_overlap((row["score_ci_lower"], row["score_ci_upper"]), cutoff_interval):
                    if row not in selected:
                        selected.append(row)
                    row["uncertainty_overlap"] = True
                    row["requires_review"] = True
            selected.sort(key=lambda row: row["score"], reverse=True)
    for row in selected:
        row.setdefault("uncertainty_overlap", False)
        row.setdefault("requires_review", bool(row.get("near_cutoff_review", False)))
    return selected


def _score_interval(
    evaluation: dict[str, Any],
    metric_weights: dict[str, float],
    total_weight: float,
    metrics: dict[str, float],
) -> tuple[float, float] | None:
    """Return a score interval without fabricating uncertainty.

    A pre-computed score CI takes precedence. Otherwise metric-level CIs are
    combined using the ranking weights. Missing or malformed bounds make the
    interval unavailable rather than silently treating them as zero.
    """
    payload = dict(evaluation.get("composite_inputs") or {})
    payload.update({key: value for key, value in evaluation.items() if key not in payload})
    for lower_key, upper_key in (("score_ci_lower", "score_ci_upper"), ("ci_lower", "ci_upper")):
        lower = _finite_or_none(payload.get(lower_key))
        upper = _finite_or_none(payload.get(upper_key))
        if lower is not None and upper is not None and lower <= upper:
            return max(0.0, lower), min(1.0, upper)
    bounds: list[tuple[float, float, float]] = []
    for metric, weight in metric_weights.items():
        if float(weight) <= 0 or metric not in metrics:
            continue
        lower = _finite_or_none(payload.get(f"{metric}_ci_lower"))
        upper = _finite_or_none(payload.get(f"{metric}_ci_upper"))
        if lower is None or upper is None or lower > upper:
            return None
        bounds.append((lower, upper, float(weight)))
    if not bounds:
        return None
    lower = sum(item[0] * item[2] for item in bounds) / total_weight
    upper = sum(item[1] * item[2] for item in bounds) / total_weight
    return max(0.0, lower), min(1.0, upper)


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _intervals_overlap(left: tuple[float, float], right: tuple[float, float]) -> bool:
    return left[0] <= right[1] and right[0] <= left[1]


def _numeric_metrics(evaluation: dict[str, Any]) -> dict[str, float]:
    if "composite_inputs" in evaluation:
        values = dict(evaluation.get("composite_inputs") or {})
    else:
        values = dict(evaluation)
    metrics: dict[str, float] = {}
    if values.get("likert_mean") is not None:
        parsed = _likert01_or_none(values.get("likert_mean"))
        if parsed is not None:
            metrics["likert_mean"] = parsed
    if values.get("structure_score") is not None:
        parsed = _clamp01_or_none(values.get("structure_score"))
        if parsed is not None:
            metrics["structure_score"] = parsed
    if values.get("finding_coverage") is not None:
        parsed = _clamp01_or_none(values.get("finding_coverage"))
        if parsed is not None:
            metrics["finding_coverage"] = parsed
    return metrics


def _clamp01(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(0.0, min(1.0, number))


def _clamp01_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return max(0.0, min(1.0, number))


def _likert01(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    if 0.0 <= number < 1.0:
        return _clamp01(number)
    return _clamp01((number - 1.0) / 4.0)


def _likert01_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if 0.0 <= number < 1.0:
        return max(0.0, min(1.0, number))
    return max(0.0, min(1.0, (number - 1.0) / 4.0))


def _eligible_for_statistics(evaluation: dict[str, Any]) -> bool:
    metadata = evaluation.get("metadata") or evaluation.get("provenance") or {}
    if bool(metadata.get("fallback_used")):
        return False
    if str(evaluation.get("evidence_tier") or "").lower() in {"debug_fallback", "mock"}:
        return False
    if str(evaluation.get("source") or "").lower() in {"local_vlm_fallback", "mock", "fallback", "mock_fallback", "mock_judge"}:
        return False
    return True
