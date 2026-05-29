from __future__ import annotations

from typing import Any

from medharness2.llm_client import LLMClient
from medharness2.utils.io import parse_json_object


DEFAULT_HAZARD = {
    "false_finding": 3,
    "omission_finding": 4,
    "incorrect_location": 3,
    "incorrect_severity": 2,
    "mismatched_finding": 3,
}


def evaluate_hazards(error_candidates: list[dict[str, Any]], llm_client: LLMClient | None = None) -> dict[str, Any]:
    deterministic = {"errors": [_default_error(error) for error in error_candidates]}
    if not error_candidates:
        return {"errors": []}
    client = llm_client or LLMClient()
    prompt = f"Assign hazard levels to these report comparison errors as JSON:\n{error_candidates}"
    raw = client.call(prompt, response_format="json", response_json=deterministic)
    try:
        result = parse_json_object(raw, context="Tool 4 Hazard")
    except ValueError:
        result = deterministic
    errors = result.get("errors")
    if not isinstance(errors, list):
        errors = deterministic["errors"]
    return {"errors": [_normalize_error(error) for error in errors]}


def _default_error(error: dict[str, Any]) -> dict[str, Any]:
    error_type = str(error.get("error_type") or "mismatched_finding")
    return {
        **error,
        "hazard_level": DEFAULT_HAZARD.get(error_type, 3),
        "explanation": f"MVP hazard estimate for {error_type}.",
    }


def _normalize_error(error: dict[str, Any]) -> dict[str, Any]:
    error_type = str(error.get("error_type") or "mismatched_finding")
    try:
        level = int(error.get("hazard_level", DEFAULT_HAZARD.get(error_type, 3)))
    except (TypeError, ValueError):
        level = DEFAULT_HAZARD.get(error_type, 3)
    return {
        **error,
        "error_type": error_type,
        "hazard_level": max(1, min(5, level)),
        "explanation": str(error.get("explanation") or f"MVP hazard estimate for {error_type}."),
    }
