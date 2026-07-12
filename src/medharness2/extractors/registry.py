from __future__ import annotations

from medharness2.extractors.base import FindingExtractor
from medharness2.extractors.ct import CT_EXTRACTOR
from medharness2.extractors.cxr import CXR_EXTRACTOR
from medharness2.extractors.mri import MRI_EXTRACTOR
from medharness2.extractors.placeholder import PLACEHOLDER_EXTRACTOR


class ExtractorRegistry:
    def __init__(self):
        self._by_backend: dict[str, FindingExtractor] = {
            extractor.backend: extractor
            for extractor in (CXR_EXTRACTOR, CT_EXTRACTOR, MRI_EXTRACTOR, PLACEHOLDER_EXTRACTOR)
        }

    def resolve(self, modality: str, backend: str = "auto") -> FindingExtractor:
        key = backend.strip().lower()
        modality_key = modality.strip().lower()
        if key in {"auto", "modality_rule"}:
            for extractor in (CXR_EXTRACTOR, CT_EXTRACTOR, MRI_EXTRACTOR):
                if modality_key in extractor.modalities:
                    return extractor
            return PLACEHOLDER_EXTRACTOR
        if key not in self._by_backend:
            raise ValueError(f"Unsupported extractor backend: {backend}")
        return self._by_backend[key]

    def backends(self) -> list[str]:
        return sorted(self._by_backend)
