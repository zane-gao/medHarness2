from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from medharness2.contracts.common import SCHEMA_VERSION, ContractModel
from medharness2.contracts.evaluation import GeneratedReportArtifact


class CaseEvaluationArtifact(ContractModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    artifact_type: Literal["case_evaluation"] = "case_evaluation"
    case_id: str = Field(min_length=1)
    input: dict[str, Any]
    human_evaluation: dict[str, Any]
    generated_reports: list[GeneratedReportArtifact] = Field(default_factory=list)
    generated_evaluations: list[dict[str, Any]] = Field(default_factory=list)
    rankings: list[dict[str, Any]] = Field(default_factory=list)
    pairwise_comparisons: list[dict[str, Any]] = Field(default_factory=list)
    migration_warnings: list[str] = Field(default_factory=list)
    legacy_extensions: dict[str, Any] = Field(default_factory=dict)
