from __future__ import annotations

from typing import Any

from medharness2.alignment.matcher import maximum_weight_finding_pairs
from medharness2.alignment.audit import audit_alignment
from medharness2.alignment.scoring import certainty, laterality, location, measurement_mm, observation, severity


def align_graphs(candidate_graph: dict[str, Any], reference_graph: dict[str, Any], tolerance_mm: float = 5.0) -> dict[str, Any]:
    """Align candidate findings against a human/reference finding graph."""
    candidate_findings = list(candidate_graph.get("findings") or [])
    reference_findings = list(reference_graph.get("findings") or [])
    matched: list[dict[str, Any]] = []
    approximate: list[dict[str, Any]] = []
    mismatched: list[dict[str, Any]] = []
    candidate_only: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    pairs = maximum_weight_finding_pairs(candidate_findings, reference_findings, tolerance_mm=tolerance_mm)
    reference_by_candidate = {candidate_index: reference_index for candidate_index, reference_index in pairs}
    used_reference = set(reference_by_candidate.values())

    for candidate_index, candidate_finding in enumerate(candidate_findings):
        reference_idx = reference_by_candidate.get(candidate_index)
        if reference_idx is None:
            candidate_only.append(candidate_finding)
            errors.append({"error_type": "false_finding", "finding": candidate_finding, "candidate": candidate_finding})
            continue
        reference_finding = reference_findings[reference_idx]
        comparison = _compare_findings(candidate_finding, reference_finding, tolerance_mm=tolerance_mm)
        row = {
            "candidate": candidate_finding,
            "reference": reference_finding,
            "a": candidate_finding,
            "b": reference_finding,
            "differences": comparison["differences"],
        }
        if comparison["category"] == "matched":
            matched.append(row)
        elif comparison["category"] == "approximate_match":
            approximate.append(row)
        else:
            mismatched.append(row)
            errors.extend(comparison["errors"])

    reference_only = [finding for idx, finding in enumerate(reference_findings) if idx not in used_reference]
    for finding in reference_only:
        errors.append({"error_type": "omission_finding", "finding": finding, "reference": finding})
    strict_matches = len(matched) + len(approximate)
    precision = strict_matches / max(len(candidate_findings), 1)
    recall = strict_matches / max(len(reference_findings), 1)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    paired_count = len(pairs)
    detection_precision = paired_count / max(len(candidate_findings), 1)
    detection_recall = paired_count / max(len(reference_findings), 1)
    detection_f1 = (
        0.0
        if detection_precision + detection_recall == 0
        else 2 * detection_precision * detection_recall / (detection_precision + detection_recall)
    )
    agreement_denominator = len(candidate_findings) + len(reference_findings)
    return {
        "matched": matched,
        "approximate_match": approximate,
        "mismatched": mismatched,
        "candidate_only": candidate_only,
        "reference_only": reference_only,
        "a_only": candidate_only,
        "b_only": reference_only,
        "metrics": {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "detection_precision": round(detection_precision, 4),
            "detection_recall": round(detection_recall, 4),
            "detection_f1": round(detection_f1, 4),
            "symmetric_agreement": round(
                (2 * len(matched) + len(approximate)) / max(agreement_denominator, 1),
                4,
            ),
        },
        "error_candidates": errors,
    }


def normalize_measurement_mm(value: Any) -> float | None:
    return measurement_mm({"measurement": value})


def _compare_findings(a: dict[str, Any], b: dict[str, Any], tolerance_mm: float) -> dict[str, Any]:
    differences: list[str] = []
    errors: list[dict[str, Any]] = []
    location_mismatch = location(a) != location(b)
    laterality_mismatch = laterality(a) != laterality(b) and "unknown" not in {laterality(a), laterality(b)}
    if location_mismatch:
        differences.append("location")
    if laterality_mismatch:
        differences.append("laterality")
    if location_mismatch or laterality_mismatch:
        errors.append({"error_type": "incorrect_location", "candidate": a, "reference": b, "a": a, "b": b})
    if severity(a) != severity(b):
        differences.append("severity")
        errors.append({"error_type": "incorrect_severity", "candidate": a, "reference": b, "a": a, "b": b})
    if certainty(a) != certainty(b):
        differences.append("certainty")
        error_type = "contradiction" if {certainty(a), certainty(b)} == {"present", "absent"} else "mismatched_finding"
        errors.append({"error_type": error_type, "candidate": a, "reference": b, "a": a, "b": b})
    a_mm = measurement_mm(a)
    b_mm = measurement_mm(b)
    if (a_mm is None) != (b_mm is None):
        differences.append("measurement_missing")
        errors.append({"error_type": "mismatched_finding", "candidate": a, "reference": b, "a": a, "b": b})
    elif a_mm is not None and b_mm is not None and abs(a_mm - b_mm) > tolerance_mm:
        differences.append("measurement")
        errors.append({"error_type": "mismatched_finding", "candidate": a, "reference": b, "a": a, "b": b})
    if not differences:
        if a_mm is not None and b_mm is not None and a_mm != b_mm:
            return {"category": "approximate_match", "differences": ["measurement_approximate"], "errors": []}
        return {"category": "matched", "differences": [], "errors": []}
    return {"category": "mismatched", "differences": differences, "errors": errors}


__all__ = ["align_graphs", "audit_alignment", "normalize_measurement_mm"]
