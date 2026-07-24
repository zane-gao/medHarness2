from __future__ import annotations

import json
from pathlib import Path

from medharness2.config import AppConfig, GeneratorConfig, LLMConfig
from medharness2.contracts import ProductionGenerationArtifact
from medharness2.llm_client import LLMClient
from medharness2.schema import GeneratedReport
from medharness2.workflows.single_case import run_single_case


def test_single_case_production_output_round_trips_through_generation_contract(tmp_path: Path):
    image = tmp_path / "image.png"
    output = tmp_path / "production.json"
    image.write_bytes(b"png")
    config = AppConfig(
        llm=LLMConfig(provider="mock"),
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["local-stub"],
            local_models=[
                {
                    "key": "local-stub",
                    "source": "local",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "ready": True,
                }
            ],
        ),
    )
    report = GeneratedReport(
        model="local-stub",
        source="local",
        report="FINDINGS: Clear lungs. IMPRESSION: No acute disease.",
        modality="cxr",
        metadata={
            "generator_key": "local-stub",
            "case_id": "single-case-contract",
            "fresh_inference": True,
            "reference_report_used": False,
        },
    )

    result = run_single_case(
        image_path=image,
        output_path=output,
        modality="cxr",
        body_part="chest",
        case_id="single-case-contract",
        generation_mode="production",
        precomputed_generated_reports=[report],
        config=config,
        llm_client=LLMClient(config),
    )
    persisted = json.loads(output.read_text(encoding="utf-8"))

    for payload in (result, persisted):
        validated = ProductionGenerationArtifact.model_validate(payload)
        assert validated.case_id == "single-case-contract"
        assert validated.input["image_path"] == str(image)
        assert validated.errors == []
        assert validated.generated_evaluations == []
        assert validated.rankings == []
        assert validated.pairwise_comparisons == []
