from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from medharness2.contracts import (
    CandidateFailureArtifact,
    CandidateReportStructure,
    CandidateStructureSpan,
    FusionReportArtifact,
    ProductionGenerationArtifact,
    export_json_schemas,
)
from medharness2.config import AppConfig, GeneratorConfig
from medharness2.generators.pipeline import run_production_generation
from medharness2.schema import GeneratedReport
from medharness2.tools.report_structure import structure_report


def test_candidate_structure_contract_round_trip_validates_runtime_output():
    payload = structure_report(
        "FINDINGS: An 8 mm right upper lobe nodule is present.",
        modality="cxr",
        body_part="chest",
    )

    validated = CandidateReportStructure.model_validate(payload)

    assert validated.spans[0].measurements[0].normalized_mm == 8.0
    assert validated.template.template_sha256


def test_candidate_structure_span_rejects_offset_length_mismatch():
    with pytest.raises(ValidationError):
        CandidateStructureSpan.model_validate(
            {
                "span_id": 0,
                "subject": "lung",
                "entity": "nodule",
                "attribute": "observation",
                "value_raw": "nodule",
                "observation_status": "present",
                "certainty": "present",
                "laterality": "unknown",
                "severity": None,
                "measurements": [],
                "evidence_snippet": "nodule",
                "start": 0,
                "end": 2,
                "section": "findings",
                "attributes": {},
            }
        )


def test_report_generation_contracts_reject_unknown_failure_stage_and_fusion_status():
    with pytest.raises(ValidationError):
        CandidateFailureArtifact.model_validate(
            {
                "candidate_id": "case:model",
                "model": "model",
                "source": "local",
                "stage": "unknown",
            }
        )
    with pytest.raises(ValidationError):
        FusionReportArtifact.model_validate({"fusion_status": "unknown"})


def test_production_generation_contract_validates_complete_runtime_output(tmp_path: Path):
    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    config = AppConfig(
        generator=GeneratorConfig(
            include_legacy_ready_models=False,
            cloud_fallback_enabled=False,
            default_models=["local-cxr"],
            local_models=[
                {
                    "key": "local-cxr",
                    "source": "local",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "ready": True,
                }
            ],
        )
    )
    report = GeneratedReport(
        model="local-cxr",
        source="local",
        report="FINDINGS: Clear lungs. IMPRESSION: No acute disease.",
        modality="cxr",
        metadata={
            "generator_key": "local-cxr",
            "case_id": "contract-case",
            "fresh_inference": True,
            "reference_report_used": False,
        },
    )

    payload = run_production_generation(
        image_path=str(image),
        modality="cxr",
        body_part="chest",
        case_id="contract-case",
        precomputed_generated_reports=[report],
        config=config,
    ).to_json()
    validated = ProductionGenerationArtifact.model_validate(payload)

    assert validated.schema_version == "2.0"
    assert validated.route_plan.candidate_model_keys == ["local-cxr"]
    assert validated.candidate_reports[0].candidate_id == "contract-case:local-cxr"
    assert validated.generated_reports[0].report.startswith("FINDINGS: Clear lungs.")


def test_production_generation_contract_rejects_candidate_reference_leakage(tmp_path: Path):
    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    config = AppConfig(
        generator=GeneratorConfig(
            include_legacy_ready_models=False,
            cloud_fallback_enabled=False,
            default_models=["local-cxr"],
            local_models=[
                {
                    "key": "local-cxr",
                    "source": "local",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "ready": True,
                }
            ],
        )
    )
    report = GeneratedReport(
        model="local-cxr",
        source="local",
        report="FINDINGS: Clear lungs. IMPRESSION: No acute disease.",
        modality="cxr",
        metadata={
            "generator_key": "local-cxr",
            "case_id": "reference-contract",
            "fresh_inference": True,
            "reference_report_used": False,
        },
    )
    payload = run_production_generation(
        image_path=str(image),
        modality="cxr",
        body_part="chest",
        case_id="reference-contract",
        precomputed_generated_reports=[report],
        config=config,
    ).to_json()
    payload["candidate_reports"][0]["metadata"]["reference_report_used"] = True

    with pytest.raises(ValidationError, match="reference_report_used"):
        ProductionGenerationArtifact.model_validate(payload)


def test_exported_schema_index_includes_report_generation_contracts(tmp_path: Path):
    index = export_json_schemas(tmp_path)

    assert "candidate_report_structure" in index["schemas"]
    assert "candidate_structure_comparison" in index["schemas"]
    assert "candidate_failure" in index["schemas"]
    assert "fusion_report" in index["schemas"]
    assert "production_report_generation" in index["schemas"]
    schema = json.loads((tmp_path / index["schemas"]["candidate_report_structure"]).read_text(encoding="utf-8"))
    assert schema["title"] == "CandidateReportStructure"
