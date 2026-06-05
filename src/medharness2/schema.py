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


@dataclass
class CaseManifest:
    case_id: str
    reader: str
    modality: str
    body_part: str
    report_pdf: str
    report_text: str = ""
    image_paths: list[str] = field(default_factory=list)
    volume_path: str | None = None
    derived_assets: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "CaseManifest":
        return cls(
            case_id=str(payload.get("case_id") or payload.get("id") or ""),
            reader=str(payload.get("reader") or payload.get("radiologist_id") or "unknown"),
            modality=str(payload.get("modality") or "unknown"),
            body_part=str(payload.get("body_part") or "unknown"),
            report_pdf=str(payload.get("report_pdf") or ""),
            report_text=str(payload.get("report_text") or payload.get("report_text_path") or ""),
            image_paths=[str(path) for path in payload.get("image_paths") or []],
            volume_path=str(payload["volume_path"]) if payload.get("volume_path") else None,
            derived_assets=dict(payload.get("derived_assets") or {}),
            warnings=list(payload.get("warnings") or []),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass
class ReportTextResult:
    case_id: str
    text: str
    method: str
    cache_path: str
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreparedCase:
    case_id: str
    modality: str
    body_part: str
    image_paths: list[str] = field(default_factory=list)
    volume_path: str | None = None
    derived_assets: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)
