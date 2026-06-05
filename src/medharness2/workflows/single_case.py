from __future__ import annotations

from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.llm_client import LLMClient
from medharness2.modules.pairwise_report import evaluate_pairwise
from medharness2.modules.single_report import evaluate_single_report
from medharness2.schema import GeneratedReport
from medharness2.tools.quality_gate import apply_generation_quality_gate
from medharness2.tools.tool7_modality import recognize_modality
from medharness2.tools.tool8_generate import generate_reports
from medharness2.tools.tool9_rank import select_top_k
from medharness2.utils.io import read_text, write_json


def run_single_case(
    report_path: str | Path | None = None,
    image_path: str | Path | None = None,
    output_path: str | Path | None = None,
    report_text: str | None = None,
    prepared_assets: dict[str, Any] | None = None,
    modality: str | None = None,
    body_part: str | None = None,
    top_n: int | None = None,
    model_keys: list[str] | None = None,
    model_sources: list[str] | None = None,
    precomputed_generated_reports: list[GeneratedReport] | None = None,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    if image_path is None or output_path is None:
        raise ValueError("Provide image_path and output_path.")
    if report_text is None:
        if report_path is None:
            raise ValueError("Provide report_path or report_text.")
        report_text = read_text(report_path)
    image = str((prepared_assets or {}).get("primary_image") or image_path)
    generation_image = str((prepared_assets or {}).get("volume_path") or (prepared_assets or {}).get("primary_image") or image_path)
    modality_key = modality or recognize_modality(image, config=cfg, llm_client=client)
    generated = (
        list(precomputed_generated_reports)
        if precomputed_generated_reports is not None
        else generate_reports(
            generation_image,
            modality_key,
            reference_report=report_text,
            model_keys=model_keys,
            model_sources=model_sources,
            body_part=body_part,
            fallback_image_path=image,
            config=cfg,
            llm_client=client,
        )
    )
    generated = [
        apply_generation_quality_gate(report, modality=modality_key, body_part=body_part)
        for report in generated
    ]
    human_evaluation = evaluate_single_report(
        report_text,
        image_path=image,
        modality=modality_key,
        config=cfg,
        llm_client=client,
    )
    generated_evaluations: list[dict[str, Any]] = []
    for report in generated:
        evaluation = evaluate_single_report(
            report.report,
            image_path=image,
            modality=modality_key,
            config=cfg,
            llm_client=client,
        )
        evaluation["model"] = report.model
        evaluation["source"] = report.source
        evaluation["warnings"] = report.warnings
        evaluation["quality_gate"] = report.metadata.get("quality_gate", {"passed": True})
        generated_evaluations.append(evaluation)
    ranking_inputs = [
        evaluation
        for evaluation in generated_evaluations
        if evaluation.get("quality_gate", {}).get("passed", True)
    ]
    ranking_index_map = [
        index
        for index, evaluation in enumerate(generated_evaluations)
        if evaluation.get("quality_gate", {}).get("passed", True)
    ]
    rankings = select_top_k(
        ranking_inputs,
        weights=cfg.ranking.weights,
        top_k=top_n if top_n is not None else cfg.ranking.top_n,
    )
    for row in rankings:
        row["index"] = ranking_index_map[row["index"]]
    pairwise = []
    for row in rankings:
        evaluation = generated_evaluations[row["index"]]
        generated_report = generated[row["index"]]
        pairwise.append(
            {
                "model": generated_report.model,
                "rank": row["rank"],
                "comparison": evaluate_pairwise(
                    report_text,
                    generated_report.report,
                    image_path=image,
                    modality=modality_key,
                    config=cfg,
                    llm_client=client,
                ),
                "selected_evaluation": evaluation,
            }
        )
    result = {
        "input": {
            "report_path": str(report_path) if report_path is not None else None,
            "image_path": image,
            "modality": modality_key,
            "body_part": body_part,
            "prepared_assets": prepared_assets or {},
        },
        "human_evaluation": human_evaluation,
        "generated_reports": [report.to_json() for report in generated],
        "generated_evaluations": generated_evaluations,
        "rankings": rankings,
        "pairwise_comparisons": pairwise,
    }
    write_json(output_path, result)
    return result
