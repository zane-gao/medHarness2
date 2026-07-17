from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from medharness2.tools.tool12_statistics import calculate_statistics, percentile_rank
from medharness2.utils.io import read_json, write_json


def _nonnegative_count(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def run_department_comparison(batch_result_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    batch = read_json(batch_result_path)
    per_reader = _strict_object(batch.get("per_reader"), "per_reader")
    reader_scores: dict[str, float] = {}
    excluded_readers: dict[str, str] = {}
    for reader, payload in per_reader.items():
        if not isinstance(payload, dict):
            raise ValueError(f"per_reader.{reader} must be an object")
        raw_score = payload.get("overall_score")
        if raw_score is None or isinstance(raw_score, bool):
            excluded_readers[reader] = "missing_overall_score"
            continue
        try:
            score = float(raw_score)
            if not math.isfinite(score):
                raise ValueError("non_finite_overall_score")
            reader_scores[reader] = score
        except (TypeError, ValueError):
            excluded_readers[reader] = "non_finite_overall_score" if str(raw_score).lower() in {"nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"} else "invalid_overall_score"
    population = list(reader_scores.values())
    reader_percentiles = {
        reader: {
            "overall_score": score,
            "percentile": percentile_rank(score, population),
            "case_count": per_reader[reader].get("case_count", 0),
        }
        for reader, score in reader_scores.items()
    }
    cases = batch.get("cases") or []
    if not isinstance(cases, list) or any(not isinstance(case, dict) for case in cases):
        raise ValueError("cases must be a list of objects")
    model_group_rows: list[dict[str, Any]] = []
    for case in cases:
        metrics = case.get("modelwise_metrics")
        if metrics is None:
            continue
        if not isinstance(metrics, dict):
            raise ValueError("cases.modelwise_metrics must be an object")
        model_group_rows.append(dict(metrics))
    denominator = _strict_object(batch.get("denominator"), "denominator")
    source_case_count = _nonnegative_count(
        _first_present(
            denominator.get("manifest_case_count"),
            denominator.get("source_case_count"),
            batch.get("case_count", 0),
        ),
        "source_case_count",
    )
    successful_case_count = _nonnegative_count(
        _first_present(denominator.get("successful_case_count"), batch.get("case_count", 0)),
        "successful_case_count",
    )
    failed_case_count = _nonnegative_count(
        _first_present(denominator.get("failed_case_count"), batch.get("failed_case_count", 0)),
        "failed_case_count",
    )
    denominator.update(
        {
            "source_case_count": source_case_count,
            "successful_case_count": successful_case_count,
            "failed_case_count": failed_case_count,
            "success_rate": round(successful_case_count / max(source_case_count, 1), 4),
            "failure_rate": round(failed_case_count / max(source_case_count, 1), 4),
        }
    )
    result = {
        "batch_result_path": str(batch_result_path),
        "reader_total_count": len(per_reader),
        "reader_count": len(reader_scores),
        "excluded_reader_count": len(excluded_readers),
        "case_count": _nonnegative_count(batch.get("case_count", 0), "case_count"),
        "failed_case_count": failed_case_count,
        "denominator": denominator,
        "statistics": {
            "readers": calculate_statistics([{"overall_score": score} for score in population]),
            "model_group": calculate_statistics(model_group_rows),
        },
        "reader_percentiles": reader_percentiles,
        "comparisons": {
            "doctor_group": {"scores": reader_scores},
            "excluded_readers": excluded_readers,
            "model_group": {"case_metric_count": len(model_group_rows)},
        },
    }
    if _nonnegative_count(batch.get("case_count", 0), "case_count") == 0 and _nonnegative_count(batch.get("failed_case_count", 0), "failed_case_count") == 0:
        result["errors"] = ["no_cases_discovered"]
    write_json(output_path, result)
    return result


def _first_present(*values: Any) -> Any:
    """Return the first non-None value, preserving explicit zeroes."""
    for value in values:
        if value is not None:
            return value
    return 0


def _strict_object(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return dict(value)
