from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, StrictFloat, StrictInt, model_validator

from medharness2.contracts.common import (
    SCHEMA_VERSION,
    ContractModel,
    EvidenceTier,
    Measurement,
    ModelProvenance,
    TextSpan,
)


class Finding(ContractModel):
    finding_id: str = Field(min_length=1)
    observation_code: str | None = None
    observation_text: str = Field(min_length=1)
    anatomy_code: str | None = None
    location_text: str | None = None
    laterality: Literal["left", "right", "bilateral", "midline", "unknown"] = "unknown"
    certainty: Literal["present", "absent", "uncertain"] = "present"
    severity: str | None = None
    measurements: list[Measurement] = Field(default_factory=list)
    source_span: TextSpan | None = None
    source_text: str = ""
    extractor: ModelProvenance
    attributes: dict[str, Any] = Field(default_factory=dict)


class FindingGraph(ContractModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    artifact_type: Literal["finding_graph"] = "finding_graph"
    modality: str = Field(min_length=1)
    backend: str = Field(min_length=1)
    findings: list[Finding] = Field(default_factory=list)
    relations: list[dict[str, Any]] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    coverage: StrictFloat = Field(default=0.0, ge=0, le=1)
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    template_coverage: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_finding_ids(self) -> "FindingGraph":
        ids = [finding.finding_id for finding in self.findings]
        if len(ids) != len(set(ids)):
            raise ValueError("FindingGraph finding_id values must be unique")
        return self


class GeneratedReportArtifact(ContractModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    artifact_type: Literal["generated_report"] = "generated_report"
    model: str = Field(min_length=1)
    source: str = Field(min_length=1)
    report: str
    modality: str = Field(min_length=1)
    evidence_tier: EvidenceTier
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: ModelProvenance | None = None


class HazardJudgement(ContractModel):
    error_type: str = Field(min_length=1)
    hazard_level: StrictInt = Field(ge=1, le=5)
    explanation: str = Field(min_length=1)
    recommended_action: str = Field(min_length=1)
    confidence: StrictFloat | None = Field(default=None, ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    abstain: bool = False
    finding: dict[str, Any] | str | None = None
    candidate: dict[str, Any] | str | None = None
    reference: dict[str, Any] | str | None = None
    a: dict[str, Any] | str | None = None
    b: dict[str, Any] | str | None = None
    observation: str | None = None
    location: str | None = None
    severity: str | None = None
    measurement: str | float | None = None
    certainty: str | None = None
    text: str | None = None
    alignment_error_index: StrictInt | None = Field(default=None, ge=0)
    alignment_audit_judgement: dict[str, Any] | None = None
    original_error_type: str | None = None


class HazardResult(ContractModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    artifact_type: Literal["hazard_result"] = "hazard_result"
    errors: list[HazardJudgement] = Field(default_factory=list)
    provenance: ModelProvenance
    metadata: dict[str, Any] = Field(default_factory=dict)


class HazardDisagreement(ContractModel):
    error_index: StrictInt = Field(ge=0)
    error_type: str = Field(min_length=1)
    primary_hazard_level: StrictInt = Field(ge=1, le=5)
    reviewer_hazard_level: StrictInt = Field(ge=1, le=5)
    level_delta: StrictInt = Field(ge=0, le=4)
    primary_recommended_action: str = Field(min_length=1)
    reviewer_recommended_action: str = Field(min_length=1)
    disagreement_types: list[Literal["hazard_level", "recommended_action"]] = Field(default_factory=list)
    requires_adjudication: bool = True


class HazardReviewArtifact(ContractModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    artifact_type: Literal["hazard_review"] = "hazard_review"
    primary_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    primary_provenance: ModelProvenance
    reviewer_result: HazardResult
    reviewer_consistency: dict[str, Any] = Field(default_factory=dict)
    disagreements: list[HazardDisagreement] = Field(default_factory=list)
    agreement_summary: dict[str, Any] = Field(default_factory=dict)
    primary_preserved: Literal[True] = True
    requires_adjudication: bool = False


class HazardAdjudicationDecision(ContractModel):
    error_index: StrictInt = Field(ge=0)
    error_type: str = Field(min_length=1)
    hazard_level: StrictInt = Field(ge=1, le=5)
    recommended_action: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    confidence: StrictFloat = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    abstain: bool = False
    primary_hazard_level: StrictInt = Field(ge=1, le=5)
    reviewer_hazard_level: StrictInt = Field(ge=1, le=5)
    primary_recommended_action: str = Field(min_length=1)
    reviewer_recommended_action: str = Field(min_length=1)


class HazardAdjudicationArtifact(ContractModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    artifact_type: Literal["hazard_adjudication"] = "hazard_adjudication"
    primary_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hazard_review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adjudicator_provenance: ModelProvenance
    decisions: list[HazardAdjudicationDecision] = Field(default_factory=list)
    disagreement_count: StrictInt = Field(ge=0)
    resolved_count: StrictInt = Field(ge=0)
    abstained_count: StrictInt = Field(ge=0)
    primary_preserved: Literal[True] = True
    reviewer_preserved: Literal[True] = True
    clinical_validation_required: Literal[True] = True

    @model_validator(mode="after")
    def validate_counts(self) -> "HazardAdjudicationArtifact":
        if self.disagreement_count != len(self.decisions):
            raise ValueError("disagreement_count must equal the number of decisions")
        if self.resolved_count != sum(not item.abstain for item in self.decisions):
            raise ValueError("resolved_count does not match decisions")
        if self.abstained_count != sum(item.abstain for item in self.decisions):
            raise ValueError("abstained_count does not match decisions")
        return self


class AlignmentAuditIssue(ContractModel):
    issue_type: Literal[
        "missed_match",
        "incorrect_match",
        "incorrect_error_type",
        "unsupported_error",
        "missing_error",
        "other",
    ]
    candidate_id: str | None = None
    reference_id: str | None = None
    error_index: StrictInt | None = Field(default=None, ge=0)
    suggested_error_type: str | None = None
    explanation: str = Field(min_length=1)
    confidence: StrictFloat = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_issue_references(self) -> "AlignmentAuditIssue":
        if self.issue_type in {"missed_match", "incorrect_match"} and not (
            self.candidate_id and self.reference_id
        ):
            raise ValueError(f"{self.issue_type} requires candidate_id and reference_id")
        if self.issue_type in {"incorrect_error_type", "unsupported_error"} and self.error_index is None:
            raise ValueError(f"{self.issue_type} requires error_index")
        if self.issue_type == "incorrect_error_type" and not self.suggested_error_type:
            raise ValueError("incorrect_error_type requires suggested_error_type")
        return self


class AlignmentErrorJudgement(ContractModel):
    error_index: StrictInt = Field(ge=0)
    disposition: Literal[
        "valid",
        "unsupported",
        "incorrect_error_type",
        "abstain",
    ]
    suggested_error_type: str | None = None
    explanation: str = Field(min_length=1)
    confidence: StrictFloat = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_suggested_error_type(self) -> "AlignmentErrorJudgement":
        if self.disposition == "incorrect_error_type" and not self.suggested_error_type:
            raise ValueError("incorrect_error_type requires suggested_error_type")
        return self


class AlignmentAuditArtifact(ContractModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    artifact_type: Literal["alignment_audit"] = "alignment_audit"
    alignment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    auditor_provenance: ModelProvenance
    verdict: Literal["pass", "issues_found", "abstain"]
    confidence: StrictFloat = Field(ge=0, le=1)
    summary: str = Field(min_length=1)
    issues: list[AlignmentAuditIssue] = Field(default_factory=list)
    error_judgements: list[AlignmentErrorJudgement] = Field(default_factory=list)
    adjudicated_error_candidates: list[dict[str, Any]] = Field(default_factory=list)
    adjudication_summary: dict[str, Any] = Field(default_factory=dict)
    primary_preserved: Literal[True] = True
    requires_adjudication: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_verdict(self) -> "AlignmentAuditArtifact":
        if self.verdict == "pass" and self.issues:
            raise ValueError("alignment audit pass verdict cannot contain issues")
        if (
            self.verdict == "issues_found"
            and not self.issues
            and all(item.disposition == "valid" for item in self.error_judgements)
        ):
            raise ValueError(
                "alignment audit issues_found verdict requires issues or non-valid error judgements"
            )
        if self.requires_adjudication != (self.verdict != "pass"):
            raise ValueError("requires_adjudication must be true unless the audit passes")
        return self


class StructureAuditIssue(ContractModel):
    issue_type: Literal[
        "missing_section",
        "misordered_section",
        "content_placement",
        "redundancy",
        "findings_impression_inconsistency",
        "clarity",
        "other",
    ]
    report_role: Literal["reference", "candidate", "comparison"]
    section: Literal["findings", "impression", "clinical_history", "other", "overall"]
    severity: Literal["minor", "moderate", "major"]
    explanation: str = Field(min_length=1)
    recommended_action: str = Field(min_length=1)


class StructureAuditArtifact(ContractModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    artifact_type: Literal["structure_audit"] = "structure_audit"
    structure_diff_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assessor_provenance: ModelProvenance
    verdict: Literal["no_material_issue", "minor_issue", "major_issue", "abstain"]
    clinical_impact: StrictInt = Field(ge=1, le=5)
    confidence: StrictFloat = Field(ge=0, le=1)
    summary: str = Field(min_length=1)
    issues: list[StructureAuditIssue] = Field(default_factory=list)
    primary_preserved: Literal[True] = True
    requires_review: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_verdict(self) -> "StructureAuditArtifact":
        if self.verdict == "no_material_issue" and self.issues:
            raise ValueError("no_material_issue verdict cannot contain issues")
        if self.verdict in {"minor_issue", "major_issue"} and not self.issues:
            raise ValueError(f"{self.verdict} verdict requires at least one issue")
        if self.verdict == "major_issue" and self.clinical_impact < 4:
            raise ValueError("major_issue requires clinical_impact of at least 4")
        if self.requires_review != (self.verdict != "no_material_issue"):
            raise ValueError("requires_review must be true unless there is no material issue")
        return self
