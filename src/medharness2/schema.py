from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class GeneratedReport:
    model: str
    source: str
    report: str
    modality: str
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SingleReportResult:
    likert: dict[str, Any]
    finding_graph: dict[str, Any]
    structure: dict[str, Any]
    composite_inputs: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return asdict(self)
