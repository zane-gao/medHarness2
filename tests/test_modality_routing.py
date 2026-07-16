from __future__ import annotations

import pytest

from medharness2.config import AppConfig, GeneratorConfig
from medharness2.generators.registry import GeneratorEntry, ReportGeneratorRegistry
from medharness2.tools.tool7_modality import _normalize_modality_token, recognize_modality
from medharness2.tools.tool2_extract import _canonical_observation_code


def test_registry_keeps_modality_route_when_body_part_is_unknown():
    registry = ReportGeneratorRegistry(AppConfig())
    entries = registry.compatible_entries("ct", body_part="wrist")
    assert any(entry.key == "merlin_fresh" for entry in entries)


@pytest.mark.parametrize("field", ["max_new_tokens", "timeout_sec"])
@pytest.mark.parametrize("bad", [True, 1.5, "160", 0, -1])
def test_registry_rejects_invalid_generation_limits_without_coercion(field, bad):
    config = AppConfig(
        generator=GeneratorConfig(
            local_models=[
                {
                    "key": "bad_model",
                    "source": "artifact_reuse",
                    field: bad,
                }
            ]
        )
    )
    with pytest.raises(ValueError, match=field):
        ReportGeneratorRegistry(config)


@pytest.mark.parametrize("field", ["max_new_tokens", "timeout_sec"])
@pytest.mark.parametrize("bad", [True, 1.5, "160", 0, -1])
def test_generator_entry_rejects_invalid_generation_limits_without_coercion(field, bad):
    kwargs = {
        "key": "bad_model",
        "title": "Bad model",
        "source": "artifact_reuse",
        "supported_modalities": ["cxr"],
        field: bad,
    }
    with pytest.raises(ValueError, match=field):
        GeneratorEntry(**kwargs)


def test_registry_prefers_matching_body_part_without_requiring_it():
    registry = ReportGeneratorRegistry(AppConfig())
    registry.entries = {
        "ct_match": GeneratorEntry("ct_match", "match", "medharness_cli", ["ct"], ["chest"]),
        "ct_other": GeneratorEntry("ct_other", "other", "medharness_cli", ["ct"], ["abdomen"]),
    }
    selected = registry.compatible_entries("ct", body_part="chest")
    assert [entry.key for entry in selected] == ["ct_match", "ct_other"]


def test_registry_expands_wildcard_default_models_for_each_modality():
    registry = ReportGeneratorRegistry(
        AppConfig(
            generator=GeneratorConfig(
                default_models=["*"],
                include_legacy_ready_models=False,
                local_models=[
                    {
                        "key": "cxr_model",
                        "title": "CXR",
                        "source": "artifact_reuse",
                        "supported_modalities": ["cxr"],
                        "ready": True,
                    },
                    {
                        "key": "ct_model",
                        "title": "CT",
                        "source": "artifact_reuse",
                        "supported_modalities": ["ct"],
                        "ready": True,
                    },
                ],
            )
        )
    )

    assert [entry.key for entry in registry.select("cxr")] == ["cxr_model"]
    assert [entry.key for entry in registry.select("ct")] == ["ct_model"]


def test_registry_normalizes_modality_aliases_before_selection():
    registry = ReportGeneratorRegistry(
        AppConfig(
            generator=GeneratorConfig(
                default_models=["alias_model"],
                include_legacy_ready_models=False,
                local_models=[
                    {
                        "key": "alias_model",
                        "title": "MRI",
                        "source": "artifact_reuse",
                        "supported_modalities": ["mri"],
                        "ready": True,
                    }
                ],
            )
        )
    )

    assert [entry.key for entry in registry.select("MRI")] == ["alias_model"]


def test_modality_token_normalization_handles_common_vlm_phrasing():
    assert _normalize_modality_token("The study is an MRI examination") == "MR"
    assert _normalize_modality_token("CT abdomen") == "CT"
    assert _normalize_modality_token("chest x-ray") == "DX"


def test_recognize_modality_uses_dicom_header_before_filename_or_llm(tmp_path):
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset

    path = tmp_path / "scan.png"
    meta = FileMetaDataset()
    dataset = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    dataset.Modality = "MR"
    dataset.save_as(path)

    assert recognize_modality(str(path), config=AppConfig()) == "mri"


def test_recognize_modality_uses_image_suffix_without_llm(tmp_path):
    path = tmp_path / "portable.jpg"
    path.write_bytes(b"not a dicom")

    assert recognize_modality(str(path), config=AppConfig()) == "xray"


def test_recognize_modality_normalizes_vlm_result_and_empty_reply(monkeypatch, tmp_path):
    path = tmp_path / "unknown.bin"
    path.write_bytes(b"not a dicom")

    class Client:
        def __init__(self, text):
            self.text = text

        def call(self, *args, **kwargs):
            return self.text

    assert recognize_modality(str(path), config=AppConfig(), llm_client=Client("MRI examination")) == "mri"
    assert recognize_modality(str(path), config=AppConfig(), llm_client=Client("")) == "unknown"


def test_non_cxr_observation_codes_are_stable_slugs_for_alignment():
    assert _canonical_observation_code("Small hepatic cyst", "small hepatic cyst") == "small_hepatic_cyst"
    assert _canonical_observation_code("liver-cyst", "liver cyst") == "liver_cyst"

@pytest.mark.parametrize("field", ["supported_modalities", "supported_body_parts", "python_paths"])
@pytest.mark.parametrize("bad", ["cxr", {"x": 1}, ["cxr", 2]])
def test_registry_rejects_malformed_string_list_fields(field, bad):
    config = AppConfig(
        generator=GeneratorConfig(
            include_legacy_ready_models=False,
            local_models=[
                {
                    "key": "bad_model",
                    "source": "artifact_reuse",
                    field: bad,
                }
            ],
        )
    )
    with pytest.raises(ValueError, match=field):
        ReportGeneratorRegistry(config)
