from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, model_validator

from medharness2.contracts.common import SCHEMA_VERSION, ContractModel, Measurement
from medharness2.contracts.evaluation import FindingGraph, GeneratedReportArtifact


StructureStatus = Literal["succeeded", "empty_report", "failed"]
ObservationStatus = Literal["present", "absent", "uncertain"]
RouteTier = Literal[
    "exact_modality_body_part",
    "same_modality",
    "same_body_part_cross_modality",
    "universal",
]
RuntimeState = Literal["unavailable", "preflight_only", "runnable", "smoke_verified"]
ValidationState = Literal[
    "unvalidated",
    "engineering_smoke_only",
    "exploratory",
    "formal",
    "quality_blocked",
]


class CandidateStructureSpan(ContractModel):
    span_id: StrictInt = Field(ge=0)
    subject: str = Field(min_length=1)
    entity: str = Field(min_length=1)
    anatomy_code: str | None = None
    location_text: str | None = None
    finding_id: str = ""
    attribute: str = Field(min_length=1)
    value_raw: str = Field(min_length=1)
    observation_status: ObservationStatus
    certainty: ObservationStatus
    laterality: Literal["left", "right", "bilateral", "midline", "unknown"] = "unknown"
    severity: str | None = None
    measurements: list[Measurement] = Field(default_factory=list)
    evidence_snippet: str = Field(min_length=1)
    start: StrictInt = Field(ge=0)
    end: StrictInt = Field(gt=0)
    section: str = Field(min_length=1)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_evidence_length(self) -> "CandidateStructureSpan":
        if self.end <= self.start:
            raise ValueError("CandidateStructureSpan.end must be greater than start")
        if self.end - self.start != len(self.evidence_snippet):
            raise ValueError("CandidateStructureSpan offsets must match evidence_snippet length")
        if self.observation_status != self.certainty:
            raise ValueError("observation_status and certainty must agree")
        return self


class CandidateStructureEntity(ContractModel):
    entity: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    anatomy_code: str | None = None
    location_text: str | None = None
    laterality: Literal["left", "right", "bilateral", "midline", "unknown"] = "unknown"
    observation_status: ObservationStatus
    certainty: ObservationStatus
    severity: str | None = None
    measurements: list[Measurement] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence_span_ids: list[StrictInt] = Field(default_factory=list)
    evidence_snippets: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence_lists(self) -> "CandidateStructureEntity":
        if self.observation_status != self.certainty:
            raise ValueError("observation_status and certainty must agree")
        if len(self.evidence_span_ids) != len(self.evidence_snippets):
            raise ValueError("entity evidence span IDs and snippets must have equal length")
        return self


class StructureTemplateAttachment(ContractModel):
    status: Literal["matched", "generic_fallback"]
    template_id: str = Field(min_length=1)
    template_version: str = Field(min_length=1)
    template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_version: str = Field(min_length=1)
    registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    matched_on: Literal["exact_modality_body_part", "generic_fallback"]
    reason: str = ""
    anatomy_sections: list[str] = Field(default_factory=list)


class CandidateReportStructure(ContractModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    artifact_type: Literal["candidate_report_structure"] = "candidate_report_structure"
    structure_status: StructureStatus
    structure_version: Literal["candidate-structure-v2"] = "candidate-structure-v2"
    modality: str = Field(min_length=1)
    body_part: str = Field(min_length=1)
    sections: dict[str, str] = Field(default_factory=dict)
    spans: list[CandidateStructureSpan] = Field(default_factory=list)
    entities: list[CandidateStructureEntity] = Field(default_factory=list)
    finding_graph: FindingGraph
    template: StructureTemplateAttachment
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None

    @model_validator(mode="after")
    def validate_structure_links(self) -> "CandidateReportStructure":
        span_ids = [span.span_id for span in self.spans]
        if len(span_ids) != len(set(span_ids)):
            raise ValueError("candidate structure span IDs must be unique")
        known = set(span_ids)
        for entity in self.entities:
            if not set(entity.evidence_span_ids).issubset(known):
                raise ValueError("entity references an unknown evidence span")
        if self.structure_status == "failed" and not self.error:
            raise ValueError("failed candidate structure requires an error")
        return self


ComparisonType = Literal[
    "agreement",
    "observation_status",
    "laterality",
    "anatomy",
    "measurement",
    "severity",
    "candidate_missing",
    "internal_status",
]


class CandidateComparisonItem(ContractModel):
    entity: str = Field(min_length=1)
    comparison_type: ComparisonType
    candidate_ids: list[str] = Field(default_factory=list)
    candidate_values: dict[str, list[str]] = Field(default_factory=dict)
    missing_candidate_ids: list[str] = Field(default_factory=list)


class CandidateStructureComparison(ContractModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    artifact_type: Literal["candidate_structure_comparison"] = "candidate_structure_comparison"
    structure_version: Literal["candidate-structure-v2"] = "candidate-structure-v2"
    candidate_ids: list[str] = Field(default_factory=list)
    agreement_count: StrictInt = Field(ge=0)
    conflict_count: StrictInt = Field(ge=0)
    omission_count: StrictInt = Field(ge=0)
    internal_conflict_count: StrictInt = Field(ge=0)
    agreements: list[CandidateComparisonItem] = Field(default_factory=list)
    conflicts: list[CandidateComparisonItem] = Field(default_factory=list)
    omissions: list[CandidateComparisonItem] = Field(default_factory=list)
    internal_conflicts: list[CandidateComparisonItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_counts(self) -> "CandidateStructureComparison":
        expected = {
            "agreement_count": len(self.agreements),
            "conflict_count": len(self.conflicts),
            "omission_count": len(self.omissions),
            "internal_conflict_count": len(self.internal_conflicts),
        }
        for field_name, count in expected.items():
            if getattr(self, field_name) != count:
                raise ValueError(f"{field_name} does not match its item list")
        return self


class CandidateFailureArtifact(ContractModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    artifact_type: Literal["candidate_failure"] = "candidate_failure"
    candidate_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    source: str = Field(min_length=1)
    route_tier: str | None = None
    stage: Literal["generation", "quality_gate", "structure"] = "generation"
    warnings: list[str] = Field(default_factory=list)
    runtime_state: str = "unavailable"
    validation_state: str = "unvalidated"
    metadata: dict[str, Any] = Field(default_factory=dict)


class FusionReportArtifact(ContractModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    artifact_type: Literal["fusion_report"] = "fusion_report"
    fusion_status: Literal[
        "disabled",
        "no_candidates",
        "role_not_configured",
        "failed",
        "empty_output",
        "succeeded",
    ]
    fusion_model: str = ""
    report: str = ""
    input_candidate_ids: list[str] = Field(default_factory=list)
    used_image_asset: str | None = None
    structure_version: str = ""
    warnings: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_success_payload(self) -> "FusionReportArtifact":
        if self.fusion_status == "succeeded" and not self.report.strip():
            raise ValueError("succeeded fusion report requires report text")
        return self


class RoutePlanEntryArtifact(ContractModel):
    model_key: str = Field(min_length=1)
    source: str = Field(min_length=1)
    runtime_state: RuntimeState
    validation_state: ValidationState
    route_tier: RouteTier | None = None
    route_reason: str = ""
    eligible: StrictBool
    excluded_reason: str | None = None
    input_capabilities: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_decision(self) -> "RoutePlanEntryArtifact":
        if self.eligible:
            if self.route_tier is None or not self.route_reason:
                raise ValueError("eligible route entries require route_tier and route_reason")
            if self.excluded_reason is not None:
                raise ValueError("eligible route entries cannot have excluded_reason")
        elif not self.excluded_reason:
            raise ValueError("excluded route entries require excluded_reason")
        return self


class RoutePlanArtifact(ContractModel):
    normalized_modality: str = Field(min_length=1)
    normalized_body_part: str = Field(min_length=1)
    case_id: str | None = None
    generation_mode: Literal["production", "benchmark", "replay"]
    available_input_capabilities: list[str] = Field(default_factory=list)
    entries: list[RoutePlanEntryArtifact] = Field(default_factory=list)
    candidate_model_keys: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_candidates(self) -> "RoutePlanArtifact":
        entry_keys = [entry.model_key for entry in self.entries]
        if len(entry_keys) != len(set(entry_keys)):
            raise ValueError("route plan model keys must be unique")
        eligible = {entry.model_key for entry in self.entries if entry.eligible}
        if len(self.candidate_model_keys) != len(set(self.candidate_model_keys)):
            raise ValueError("route plan candidate model keys must be unique")
        if set(self.candidate_model_keys) != eligible:
            raise ValueError("route plan candidate_model_keys must match eligible entries")
        return self


class CandidateReportArtifact(GeneratedReportArtifact):
    candidate_id: str = Field(min_length=1)
    route_tier: RouteTier
    route_reason: str = Field(min_length=1)
    runtime_state: RuntimeState
    validation_state: ValidationState
    structure: CandidateReportStructure
    candidate_metadata: dict[str, Any] = Field(default_factory=dict)

class ReferenceFreeRankingArtifact(ContractModel):
    candidate_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    source: str = Field(min_length=1)
    rank: StrictInt = Field(ge=1)
    score: StrictFloat = Field(ge=0, le=1)
    ranking_mode: Literal[
        "production_reference_free",
        "benchmark_reference_free",
        "replay_reference_free",
    ]
    metrics: dict[str, StrictFloat] = Field(default_factory=dict)
    ranking_reason: list[str] = Field(default_factory=list)
    selected_top_k: StrictBool


class ProductionRankingArtifact(ReferenceFreeRankingArtifact):
    ranking_mode: Literal["production_reference_free"] = "production_reference_free"


class ProductionGenerationArtifact(ContractModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    artifact_type: Literal["production_report_generation"] = "production_report_generation"
    generation_mode: Literal["production_reference_free"] = "production_reference_free"
    case_id: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    route_plan: RoutePlanArtifact
    candidate_reports: list[CandidateReportArtifact] = Field(default_factory=list)
    candidate_failures: list[CandidateFailureArtifact] = Field(default_factory=list)
    candidate_structure_comparison: CandidateStructureComparison
    top_k_reports: list[ProductionRankingArtifact] = Field(default_factory=list)
    fusion_report: FusionReportArtifact
    generated_reports: list[GeneratedReportArtifact] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    generated_evaluations: list[dict[str, Any]] = Field(default_factory=list)
    rankings: list[dict[str, Any]] = Field(default_factory=list)
    pairwise_comparisons: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_cross_references(self) -> "ProductionGenerationArtifact":
        if self.route_plan.generation_mode != "production":
            raise ValueError("production result requires a production RoutePlan")
        if any(
            candidate.metadata.get("reference_report_used") is not False
            for candidate in self.candidate_reports
        ):
            raise ValueError("production candidate reference_report_used must be false")
        candidate_ids = [candidate.candidate_id for candidate in self.candidate_reports]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate report IDs must be unique")
        known_candidates = set(candidate_ids)
        top_k_ids = [ranking.candidate_id for ranking in self.top_k_reports]
        if not set(top_k_ids).issubset(known_candidates):
            raise ValueError("Top-K report references an unknown candidate")
        expected_ranks = list(range(1, len(self.top_k_reports) + 1))
        if [ranking.rank for ranking in self.top_k_reports] != expected_ranks:
            raise ValueError("Top-K ranks must be contiguous and ordered")
        if not set(self.fusion_report.input_candidate_ids).issubset(known_candidates):
            raise ValueError("fusion report references an unknown candidate")
        if len(self.generated_reports) != len(self.candidate_reports):
            raise ValueError("legacy generated_reports must mirror candidate_reports")
        for candidate, generated in zip(self.candidate_reports, self.generated_reports, strict=True):
            if (
                candidate.model != generated.model
                or candidate.source != generated.source
                or candidate.report != generated.report
            ):
                raise ValueError("legacy generated_reports must preserve candidate report order and text")
        route_keys = set(self.route_plan.candidate_model_keys)
        represented_route_keys = {
            candidate.candidate_id.rsplit(":", 1)[-1]
            for candidate in self.candidate_reports
        } | {
            failure.candidate_id.rsplit(":", 1)[-1]
            for failure in self.candidate_failures
        }
        if not route_keys.issubset(represented_route_keys):
            raise ValueError("every routed model must produce a candidate or failure")
        return self


__all__ = [
    "CandidateComparisonItem",
    "CandidateFailureArtifact",
    "CandidateReportStructure",
    "CandidateStructureComparison",
    "CandidateStructureEntity",
    "CandidateStructureSpan",
    "FusionReportArtifact",
    "CandidateReportArtifact",
    "ProductionGenerationArtifact",
    "ProductionRankingArtifact",
    "ReferenceFreeRankingArtifact",
    "RoutePlanArtifact",
    "RoutePlanEntryArtifact",
    "StructureTemplateAttachment",
]
