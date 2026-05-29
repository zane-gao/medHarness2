from __future__ import annotations

from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.llm_client import LLMClient
from medharness2.tools.tool2_extract import extract_findings
from medharness2.tools.tool3_structure import check_structure
from medharness2.tools.tool4_hazard import evaluate_hazards
from medharness2.tools.tool5_align import align_graphs


def evaluate_pairwise(
    report_a: str,
    report_b: str,
    image_path: str | None = None,
    modality: str | None = None,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    modality_key = modality or "unknown"
    graph_a = extract_findings(report_a, modality=modality_key, backend=cfg.extractor.backend)
    graph_b = extract_findings(report_b, modality=modality_key, backend=cfg.extractor.backend)
    # Align candidate (B) against human/reference (A), so false_finding and omission
    # match the usual AI-vs-human interpretation.
    alignment = align_graphs(graph_b, graph_a, tolerance_mm=cfg.alignment.tolerance_mm)
    hazards = evaluate_hazards(alignment.get("error_candidates") or [], llm_client=client)
    return {
        "report_a": "human_or_reference",
        "report_b": "candidate",
        "modality": modality_key,
        "graph_a": graph_a,
        "graph_b": graph_b,
        "alignment": alignment,
        "hazards": hazards,
        "structure_diff": _structure_diff(report_a, report_b),
        "warnings": ["image_path_unused_in_mvp_pairwise"] if image_path else [],
    }


def _structure_diff(report_a: str, report_b: str) -> dict[str, Any]:
    structure_a = check_structure(report_a)
    structure_b = check_structure(report_b)
    sections = sorted(set(structure_a["section_scores"]) | set(structure_b["section_scores"]))
    return {
        section: {
            "score_a": structure_a["section_scores"].get(section, 0.0),
            "score_b": structure_b["section_scores"].get(section, 0.0),
            "difference": round(structure_b["section_scores"].get(section, 0.0) - structure_a["section_scores"].get(section, 0.0), 4),
        }
        for section in sections
    }
