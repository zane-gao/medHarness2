from __future__ import annotations

import pytest

from medharness2.schema import GeneratedReport, require_formal_fresh_reports
from medharness2.config import AppConfig, GeneratorConfig
from medharness2.tools.tool8_generate import generate_reports


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("medharness_cli", "exploratory_fresh"),
        ("artifact_reuse", "artifact"),
        ("local_vlm_fallback", "debug_fallback"),
        ("cloud_fallback", "debug_fallback"),
        ("mock_fallback", "mock"),
    ],
)
def test_generated_report_infers_conservative_evidence_tier(source: str, expected: str):
    report = GeneratedReport(model="model", source=source, report="text", modality="cxr")

    assert report.evidence_tier == expected
    assert report.to_json()["schema_version"] == "2.0"


def test_explicit_formal_fresh_tier_is_preserved():
    report = GeneratedReport(
        model="validated-model",
        source="medharness_cli",
        report="text",
        modality="cxr",
        evidence_tier="formal_fresh",
    )

    assert report.evidence_tier == "formal_fresh"


def test_formal_run_gate_rejects_any_non_formal_report():
    reports = [
        GeneratedReport(
            model="validated-model",
            source="medharness_cli",
            report="text",
            modality="cxr",
            evidence_tier="formal_fresh",
        ),
        GeneratedReport(model="artifact", source="artifact_reuse", report="text", modality="cxr"),
    ]

    with pytest.raises(ValueError, match="artifact:artifact"):
        require_formal_fresh_reports(reports)


def test_formal_run_gate_accepts_all_formal_reports():
    reports = [
        GeneratedReport(
            model="validated-model",
            source="medharness_cli",
            report="text",
            modality="cxr",
            evidence_tier="formal_fresh",
            metadata=_formal_metadata(),
        )
    ]

    require_formal_fresh_reports(reports)


def test_formal_run_gate_rejects_empty_report_even_with_formal_tier():
    report = GeneratedReport(
        model="validated-model",
        source="medharness_cli",
        report="",
        modality="cxr",
        evidence_tier="formal_fresh",
        metadata=_formal_metadata(),
    )

    with pytest.raises(ValueError, match="empty_report"):
        require_formal_fresh_reports([report])


def test_formal_run_gate_rejects_missing_frozen_provenance():
    report = GeneratedReport(
        model="validated-model",
        source="medharness_cli",
        report="FINDINGS: Nodule.",
        modality="cxr",
        evidence_tier="formal_fresh",
        metadata={
            "reference_report_used": False,
            "fresh_inference": True,
            "quality_gate": {"passed": True},
        },
    )

    with pytest.raises(ValueError, match="missing_model_sha256"):
        require_formal_fresh_reports([report])


def test_formal_run_gate_rejects_reference_assisted_or_failed_quality_report():
    reference_assisted = GeneratedReport(
        model="validated-model",
        source="medharness_cli",
        report="FINDINGS: Nodule.",
        modality="cxr",
        evidence_tier="formal_fresh",
        metadata={**_formal_metadata(), "reference_report_used": True},
    )
    failed_quality = GeneratedReport(
        model="validated-model",
        source="medharness_cli",
        report="FINDINGS: Nodule.",
        modality="cxr",
        evidence_tier="formal_fresh",
        metadata={**_formal_metadata(), "quality_gate": {"passed": False}},
    )

    with pytest.raises(ValueError, match="reference_report_used"):
        require_formal_fresh_reports([reference_assisted])
    with pytest.raises(ValueError, match="quality_gate_failed"):
        require_formal_fresh_reports([failed_quality])


def test_report_generation_ignores_reference_by_default():
    cfg = AppConfig(
        generator=GeneratorConfig(
            include_legacy_ready_models=False,
            cloud_fallback_enabled=False,
            default_models=["stub"],
            local_models=[
                {
                    "key": "stub",
                    "source": "local_stub",
                    "supported_modalities": ["cxr"],
                    "ready": True,
                }
            ],
        )
    )

    report = generate_reports("image.png", "cxr", reference_report="SECRET REFERENCE", config=cfg)[0]

    assert "Reference report was provided" not in report.report
    assert report.metadata["reference_report_used"] is False
    assert report.evidence_tier == "exploratory_fresh"


def test_explicit_reference_assisted_generation_is_debug_only():
    cfg = AppConfig(
        generator=GeneratorConfig(
            include_legacy_ready_models=False,
            cloud_fallback_enabled=False,
            reference_assisted_generation=True,
            default_models=["stub"],
            local_models=[
                {
                    "key": "stub",
                    "source": "local_stub",
                    "supported_modalities": ["cxr"],
                    "ready": True,
                }
            ],
        )
    )

    report = generate_reports("image.png", "cxr", reference_report="SECRET REFERENCE", config=cfg)[0]

    assert "Reference report was provided" in report.report
    assert report.metadata["reference_report_used"] is True
    assert report.evidence_tier == "debug_fallback"
    assert "reference_assisted_generation" in report.warnings


def _formal_metadata() -> dict[str, object]:
    return {
        "reference_report_used": False,
        "fresh_inference": True,
        "quality_gate": {"passed": True},
        "model_sha256": "a" * 64,
        "model_version": "validated-v1",
        "prompt_version": "reportgen-v1",
        "preprocessing_version": "dicom-v1",
        "formal_validation_id": "validation-2026-07-10",
    }
