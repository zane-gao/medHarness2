from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.llm_client import LLMClient, LLMClientError
from medharness2.tools.tool1_likert import LIKERT_METRICS
from medharness2.utils.io import parse_json_object, read_json, write_json


ACTIONABLE_ERRORS = {"omission_finding", "incorrect_location", "incorrect_severity", "false_finding"}


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
    human = payload.get("human_evaluation") or {}
    likert = human.get("likert") or {}
    graph = human.get("finding_graph") or {}
    findings = list(graph.get("findings") or [])
    if not findings:
        raise ValueError("Workflow 1 result must contain human_evaluation.finding_graph.findings.")
    weakest_metric, weakest_score = _weakest_likert(likert)
    hazards = _hazards(payload)
    targeted_ids = _target_finding_ids(findings, hazards)
    default = {
        "mode": "eval_report",
        "status": "suggestions_generated",
        "report_summary": {
            "overall_score": _overall_likert(likert),
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
            "top_models": [item.get("model") for item in payload.get("rankings") or [] if item.get("selected_top_n")],
        },
    }
    return _try_llm_json(client, _report_prompt(payload, default), default)


def _radiologist_suggestions(payload: dict[str, Any], client: LLMClient) -> dict[str, Any]:
    readers = payload.get("per_reader") or {}
    if not readers:
        raise ValueError("Workflow 2 result must contain per_reader.")
    reader_id, reader = sorted(readers.items(), key=lambda item: str(item[0]))[0]
    peer_means = _peer_means(readers, exclude=str(reader_id))
    stats = dict(reader.get("human_statistics") or {})
    weakest = _weak_reader_metrics(stats, peer_means)
    if not weakest:
        weakest = [_min_stat_metric(stats)]
    default = {
        "mode": "eval_radiologist",
        "status": "suggestions_generated",
        "radiologist_summary": {
            "radiologist_id": str(reader_id),
            "n_reports": int(reader.get("case_count") or 0),
            "weakest_metrics": weakest,
            "peer_gaps": {
                metric: round(float(stats.get(metric, {}).get("mean", 0.0)) - float(peer_means.get(metric, 0.0)), 4)
                for metric in weakest
            },
        },
        "suggestions": [
            {
                "metric": metric,
                "pattern": f"{metric} is below the peer baseline.",
                "peer_comparison": f"Reader mean={_stat_mean(stats, metric):.2f}; peer mean={peer_means.get(metric, 0.0):.2f}.",
                "suggestion": _metric_guidance(metric),
                "reasoning": "Suggestion is derived from reader-level metric aggregates and peer gap.",
            }
            for metric in weakest
        ],
        "metadata": {"source": "deterministic_or_llm"},
    }
    return _try_llm_json(client, _radiologist_prompt(payload, default), default)


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
    except (ValueError, LLMClientError):
        return default
    return _merge_required(default, parsed)


def _merge_required(default: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    merged = dict(default)
    for key, value in parsed.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


def _weakest_likert(likert: dict[str, Any]) -> tuple[str, int]:
    best_metric = LIKERT_METRICS[0]
    best_score = 6
    for metric in LIKERT_METRICS:
        item = likert.get(metric) or {}
        try:
            score = int(float(item.get("score", 0)))
        except (TypeError, ValueError):
            score = 0
        if score < best_score:
            best_metric, best_score = metric, score
    return best_metric, max(1, min(5, best_score if best_score != 6 else 1))


def _overall_likert(likert: dict[str, Any]) -> float:
    scores = []
    for metric in LIKERT_METRICS:
        try:
            scores.append(float((likert.get(metric) or {}).get("score", 0)))
        except (TypeError, ValueError):
            continue
    return round(sum(scores) / len(scores), 4) if scores else 0.0


def _hazards(payload: dict[str, Any]) -> list[dict[str, Any]]:
    hazards: list[dict[str, Any]] = []
    for item in payload.get("pairwise_comparisons") or []:
        comparison = item.get("comparison") or {}
        hazard_payload = comparison.get("hazards") or {}
        hazards.extend(list(hazard_payload.get("errors") or []))
        alignment = comparison.get("alignment") or {}
        hazards.extend(list(alignment.get("error_candidates") or []))
    return hazards


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


def _peer_means(readers: dict[str, Any], *, exclude: str) -> dict[str, float]:
    values: dict[str, list[float]] = {}
    for reader_id, payload in readers.items():
        if str(reader_id) == exclude:
            continue
        stats = payload.get("human_statistics") or {}
        for metric, item in stats.items():
            if isinstance(item, dict) and isinstance(item.get("mean"), (int, float)):
                values.setdefault(str(metric), []).append(float(item["mean"]))
    return {metric: sum(rows) / len(rows) for metric, rows in values.items() if rows}


def _weak_reader_metrics(stats: dict[str, Any], peer_means: dict[str, float]) -> list[str]:
    weak = []
    for metric, peer_mean in peer_means.items():
        if _stat_mean(stats, metric) < peer_mean - 1.0:
            weak.append(metric)
    return weak


def _min_stat_metric(stats: dict[str, Any]) -> str:
    if not stats:
        return "Completeness and Accuracy"
    return min(stats, key=lambda metric: _stat_mean(stats, str(metric)))


def _stat_mean(stats: dict[str, Any], metric: str) -> float:
    item = stats.get(metric) or {}
    try:
        return float(item.get("mean", 0.0))
    except (TypeError, ValueError):
        return 0.0


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
