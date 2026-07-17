from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.llm_client import LLMClient, LLMClientError
from medharness2.tools.tool1_likert import LIKERT_METRICS
from medharness2.tools.tool12_statistics import calculate_statistics
from medharness2.utils.io import parse_json_object, read_json, write_json


ACTIONABLE_ERRORS = {"omission_finding", "incorrect_location", "incorrect_severity", "false_finding"}


def _count_or_zero(value: Any, label: str) -> int:
    if value is None:
        return 0
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def run_education_suggestions(
    *,
    eval_report: str | Path | None = None,
    eval_radiologist: str | Path | None = None,
    output_path: str | Path,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    if bool(eval_report) == bool(eval_radiologist):
        raise ValueError("Provide exactly one of eval_report or eval_radiologist.")
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    if eval_report:
        payload = read_json(eval_report)
        result = _report_suggestions(payload, client)
    else:
        payload = read_json(eval_radiologist)  # type: ignore[arg-type]
        result = _radiologist_suggestions(payload, client)
    write_json(output_path, result)
    return result


def _report_suggestions(payload: dict[str, Any], client: LLMClient) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Workflow 1 result must be an object")
    human = _object(payload.get("human_evaluation"), "human_evaluation")
    likert = _object(human.get("likert"), "human_evaluation.likert")
    graph = _object(human.get("finding_graph"), "human_evaluation.finding_graph")
    findings = _object_list(graph.get("findings"), "human_evaluation.finding_graph.findings")
    if not findings:
        raise ValueError("Workflow 1 result must contain human_evaluation.finding_graph.findings.")
    weakest_metric, weakest_score = _weakest_likert(likert)
    overall_score = _overall_likert(likert)
    if weakest_metric is None or weakest_score is None or overall_score is None:
        return _blocked_report_result("missing_likert_statistics")
    hazards = _hazards(payload)
    targeted_ids = _target_finding_ids(findings, hazards)
    default = {
        "mode": "eval_report",
        "status": "suggestions_generated",
        "report_summary": {
            "overall_score": overall_score,
            "weakest_metric": weakest_metric,
            "weakest_score": weakest_score,
            "peer_gap": None,
        },
        "suggestions": [
            _finding_suggestion(finding, weakest_metric, weakest_score, hazards)
            for finding in findings
            if _finding_id(finding).lower() in targeted_ids
        ],
        "general_suggestions": [_general_suggestion(weakest_metric, weakest_score, likert)],
        "metadata": {
            "source": "deterministic_or_llm",
            "top_models": [
                item.get("model")
                for item in _object_list(payload.get("rankings"), "rankings")
                if item.get("selected_top_n")
            ],
        },
    }
    return _try_llm_json(client, _report_prompt(payload, default), default)


def _radiologist_suggestions(payload: dict[str, Any], client: LLMClient) -> dict[str, Any]:
    readers = payload.get("per_reader")
    if readers is None:
        readers = {}
    if not isinstance(readers, dict):
        raise ValueError("per_reader must be an object")
    if not readers:
        raise ValueError("Workflow 2 result must contain per_reader.")
    for reader_id, reader in readers.items():
        if not isinstance(reader_id, str) or not isinstance(reader, dict):
            raise ValueError(f"per_reader.{reader_id} must be an object")
    reader_id, reader = sorted(readers.items(), key=lambda item: str(item[0]))[0]
    effective_stats = {
        str(identifier): _effective_reader_statistics(payload, str(identifier), item)
        for identifier, item in readers.items()
    }
    peer_means = _peer_means(effective_stats, exclude=str(reader_id))
    stats = effective_stats[str(reader_id)]
    if not stats:
        return _blocked_radiologist_result(str(reader_id), _count_or_zero(reader.get("case_count"), "case_count"), "missing_reader_statistics")
    weakest = _weak_reader_metrics(stats, peer_means) if peer_means else []
    peer_baseline_available = bool(peer_means)
    if not weakest:
        weakest = _weakest_available_metrics(stats)
    if not weakest:
        return _blocked_radiologist_result(str(reader_id), _count_or_zero(reader.get("case_count"), "case_count"), "no_comparable_metrics")
    default = {
        "mode": "eval_radiologist",
        "status": "suggestions_generated",
        "radiologist_summary": {
            "radiologist_id": str(reader_id),
            "n_reports": _count_or_zero(reader.get("case_count"), "case_count"),
            "weakest_metrics": weakest,
            "peer_gaps": {
                metric: round(float(stats[metric]["mean"]) - float(peer_means[metric]), 4)
                if metric in peer_means
                else None
                for metric in weakest
            },
        },
        "suggestions": [
            {
                "metric": metric,
                "pattern": f"{metric} is below the peer baseline.",
                "peer_comparison": (
                    f"Reader mean={_stat_mean(stats, metric):.2f}; peer mean={peer_means[metric]:.2f}."
                    if metric in peer_means
                    else "Peer baseline unavailable; this suggestion is based on the reader's own statistics."
                ),
                "suggestion": _metric_guidance(metric),
                "reasoning": "Suggestion is derived from reader-level metric aggregates and peer gap.",
            }
            for metric in weakest
        ],
        "metadata": {
            "source": "deterministic_or_llm",
            "peer_baseline_available": peer_baseline_available,
            "limitations": [] if peer_baseline_available else ["missing_peer_statistics"],
        },
    }
    return _try_llm_json(client, _radiologist_prompt(payload, default), default)


def _blocked_radiologist_result(reader_id: str, case_count: int, reason: str) -> dict[str, Any]:
    return {
        "mode": "eval_radiologist",
        "status": "blocked_insufficient_data",
        "radiologist_summary": {
            "radiologist_id": reader_id,
            "n_reports": case_count,
            "weakest_metrics": [],
            "peer_gaps": {},
        },
        "suggestions": [],
        "metadata": {"source": "insufficient_data", "fallback_used": False, "blocked_reasons": [reason]},
    }


def _try_llm_json(client: LLMClient, prompt: str, default: dict[str, Any]) -> dict[str, Any]:
    try:
        raw = client.call(
            prompt,
            response_format="json",
            response_json=default,
            temperature=0.3,
            payload_classification="deidentified_structured",
        )
        parsed = parse_json_object(raw, context="Workflow 4 education")
        _validate_education_output_shape(parsed, default)
    except (ValueError, LLMClientError, RuntimeError):
        fallback = dict(default)
        metadata = dict(fallback.get("metadata") or {})
        metadata.update({"source": "deterministic_fallback", "fallback_used": True})
        fallback["metadata"] = metadata
        return fallback
    merged = _merge_required(default, parsed)
    metadata = dict(merged.get("metadata") or {})
    provider = str(getattr(getattr(client, "config", None), "llm", None) and getattr(client.config.llm, "provider", "") or "").lower()
    if provider == "mock":
        metadata.update({"source": "mock_judge", "fallback_used": True})
    else:
        metadata.update({"source": "llm_judge", "fallback_used": False})
    merged["metadata"] = metadata
    return merged


def _merge_required(default: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    merged = dict(default)
    for key, value in parsed.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


def _validate_education_output_shape(parsed: dict[str, Any], default: dict[str, Any]) -> None:
    if "metadata" in parsed and not isinstance(parsed["metadata"], dict):
        raise ValueError("education.metadata must be an object")
    mode = default.get("mode")
    object_fields = ["report_summary"] if mode == "eval_report" else ["radiologist_summary"]
    for field in object_fields:
        if field in parsed and not isinstance(parsed[field], dict):
            raise ValueError(f"education.{field} must be an object")
    for field in ("suggestions", "general_suggestions"):
        if field not in parsed:
            continue
        value = parsed[field]
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise ValueError(f"education.{field} must be a list of objects")


def _weakest_likert(likert: dict[str, Any]) -> tuple[str | None, int | None]:
    valid: list[tuple[str, int]] = []
    for metric in LIKERT_METRICS:
        item = likert.get(metric) or {}
        try:
            score = _strict_likert_score(item.get("score"))
        except (TypeError, ValueError):
            continue
        if 1 <= score <= 5:
            valid.append((metric, score))
    return min(valid, key=lambda item: item[1]) if valid else (None, None)


def _overall_likert(likert: dict[str, Any]) -> float | None:
    scores = []
    for metric in LIKERT_METRICS:
        try:
            score = _strict_likert_score((likert.get(metric) or {}).get("score"))
            scores.append(float(score))
        except (TypeError, ValueError):
            continue
    return round(sum(scores) / len(scores), 4) if scores else None


def _strict_likert_score(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean Likert score")
    if isinstance(value, int):
        score = value
    elif isinstance(value, str) and value.strip().lstrip("+-").isdigit():
        score = int(value.strip())
    else:
        raise ValueError("Likert score must be an integer")
    if not 1 <= score <= 5:
        raise ValueError("Likert score out of range")
    return score


def _blocked_report_result(reason: str) -> dict[str, Any]:
    return {
        "mode": "eval_report",
        "status": "blocked_insufficient_data",
        "report_summary": {
            "overall_score": None,
            "weakest_metric": None,
            "weakest_score": None,
            "peer_gap": None,
        },
        "suggestions": [],
        "general_suggestions": [],
        "metadata": {"source": "insufficient_data", "fallback_used": False, "blocked_reasons": [reason]},
    }


def _hazards(payload: dict[str, Any]) -> list[dict[str, Any]]:
    hazards: list[dict[str, Any]] = []
    for item in _object_list(payload.get("pairwise_comparisons"), "pairwise_comparisons"):
        comparison = _object(item.get("comparison"), "pairwise_comparisons.comparison")
        hazard_payload = _object(comparison.get("hazards"), "pairwise_comparisons.comparison.hazards")
        hazards.extend(_object_list(hazard_payload.get("errors"), "hazards.errors"))
        alignment = _object(comparison.get("alignment"), "pairwise_comparisons.comparison.alignment")
        hazards.extend(_object_list(alignment.get("error_candidates"), "alignment.error_candidates"))
    return hazards


def _object(value: Any, label: str) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _object_list(value: Any, label: str) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be a list of objects")
    return list(value)


def _target_finding_ids(findings: list[dict[str, Any]], hazards: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for error in hazards:
        if str(error.get("error_type") or "") not in ACTIONABLE_ERRORS:
            continue
        for key in ("finding", "candidate", "reference", "a", "b"):
            finding = error.get(key) or {}
            if isinstance(finding, dict) and _finding_id(finding):
                ids.add(_finding_id(finding).lower())
    if not ids and findings:
        ids.add((_finding_id(findings[0]) or "f1").lower())
    return ids


def _finding_suggestion(
    finding: dict[str, Any],
    weakest_metric: str,
    weakest_score: int,
    hazards: list[dict[str, Any]],
) -> dict[str, Any]:
    finding_id = _finding_id(finding) or "f1"
    text = _finding_text(finding)
    issue = _first_hazard_for_finding(finding_id, hazards)
    return {
        "finding_id": finding_id,
        "metric": weakest_metric,
        "metric_score": weakest_score,
        "current_text": text,
        "suggestion": _metric_guidance(weakest_metric),
        "reasoning": issue or "Finding was selected because it is tied to the weakest report metric.",
    }


def _first_hazard_for_finding(finding_id: str, hazards: list[dict[str, Any]]) -> str:
    target = finding_id.lower()
    for error in hazards:
        for key in ("finding", "candidate", "reference", "a", "b"):
            finding = error.get(key) or {}
            if isinstance(finding, dict) and _finding_id(finding).lower() == target:
                return str(error.get("explanation") or f"Actionable error: {error.get('error_type')}")
    return ""


def _general_suggestion(metric: str, score: int, likert: dict[str, Any]) -> dict[str, Any]:
    explanation = str((likert.get(metric) or {}).get("explanation") or "")
    return {
        "metric": metric,
        "issue": explanation or f"{metric} received the lowest score ({score}).",
        "suggestion": _metric_guidance(metric),
        "reasoning": "General suggestion targets the weakest Likert dimension.",
    }


def _metric_guidance(metric: str) -> str:
    guidance = {
        "Completeness and Accuracy": "Add missing clinically relevant findings and state pertinent negatives explicitly.",
        "Conciseness and Clarity": "Remove redundant wording and keep each sentence focused on one clinical point.",
        "Terminological Accuracy": "Use standard radiology terms, including anatomy, laterality, severity, and measurements.",
        "Structure and Style": "Use consistent FINDINGS and IMPRESSION sections with aligned content.",
        "Overall Writing Quality": "Prioritize clinically actionable wording and clear impression synthesis.",
    }
    return guidance.get(metric, "Revise the report so the clinical finding, evidence, and impression are explicit.")


def _effective_reader_statistics(payload: dict[str, Any], reader_id: str, reader: dict[str, Any]) -> dict[str, Any]:
    existing = reader.get("human_statistics")
    if existing is None:
        existing = {}
    if not isinstance(existing, dict):
        raise ValueError(f"per_reader.{reader_id}.human_statistics must be an object")
    if existing:
        return dict(existing)
    raw_cases = payload.get("cases") or []
    if not isinstance(raw_cases, list) or any(not isinstance(case, dict) for case in raw_cases):
        raise ValueError("cases must be a list of objects")
    rows = []
    for case in raw_cases:
        metrics = case.get("human_metrics")
        if str(case.get("reader") or "") == reader_id and metrics:
            if not isinstance(metrics, dict):
                raise ValueError("human_metrics must be an object")
            rows.append(dict(metrics))
    return calculate_statistics(rows) if rows else {}


def _peer_means(readers: dict[str, dict[str, Any]], *, exclude: str) -> dict[str, float]:
    values: dict[str, list[float]] = {}
    for reader_id, payload in readers.items():
        if str(reader_id) == exclude:
            continue
        stats = payload or {}
        for metric, item in stats.items():
            if isinstance(item, dict):
                mean = _finite_stat_mean(item.get("mean"))
                if mean is not None:
                    values.setdefault(str(metric), []).append(mean)
    return {metric: sum(rows) / len(rows) for metric, rows in values.items() if rows}


def _weak_reader_metrics(stats: dict[str, Any], peer_means: dict[str, float]) -> list[str]:
    weak = []
    for metric, peer_mean in peer_means.items():
        reader_mean = _stat_mean(stats, metric)
        if reader_mean is not None and reader_mean < peer_mean - 1.0:
            weak.append(metric)
    return weak


def _weakest_available_metrics(stats: dict[str, Any]) -> list[str]:
    valid = [(metric, _stat_mean(stats, str(metric))) for metric in stats]
    valid = [(metric, value) for metric, value in valid if value is not None]
    if not valid:
        return []
    minimum = min(value for _, value in valid)
    return [metric for metric, value in valid if value == minimum]


def _stat_mean(stats: dict[str, Any], metric: str) -> float | None:
    item = stats.get(metric) or {}
    return _finite_stat_mean(item.get("mean")) if isinstance(item, dict) else None


def _finite_stat_mean(value: Any) -> float | None:
    """Accept only finite numeric means; bool/NaN/Inf are not measurements."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _report_prompt(payload: dict[str, Any], default: dict[str, Any]) -> str:
    context = {
        "report_summary": default.get("report_summary") or {},
        "target_findings": [
            {
                "finding_id": item.get("finding_id"),
                "metric": item.get("metric"),
                "metric_score": item.get("metric_score"),
                "error_type": _error_type_for_finding(str(item.get("finding_id") or ""), _hazards(payload)),
            }
            for item in default.get("suggestions") or []
        ],
        "top_models": list((default.get("metadata") or {}).get("top_models") or []),
    }
    return (
        "Generate structured radiology report education suggestions as JSON. "
        "Preserve the provided schema and cite existing finding_id values only.\n\n"
        f"Deidentified structured evidence:\n{json.dumps(context, ensure_ascii=False)}\n\n"
        f"Required schema shape:\n{json.dumps(_schema_shape(default), ensure_ascii=False)}"
    )


def _radiologist_prompt(payload: dict[str, Any], default: dict[str, Any]) -> str:
    summary = dict(default.get("radiologist_summary") or {})
    summary["radiologist_id"] = "target_reader"
    context = {
        "radiologist_summary": summary,
        "weak_metrics": [
            {
                "metric": item.get("metric"),
                "peer_comparison": item.get("peer_comparison"),
            }
            for item in default.get("suggestions") or []
        ],
    }
    return (
        "Generate structured reader-level radiology education suggestions as JSON. "
        "Preserve the provided schema and base suggestions on weak metrics and peer gaps.\n\n"
        f"Deidentified aggregate evidence:\n{json.dumps(context, ensure_ascii=False)}\n\n"
        f"Required schema shape:\n{json.dumps(_schema_shape(default), ensure_ascii=False)}"
    )


def _error_type_for_finding(finding_id: str, hazards: list[dict[str, Any]]) -> str:
    target = finding_id.lower()
    for error in hazards:
        for key in ("finding", "candidate", "reference", "a", "b"):
            finding = error.get(key) or {}
            if isinstance(finding, dict) and _finding_id(finding).lower() == target:
                return str(error.get("error_type") or "")
    return ""


def _finding_id(finding: dict[str, Any]) -> str:
    return str(finding.get("finding_id") or finding.get("id") or "")


def _finding_text(finding: dict[str, Any]) -> str:
    return str(
        finding.get("source_text")
        or finding.get("text")
        or finding.get("observation_text")
        or finding.get("observation")
        or ""
    )


def _schema_shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _schema_shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_schema_shape(value[0])] if value else []
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return 0
    if value is None:
        return None
    return "<string>"
