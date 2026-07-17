from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictBool

from medharness2.contracts.common import SCHEMA_VERSION, ContractModel, Measurement


class CandidateReportForAnnotation(ContractModel):
    candidate_id: str = Field(min_length=1)
    blinded_model_id: str = Field(min_length=1)
    report_text: str


class FindingAnnotation(ContractModel):
    finding_id: str = Field(min_length=1)
    observation_text: str = Field(min_length=1)
    location_text: str | None = None
    laterality: Literal["left", "right", "bilateral", "midline", "unknown"] = "unknown"
    certainty: Literal["present", "absent", "uncertain"] = "present"
    severity: str | None = None
    measurements: list[Measurement] = Field(default_factory=list)
    source: Literal["reference", "candidate"]
    candidate_id: str | None = None
    notes: str = ""


class HazardAnnotation(ContractModel):
    error_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    error_type: Literal[
        "omission_finding",
        "false_finding",
        "incorrect_location",
        "incorrect_severity",
        "mismatched_finding",
        "contradiction",
        "other",
    ]
    hazard_level: int = Field(ge=1, le=5)
    clinically_significant: StrictBool
    evidence_finding_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)


class ReaderAnnotation(ContractModel):
    reader_slot: Literal["reader_a", "reader_b", "adjudication"]
    status: Literal["not_started", "in_progress", "complete"] = "not_started"
    findings: list[FindingAnnotation] = Field(default_factory=list)
    hazards: list[HazardAnnotation] = Field(default_factory=list)
    overall_notes: str = ""
    confidence: float | None = Field(default=None, ge=0, le=1)


class AnnotationCase(ContractModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    artifact_type: Literal["clinical_annotation_case"] = "clinical_annotation_case"
    pilot_case_id: str = Field(min_length=1)
    source_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    modality: str = Field(min_length=1)
    body_part: str = Field(min_length=1)
    reference_report: str
    candidate_reports: list[CandidateReportForAnnotation] = Field(default_factory=list)
    annotations: dict[Literal["reader_a", "reader_b", "adjudication"], ReaderAnnotation]
    instructions_version: str = "1.0"
