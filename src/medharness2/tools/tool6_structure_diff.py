from __future__ import annotations

from typing import Any

from medharness2.tools.tool3_structure import check_structure


def compare_structure(report_a: str, report_b: str) -> dict[str, Any]:
    structure_a = check_structure(report_a)
    structure_b = check_structure(report_b)
    sections = sorted(set(structure_a.get("section_scores") or {}) | set(structure_b.get("section_scores") or {}))
    section_diff = {
        section: {
            "score_a": float((structure_a.get("section_scores") or {}).get(section, 0.0)),
            "score_b": float((structure_b.get("section_scores") or {}).get(section, 0.0)),
            "difference": round(float((structure_b.get("section_scores") or {}).get(section, 0.0)) - float((structure_a.get("section_scores") or {}).get(section, 0.0)), 4),
        }
        for section in sections
    }
    score_a = float(structure_a.get("score", 0.0))
    score_b = float(structure_b.get("score", 0.0))
    return {
        "score_a": score_a,
        "score_b": score_b,
        "score_delta": round(score_b - score_a, 4),
        "section_diff": section_diff,
        "structure_a": structure_a,
        "structure_b": structure_b,
    }
