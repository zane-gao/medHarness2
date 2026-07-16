from __future__ import annotations

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
        rows.append(
            {
                "index": index,
                "model": evaluation.get("model"),
                "score": round(score / total, 4),
                "metrics": metrics,
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
    return selected


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
    return max(0.0, min(1.0, number))


def _clamp01_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, number))


def _likert01(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if 0.0 <= number < 1.0:
        return _clamp01(number)
    return _clamp01((number - 1.0) / 4.0)


def _likert01_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
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
