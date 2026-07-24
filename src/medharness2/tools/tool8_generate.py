from __future__ import annotations

from medharness2.config import AppConfig, load_config
from medharness2.generators.orchestrator import CandidateGenerationResult, generate_candidates
from medharness2.generators.registry import ReportGeneratorRegistry
from medharness2.llm_client import LLMClient
from medharness2.modality import canonical_modality
from medharness2.schema import GeneratedReport


def generate_reports(
    image_path: str,
    modality: str,
    reference_report: str | None = None,
    model_keys: list[str] | None = None,
    model_sources: list[str] | None = None,
    body_part: str | None = None,
    prepared_assets: dict[str, object] | None = None,
    fallback_image_path: str | None = None,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
    case_id: str | None = None,
    generation_mode: str = "production",
) -> list[GeneratedReport]:
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    modality = canonical_modality(modality)
    generation_reference = (
        reference_report
        if cfg.generator.reference_assisted_generation and generation_mode in {"benchmark", "replay"}
        else None
    )
    generated = generate_candidate_reports(
        image_path=image_path,
        modality=modality,
        body_part=body_part,
        reference_report=generation_reference,
        model_keys=model_keys,
        model_sources=model_sources,
        case_id=case_id,
        generation_mode=generation_mode,
        prepared_assets=prepared_assets,
        config=cfg,
        llm_client=client,
    )
    reports = list(generated.reports)
    failed_attempts = _failed_attempts(generated)
    if not reports and cfg.generator.cloud_fallback_enabled:
        prompt = f"Generate a concise radiology report for modality={modality}, body_part={body_part or 'unknown'}."
        if generation_reference:
            prompt += f"\nReference report for context:\n{generation_reference}"
        text = client.call(
            prompt,
            image_path=fallback_image_path or image_path,
            payload_classification="raw_medical_image",
        )
        fallback_source = _fallback_source(cfg.llm.provider)
        reports.append(
            GeneratedReport(
                model=cfg.llm.model,
                source=fallback_source,
                report=text,
                modality=modality,
                evidence_tier=("mock" if cfg.llm.provider.lower() == "mock" else "exploratory_fresh"),
                    warnings=[
                        f"{fallback_source}_used",
                        "no_compatible_local_generator"
                        if not generated.route_plan.candidates
                        else "compatible_local_generator_returned_no_text",
                    ],
                metadata={
                    "body_part": body_part,
                    "reference_report_used": bool(generation_reference),
                    "fallback_provider": cfg.llm.provider,
                    "fallback_source": fallback_source,
                    "fallback_used": True,
                    "requested_models": model_keys or cfg.generator.default_models,
                    "requested_sources": model_sources or [],
                    "local_attempts": failed_attempts,
                },
            )
        )
    if not reports:
        reports.extend(_failed_reports(generated, modality=modality))
    if not reports:
        reports.append(
            GeneratedReport(
                model="none",
                source="none",
                report="",
                modality=modality,
                warnings=["no_generation_backend_available"],
            )
        )
    return reports


def generate_candidate_reports(
    image_path: str,
    modality: str,
    reference_report: str | None = None,
    model_keys: list[str] | None = None,
    model_sources: list[str] | None = None,
    body_part: str | None = None,
    prepared_assets: dict[str, object] | None = None,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
    case_id: str | None = None,
    generation_mode: str = "production",
) -> CandidateGenerationResult:
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    registry = ReportGeneratorRegistry(cfg)
    return generate_candidates(
        registry,
        image_path=image_path,
        modality=canonical_modality(modality),
        body_part=body_part,
        case_id=case_id,
        reference_report=(
            reference_report
            if cfg.generator.reference_assisted_generation and generation_mode in {"benchmark", "replay"}
            else None
        ),
        generation_mode=generation_mode,
        model_keys=model_keys,
        model_sources=set(model_sources or []),
        prepared_assets=prepared_assets,
        llm_client=client,
    )


def _failed_attempts(generated: CandidateGenerationResult) -> list[dict[str, object]]:
    attempts = [
        {
            "model": failure.model,
            "source": failure.source,
            "warnings": list(failure.warnings),
            "metadata": dict(failure.metadata),
        }
        for failure in generated.failures
    ]
    for decision in generated.route_plan.entries:
        if decision.eligible or decision.excluded_reason in {None, "requested_model_filter", "requested_source_filter"}:
            continue
        attempts.append(
            {
                "model": decision.model_key,
                "source": decision.source,
                "warnings": [decision.excluded_reason],
                "metadata": {
                    "route_tier": decision.route_tier,
                    "route_reason": decision.route_reason,
                    "runtime_state": decision.runtime_state,
                    "validation_state": decision.validation_state,
                },
            }
        )
    return attempts


def _failed_reports(generated: CandidateGenerationResult, *, modality: str) -> list[GeneratedReport]:
    reports = [
        GeneratedReport(
            model=failure.model,
            source=failure.source,
            report="",
            modality=modality,
            warnings=list(failure.warnings),
            metadata=dict(failure.metadata),
        )
        for failure in generated.failures
    ]
    if reports:
        return reports
    for decision in generated.route_plan.entries:
        if decision.eligible or decision.excluded_reason in {None, "requested_model_filter", "requested_source_filter"}:
            continue
        return [
            GeneratedReport(
                model=decision.model_key,
                source=decision.source,
                report="",
                modality=modality,
                warnings=[decision.excluded_reason],
                metadata={
                    "route_tier": decision.route_tier,
                    "route_reason": decision.route_reason,
                    "runtime_state": decision.runtime_state,
                    "validation_state": decision.validation_state,
                },
            )
        ]
    return []


def _fallback_source(provider: str) -> str:
    key = provider.lower()
    if key in {"openai", "openai_responses"}:
        return "cloud_fallback"
    if key in {"local_vlm_cli", "medharness_cli_vlm", "local_hf_vlm", "hf_vlm_local"}:
        return "local_vlm_fallback"
    if key == "mock":
        return "mock_fallback"
    return "llm_fallback"
