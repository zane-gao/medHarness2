from __future__ import annotations

from pathlib import Path
from typing import Any

from medharness2.checkpoints import StageCheckpointStore
from medharness2.config import AppConfig, load_config
from medharness2.contracts import CaseEvaluationArtifact, ProductionGenerationArtifact
from medharness2.generators.pipeline import run_candidate_generation, run_production_generation
from medharness2.llm_client import LLMClient
from medharness2.modality import normalize_modality
from medharness2.modules.pairwise_report import evaluate_pairwise
from medharness2.modules.single_report import evaluate_single_report
from medharness2.schema import GeneratedReport
from medharness2.tools.tool7_modality import recognize_modality
from medharness2.tools.tool9_rank import select_top_k
from medharness2.tools.tool5_align import align_graphs
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
    checkpoint_store: StageCheckpointStore | None = None,
    *,
    case_id: str | None = None,
    generation_mode: str = "benchmark",
) -> dict[str, Any]:
    if generation_mode not in {"benchmark", "replay", "production"}:
        raise ValueError("generation_mode must be one of: benchmark, replay, production.")
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    if image_path is None or output_path is None:
        raise ValueError("Provide image_path and output_path.")
    assets = _strict_prepared_assets(prepared_assets)
    image = assets.get("contact_sheet") or assets.get("primary_image") or str(image_path)
    generation_image = (
        assets.get("feature_path")
        or assets.get("wsi_feature_path")
        or assets.get("h5_feature_path")
        or assets.get("histgen_feature_path")
        or assets.get("volume_path")
        or assets.get("contact_sheet")
        or assets.get("primary_image")
        or str(image_path)
    )
    modality_key = (
        normalize_modality(modality)
        if modality is not None
        else recognize_modality(image, config=cfg, llm_client=client)
    )
    resolved_case_id = str(case_id or Path(output_path).stem)
    if generation_mode == "production":
        production = run_production_generation(
            image_path=generation_image,
            modality=modality_key,
            body_part=body_part,
            case_id=resolved_case_id,
            prepared_assets=assets,
            model_keys=model_keys,
            model_sources=model_sources,
            top_n=top_n,
            precomputed_generated_reports=precomputed_generated_reports,
            config=cfg,
            llm_client=client,
        )
        result = production.to_json()
        result["case_id"] = resolved_case_id
        result["input"] = {
            "case_id": resolved_case_id,
            "report_path": str(report_path) if report_path is not None else None,
            "image_path": image,
            "modality": modality_key,
            "body_part": body_part,
            "prepared_assets": assets,
        }
        if not production.candidate_reports:
            result["errors"] = ["no_generated_reports"]
        result = ProductionGenerationArtifact.model_validate(result).model_dump(mode="json")
        write_json(output_path, result)
        return result

    reference_text = report_text
    if reference_text is None and report_path is not None:
        reference_text = read_text(report_path)
    if reference_text is not None and not reference_text.strip():
        reference_text = None
    generation = run_candidate_generation(
        image_path=generation_image,
        modality=modality_key,
        body_part=body_part,
        case_id=resolved_case_id,
        generation_mode=generation_mode,
        reference_report=(
            reference_text if cfg.generator.reference_assisted_generation else None
        ),
        prepared_assets=assets,
        model_keys=model_keys,
        model_sources=model_sources,
        top_n=top_n,
        precomputed_generated_reports=precomputed_generated_reports,
        config=cfg,
        llm_client=client,
    )
    generated = [candidate.generated for candidate in generation.candidate_reports]
    human_evaluation: dict[str, Any] | None = None
    generated_evaluations: list[dict[str, Any]] = []
    rankings: list[dict[str, Any]] = []
    pairwise: list[dict[str, Any]] = []
    if reference_text is not None:
        human_evaluation = evaluate_single_report(
            reference_text,
            image_path=image,
            modality=modality_key,
            config=cfg,
            llm_client=client,
            checkpoint_store=checkpoint_store,
            checkpoint_namespace="reference",
        )
        for report_index, report in enumerate(generated):
            evaluation = evaluate_single_report(
                report.report,
                image_path=image,
                modality=modality_key,
                config=cfg,
                llm_client=client,
                checkpoint_store=checkpoint_store,
                checkpoint_namespace=f"candidate_{report_index}",
            )
            evaluation["model"] = report.model
            evaluation["source"] = report.source
            evaluation["evidence_tier"] = report.evidence_tier
            evaluation["warnings"] = report.warnings
            evaluation["metadata"] = {**(evaluation.get("metadata") or {}), **report.metadata}
            evaluation["quality_gate"] = report.metadata.get("quality_gate", {"passed": True})
            alignment = align_graphs(
                evaluation.get("finding_graph") or {},
                human_evaluation.get("finding_graph") or {},
                tolerance_mm=cfg.alignment.tolerance_mm,
            )
            evaluation["finding_alignment"] = alignment
            composite = _strict_object(
                evaluation.get("composite_inputs"),
                "generated_evaluation.composite_inputs",
            )
            composite["finding_coverage"] = float(
                (alignment.get("metrics") or {}).get("recall", 0.0)
            )
            evaluation["composite_inputs"] = composite
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
            row["evidence_tier"] = generated[row["index"]].evidence_tier
        for row in rankings:
            evaluation = generated_evaluations[row["index"]]
            generated_report = generated[row["index"]]
            pairwise.append(
                {
                    "model": generated_report.model,
                    "evidence_tier": generated_report.evidence_tier,
                    "rank": row["rank"],
                    "comparison": evaluate_pairwise(
                        reference_text,
                        generated_report.report,
                        image_path=image,
                        modality=modality_key,
                        reference_graph=human_evaluation["finding_graph"],
                        candidate_graph=evaluation["finding_graph"],
                        config=cfg,
                        llm_client=client,
                        checkpoint_store=checkpoint_store,
                        checkpoint_namespace=f"candidate_{row['index']}",
                    ),
                    "selected_evaluation": evaluation,
                }
            )
    result = {
        "schema_version": "2.0",
        "artifact_type": "case_evaluation",
        "generation_mode": generation_mode,
        "case_id": resolved_case_id,
        "input": {
            "case_id": resolved_case_id,
            "report_path": str(report_path) if report_path is not None else None,
            "image_path": image,
            "modality": modality_key,
            "body_part": body_part,
            "prepared_assets": assets,
        },
        "route_plan": generation.route_plan,
        "candidate_reports": [candidate.to_json() for candidate in generation.candidate_reports],
        "candidate_failures": generation.candidate_failures,
        "candidate_structure_comparison": generation.candidate_structure_comparison,
        "top_k_reports": generation.top_k_reports,
        "fusion_report": generation.fusion_report.to_json(),
        "human_evaluation": human_evaluation,
        "generated_reports": [report.to_json() for report in generated],
        "generated_evaluations": generated_evaluations,
        "rankings": rankings,
        "pairwise_comparisons": pairwise,
    }
    if not generated:
        result["errors"] = ["no_generated_reports"]
    result = CaseEvaluationArtifact.model_validate(result).model_dump(mode="json")
    write_json(output_path, result)
    return result


def _strict_prepared_assets(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("prepared_assets must be an object")
    result: dict[str, str] = {}
    for key in (
        "contact_sheet",
        "primary_image",
        "volume_path",
        "feature_path",
        "wsi_feature_path",
        "h5_feature_path",
        "histgen_feature_path",
    ):
        item = value.get(key)
        if item is None or item == "":
            continue
        if not isinstance(item, str):
            raise ValueError(f"prepared_assets.{key} must be a string")
        result[key] = item
    return result


def _strict_object(value: Any, label: str) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value
