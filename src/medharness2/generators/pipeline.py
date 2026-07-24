from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.contracts import ProductionGenerationArtifact
from medharness2.generators.assets import ImageAsset, select_2d_image_asset
from medharness2.generators.fusion import fuse_candidate_reports
from medharness2.generators.orchestrator import CandidateGenerationResult, generate_candidates
from medharness2.generators.registry import ReportGeneratorRegistry
from medharness2.llm_client import LLMClient
from medharness2.schema import CandidateFailure, CandidateReport, FusionReport, GeneratedReport
from medharness2.tools.quality_gate import apply_generation_quality_gate
from medharness2.tools.report_structure import (
    compare_candidate_structures,
    failed_structure_report,
    structure_report,
)
from medharness2.tools.tool9_rank import select_production_top_k


@dataclass
class ProductionGenerationResult:
    route_plan: dict[str, Any]
    candidate_reports: list[CandidateReport]
    candidate_failures: list[dict[str, Any]]
    candidate_structure_comparison: dict[str, Any]
    top_k_reports: list[dict[str, Any]]
    fusion_report: FusionReport

    def to_json(self) -> dict[str, Any]:
        payload = {
            "schema_version": "2.0",
            "artifact_type": "production_report_generation",
            "generation_mode": "production_reference_free",
            "route_plan": self.route_plan,
            "candidate_reports": [candidate.to_json() for candidate in self.candidate_reports],
            "candidate_failures": self.candidate_failures,
            "candidate_structure_comparison": self.candidate_structure_comparison,
            "top_k_reports": self.top_k_reports,
            "fusion_report": self.fusion_report.to_json(),
            "generated_reports": [candidate.generated.to_json() for candidate in self.candidate_reports],
        }
        return ProductionGenerationArtifact.model_validate(payload).model_dump(mode="json")


def run_production_generation(
    *,
    image_path: str,
    modality: str,
    body_part: str | None,
    case_id: str | None,
    reference_report: str | None = None,
    prepared_assets: dict[str, Any] | None = None,
    model_keys: list[str] | None = None,
    model_sources: list[str] | None = None,
    top_n: int | None = None,
    precomputed_generated_reports: list[GeneratedReport] | None = None,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
) -> ProductionGenerationResult:
    del reference_report
    return run_candidate_generation(
        image_path=image_path,
        modality=modality,
        body_part=body_part,
        case_id=case_id,
        generation_mode="production",
        reference_report=None,
        prepared_assets=prepared_assets,
        model_keys=model_keys,
        model_sources=model_sources,
        top_n=top_n,
        precomputed_generated_reports=precomputed_generated_reports,
        config=config,
        llm_client=llm_client,
    )


def run_candidate_generation(
    *,
    image_path: str,
    modality: str,
    body_part: str | None,
    case_id: str | None,
    generation_mode: str,
    reference_report: str | None = None,
    prepared_assets: dict[str, Any] | None = None,
    model_keys: list[str] | None = None,
    model_sources: list[str] | None = None,
    top_n: int | None = None,
    precomputed_generated_reports: list[GeneratedReport] | None = None,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
) -> ProductionGenerationResult:
    if generation_mode not in {"benchmark", "replay", "production"}:
        raise ValueError("generation_mode must be one of: benchmark, replay, production.")
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    registry = ReportGeneratorRegistry(cfg)
    precomputed_reports = _precomputed_reports_by_key(precomputed_generated_reports)
    generated = generate_candidates(
        registry,
        image_path=image_path,
        modality=modality,
        body_part=body_part,
        case_id=case_id,
        reference_report=None if generation_mode == "production" else reference_report,
        generation_mode=generation_mode,
        model_keys=model_keys,
        model_sources=set(model_sources or []),
        prepared_assets=prepared_assets,
        precomputed_reports=precomputed_reports,
        llm_client=client,
    )
    candidates, structure_failures = _structure_candidates(generated, modality=modality, body_part=body_part)
    comparison = compare_candidate_structures(
        {candidate.candidate_id: candidate.structure for candidate in candidates}
    )
    top_k = select_production_top_k(
        candidates,
        top_k=top_n if top_n is not None else cfg.ranking.top_n,
        ranking_mode=f"{generation_mode}_reference_free",
    )
    fusion_asset = _fusion_image_asset(image_path, prepared_assets)
    fusion = fuse_candidate_reports(
        candidates,
        modality=modality,
        body_part=body_part,
        config=cfg,
        llm_client=client,
        image_path=fusion_asset.path if fusion_asset is not None else None,
        image_asset_kind=fusion_asset.kind if fusion_asset is not None else None,
        image_asset_provenance=(
            {
                "input_asset_capability": fusion_asset.capability,
                "input_asset_sha256": fusion_asset.sha256,
                "input_asset_size_bytes": fusion_asset.size_bytes,
            }
            if fusion_asset is not None
            else None
        ),
        comparison=comparison,
    )
    return ProductionGenerationResult(
        route_plan=generated.route_plan.to_json(),
        candidate_reports=candidates,
        candidate_failures=[failure.to_json() for failure in [*generated.failures, *structure_failures]],
        candidate_structure_comparison=comparison,
        top_k_reports=top_k,
        fusion_report=fusion,
    )


def _structure_candidates(
    generated: CandidateGenerationResult,
    *,
    modality: str,
    body_part: str | None,
) -> tuple[list[CandidateReport], list[CandidateFailure]]:
    decisions = {item.model_key: item for item in generated.route_plan.candidates}
    candidates: list[CandidateReport] = []
    failures: list[CandidateFailure] = []
    for report in generated.reports:
        decision = decisions.get(str(report.metadata.get("candidate_id", "")).split(":", 1)[-1])
        if decision is None:
            decision = next(
                (item for item in generated.route_plan.candidates if item.source == report.source),
                None,
            )
        if decision is None:
            continue
        gated = apply_generation_quality_gate(report, modality=modality, body_part=body_part)
        candidate_id = str(gated.metadata.get("candidate_id") or f"unknown-case:{decision.model_key}")
        try:
            structure = structure_report(gated.report, modality=modality, body_part=body_part)
        except Exception as exc:
            structure = failed_structure_report(
                gated.report,
                modality=modality,
                body_part=body_part,
                error=exc,
            )
        structure_error = str(structure.get("error") or "")
        if structure.get("structure_status") == "failed":
            failures.append(
                CandidateFailure(
                    candidate_id=candidate_id,
                    model=decision.model_key,
                    source=decision.source,
                    route_tier=decision.route_tier,
                    stage="structure",
                    warnings=["candidate_structure_failed", structure_error],
                    runtime_state=decision.runtime_state,
                    validation_state=decision.validation_state,
                    metadata={"structure_status": "failed"},
                )
            )
        candidates.append(
            CandidateReport(
                candidate_id=candidate_id,
                generated=gated,
                route_tier=str(decision.route_tier or "universal"),
                route_reason=decision.route_reason,
                runtime_state=decision.runtime_state,
                validation_state=decision.validation_state,
                structure=structure,
                metadata={
                    "quality_gate": gated.metadata.get("quality_gate", {"passed": True}),
                    "structure_status": structure.get("structure_status"),
                },
            )
        )
    return candidates, failures


def _precomputed_reports_by_key(
    reports: list[GeneratedReport] | None,
) -> dict[str, GeneratedReport]:
    result: dict[str, GeneratedReport] = {}
    for report in reports or []:
        keys = {
            str(report.metadata.get("generator_key") or "").strip(),
            str(report.model or "").strip(),
        }
        for key in keys - {""}:
            result.setdefault(key, report)
    return result


def _fusion_image_asset(
    image_path: str,
    prepared_assets: dict[str, Any] | None,
) -> ImageAsset | None:
    return select_2d_image_asset(image_path, prepared_assets)


__all__ = ["ProductionGenerationResult", "run_candidate_generation", "run_production_generation"]
