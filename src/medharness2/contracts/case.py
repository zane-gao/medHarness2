from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from medharness2.contracts.common import SCHEMA_VERSION, ContractModel
from medharness2.contracts.evaluation import GeneratedReportArtifact
from medharness2.contracts.report_generation import (
    CandidateFailureArtifact,
    CandidateReportArtifact,
    CandidateStructureComparison,
    FusionReportArtifact,
    ReferenceFreeRankingArtifact,
    RoutePlanArtifact,
)


class CaseEvaluationArtifact(ContractModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    artifact_type: Literal["case_evaluation"] = "case_evaluation"
    case_id: str = Field(min_length=1)
    input: dict[str, Any]
    generation_mode: Literal["benchmark", "replay"] | None = None
    route_plan: RoutePlanArtifact | None = None
    candidate_reports: list[CandidateReportArtifact] = Field(default_factory=list)
    candidate_failures: list[CandidateFailureArtifact] = Field(default_factory=list)
    candidate_structure_comparison: CandidateStructureComparison | None = None
    top_k_reports: list[ReferenceFreeRankingArtifact] = Field(default_factory=list)
    fusion_report: FusionReportArtifact | None = None
    human_evaluation: dict[str, Any] | None
    generated_reports: list[GeneratedReportArtifact] = Field(default_factory=list)
    generated_evaluations: list[dict[str, Any]] = Field(default_factory=list)
    rankings: list[dict[str, Any]] = Field(default_factory=list)
    pairwise_comparisons: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    migration_warnings: list[str] = Field(default_factory=list)
    legacy_extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_generation_contract(self) -> "CaseEvaluationArtifact":
        if self.generation_mode is None:
            return self
        if self.route_plan is None or self.candidate_structure_comparison is None or self.fusion_report is None:
            raise ValueError("benchmark/replay generation fields must be complete")
        if self.route_plan.generation_mode != self.generation_mode:
            raise ValueError("case generation mode must match RoutePlan")
        candidate_ids = [candidate.candidate_id for candidate in self.candidate_reports]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate report IDs must be unique")
        known_candidates = set(candidate_ids)
        if not {ranking.candidate_id for ranking in self.top_k_reports}.issubset(known_candidates):
            raise ValueError("Top-K report references an unknown candidate")
        if [ranking.rank for ranking in self.top_k_reports] != list(
            range(1, len(self.top_k_reports) + 1)
        ):
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
        represented_route_keys = {
            candidate.candidate_id.rsplit(":", 1)[-1]
            for candidate in self.candidate_reports
        } | {
            failure.candidate_id.rsplit(":", 1)[-1]
            for failure in self.candidate_failures
        }
        if not set(self.route_plan.candidate_model_keys).issubset(represented_route_keys):
            raise ValueError("every routed model must produce a candidate or failure")
        if self.human_evaluation is None and (
            self.generated_evaluations or self.rankings or self.pairwise_comparisons
        ):
            raise ValueError("generation-only result cannot contain reference-aware evaluation")
        return self
