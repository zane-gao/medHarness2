from __future__ import annotations

from typing import Any, Protocol


class FindingExtractor(Protocol):
    backend: str
    modalities: tuple[str, ...]

    def extract(self, report_text: str, *, modality: str) -> dict[str, Any]: ...
