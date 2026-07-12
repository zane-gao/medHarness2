from __future__ import annotations

from medharness2.extractors import ExtractorRegistry
from medharness2.tools.tool2_extract import extract_findings


def test_auto_backend_routes_to_modality_specific_plugins():
    registry = ExtractorRegistry()

    assert registry.resolve("cxr", "auto").backend == "cxr_rule"
    assert registry.resolve("ct", "auto").backend == "ct_rule"
    assert registry.resolve("mri", "auto").backend == "mri_rule"
    assert registry.resolve("unknown", "auto").backend == "placeholder"


def test_unknown_modality_auto_uses_explicit_placeholder_warning():
    result = extract_findings("A reported abnormality.", modality="ultrasound", backend="auto")

    assert result["backend"] == "placeholder"
    assert "placeholder_extractor" in result["warnings"]
