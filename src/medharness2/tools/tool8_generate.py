from __future__ import annotations

from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.generators.registry import ReportGeneratorRegistry
from medharness2.llm_client import LLMClient
from medharness2.schema import GeneratedReport


def generate_reports(
    image_path: str,
    modality: str,
    reference_report: str | None = None,
    model_keys: list[str] | None = None,
    body_part: str | None = None,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
) -> list[GeneratedReport]:
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    registry = ReportGeneratorRegistry(cfg)
    reports: list[GeneratedReport] = []
    selected_entries = registry.select(modality, requested=model_keys, body_part=body_part)
    for entry in selected_entries:
        generated = registry.generate(entry, image_path, modality, reference_report=reference_report, body_part=body_part)
        if generated.report:
            reports.append(generated)
    if not reports and cfg.generator.cloud_fallback_enabled:
        prompt = f"Generate a concise radiology report for modality={modality}, body_part={body_part or 'unknown'}."
        if reference_report:
            prompt += f"\nReference report for context:\n{reference_report}"
        text = client.call(prompt, image_path=image_path)
        reports.append(
            GeneratedReport(
                model=cfg.llm.model,
                source="cloud_fallback",
                report=text,
                modality=modality,
                warnings=[
                    "cloud_fallback_used",
                    "no_compatible_local_generator" if not selected_entries else "compatible_local_generator_returned_no_text",
                ],
                metadata={"body_part": body_part, "requested_models": model_keys or cfg.generator.default_models},
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
