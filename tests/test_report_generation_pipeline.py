from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from medharness2.config import AppConfig, GeneratorConfig, ModelRoleConfig
from medharness2.contracts import CaseEvaluationArtifact
from medharness2.generators.pipeline import run_production_generation
from medharness2.generators.registry import ReportGeneratorRegistry
from medharness2.llm_client import LLMClient
from medharness2.privacy import PrivacyViolation
from medharness2.schema import GeneratedReport
from medharness2.tools.tool8_generate import generate_candidate_reports
from medharness2.workflows.batch_readers import run_batch_readers
from medharness2.workflows.single_case import run_single_case


def _write_png(path: Path) -> None:
    Image.new("L", (4, 4), color=0).save(path)


def _reference_free_generation_config() -> AppConfig:
    return AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["*"],
            external_vlm_enabled=True,
            fusion_enabled=True,
        ),
        model_roles={
            "ocr_primary": ModelRoleConfig(provider="mock", model="ocr-model", max_tokens=256),
            "report_generation": ModelRoleConfig(provider="mock", model="yunwu-candidate", max_tokens=256),
            "report_fusion": ModelRoleConfig(provider="mock", model="yunwu-fusion", max_tokens=256),
        },
    )


def test_production_pipeline_returns_route_candidates_top_k_and_fusion_without_reference_leakage(tmp_path: Path):
    image = tmp_path / "case.png"
    _write_png(image)
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["*"],
            external_vlm_enabled=True,
            external_vlm_model_role="report_generation",
            fusion_enabled=True,
            fusion_model_role="report_fusion",
        ),
        model_roles={
            "report_generation": ModelRoleConfig(provider="mock", model="yunwu-candidate", max_tokens=256),
            "report_fusion": ModelRoleConfig(provider="mock", model="yunwu-fusion", max_tokens=256),
        },
    )

    result = run_production_generation(
        image_path=str(image),
        modality="cxr",
        body_part="chest",
        case_id="case-7",
        reference_report="SECRET HUMAN REFERENCE THAT MUST NOT BE USED",
        config=config,
        llm_client=LLMClient(config),
    )
    payload = result.to_json()

    assert payload["generation_mode"] == "production_reference_free"
    assert payload["route_plan"]["candidate_model_keys"] == ["yunwu_general"]
    assert len(payload["candidate_reports"]) == 1
    assert len(payload["top_k_reports"]) == 1
    assert payload["fusion_report"]["fusion_status"] == "succeeded"
    assert payload["candidate_reports"][0]["metadata"]["reference_report_used"] is False
    assert payload["fusion_report"]["provenance"]["reference_report_used"] is False


def test_single_case_production_mode_writes_generation_contract_without_reference(tmp_path):
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["*"],
            external_vlm_enabled=True,
            fusion_enabled=True,
        ),
        model_roles={
            "report_generation": ModelRoleConfig(provider="mock", model="yunwu-candidate", max_tokens=256),
            "report_fusion": ModelRoleConfig(provider="mock", model="yunwu-fusion", max_tokens=256),
        },
    )
    output = tmp_path / "production.json"
    image = tmp_path / "image.png"
    _write_png(image)

    result = run_single_case(
        image_path=image,
        output_path=output,
        modality="cxr",
        body_part="chest",
        case_id="case-8",
        generation_mode="production",
        config=config,
        llm_client=LLMClient(config),
    )

    assert output.exists()
    assert result["generation_mode"] == "production_reference_free"
    assert result["top_k_reports"]
    assert result["fusion_report"]["fusion_status"] == "succeeded"


@pytest.mark.parametrize("generation_mode", ["benchmark", "replay"])
def test_single_case_nonproduction_without_reference_uses_unified_candidate_contract(
    tmp_path: Path,
    generation_mode: str,
):
    config = _reference_free_generation_config()
    image = tmp_path / "image.png"
    output = tmp_path / f"{generation_mode}.json"
    _write_png(image)

    result = run_single_case(
        image_path=image,
        output_path=output,
        modality="cxr",
        body_part="chest",
        case_id=f"case-{generation_mode}",
        generation_mode=generation_mode,
        config=config,
        llm_client=LLMClient(config),
    )

    validated = CaseEvaluationArtifact.model_validate(result)
    assert validated.generation_mode == generation_mode
    assert result["route_plan"]["generation_mode"] == generation_mode
    assert result["route_plan"]["candidate_model_keys"] == ["yunwu_general"]
    assert len(result["candidate_reports"]) == 1
    assert result["candidate_reports"][0]["source"] == "external_vlm"
    assert result["top_k_reports"][0]["ranking_mode"] == f"{generation_mode}_reference_free"
    assert result["fusion_report"]["fusion_status"] == "succeeded"
    assert result["human_evaluation"] is None
    assert result["generated_evaluations"] == []
    assert result["rankings"] == []
    assert result["pairwise_comparisons"] == []
    assert result["generated_reports"][0]["report"] == result["candidate_reports"][0]["report"]
    assert json.loads(output.read_text(encoding="utf-8")) == result


def test_single_case_benchmark_with_reference_adds_evaluation_to_unified_candidates(
    tmp_path: Path,
):
    config = _reference_free_generation_config()
    image = tmp_path / "image.png"
    output = tmp_path / "benchmark.json"
    _write_png(image)

    result = run_single_case(
        report_text="FINDINGS: No focal opacity. IMPRESSION: No acute cardiopulmonary abnormality.",
        image_path=image,
        output_path=output,
        modality="cxr",
        body_part="chest",
        case_id="case-benchmark-reference",
        generation_mode="benchmark",
        config=config,
        llm_client=LLMClient(config),
    )

    validated = CaseEvaluationArtifact.model_validate(result)
    assert validated.generation_mode == "benchmark"
    assert result["candidate_reports"]
    assert result["top_k_reports"]
    assert result["fusion_report"]["fusion_status"] == "succeeded"
    assert isinstance(result["human_evaluation"], dict)
    assert len(result["generated_evaluations"]) == 1
    assert result["rankings"]
    assert result["pairwise_comparisons"]
    assert result["generated_reports"][0]["report"] == result["candidate_reports"][0]["report"]


def test_single_case_production_mode_honors_top_n_override(tmp_path):
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["*"],
            external_vlm_enabled=True,
            fusion_enabled=True,
            local_models=[
                {
                    "key": "cxr-local",
                    "source": "local",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "ready": True,
                }
            ],
        ),
        model_roles={
            "report_generation": ModelRoleConfig(provider="mock", model="yunwu-candidate", max_tokens=256),
            "report_fusion": ModelRoleConfig(provider="mock", model="yunwu-fusion", max_tokens=256),
        },
    )
    image = tmp_path / "image.png"
    _write_png(image)

    result = run_single_case(
        image_path=image,
        output_path=tmp_path / "production.json",
        modality="cxr",
        body_part="chest",
        case_id="case-9",
        generation_mode="production",
        top_n=1,
        config=config,
        llm_client=LLMClient(config),
    )

    assert len(result["candidate_reports"]) == 2
    assert len(result["top_k_reports"]) == 1


def test_production_pipeline_rejects_precomputed_report_that_used_a_reference(tmp_path: Path):
    image = tmp_path / "case.png"
    _write_png(image)
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
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
    leaked = GeneratedReport(
        model="local-cxr",
        source="local",
        report="FINDINGS: This text came from a human reference.",
        modality="cxr",
        metadata={"generator_key": "local-cxr", "reference_report_used": True},
    )

    result = run_production_generation(
        image_path=str(image),
        modality="cxr",
        body_part="chest",
        case_id="reference-leak",
        precomputed_generated_reports=[leaked],
        config=config,
    ).to_json()

    assert result["candidate_reports"] == []
    assert result["top_k_reports"] == []
    assert result["fusion_report"]["fusion_status"] == "disabled"
    assert result["candidate_failures"][0]["warnings"] == ["precomputed_reference_not_allowed"]


def test_tool8_production_never_forwards_reference_to_candidate_generation(monkeypatch: pytest.MonkeyPatch):
    observed_references: list[str | None] = []
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            reference_assisted_generation=True,
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

    def record_generate(self, entry, image_path, modality, *, reference_report=None, **kwargs):
        del self, image_path, kwargs
        observed_references.append(reference_report)
        return GeneratedReport(
            model=entry.key,
            source=entry.source,
            report="FINDINGS: Clear lungs.",
            modality=modality,
            metadata={"reference_report_used": reference_report is not None},
        )

    monkeypatch.setattr(ReportGeneratorRegistry, "generate", record_generate)

    result = generate_candidate_reports(
        "image.png",
        "cxr",
        body_part="chest",
        case_id="production-reference-boundary",
        reference_report="SECRET HUMAN REFERENCE",
        generation_mode="production",
        config=config,
    )

    assert len(result.reports) == 1
    assert observed_references == [None]


def test_single_case_benchmark_does_not_forward_reference_without_explicit_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    image = tmp_path / "case.png"
    report = tmp_path / "reference.txt"
    output = tmp_path / "case.json"
    _write_png(image)
    report.write_text("FINDINGS: Mild opacity. IMPRESSION: Mild opacity.", encoding="utf-8")
    observed_references: list[str | None] = []
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["local-cxr"],
            local_models=[
                {
                    "key": "local-cxr",
                    "source": "local",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "input_capabilities": ["image_2d"],
                    "ready": True,
                }
            ],
        )
    )

    def record_generate(self, entry, image_path, modality, *, reference_report=None, **kwargs):
        del self, image_path, kwargs
        observed_references.append(reference_report)
        return GeneratedReport(
            model=entry.key,
            source=entry.source,
            report="FINDINGS: Clear lungs. IMPRESSION: No acute disease.",
            modality=modality,
            metadata={"reference_report_used": reference_report is not None},
        )

    monkeypatch.setattr(ReportGeneratorRegistry, "generate", record_generate)

    result = run_single_case(
        report_path=report,
        image_path=image,
        output_path=output,
        modality="cxr",
        body_part="chest",
        config=config,
        llm_client=LLMClient(config),
    )

    assert observed_references == [None]
    assert result["human_evaluation"] is not None
    assert result["generated_reports"][0]["metadata"]["reference_report_used"] is False


@pytest.mark.parametrize(
    ("source", "metadata_update", "expected_warning"),
    [
        ("local", {"fresh_inference": False}, "precomputed_fresh_inference_unverified"),
        ("local", {"case_id": "other-case"}, "precomputed_case_id_mismatch"),
        ("artifact_reuse", {}, "precomputed_source_mismatch"),
        ("local", {"generator_key": "other-model"}, "precomputed_generator_key_mismatch"),
    ],
)
def test_production_pipeline_rejects_untrusted_precomputed_provenance(
    tmp_path: Path,
    source: str,
    metadata_update: dict[str, object],
    expected_warning: str,
):
    image = tmp_path / "case.png"
    _write_png(image)
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
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
    metadata = {
        "generator_key": "local-cxr",
        "case_id": "trusted-precomputed",
        "reference_report_used": False,
        "fresh_inference": True,
    }
    metadata.update(metadata_update)
    report = GeneratedReport(
        model="local-cxr",
        source=source,
        report="FINDINGS: Precomputed report.",
        modality="cxr",
        metadata=metadata,
    )

    result = run_production_generation(
        image_path=str(image),
        modality="cxr",
        body_part="chest",
        case_id="trusted-precomputed",
        precomputed_generated_reports=[report],
        config=config,
    ).to_json()

    assert result["candidate_reports"] == []
    assert expected_warning in result["candidate_failures"][0]["warnings"]


def test_production_pipeline_does_not_send_missing_asset_to_external_vlm(tmp_path: Path):
    class RecordingClient:
        def __init__(self) -> None:
            self.calls = 0

        def call(self, *args: object, **kwargs: object) -> str:
            self.calls += 1
            return "FINDINGS: Should not be produced."

    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["*"],
            external_vlm_enabled=True,
        ),
        model_roles={
            "report_generation": ModelRoleConfig(provider="mock", model="yunwu-candidate", max_tokens=256),
        },
    )
    client = RecordingClient()

    result = run_production_generation(
        image_path=str(tmp_path / "missing.png"),
        modality="cxr",
        body_part="chest",
        case_id="missing-asset",
        config=config,
        llm_client=client,
    ).to_json()

    assert client.calls == 0
    assert result["candidate_reports"] == []
    route_entry = result["route_plan"]["entries"][0]
    assert route_entry["model_key"] == "yunwu_general"
    assert route_entry["excluded_reason"] == "input_asset_incompatible"


def test_production_pipeline_uses_explicit_contact_sheet_for_ct_candidate_and_fusion(tmp_path: Path):
    contact_sheet = tmp_path / "contact_sheet.png"
    volume = tmp_path / "study.nii.gz"
    _write_png(contact_sheet)
    volume.write_bytes(b"volume")

    class RecordingClient:
        def __init__(self) -> None:
            self.image_paths: list[str | None] = []

        def call(self, prompt: str, image_path: str | None = None, **kwargs: object) -> str:
            del prompt, kwargs
            self.image_paths.append(image_path)
            return "FINDINGS: No acute intracranial hemorrhage. IMPRESSION: No acute abnormality."

    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["*"],
            external_vlm_enabled=True,
            fusion_enabled=True,
        ),
        model_roles={
            "report_generation": ModelRoleConfig(provider="mock", model="yunwu-candidate", max_tokens=256),
            "report_fusion": ModelRoleConfig(provider="mock", model="yunwu-fusion", max_tokens=256),
        },
    )
    client = RecordingClient()

    result = run_production_generation(
        image_path=str(volume),
        modality="ct",
        body_part="head",
        case_id="ct-contact-sheet",
        prepared_assets={"volume_path": str(volume), "contact_sheet": str(contact_sheet)},
        config=config,
        llm_client=client,
    )
    payload = result.to_json()

    assert client.image_paths == [str(contact_sheet), str(contact_sheet)]
    assert payload["candidate_reports"][0]["metadata"]["input_asset"] == str(contact_sheet)
    assert payload["candidate_reports"][0]["metadata"]["input_asset_kind"] == "contact_sheet"
    expected_sha256 = hashlib.sha256(contact_sheet.read_bytes()).hexdigest()
    assert payload["candidate_reports"][0]["metadata"]["input_asset_sha256"] == expected_sha256
    assert payload["fusion_report"]["used_image_asset"] == str(contact_sheet)
    assert payload["fusion_report"]["provenance"]["input_asset_kind"] == "contact_sheet"
    assert payload["fusion_report"]["provenance"]["input_asset_capability"] == "image_2d"
    assert payload["fusion_report"]["provenance"]["input_asset_sha256"] == expected_sha256
    assert payload["fusion_report"]["provenance"]["input_asset_size_bytes"] == contact_sheet.stat().st_size


def test_batch_production_generates_candidates_without_a_reference_report(tmp_path: Path):
    image = tmp_path / "case.png"
    _write_png(image)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "case_id": "production-case",
                "reader": "reader-a",
                "modality": "cxr",
                "body_part": "chest",
                "report_pdf": "",
                "report_text": "",
                "image_paths": [str(image)],
                "derived_assets": {"primary_image": str(image)},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["*"],
            external_vlm_enabled=True,
            fusion_enabled=True,
        ),
        model_roles={
            "report_generation": ModelRoleConfig(provider="mock", model="yunwu-candidate", max_tokens=256),
            "report_fusion": ModelRoleConfig(provider="mock", model="yunwu-fusion", max_tokens=256),
        },
    )

    result = run_batch_readers(
        manifest,
        tmp_path / "batch.json",
        generation_mode="production",
        config=config,
        llm_client=LLMClient(config),
    )

    assert result["generation_mode"] == "production"
    assert result["failed_case_count"] == 0
    assert result["cases"][0]["candidate_report_count"] == 1
    assert result["cases"][0]["top_k_report_count"] == 1
    assert result["cases"][0]["fusion_status"] == "succeeded"
    case_payload = json.loads(Path(result["cases"][0]["workflow1_output"]).read_text(encoding="utf-8"))
    assert case_payload["generation_mode"] == "production_reference_free"
    assert "human_evaluation" not in case_payload


@pytest.mark.parametrize("generation_mode", ["benchmark", "replay"])
def test_batch_nonproduction_without_reference_uses_generation_only_contract(
    tmp_path: Path,
    generation_mode: str,
):
    image = tmp_path / "case.png"
    _write_png(image)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "case_id": f"{generation_mode}-case",
                "reader": "reader-a",
                "modality": "cxr",
                "body_part": "chest",
                "report_pdf": "",
                "report_text": "",
                "image_paths": [str(image)],
                "derived_assets": {"primary_image": str(image)},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    config = _reference_free_generation_config()

    result = run_batch_readers(
        manifest,
        tmp_path / "batch.json",
        generation_mode=generation_mode,
        config=config,
        llm_client=LLMClient(config),
    )

    assert result["artifact_type"] == f"{generation_mode}_batch_report_generation"
    assert result["generation_mode"] == generation_mode
    assert result["failed_case_count"] == 0
    assert result["case_count"] == 1
    assert result["cases"][0]["candidate_report_count"] == 1
    assert result["cases"][0]["reference_available"] is False
    assert result["cases"][0]["reference_evaluated"] is False
    assert result["denominator"]["reference_available_case_count"] == 0
    assert result["denominator"]["reference_evaluated_case_count"] == 0
    assert result["statistics"] == {}
    case_payload = json.loads(
        Path(result["cases"][0]["workflow1_output"]).read_text(encoding="utf-8")
    )
    assert CaseEvaluationArtifact.model_validate(case_payload).generation_mode == generation_mode
    assert case_payload["candidate_reports"]
    assert case_payload["human_evaluation"] is None


def test_batch_production_groups_local_candidates_without_a_reference_report(monkeypatch, tmp_path: Path):
    image_a = tmp_path / "case-a.png"
    image_b = tmp_path / "case-b.png"
    _write_png(image_a)
    _write_png(image_b)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "\n".join(
            json.dumps(
                {
                    "case_id": case_id,
                    "reader": "reader-a",
                    "modality": "cxr",
                    "body_part": "chest",
                    "report_pdf": "",
                    "report_text": "",
                    "image_paths": [str(image)],
                    "derived_assets": {"primary_image": str(image)},
                }
            )
            for case_id, image in (("case-a", image_a), ("case-b", image_b))
        )
        + "\n",
        encoding="utf-8",
    )
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["local-cxr"],
            local_models=[
                {
                    "key": "local-cxr",
                    "source": "medharness_cli",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "input_capabilities": ["image_2d"],
                    "report_trained": True,
                    "fresh_inference": True,
                    "ready": True,
                }
            ],
        )
    )
    batches: list[list[str]] = []
    include_failures_values: list[bool] = []

    def fake_generate_batch(self, entry, cases, *, include_failures=False):
        del self
        batches.append([str(case["case_id"]) for case in cases])
        include_failures_values.append(include_failures)
        return {
            str(case["case_id"]): GeneratedReport(
                model=entry.key,
                source=entry.source,
                report="FINDINGS: Clear lungs. IMPRESSION: No acute cardiopulmonary abnormality.",
                modality=str(case["modality"]),
                metadata={"reference_report_used": False},
            )
            for case in cases
        }

    def unexpected_generate(self, *args, **kwargs):
        raise AssertionError("production batch must reuse grouped local output")

    monkeypatch.setattr(ReportGeneratorRegistry, "generate_batch", fake_generate_batch)
    monkeypatch.setattr(ReportGeneratorRegistry, "generate", unexpected_generate)

    result = run_batch_readers(
        manifest,
        tmp_path / "batch.json",
        generation_mode="production",
        config=config,
    )

    assert batches == [["case-a", "case-b"]]
    assert include_failures_values == [True]
    assert result["failed_case_count"] == 0
    assert [case["candidate_report_count"] for case in result["cases"]] == [1, 1]


def test_batch_production_binds_model_groups_to_capability_specific_assets(monkeypatch, tmp_path: Path):
    image = tmp_path / "preview.png"
    volume = tmp_path / "study.npy"
    _write_png(image)
    np.save(volume, np.zeros((2, 4, 4), dtype=np.float32))
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "case_id": "mixed-assets",
                "reader": "reader-a",
                "modality": "ct",
                "body_part": "abdomen",
                "report_pdf": "",
                "report_text": "",
                "image_paths": [str(image)],
                "volume_path": str(volume),
                "derived_assets": {"primary_image": str(image)},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["image-model", "volume-model"],
            local_models=[
                {
                    "key": "image-model",
                    "source": "medharness_cli",
                    "supported_modalities": ["ct"],
                    "supported_body_parts": ["abdomen"],
                    "input_capabilities": ["image_2d"],
                    "report_trained": True,
                    "fresh_inference": True,
                    "ready": True,
                },
                {
                    "key": "volume-model",
                    "source": "medharness_cli",
                    "supported_modalities": ["ct"],
                    "supported_body_parts": ["abdomen"],
                    "input_capabilities": ["volume"],
                    "report_trained": True,
                    "fresh_inference": True,
                    "ready": True,
                },
            ],
        )
    )
    observed: dict[str, str] = {}

    def fake_generate_batch(self, entry, cases, *, include_failures=False):
        del self
        assert include_failures is True
        observed[entry.key] = str(cases[0]["image_path"])
        return {
            str(case["case_id"]): GeneratedReport(
                model=entry.key,
                source=entry.source,
                report="FINDINGS: No acute abnormality.",
                modality=str(case["modality"]),
                metadata={"reference_report_used": False},
            )
            for case in cases
        }

    monkeypatch.setattr(ReportGeneratorRegistry, "generate_batch", fake_generate_batch)

    result = run_batch_readers(
        manifest,
        tmp_path / "batch.json",
        generation_mode="production",
        config=config,
    )

    assert result["failed_case_count"] == 0
    assert observed == {"image-model": str(image), "volume-model": str(volume)}


def test_batch_production_marks_zero_generated_candidates_as_a_failed_case(tmp_path: Path):
    image = tmp_path / "case.png"
    _write_png(image)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "case_id": "no-candidate",
                "reader": "reader-a",
                "modality": "cxr",
                "body_part": "chest",
                "report_pdf": "",
                "report_text": "",
                "image_paths": [str(image)],
                "derived_assets": {"primary_image": str(image)},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["missing-model"],
        )
    )

    result = run_batch_readers(
        manifest,
        tmp_path / "batch.json",
        generation_mode="production",
        config=config,
    )

    assert result["case_count"] == 0
    assert result["failed_case_count"] == 1
    assert result["failed_cases"][0]["error"] == "no_candidate_generated"


def test_production_pipeline_isolates_one_candidate_structure_failure(monkeypatch: pytest.MonkeyPatch):
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["good", "bad"],
            fusion_enabled=True,
            local_models=[
                {
                    "key": key,
                    "source": "local",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "ready": True,
                }
                for key in ("good", "bad")
            ],
        ),
        model_roles={"report_fusion": ModelRoleConfig(provider="mock", model="yunwu-fusion", max_tokens=256)},
    )
    reports = [
        GeneratedReport(
            model="good",
            source="local",
            report="FINDINGS: No pneumothorax. IMPRESSION: No acute disease.",
            modality="cxr",
                metadata={
                    "generator_key": "good",
                    "case_id": "structure-isolation",
                    "fresh_inference": True,
                    "reference_report_used": False,
                },
        ),
        GeneratedReport(
            model="bad",
            source="local",
            report="FINDINGS: STRUCTURE FAILURE SENTINEL. IMPRESSION: Report remains available.",
            modality="cxr",
                metadata={
                    "generator_key": "bad",
                    "case_id": "structure-isolation",
                    "fresh_inference": True,
                    "reference_report_used": False,
                },
        ),
    ]

    from medharness2.generators import pipeline as pipeline_module

    original = pipeline_module.structure_report

    def fail_one(report_text: str, **kwargs: object) -> dict[str, object]:
        if "STRUCTURE FAILURE SENTINEL" in report_text:
            raise ValueError("injected structure failure")
        return original(report_text, **kwargs)

    monkeypatch.setattr(pipeline_module, "structure_report", fail_one)

    result = run_production_generation(
        image_path="case.png",
        modality="cxr",
        body_part="chest",
        case_id="structure-isolation",
        precomputed_generated_reports=reports,
        top_n=2,
        config=config,
        llm_client=LLMClient(config),
    ).to_json()

    assert len(result["candidate_reports"]) == 2
    failed = next(item for item in result["candidate_reports"] if item["model"] == "bad")
    assert failed["report"].startswith("FINDINGS: STRUCTURE FAILURE SENTINEL")
    assert failed["structure"]["structure_status"] == "failed"
    assert any(item["stage"] == "structure" and item["model"] == "bad" for item in result["candidate_failures"])
    assert [item["model"] for item in result["top_k_reports"]] == ["good"]
    assert result["fusion_report"]["fusion_status"] == "succeeded"


def test_production_pipeline_preserves_candidates_when_fusion_is_blocked(tmp_path: Path):
    class FailingClient:
        def call(self, *args: object, **kwargs: object) -> str:
            del args, kwargs
            raise PrivacyViolation("blocked fusion payload")

    image = tmp_path / "image.png"
    _write_png(image)
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["local-cxr"],
            fusion_enabled=True,
            local_models=[
                {
                    "key": "local-cxr",
                    "source": "local",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "input_capabilities": ["image_2d"],
                    "ready": True,
                }
            ],
        ),
        model_roles={"report_fusion": ModelRoleConfig(provider="mock", model="yunwu-fusion", max_tokens=256)},
    )
    report = GeneratedReport(
        model="local-cxr",
        source="local",
        report="FINDINGS: Clear lungs. IMPRESSION: No acute disease.",
        modality="cxr",
        metadata={
            "generator_key": "local-cxr",
            "case_id": "fusion-isolation",
            "fresh_inference": True,
            "reference_report_used": False,
        },
    )

    result = run_production_generation(
        image_path=str(image),
        modality="cxr",
        body_part="chest",
        case_id="fusion-isolation",
        precomputed_generated_reports=[report],
        config=config,
        llm_client=FailingClient(),
    ).to_json()

    assert len(result["candidate_reports"]) == 1
    assert len(result["top_k_reports"]) == 1
    assert result["fusion_report"]["fusion_status"] == "failed"
