from __future__ import annotations

from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.llm_client import LLMClient
from medharness2.schema import SingleReportResult
from medharness2.tools.tool1_likert import evaluate_likert, likert_mean
from medharness2.tools.tool2_extract import extract_findings
from medharness2.tools.tool3_structure import check_structure


def evaluate_single_report(
    report_text: str,
    image_path: str | None = None,
    modality: str | None = None,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    modality_key = modality or "unknown"
    likert = evaluate_likert(report_text, image_path=image_path, llm_client=client)
    finding_graph = extract_findings(report_text, modality=modality_key, backend=cfg.extractor.backend)
    structure = check_structure(report_text)
    composite_inputs = {
        "likert_mean": likert_mean(likert),
        "structure_score": float(structure.get("score", 0.0)),
        "finding_coverage": float(finding_graph.get("coverage", 0.0)),
    }
    return SingleReportResult(
        likert=likert,
        finding_graph=finding_graph,
        structure=structure,
        composite_inputs=composite_inputs,
    ).to_json()
