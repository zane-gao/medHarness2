from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from PIL import Image

from medharness2.generators.registry import GeneratorEntry
from medharness2.generators.routing import build_route_plan
from medharness2.generators.orchestrator import generate_candidates
from medharness2.config import AppConfig, GeneratorConfig, ModelRoleConfig
from medharness2.generators.registry import ReportGeneratorRegistry
from medharness2.generators.assets import available_input_capabilities
from medharness2.schema import GeneratedReport
from medharness2.tools.tool8_generate import generate_reports


def _entry(
    key: str,
    *,
    modalities: list[str],
    body_parts: list[str],
    runtime_state: str = "runnable",
    source: str = "medharness_cli",
    cross_modality_allowed: bool = False,
    is_universal: bool = False,
    input_capabilities: list[str] | None = None,
    validation_state: str = "unvalidated",
) -> GeneratorEntry:
    return GeneratorEntry(
        key=key,
        title=key,
        source=source,
        supported_modalities=modalities,
        supported_body_parts=body_parts,
        runtime_state=runtime_state,
        validation_state=validation_state,
        cross_modality_allowed=cross_modality_allowed,
        is_universal=is_universal,
        input_capabilities=input_capabilities or [],
    )


def test_route_plan_collects_all_matching_tiers_including_same_modality_specialists():
    entries = [
        _entry("ct-abdomen", modalities=["ct"], body_parts=["abdomen"]),
        _entry("ct-general", modalities=["ct"], body_parts=["unknown"]),
        _entry(
            "abdomen-cross-modality",
            modalities=["mri"],
            body_parts=["abdomen"],
            cross_modality_allowed=True,
        ),
        _entry("yunwu", modalities=["unknown"], body_parts=["unknown"], source="external_vlm", is_universal=True),
        _entry("ct-head", modalities=["ct"], body_parts=["head"]),
        _entry("blocked", modalities=["ct"], body_parts=["abdomen"], runtime_state="preflight_only"),
    ]

    plan = build_route_plan(
        entries,
        modality="ct",
        body_part="abdomen",
        case_id="case-1",
        generation_mode="production",
        available_input_capabilities={"volume"},
    )

    selected = {item.model_key: item.route_tier for item in plan.candidates}
    assert selected == {
        "ct-abdomen": "exact_modality_body_part",
        "ct-general": "same_modality",
        "ct-head": "same_modality",
        "abdomen-cross-modality": "same_body_part_cross_modality",
        "yunwu": "universal",
    }
    decisions = {item.model_key: item for item in plan.entries}
    assert decisions["ct-head"].route_reason == "modality_match_body_part_not_exact"
    assert decisions["blocked"].excluded_reason == "runtime_not_runnable"


def test_route_plan_requires_explicit_cross_modality_and_rejects_unknown_input_for_specialists():
    entries = [
        _entry("brain-mri", modalities=["mri"], body_parts=["brain"]),
        _entry("spine-mri", modalities=["mri"], body_parts=["spine"]),
        _entry("spine-ct", modalities=["ct"], body_parts=["spine"]),
        _entry("universal", modalities=["unknown"], body_parts=["unknown"], is_universal=True),
    ]

    spine_plan = build_route_plan(
        entries,
        modality="mri",
        body_part="spine",
        case_id="case-2",
        generation_mode="production",
    )
    unknown_plan = build_route_plan(
        entries,
        modality="unknown",
        body_part="unknown",
        case_id="case-3",
        generation_mode="production",
    )

    assert {item.model_key for item in spine_plan.candidates} == {
        "brain-mri",
        "spine-mri",
        "universal",
    }
    assert {item.model_key for item in unknown_plan.candidates} == {"universal"}
    decisions = {item.model_key: item for item in spine_plan.entries}
    assert decisions["brain-mri"].route_tier == "same_modality"
    assert decisions["brain-mri"].route_reason == "modality_match_body_part_not_exact"
    assert decisions["spine-ct"].excluded_reason == "cross_modality_not_declared"


def test_route_plan_allows_artifact_only_for_exact_case_replay_or_benchmark():
    artifact = _entry(
        "artifact",
        modalities=["cxr"],
        body_parts=["chest"],
        source="artifact_reuse",
    )

    production = build_route_plan(
        [artifact],
        modality="cxr",
        body_part="chest",
        case_id="case-a",
        generation_mode="production",
    )
    missing_case = build_route_plan(
        [artifact],
        modality="cxr",
        body_part="chest",
        case_id=None,
        generation_mode="benchmark",
    )
    replay = build_route_plan(
        [artifact],
        modality="cxr",
        body_part="chest",
        case_id="case-a",
        generation_mode="replay",
    )

    assert production.entries[0].excluded_reason == "artifact_mode_not_enabled"
    assert missing_case.entries[0].excluded_reason == "artifact_case_id_required"
    assert [item.model_key for item in replay.candidates] == ["artifact"]


def test_route_plan_excludes_models_without_a_compatible_input_asset():
    volume_model = _entry(
        "volume-model",
        modalities=["ct"],
        body_parts=["abdomen"],
        input_capabilities=["volume"],
    )

    plan = build_route_plan(
        [volume_model],
        modality="ct",
        body_part="abdomen",
        case_id="case-4",
        generation_mode="production",
        available_input_capabilities={"image_2d"},
    )

    assert plan.candidates == ()
    assert plan.entries[0].excluded_reason == "input_asset_incompatible"


def test_feature_embedding_assets_are_distinct_from_images_and_volumes(tmp_path):
    h5py = pytest.importorskip("h5py", reason="h5py is required for HDF5 validation")
    feature_path = tmp_path / "case.h5"
    with h5py.File(feature_path, "w") as handle:
        handle.create_dataset("features", data=np.arange(12, dtype=np.float32).reshape(3, 4))
    assert available_input_capabilities(
        str(feature_path),
        {"feature_path": str(feature_path)},
    ) == {"feature_embedding"}

    feature_model = _entry(
        "feature-model",
        modalities=["pathology"],
        body_parts=["wsi"],
        input_capabilities=["feature_embedding"],
    )
    plan = build_route_plan(
        [feature_model],
        modality="pathology",
        body_part="wsi",
        case_id="case-feature",
        generation_mode="production",
        available_input_capabilities=available_input_capabilities(
            str(feature_path),
            {"feature_path": str(feature_path)},
        ),
    )

    assert [item.model_key for item in plan.candidates] == ["feature-model"]


def test_available_input_capabilities_rejects_corrupt_image_payload(tmp_path):
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not-a-decodable-image")

    assert available_input_capabilities(str(corrupt), {"primary_image": str(corrupt)}) == set()


def test_candidate_orchestrator_binds_assets_by_model_capability(monkeypatch, tmp_path):
    image = tmp_path / "preview.png"
    volume = tmp_path / "volume.npy"
    Image.new("L", (4, 4), color=0).save(image)
    np.save(volume, np.zeros((2, 4, 4), dtype=np.float32))
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["image-model", "volume-model"],
            local_models=[
                {
                    "key": "image-model",
                    "source": "local",
                    "supported_modalities": ["ct"],
                    "supported_body_parts": ["abdomen"],
                    "input_capabilities": ["image_2d"],
                    "ready": True,
                },
                {
                    "key": "volume-model",
                    "source": "local",
                    "supported_modalities": ["ct"],
                    "supported_body_parts": ["abdomen"],
                    "input_capabilities": ["volume"],
                    "ready": True,
                },
            ],
        )
    )
    registry = ReportGeneratorRegistry(config)
    observed: dict[str, str] = {}

    def record_generate(entry, image_path, modality, **kwargs):
        del kwargs
        observed[entry.key] = image_path
        return GeneratedReport(
            model=entry.key,
            source=entry.source,
            report="FINDINGS: Test report.",
            modality=modality,
        )

    monkeypatch.setattr(registry, "generate", record_generate)

    result = generate_candidates(
        registry,
        image_path=str(image),
        modality="ct",
        body_part="abdomen",
        case_id="asset-binding",
        prepared_assets={"primary_image": str(image), "volume_path": str(volume)},
    )

    assert observed == {"image-model": str(image), "volume-model": str(volume)}
    assert {report.metadata["input_asset_kind"] for report in result.reports} == {
        "primary_image",
        "volume_path",
    }


def test_explicit_local_model_filter_keeps_yunwu_as_forced_universal_candidate(tmp_path):
    image = tmp_path / "case.png"
    Image.new("L", (4, 4), color=0).save(image)
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["local-cxr"],
            external_vlm_enabled=True,
            local_models=[
                {
                    "key": "local-cxr",
                    "source": "local",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "ready": True,
                }
            ],
        ),
        model_roles={
            "report_generation": ModelRoleConfig(provider="mock", model="yunwu-candidate", max_tokens=256),
        },
    )
    registry = ReportGeneratorRegistry(config)

    plan = registry.plan_routes(
        "cxr",
        body_part="chest",
        requested=["local-cxr"],
        image_path=str(image),
        case_id="forced-yunwu",
        generation_mode="production",
    )

    assert [item.model_key for item in plan.candidates] == ["local-cxr", "yunwu_general"]


def test_declared_generic_imaging_modality_routes_as_universal():
    generic_model = _entry(
        "generic-model",
        modalities=["medical_image"],
        body_parts=["unknown"],
        input_capabilities=["image_2d"],
    )

    plan = build_route_plan(
        [generic_model],
        modality="mammography",
        body_part="breast",
        case_id="case-generic",
        generation_mode="production",
        available_input_capabilities={"image_2d"},
    )

    assert [item.model_key for item in plan.candidates] == ["generic-model"]
    assert plan.candidates[0].route_tier == "universal"


def test_route_plan_excludes_models_with_an_explicit_quality_block():
    model = _entry(
        "quality-blocked-brain-mri",
        modalities=["mri"],
        body_parts=["brain"],
        runtime_state="smoke_verified",
        validation_state="quality_blocked",
        input_capabilities=["volume"],
    )

    plan = build_route_plan(
        [model],
        modality="mri",
        body_part="brain",
        case_id="case-quality-blocked",
        generation_mode="production",
        available_input_capabilities={"volume"},
    )

    assert plan.candidates == ()
    assert plan.entries[0].excluded_reason == "validation_quality_blocked"


def test_candidate_orchestrator_preserves_successes_when_one_candidate_fails(monkeypatch):
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["*"],
            local_models=[
                {
                    "key": "good",
                    "source": "local",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "ready": True,
                },
                {
                    "key": "bad",
                    "source": "local",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "ready": True,
                },
            ],
        )
    )
    registry = ReportGeneratorRegistry(config)

    def fake_generate(entry, image_path, modality, **kwargs):
        if entry.key == "bad":
            return GeneratedReport(
                model="bad",
                source="local",
                report="",
                modality=modality,
                warnings=["simulated_failure"],
            )
        return GeneratedReport(
            model="good",
            source="local",
            report="FINDINGS: Clear lungs. IMPRESSION: Normal chest.",
            modality=modality,
        )

    monkeypatch.setattr(registry, "generate", fake_generate)

    result = generate_candidates(
        registry,
        image_path="image.png",
        modality="cxr",
        body_part="chest",
        case_id="case-5",
    )

    assert result.route_plan.to_json()["candidate_model_keys"] == ["bad", "good"]
    assert [report.model for report in result.reports] == ["good"]
    assert result.failures[0].model == "bad"
    assert result.failures[0].warnings == ["simulated_failure"]


def test_candidate_orchestrator_limits_local_candidates_per_device(monkeypatch):
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["*"],
            candidate_max_workers=2,
            local_max_workers=1,
            local_models=[
                {
                    "key": "first-local",
                    "source": "local",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "device": "cuda:0",
                    "ready": True,
                },
                {
                    "key": "second-local",
                    "source": "local",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "device": "cuda:0",
                    "ready": True,
                },
            ],
        )
    )
    registry = ReportGeneratorRegistry(config)
    lock = threading.Lock()
    active = 0
    peak_active = 0

    def fake_generate(entry, image_path, modality, **kwargs):
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        time.sleep(0.08)
        with lock:
            active -= 1
        return GeneratedReport(
            model=entry.key,
            source=entry.source,
            report="FINDINGS: Clear lungs. IMPRESSION: Normal chest.",
            modality=modality,
        )

    monkeypatch.setattr(registry, "generate", fake_generate)

    result = generate_candidates(
        registry,
        image_path="image.png",
        modality="cxr",
        body_part="chest",
        case_id="case-local-limit",
    )

    assert len(result.reports) == 2
    assert peak_active == 1


def test_generate_reports_uses_orchestrated_candidates_and_keeps_route_provenance():
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["*"],
            candidate_max_workers=2,
            local_models=[
                {
                    "key": "candidate-a",
                    "source": "local",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "ready": True,
                },
                {
                    "key": "candidate-b",
                    "source": "local",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "ready": True,
                },
            ],
        )
    )

    reports = generate_reports(
        "image.png",
        "cxr",
        body_part="chest",
        case_id="case-9",
        generation_mode="production",
        config=config,
    )

    assert [report.model for report in reports] == ["candidate-a", "candidate-b"]
    assert {report.metadata["candidate_id"] for report in reports} == {
        "case-9:candidate-a",
        "case-9:candidate-b",
    }
    assert {report.metadata["route_tier"] for report in reports} == {"exact_modality_body_part"}
    assert all("elapsed_sec" in report.metadata for report in reports)


def test_enabled_external_vlm_is_a_universal_candidate_and_not_a_fallback(tmp_path):
    image = tmp_path / "image.png"
    Image.new("L", (4, 4), color=0).save(image)
    config = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            include_legacy_ready_models=False,
            default_models=["*"],
            external_vlm_enabled=True,
            external_vlm_key="yunwu_general",
            external_vlm_model_role="report_generation",
        ),
        model_roles={
            "report_generation": ModelRoleConfig(provider="mock", model="yunwu-test", max_tokens=256),
        },
    )
    registry = ReportGeneratorRegistry(config)

    result = generate_candidates(
        registry,
        image_path=str(image),
        modality="cxr",
        body_part="chest",
        case_id="case-6",
    )

    assert [report.source for report in result.reports] == ["external_vlm"]
    assert result.reports[0].model == "yunwu-test"
    assert result.reports[0].metadata["route_tier"] == "universal"
    assert result.reports[0].metadata["fresh_inference"] is True
