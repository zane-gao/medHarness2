from __future__ import annotations

from medharness2.config import AppConfig
from medharness2.generators.registry import GeneratorEntry, ReportGeneratorRegistry
from medharness2.tools.tool7_modality import _normalize_modality_token


def test_registry_keeps_modality_route_when_body_part_is_unknown():
    registry = ReportGeneratorRegistry(AppConfig())
    entries = registry.compatible_entries("ct", body_part="wrist")
    assert any(entry.key == "merlin_fresh" for entry in entries)


def test_registry_prefers_matching_body_part_without_requiring_it():
    registry = ReportGeneratorRegistry(AppConfig())
    registry.entries = {
        "ct_match": GeneratorEntry("ct_match", "match", "medharness_cli", ["ct"], ["chest"]),
        "ct_other": GeneratorEntry("ct_other", "other", "medharness_cli", ["ct"], ["abdomen"]),
    }
    selected = registry.compatible_entries("ct", body_part="chest")
    assert [entry.key for entry in selected] == ["ct_match", "ct_other"]


def test_modality_token_normalization_handles_common_vlm_phrasing():
    assert _normalize_modality_token("The study is an MRI examination") == "MR"
    assert _normalize_modality_token("CT abdomen") == "CT"
    assert _normalize_modality_token("chest x-ray") == "DX"

