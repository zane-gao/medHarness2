from __future__ import annotations

from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.llm_client import LLMClient
from medharness2.modules.pairwise_report import evaluate_pairwise
from medharness2.modules.single_report import evaluate_single_report
from medharness2.tools.tool7_modality import recognize_modality
from medharness2.tools.tool8_generate import generate_reports
from medharness2.tools.tool9_rank import select_top_k
from medharness2.utils.io import read_text, write_json


def run_single_case(
    report_path: str | Path,
    image_path: str | Path,
    output_path: str | Path,
    modality: str | None = None,
    top_n: int | None = None,
    model_keys: list[str] | None = None,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    report_text = read_text(report_path)
    image = str(image_path)
    modality_key = modality or recognize_modality(image, config=cfg, llm_client=client)
    generated = generate_reports(
        image,
        modality_key,
        reference_report=report_text,
        model_keys=model_keys,
        config=cfg,
        llm_client=client,
    )
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
        generated_evaluations.append(evaluation)
    rankings = select_top_k(
        generated_evaluations,
        weights=cfg.ranking.weights,
        top_k=top_n if top_n is not None else cfg.ranking.top_n,
    )
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
            "report_path": str(report_path),
            "image_path": image,
            "modality": modality_key,
        },
        "human_evaluation": human_evaluation,
        "generated_reports": [report.to_json() for report in generated],
        "generated_evaluations": generated_evaluations,
        "rankings": rankings,
        "pairwise_comparisons": pairwise,
    }
    write_json(output_path, result)
    return result
