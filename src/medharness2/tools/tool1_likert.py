from __future__ import annotations

from statistics import mean
from typing import Any

from medharness2.llm_client import LLMClient
from medharness2.utils.io import parse_json_object


LIKERT_METRICS = [
    "Completeness and Accuracy",
    "Conciseness and Clarity",
    "Terminological Accuracy",
    "Structure and Style",
    "Overall Writing Quality",
]


def evaluate_likert(report_text: str, image_path: str | None = None, llm_client: LLMClient | None = None) -> dict[str, Any]:
    client = llm_client or LLMClient()
    default = _deterministic_likert(report_text, image_path=image_path)
    prompt = (
        "Evaluate this radiology report using five 1-5 Likert metrics. "
        "Return JSON where each metric maps to score and explanation.\n\n"
        f"Report:\n{report_text}"
    )
    raw = client.call(prompt, image_path=image_path, response_format="json", response_json=default)
    try:
        result = parse_json_object(raw, context="Tool 1 Likert")
    except ValueError:
        result = default
    return _normalize_likert(result, image_path=image_path)


def likert_mean(result: dict[str, Any]) -> float:
    scores = []
    for metric in LIKERT_METRICS:
        item = result.get(metric) or {}
        if isinstance(item, dict) and isinstance(item.get("score"), (int, float)):
            scores.append(float(item["score"]))
    return round(mean(scores), 4) if scores else 0.0


def _deterministic_likert(report_text: str, image_path: str | None) -> dict[str, Any]:
    token_count = len(report_text.split())
    has_findings = "finding" in report_text.lower() or "findings" in report_text.lower()
    has_impression = "impression" in report_text.lower()
    base = 3
    if token_count >= 20:
        base += 1
    if has_findings and has_impression:
        base += 1
    score = max(1, min(5, base))
    result = {
        metric: {"score": score, "explanation": "Deterministic MVP estimate from report length and section markers."}
        for metric in LIKERT_METRICS
    }
    if image_path is None:
        result["warning"] = "No image/volume provided"
    return result


def _normalize_likert(result: dict[str, Any], image_path: str | None) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for metric in LIKERT_METRICS:
        item = result.get(metric)
        if not isinstance(item, dict):
            item = {}
        raw_score = item.get("score", 1)
        try:
            score = int(round(float(raw_score)))
        except (TypeError, ValueError):
            score = 1
        normalized[metric] = {
            "score": max(1, min(5, score)),
            "explanation": str(item.get("explanation") or item.get("reasoning") or "No explanation provided."),
        }
    if image_path is None:
        normalized["warning"] = "No image/volume provided"
    return normalized
