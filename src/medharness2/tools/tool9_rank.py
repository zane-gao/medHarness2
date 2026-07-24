from __future__ import annotations

import math
from typing import Any

from medharness2.schema import CandidateReport
from medharness2.tools.report_structure import compare_candidate_structures


_PRODUCTION_RANKING_WEIGHTS = {
    "route": 0.40,
    "structure": 0.20,
    "consensus": 0.25,
    "internal_consistency": 0.15,
}
_CONSENSUS_SIGNALS = ("laterality", "anatomy", "measurement", "severity")
_NEUTRAL_SIGNAL_SCORE = 0.5


def select_top_k(
    evaluations: list[dict[str, Any]],
    weights: dict[str, float] | None = None,
    top_k: int = 3,
    *,
    near_cutoff_tolerance: float = 0.01,
) -> list[dict[str, Any]]:
    metric_weights = weights if weights is not None else {"likert_mean": 0.4, "structure_score": 0.3, "finding_coverage": 0.3}
    top_k = _strict_positive_int(top_k, "top_k")
    near_cutoff_tolerance = _strict_nonnegative_float(near_cutoff_tolerance, "near_cutoff_tolerance")
    metric_weights = _strict_weights(metric_weights)
    rows: list[dict[str, Any]] = []
    for index, evaluation in enumerate(evaluations):
        if not _eligible_for_statistics(evaluation):
            continue
        metrics = _numeric_metrics(evaluation)
        if any(key not in metrics for key, weight in metric_weights.items() if weight > 0):
            # A missing metric is not a zero score.  Exclude incomplete
            # candidates rather than silently changing the ranking semantics.
            continue
        score = sum(metric_weights.get(key, 0.0) * metrics.get(key, 0.0) for key in metric_weights)
        total = sum(metric_weights.values()) or 1.0
        score = score / total
        score_interval = _score_interval(evaluation, metric_weights, total, metrics)
        row = {
                "index": index,
                "model": evaluation.get("model"),
                "score": round(score, 4),
                "metrics": metrics,
                "score_ci_lower": None if score_interval is None else round(score_interval[0], 4),
                "score_ci_upper": None if score_interval is None else round(score_interval[1], 4),
                "uncertainty_status": "available" if score_interval is not None else "unavailable",
            }
        if "near_cutoff_review" in evaluation:
            if not isinstance(evaluation["near_cutoff_review"], bool):
                raise ValueError("near_cutoff_review must be a boolean")
            row["near_cutoff_review"] = evaluation["near_cutoff_review"]
        rows.append(row)
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
        if "near_cutoff_review" in row and not isinstance(row["near_cutoff_review"], bool):
            raise ValueError("near_cutoff_review must be a boolean")
        row.setdefault("requires_review", row.get("near_cutoff_review", False))
    return selected


def select_production_top_k(
    candidates: list[CandidateReport],
    *,
    top_k: int = 3,
    ranking_mode: str = "production_reference_free",
) -> list[dict[str, Any]]:
    top_k = _strict_positive_int(top_k, "top_k")
    if ranking_mode not in {
        "production_reference_free",
        "benchmark_reference_free",
        "replay_reference_free",
    }:
        raise ValueError("unsupported reference-free ranking mode")
    eligible = [candidate for candidate in candidates if _production_candidate_eligible(candidate)]
    entity_sets = {candidate.candidate_id: _candidate_entity_set(candidate) for candidate in eligible}
    signal_maps = {
        signal: {
            candidate.candidate_id: _candidate_signal_map(candidate, signal)
            for candidate in eligible
        }
        for signal in _CONSENSUS_SIGNALS
    }
    comparison = compare_candidate_structures(
        {candidate.candidate_id: candidate.structure for candidate in eligible}
    )
    rows: list[dict[str, Any]] = []
    for candidate in eligible:
        route_score = _production_route_score(candidate.route_tier)
        structure_score = _production_structure_score(candidate)
        entity_status_consensus_score = _production_consensus_score(
            candidate.candidate_id,
            entity_sets,
        )
        signal_scores: dict[str, float] = {}
        signal_availability: dict[str, float] = {}
        for signal in _CONSENSUS_SIGNALS:
            signal_score, signal_available = _production_signal_consensus_score(
                candidate.candidate_id,
                signal_maps[signal],
            )
            signal_scores[signal] = signal_score
            signal_availability[signal] = signal_available
        consensus_score = sum(
            [entity_status_consensus_score, *signal_scores.values()]
        ) / (len(signal_scores) + 1)
        comparison_metrics, comparison_reasons = _candidate_comparison_metrics(
            candidate.candidate_id,
            comparison,
        )
        internal_consistency_score = _production_internal_consistency_score(
            candidate,
            int(comparison_metrics["internal_conflict_count"]),
        )
        score = (
            _PRODUCTION_RANKING_WEIGHTS["route"] * route_score
            + _PRODUCTION_RANKING_WEIGHTS["structure"] * structure_score
            + _PRODUCTION_RANKING_WEIGHTS["consensus"] * consensus_score
            + _PRODUCTION_RANKING_WEIGHTS["internal_consistency"]
            * internal_consistency_score
        )
        metrics = {
            "route_score": round(route_score, 4),
            "structure_score": round(structure_score, 4),
            "entity_status_consensus_score": round(entity_status_consensus_score, 4),
            "consensus_score": round(consensus_score, 4),
            "internal_consistency_score": round(internal_consistency_score, 4),
        }
        for signal in _CONSENSUS_SIGNALS:
            metrics[f"{signal}_consensus_score"] = round(signal_scores[signal], 4)
            metrics[f"{signal}_signal_available"] = signal_availability[signal]
        metrics.update(comparison_metrics)
        ranking_reason = [
            f"route_tier={candidate.route_tier}",
            f"component:route={route_score:.4f}",
            f"component:structure={structure_score:.4f}",
            f"component:consensus={consensus_score:.4f}",
            f"component:internal_consistency={internal_consistency_score:.4f}",
        ]
        ranking_reason.extend(
            f"signal_missing:{signal}:neutral"
            for signal in _CONSENSUS_SIGNALS
            if signal_availability[signal] == 0.0
        )
        ranking_reason.extend(comparison_reasons)
        ranking_reason.extend(
            [
                "reference_report_not_used",
                "operational_ranking_not_clinical_quality",
            ]
        )
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "model": candidate.generated.model,
                "source": candidate.generated.source,
                "rank": 0,
                "score": round(score, 4),
                "ranking_mode": ranking_mode,
                "metrics": metrics,
                "ranking_reason": ranking_reason,
            }
        )
    rows.sort(key=lambda item: (-float(item["score"]), str(item["candidate_id"])))
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
        row["selected_top_k"] = index <= top_k
    return rows[:top_k]


def _production_candidate_eligible(candidate: CandidateReport) -> bool:
    if not candidate.generated.report.strip():
        return False
    if candidate.structure.get("structure_status") != "succeeded":
        return False
    quality_gate = candidate.generated.metadata.get("quality_gate") or {}
    return not isinstance(quality_gate, dict) or quality_gate.get("passed") is not False


def _candidate_entity_set(candidate: CandidateReport) -> set[tuple[str, str]]:
    return {
        (str(item.get("entity") or "").strip(), str(item.get("observation_status") or "unknown"))
        for item in candidate.structure.get("entities") or []
        if str(item.get("entity") or "").strip()
    }


def _candidate_signal_map(
    candidate: CandidateReport,
    signal: str,
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for item in candidate.structure.get("entities") or []:
        entity = str(item.get("entity") or "").strip()
        if not entity:
            continue
        values = _candidate_signal_values(item, signal)
        if values:
            result.setdefault(entity, set()).update(values)
    return result


def _candidate_signal_values(item: dict[str, Any], signal: str) -> set[str]:
    if signal == "measurement":
        values: set[str] = set()
        for measurement in item.get("measurements") or []:
            normalized = measurement.get("normalized_mm")
            if normalized is None:
                value = measurement.get("value")
                unit = str(measurement.get("unit") or "").casefold()
                if value is None:
                    continue
                normalized = float(value) * 10.0 if unit == "cm" else value
            try:
                values.add(f"{float(normalized):g}mm")
            except (TypeError, ValueError):
                continue
        return values
    if signal == "anatomy":
        value = item.get("anatomy_code") or item.get("location_text")
    else:
        value = item.get(signal)
    normalized = str(value or "").strip().casefold()
    return set() if normalized in {"", "unknown", "unspecified"} else {normalized}


def _production_route_score(route_tier: str) -> float:
    return {
        "exact_modality_body_part": 1.0,
        "same_modality": 0.75,
        "same_body_part_cross_modality": 0.5,
        "universal": 0.25,
    }.get(route_tier, 0.0)


def _production_structure_score(candidate: CandidateReport) -> float:
    structure = candidate.structure or {}
    if structure.get("structure_status") != "succeeded":
        return 0.0
    return 1.0 if structure.get("spans") else 0.5


def _production_consensus_score(
    candidate_id: str,
    entity_sets: dict[str, set[tuple[str, str]]],
) -> float:
    current = entity_sets.get(candidate_id, set())
    others = [items for other_id, items in entity_sets.items() if other_id != candidate_id]
    if not others:
        return 0.5
    similarities: list[float] = []
    for other in others:
        union = current | other
        similarities.append(1.0 if not union else len(current & other) / len(union))
    return sum(similarities) / len(similarities)


def _production_signal_consensus_score(
    candidate_id: str,
    signal_maps: dict[str, dict[str, set[str]]],
) -> tuple[float, float]:
    current = signal_maps.get(candidate_id, {})
    similarities: list[float] = []
    for other_id, other in signal_maps.items():
        if other_id == candidate_id:
            continue
        for entity in sorted(set(current) & set(other)):
            union = current[entity] | other[entity]
            similarities.append(
                1.0 if not union else len(current[entity] & other[entity]) / len(union)
            )
    if not similarities:
        return _NEUTRAL_SIGNAL_SCORE, 0.0
    return sum(similarities) / len(similarities), 1.0


def _production_internal_consistency_score(
    candidate: CandidateReport,
    internal_conflict_count: int,
) -> float:
    entities = {
        str(item.get("entity") or "").strip()
        for item in candidate.structure.get("entities") or []
        if str(item.get("entity") or "").strip()
    }
    if not entities:
        return _NEUTRAL_SIGNAL_SCORE
    return max(0.0, 1.0 - internal_conflict_count / len(entities))


def _candidate_comparison_metrics(
    candidate_id: str,
    comparison: dict[str, Any],
) -> tuple[dict[str, float], list[str]]:
    conflict_types = (
        "observation_status",
        "laterality",
        "anatomy",
        "measurement",
        "severity",
    )
    metrics = {f"{conflict_type}_conflict_count": 0.0 for conflict_type in conflict_types}
    reasons: list[str] = []
    for conflict in comparison.get("conflicts") or []:
        conflict_type = str(conflict.get("comparison_type") or "")
        if candidate_id not in set(conflict.get("candidate_ids") or []):
            continue
        metric_key = f"{conflict_type}_conflict_count"
        if metric_key in metrics:
            metrics[metric_key] += 1.0
        reasons.append(f"conflict:{conflict_type}:{conflict.get('entity')}")
    omission_count = 0.0
    for omission in comparison.get("omissions") or []:
        if candidate_id in set(omission.get("missing_candidate_ids") or []):
            omission_count += 1.0
            reasons.append(f"omission:{omission.get('entity')}")
    internal_conflict_count = 0.0
    for conflict in comparison.get("internal_conflicts") or []:
        if candidate_id in set(conflict.get("candidate_ids") or []):
            internal_conflict_count += 1.0
            reasons.append(
                "internal_conflict:"
                f"{conflict.get('comparison_type')}:{conflict.get('entity')}"
            )
    metrics["omission_count"] = omission_count
    metrics["internal_conflict_count"] = internal_conflict_count
    return metrics, reasons


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
        if lower is not None and upper is not None and lower <= upper and 0.0 <= lower <= upper <= 1.0:
            return lower, upper
    bounds: list[tuple[float, float, float]] = []
    for metric, weight in metric_weights.items():
        if weight <= 0 or metric not in metrics:
            continue
        lower = _metric_interval_bound(metric, payload.get(f"{metric}_ci_lower"))
        upper = _metric_interval_bound(metric, payload.get(f"{metric}_ci_upper"))
        if lower is None or upper is None or lower > upper:
            return None
        bounds.append((lower, upper, weight))
    if not bounds:
        return None
    lower = sum(item[0] * item[2] for item in bounds) / total_weight
    upper = sum(item[1] * item[2] for item in bounds) / total_weight
    return lower, upper


def _metric_interval_bound(metric: str, value: Any) -> float | None:
    """Normalize an uncertainty bound with the same scale as its metric."""
    number = _finite_or_none(value)
    if number is None:
        return None
    if metric == "likert_mean":
        if not 1.0 <= number <= 5.0:
            return None
        return (number - 1.0) / 4.0
    if not 0.0 <= number <= 1.0:
        return None
    return number


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _strict_positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _strict_nonnegative_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite non-negative number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} must be a finite non-negative number")
    return number


def _strict_weights(value: Any) -> dict[str, float]:
    if not isinstance(value, dict) or not value:
        raise ValueError("weights must be a non-empty mapping")
    result: dict[str, float] = {}
    for key, weight in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("weights keys must be non-empty strings")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise ValueError("weights values must be finite numbers")
        number = float(weight)
        if not math.isfinite(number) or number < 0:
            raise ValueError("weights values must be finite non-negative numbers")
        result[key] = number
    if not any(number > 0 for number in result.values()):
        raise ValueError("weights must contain a positive value")
    return result


def _intervals_overlap(left: tuple[float, float], right: tuple[float, float]) -> bool:
    return left[0] <= right[1] and right[0] <= left[1]


def _numeric_metrics(evaluation: dict[str, Any]) -> dict[str, float]:
    if not isinstance(evaluation, dict):
        raise ValueError("ranking evaluation must be an object")
    if "composite_inputs" in evaluation:
        raw_values = evaluation.get("composite_inputs")
        if raw_values is None:
            values = {}
        elif not isinstance(raw_values, dict):
            raise ValueError("composite_inputs must be an object")
        else:
            values = dict(raw_values)
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
    if not isinstance(evaluation, dict) or not _valid_provenance_shape(evaluation):
        return False
    metadata = evaluation.get("metadata") or evaluation.get("provenance") or {}
    fallback_used = metadata.get("fallback_used")
    if fallback_used is not None and not isinstance(fallback_used, bool):
        return False
    evidence_tier = str(evaluation.get("evidence_tier") or "").lower()
    source = str(evaluation.get("source") or "").lower()
    if fallback_used is True and evidence_tier != "exploratory_fresh":
        return False
    if evidence_tier in {"debug_fallback", "mock"}:
        return False
    if source in {"local_vlm_fallback", "mock", "fallback", "mock_fallback", "mock_judge"}:
        return False
    return True


def _valid_provenance_shape(evaluation: dict[str, Any]) -> bool:
    return all(
        field not in evaluation or evaluation[field] is None or isinstance(evaluation[field], dict)
        for field in ("metadata", "provenance")
    )
