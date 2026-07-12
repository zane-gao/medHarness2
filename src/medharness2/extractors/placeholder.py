from __future__ import annotations

from typing import Any

from medharness2.extractors.cxr import CXR_EXTRACTOR


class PlaceholderExtractor:
    backend = "placeholder"
    modalities: tuple[str, ...] = ()

    def extract(self, report_text: str, *, modality: str) -> dict[str, Any]:
        result = CXR_EXTRACTOR.extract(report_text, modality=modality)
        result["backend"] = self.backend
        result["warnings"] = ["placeholder_extractor"]
        for finding in result.get("findings") or []:
            finding["extractor"]["model"] = self.backend
            finding["extractor"]["fallback_used"] = True
        return result


PLACEHOLDER_EXTRACTOR = PlaceholderExtractor()
