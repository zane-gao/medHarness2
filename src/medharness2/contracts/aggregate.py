from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field

from medharness2.contracts.common import ContractModel


class AggregateCompatModel(ContractModel):
    """Typed boundary for evolving aggregate payloads.

    Aggregate files intentionally allow additive fields because historical runs
    contain analysis-specific metrics.  Known structural fields are still
    type-checked so malformed payloads cannot silently pass validation.
    """

    model_config = ConfigDict(extra="allow", validate_assignment=True)


class DenominatorAggregate(AggregateCompatModel):
    source_case_count: int | None = Field(default=None, ge=0)
    manifest_case_count: int | None = Field(default=None, ge=0)
    successful_case_count: int | None = Field(default=None, ge=0)
    failed_case_count: int | None = Field(default=None, ge=0)
    success_rate: float | None = Field(default=None, ge=0, le=1)
    failure_rate: float | None = Field(default=None, ge=0, le=1)


class ReaderAggregate(AggregateCompatModel):
    cases: list[str] = Field(default_factory=list)
    case_count: int | None = Field(default=None, ge=0)
    overall_score: float | None = None
    human_metrics: list[dict[str, Any]] = Field(default_factory=list)
    modelwise_metrics: list[dict[str, Any]] = Field(default_factory=list)
    human_statistics: dict[str, Any] = Field(default_factory=dict)
    modelwise_statistics: dict[str, Any] = Field(default_factory=dict)


class Workflow2Aggregate(AggregateCompatModel):
    case_count: int = Field(default=0, ge=0)
    failed_case_count: int = Field(default=0, ge=0)
    cases: list[dict[str, Any]] = Field(default_factory=list)
    failed_cases: list[dict[str, Any]] = Field(default_factory=list)
    per_reader: dict[str, ReaderAggregate] = Field(default_factory=dict)
    denominator: DenominatorAggregate = Field(default_factory=DenominatorAggregate)
    statistics: dict[str, Any] = Field(default_factory=dict)


class ReaderPercentile(AggregateCompatModel):
    overall_score: float | None = None
    percentile: float | None = Field(default=None, ge=0, le=100)
    case_count: int | None = Field(default=None, ge=0)


class Workflow3Aggregate(AggregateCompatModel):
    case_count: int = Field(default=0, ge=0)
    failed_case_count: int = Field(default=0, ge=0)
    reader_count: int | None = Field(default=None, ge=0)
    reader_percentiles: dict[str, ReaderPercentile] = Field(default_factory=dict)
    denominator: DenominatorAggregate = Field(default_factory=DenominatorAggregate)
    statistics: dict[str, Any] = Field(default_factory=dict)
    comparisons: dict[str, Any] = Field(default_factory=dict)
