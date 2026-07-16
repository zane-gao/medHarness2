from __future__ import annotations

from pathlib import Path
from typing import Any

from medharness2.tools.tool12_statistics import calculate_statistics, percentile_rank
from medharness2.utils.io import read_json, write_json


def run_department_comparison(batch_result_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    batch = read_json(batch_result_path)
    per_reader = dict(batch.get("per_reader") or {})
    reader_scores: dict[str, float] = {}
    excluded_readers: dict[str, str] = {}
    for reader, payload in per_reader.items():
        raw_score = payload.get("overall_score")
        if raw_score is None or isinstance(raw_score, bool):
            excluded_readers[reader] = "missing_overall_score"
            continue
        try:
            reader_scores[reader] = float(raw_score)
        except (TypeError, ValueError):
            excluded_readers[reader] = "invalid_overall_score"
    population = list(reader_scores.values())
    reader_percentiles = {
        reader: {
            "overall_score": score,
            "percentile": percentile_rank(score, population),
            "case_count": per_reader[reader].get("case_count", 0),
        }
        for reader, score in reader_scores.items()
    }
    model_group_rows = [case.get("modelwise_metrics") or {} for case in batch.get("cases") or [] if case.get("modelwise_metrics")]
    denominator = dict(batch.get("denominator") or {})
    source_case_count = int(
        _first_present(
            denominator.get("manifest_case_count"),
            denominator.get("source_case_count"),
            batch.get("case_count", 0),
        )
    )
    successful_case_count = int(
        _first_present(denominator.get("successful_case_count"), batch.get("case_count", 0))
    )
    failed_case_count = int(
        _first_present(denominator.get("failed_case_count"), batch.get("failed_case_count", 0))
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
        "case_count": int(batch.get("case_count", 0)),
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
    write_json(output_path, result)
    return result


def _first_present(*values: Any) -> Any:
    """Return the first non-None value, preserving explicit zeroes."""
    for value in values:
        if value is not None:
            return value
    return 0
