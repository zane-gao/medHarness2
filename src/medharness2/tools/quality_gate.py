from __future__ import annotations

import re
from typing import Any

from medharness2.schema import GeneratedReport


_BODY_PART_CONFLICTS = {
    "brain": ["hip", "femoral", "femur", "pelvis", "liver", "kidney", "spleen", "lung", "chest", "胸部", "双肺", "肺部", "右肺", "左肺"],
    "head": ["hip", "femoral", "femur", "pelvis", "liver", "kidney", "spleen", "lung", "chest", "胸部", "双肺", "肺部", "右肺", "左肺"],
    "chest": ["hip", "femoral", "femur", "liver", "kidney", "spleen", "brain"],
    "abdomen": ["hip", "femoral", "femur", "brain"],
}

_MODALITY_CONFLICTS = {
    "mri": ["radiograph", "x-ray", "xray", "computed tomography", " ct "],
    "ct": ["radiograph", "x-ray", "xray", "magnetic resonance", " mri "],
    "cxr": ["computed tomography", " ct ", "magnetic resonance", " mri "],
}


def apply_generation_quality_gate(report: GeneratedReport, *, modality: str | None, body_part: str | None) -> GeneratedReport:
    result = check_generation_quality(report.report, modality=modality, body_part=body_part)
    if _is_fallback_report(report):
        result["passed"] = False
        result["warnings"] = ["fallback_generation", *result["warnings"]]
    report.metadata = {**report.metadata, "quality_gate": result}
    if not result["passed"]:
        for warning in ["quality_gate_failed", *result["warnings"]]:
            if warning not in report.warnings:
                report.warnings.append(warning)
    return report


def _is_fallback_report(report: GeneratedReport) -> bool:
    metadata = report.metadata or {}
    source = str(report.source or "").lower()
    tier = str(report.evidence_tier or "").lower()
    return bool(metadata.get("fallback_used")) or tier in {"mock", "debug_fallback"} or source in {
        "mock",
        "mock_fallback",
        "fallback",
        "local_vlm_fallback",
    }


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
    modality_matches = _matched_terms(_mask_followup_modality_mentions(normalized), modality_terms)
    if modality_matches:
        warnings.append("modality_mismatch")
        conflicts["modality"] = modality_matches

    return {
        # Body-part mentions are intentionally advisory.  The router is
        # modality-first and body part is a soft ranking signal; making this
        # conflict fail closed would silently recreate the old hard-routing
        # behavior and discard otherwise usable candidates.  Modality
        # conflicts remain blocking because they indicate a different imaging
        # family.
        "passed": not modality_matches,
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


def _mask_followup_modality_mentions(text: str) -> str:
    masked = text
    masked = _mask_followup_sentences(masked)
    followup_patterns = [
        r"\bconsider\s+(?:a\s+|an\s+)?(?:ct|mri|computed tomography|magnetic resonance)\b",
        r"\brecommend(?:ed|s|ing)?\s+(?:a\s+|an\s+)?(?:follow[- ]?up\s+)?(?:ct|mri|computed tomography|magnetic resonance)\b",
        r"\bfurther\s+(?:ct|mri|computed tomography|magnetic resonance)\b",
        r"\b(?:ct|mri)\s+if\b",
        r"\be\.g\.,?\s*(?:ct|mri|computed tomography|magnetic resonance)\b",
    ]
    for pattern in followup_patterns:
        masked = re.sub(pattern, " followup imaging ", masked)
    return masked


def _mask_followup_sentences(text: str) -> str:
    cues = ("consider", "recommend", "follow", "further", "建议", "必要时", "进一步", "随诊", "评估")
    modality_terms = ("ct", "mri", "computed tomography", "magnetic resonance", "核磁", "磁共振")
    parts = re.split(r"([。.!?；;])", text)
    masked_parts: list[str] = []
    for index in range(0, len(parts), 2):
        sentence = parts[index]
        delimiter = parts[index + 1] if index + 1 < len(parts) else ""
        lower = sentence.lower()
        if any(cue in lower for cue in cues) and any(term in lower for term in modality_terms):
            sentence = re.sub(r"(?<![a-z0-9])(?:ct|mri|computed tomography|magnetic resonance)(?![a-z0-9])", " followup imaging ", sentence, flags=re.IGNORECASE)
            sentence = sentence.replace("核磁", "followup imaging").replace("磁共振", "followup imaging")
        masked_parts.append(sentence + delimiter)
    return "".join(masked_parts)
