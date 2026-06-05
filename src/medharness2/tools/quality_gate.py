from __future__ import annotations

import re
from typing import Any

from medharness2.schema import GeneratedReport


_BODY_PART_CONFLICTS = {
    "brain": ["hip", "femoral", "femur", "pelvis", "liver", "kidney", "spleen", "lung", "chest"],
    "head": ["hip", "femoral", "femur", "pelvis", "liver", "kidney", "spleen", "lung", "chest"],
    "chest": ["hip", "femoral", "femur", "liver", "kidney", "spleen", "brain"],
    "abdomen": ["hip", "femoral", "femur", "brain", "lung", "pneumothorax"],
}

_MODALITY_CONFLICTS = {
    "mri": ["radiograph", "x-ray", "xray", "computed tomography", " ct "],
    "ct": ["radiograph", "x-ray", "xray", "magnetic resonance", " mri "],
    "cxr": ["computed tomography", " ct ", "magnetic resonance", " mri "],
}


def apply_generation_quality_gate(report: GeneratedReport, *, modality: str | None, body_part: str | None) -> GeneratedReport:
    result = check_generation_quality(report.report, modality=modality, body_part=body_part)
    report.metadata = {**report.metadata, "quality_gate": result}
    if not result["passed"]:
        for warning in ["quality_gate_failed", *result["warnings"]]:
            if warning not in report.warnings:
                report.warnings.append(warning)
    return report


def check_generation_quality(text: str, *, modality: str | None, body_part: str | None) -> dict[str, Any]:
    normalized = _normalize(text)
    warnings: list[str] = []
    conflicts: dict[str, list[str]] = {}

    body_key = (body_part or "").lower()
    body_terms = _BODY_PART_CONFLICTS.get(body_key, [])
    body_matches = _matched_terms(normalized, body_terms)
    if body_matches:
        warnings.append("body_part_mismatch")
        conflicts["body_part"] = body_matches

    modality_key = (modality or "").lower()
    modality_terms = _MODALITY_CONFLICTS.get(modality_key, [])
    modality_matches = _matched_terms(normalized, modality_terms)
    if modality_matches:
        warnings.append("modality_mismatch")
        conflicts["modality"] = modality_matches

    return {
        "passed": not warnings,
        "warnings": warnings,
        "expected_modality": modality,
        "expected_body_part": body_part,
        "conflicts": conflicts,
    }


def _normalize(text: str) -> str:
    return f" {str(text or '').lower()} "


def _matched_terms(text: str, terms: list[str]) -> list[str]:
    matches: list[str] = []
    for term in terms:
        if re.search(rf"(?<![a-z0-9]){re.escape(term.strip())}(?![a-z0-9])", text):
            matches.append(term.strip())
    return matches
