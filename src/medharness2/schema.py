from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from medharness2.contracts import infer_evidence_tier


EVIDENCE_TIERS = {"formal_fresh", "exploratory_fresh", "artifact", "debug_fallback", "mock"}
FORMAL_FRESH_SOURCES = {"medharness_cli"}
FORMAL_REQUIRED_METADATA = (
    "model_version",
    "prompt_version",
    "preprocessing_version",
    "formal_validation_id",
)
FORMAL_BLOCKING_WARNINGS = {
    "artifact_reuse_not_fresh_inference",
    "compatible_local_generator_returned_no_text",
    "legacy_reference_assisted_generation_assumed",
    "local_model_not_ready",
    "no_generation_backend_available",
    "quality_gate_failed",
    "reference_assisted_generation",
}


@dataclass
class GeneratedReport:
    model: str
    source: str
    report: str
    modality: str
    evidence_tier: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "2.0"
    artifact_type: str = "generated_report"

    def __post_init__(self) -> None:
        if not self.evidence_tier:
            self.evidence_tier = infer_evidence_tier(self.source, self.metadata)
        if self.evidence_tier not in EVIDENCE_TIERS:
            raise ValueError(f"Unsupported evidence_tier: {self.evidence_tier}")
        self.metadata = {**self.metadata, "evidence_tier": self.evidence_tier}

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def require_formal_fresh_reports(reports: list[GeneratedReport]) -> None:
    invalid = []
    for report in reports:
        violations = formal_report_violations(report)
        if violations:
            invalid.append(f"{report.model}:{report.evidence_tier}:{'|'.join(violations)}")
    if invalid:
        raise ValueError(f"Formal run requires verified formal_fresh reports; invalid={','.join(invalid)}")


def formal_report_violations(report: GeneratedReport) -> list[str]:
    violations: list[str] = []
    if report.evidence_tier != "formal_fresh":
        violations.append("non_formal_evidence_tier")
    if report.source not in FORMAL_FRESH_SOURCES:
        violations.append("unsupported_formal_source")
    if not report.report.strip():
        violations.append("empty_report")
    metadata = report.metadata or {}
    if metadata.get("reference_report_used") is not False:
        violations.append("reference_report_used_or_unverified")
    if metadata.get("fresh_inference") is not True:
        violations.append("fresh_inference_unverified")
    quality_gate = metadata.get("quality_gate") or {}
    if not isinstance(quality_gate, dict) or quality_gate.get("passed") is not True:
        violations.append("quality_gate_failed_or_unverified")
    model_sha256 = str(metadata.get("model_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", model_sha256):
        violations.append("missing_model_sha256")
    for field_name in FORMAL_REQUIRED_METADATA:
        if not str(metadata.get(field_name) or "").strip():
            violations.append(f"missing_{field_name}")
    blocking = sorted(
        warning
        for warning in report.warnings
        if warning in FORMAL_BLOCKING_WARNINGS
        or warning.endswith("_fallback_used")
        or warning.startswith("legacy_generation_")
    )
    violations.extend(f"blocking_warning:{warning}" for warning in blocking)
    return list(dict.fromkeys(violations))


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
