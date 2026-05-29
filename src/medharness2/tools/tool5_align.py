from __future__ import annotations

import re
from typing import Any


def align_graphs(candidate_graph: dict[str, Any], reference_graph: dict[str, Any], tolerance_mm: float = 5.0) -> dict[str, Any]:
    """Align candidate findings against a human/reference finding graph."""
    candidate_findings = list(candidate_graph.get("findings") or [])
    reference_findings = list(reference_graph.get("findings") or [])
    used_reference: set[int] = set()
    matched: list[dict[str, Any]] = []
    approximate: list[dict[str, Any]] = []
    mismatched: list[dict[str, Any]] = []
    candidate_only: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for candidate_finding in candidate_findings:
        reference_idx = _best_match_index(candidate_finding, reference_findings, used_reference)
        if reference_idx is None:
            candidate_only.append(candidate_finding)
            errors.append({"error_type": "false_finding", "finding": candidate_finding, "candidate": candidate_finding})
            continue
        reference_finding = reference_findings[reference_idx]
        used_reference.add(reference_idx)
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
    precision = len(matched) / max(len(candidate_findings), 1)
    recall = len(matched) / max(len(reference_findings), 1)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
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
            "symmetric_agreement": round((len(matched) + 0.5 * len(approximate)) / max(len(candidate_findings) + len(reference_findings), 1), 4),
        },
        "error_candidates": errors,
    }


def normalize_measurement_mm(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*(cm|mm)", str(value).lower())
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2)
    return number * 10.0 if unit == "cm" else number


def _best_match_index(finding: dict[str, Any], candidates: list[dict[str, Any]], used: set[int]) -> int | None:
    key = _obs(finding)
    for idx, candidate in enumerate(candidates):
        if idx in used:
            continue
        if _obs(candidate) == key:
            return idx
    return None


def _compare_findings(a: dict[str, Any], b: dict[str, Any], tolerance_mm: float) -> dict[str, Any]:
    differences: list[str] = []
    errors: list[dict[str, Any]] = []
    if _loc(a) != _loc(b):
        differences.append("location")
        errors.append({"error_type": "incorrect_location", "candidate": a, "reference": b, "a": a, "b": b})
    if _severity(a) != _severity(b):
        differences.append("severity")
        errors.append({"error_type": "incorrect_severity", "candidate": a, "reference": b, "a": a, "b": b})
    a_mm = normalize_measurement_mm(a.get("measurement"))
    b_mm = normalize_measurement_mm(b.get("measurement"))
    if a_mm is not None and b_mm is not None and abs(a_mm - b_mm) > tolerance_mm:
        differences.append("measurement")
        errors.append({"error_type": "mismatched_finding", "candidate": a, "reference": b, "a": a, "b": b})
    if not differences:
        if a_mm is not None and b_mm is not None and a_mm != b_mm:
            return {"category": "approximate_match", "differences": ["measurement_approximate"], "errors": []}
        return {"category": "matched", "differences": [], "errors": []}
    return {"category": "mismatched", "differences": differences, "errors": errors}


def _obs(finding: dict[str, Any]) -> str:
    return str(finding.get("observation") or "").strip().lower()


def _loc(finding: dict[str, Any]) -> str:
    return str(finding.get("location") or "unspecified").strip().lower()


def _severity(finding: dict[str, Any]) -> str:
    return str(finding.get("severity") or "unspecified").strip().lower()
