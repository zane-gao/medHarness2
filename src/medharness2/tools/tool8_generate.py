from __future__ import annotations

from typing import Any

from medharness2.config import AppConfig, load_config
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
    fallback_image_path: str | None = None,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
    case_id: str | None = None,
) -> list[GeneratedReport]:
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    modality = canonical_modality(modality)
    registry = ReportGeneratorRegistry(cfg)
    generation_reference = reference_report if cfg.generator.reference_assisted_generation else None
    reports: list[GeneratedReport] = []
    selected_entries = registry.select(
        modality,
        requested=model_keys,
        body_part=body_part,
        sources=set(model_sources or []),
    )
    failed_attempts: list[dict[str, object]] = []
    for entry in selected_entries:
        generated = registry.generate(
            entry,
            image_path,
            modality,
            reference_report=generation_reference,
            body_part=body_part,
            case_id=case_id,
        )
        if generated.report:
            reports.append(generated)
        else:
            failed_attempts.append(
                {
                    "model": generated.model or entry.key,
                    "source": generated.source or entry.source,
                    "warnings": generated.warnings,
                    "metadata": generated.metadata,
                }
            )
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
                    "no_compatible_local_generator" if not selected_entries else "compatible_local_generator_returned_no_text",
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


def _fallback_source(provider: str) -> str:
    key = provider.lower()
    if key in {"openai", "openai_responses"}:
        return "cloud_fallback"
    if key in {"local_vlm_cli", "medharness_cli_vlm", "local_hf_vlm", "hf_vlm_local"}:
        return "local_vlm_fallback"
    if key == "mock":
        return "mock_fallback"
    return "llm_fallback"
