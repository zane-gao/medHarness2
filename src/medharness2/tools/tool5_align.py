from __future__ import annotations

import re
from typing import Any


def align_graphs(graph_a: dict[str, Any], graph_b: dict[str, Any], tolerance_mm: float = 5.0) -> dict[str, Any]:
    findings_a = list(graph_a.get("findings") or [])
    findings_b = list(graph_b.get("findings") or [])
    used_b: set[int] = set()
    matched: list[dict[str, Any]] = []
    approximate: list[dict[str, Any]] = []
    mismatched: list[dict[str, Any]] = []
    a_only: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for finding_a in findings_a:
        idx_b = _best_match_index(finding_a, findings_b, used_b)
        if idx_b is None:
            a_only.append(finding_a)
            errors.append({"error_type": "false_finding", "finding": finding_a})
            continue
        finding_b = findings_b[idx_b]
        used_b.add(idx_b)
        comparison = _compare_findings(finding_a, finding_b, tolerance_mm=tolerance_mm)
        row = {"a": finding_a, "b": finding_b, "differences": comparison["differences"]}
        if comparison["category"] == "matched":
            matched.append(row)
        elif comparison["category"] == "approximate_match":
            approximate.append(row)
        else:
            mismatched.append(row)
            errors.extend(comparison["errors"])

    b_only = [finding for idx, finding in enumerate(findings_b) if idx not in used_b]
    for finding in b_only:
        errors.append({"error_type": "omission_finding", "finding": finding})
    precision = len(matched) / max(len(findings_a), 1)
    recall = len(matched) / max(len(findings_b), 1)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {
        "matched": matched,
        "approximate_match": approximate,
        "mismatched": mismatched,
        "a_only": a_only,
        "b_only": b_only,
        "metrics": {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "symmetric_agreement": round((len(matched) + 0.5 * len(approximate)) / max(len(findings_a) + len(findings_b), 1), 4),
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
        errors.append({"error_type": "incorrect_location", "a": a, "b": b})
    if _severity(a) != _severity(b):
        differences.append("severity")
        errors.append({"error_type": "incorrect_severity", "a": a, "b": b})
    a_mm = normalize_measurement_mm(a.get("measurement"))
    b_mm = normalize_measurement_mm(b.get("measurement"))
    if a_mm is not None and b_mm is not None and abs(a_mm - b_mm) > tolerance_mm:
        differences.append("measurement")
        errors.append({"error_type": "mismatched_finding", "a": a, "b": b})
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
