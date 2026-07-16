from __future__ import annotations

import re
from typing import Any


def finding_pair_score(candidate: dict[str, Any], reference: dict[str, Any], *, tolerance_mm: float) -> float | None:
    candidate_observation = observation(candidate)
    reference_observation = observation(reference)
    if (
        candidate_observation != reference_observation
        or not candidate_observation
        or candidate_observation
        in {
            "other finding",
            "other_finding",
            "reported finding",
            "reported_finding",
            "unparsed legacy finding",
            "unparsed_legacy_finding",
        }
    ):
        return None

    score = 100.0
    candidate_location = location(candidate)
    reference_location = location(reference)
    if candidate_location == reference_location and candidate_location != "unspecified":
        score += 20.0
    elif "unspecified" in {candidate_location, reference_location}:
        score += 4.0

    candidate_laterality = laterality(candidate)
    reference_laterality = laterality(reference)
    if candidate_laterality == reference_laterality and candidate_laterality != "unknown":
        score += 15.0
    elif "unknown" in {candidate_laterality, reference_laterality}:
        score += 2.0
    else:
        score -= 10.0

    candidate_certainty = certainty(candidate)
    reference_certainty = certainty(reference)
    if candidate_certainty == reference_certainty:
        score += 20.0
    elif "uncertain" in {candidate_certainty, reference_certainty}:
        score += 3.0
    else:
        score -= 20.0

    candidate_severity = severity(candidate)
    reference_severity = severity(reference)
    if candidate_severity == reference_severity and candidate_severity != "unspecified":
        score += 5.0
    elif "unspecified" in {candidate_severity, reference_severity}:
        score += 1.0

    candidate_mm = measurement_mm(candidate)
    reference_mm = measurement_mm(reference)
    if candidate_mm is not None and reference_mm is not None:
        score += 10.0 if abs(candidate_mm - reference_mm) <= tolerance_mm else -5.0
    return score


def observation(finding: dict[str, Any]) -> str:
    return _normalized_text(
        finding.get("observation_code")
        or finding.get("observation")
        or finding.get("observation_text")
        or ""
    )


def location(finding: dict[str, Any]) -> str:
    return _normalized_text(
        finding.get("anatomy_code")
        or finding.get("location")
        or finding.get("location_text")
        or "unspecified"
    ) or "unspecified"


def laterality(finding: dict[str, Any]) -> str:
    explicit = _normalized_text(finding.get("laterality") or "")
    if explicit in {"left", "right", "bilateral", "midline"}:
        return explicit
    location_text = location(finding)
    if "bilateral" in location_text:
        return "bilateral"
    if "right" in location_text:
        return "right"
    if "left" in location_text:
        return "left"
    if "midline" in location_text:
        return "midline"
    return "unknown"


def certainty(finding: dict[str, Any]) -> str:
    value = _normalized_text(finding.get("certainty") or "present")
    if value in {"absent", "negative", "negated"}:
        return "absent"
    if value in {"uncertain", "possible", "indeterminate", "suspected"}:
        return "uncertain"
    return "present"


def severity(finding: dict[str, Any]) -> str:
    return _normalized_text(finding.get("severity") or "unspecified") or "unspecified"


def measurement_mm(finding: dict[str, Any]) -> float | None:
    measurements = finding.get("measurements") or []
    if isinstance(measurements, list) and measurements:
        first = measurements[0]
        if isinstance(first, dict):
            normalized = first.get("normalized_mm")
            if isinstance(normalized, (int, float)):
                return float(normalized)
            value = first.get("value")
            unit = str(first.get("unit") or "").lower()
            if isinstance(value, (int, float)) and unit in {"mm", "cm"}:
                return float(value) * (10.0 if unit == "cm" else 1.0)
    value = finding.get("measurement")
    if value is None:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*(cm|mm)", str(value).lower())
    if not match:
        return None
    number = float(match.group(1))
    return number * 10.0 if match.group(2) == "cm" else number


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())
