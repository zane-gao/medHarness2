from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field, model_validator

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

    @model_validator(mode="after")
    def validate_counts_and_rates(self) -> "DenominatorAggregate":
        if (
            self.source_case_count is not None
            and self.manifest_case_count is not None
            and self.source_case_count != self.manifest_case_count
        ):
            raise ValueError(
                "source_case_count must match manifest_case_count when both are provided"
            )

        # Older workflow files used manifest_case_count while newer files may
        # use source_case_count. Treat either field as the total denominator.
        source = (
            self.source_case_count
            if self.source_case_count is not None
            else self.manifest_case_count
        )
        counts = (source, self.successful_case_count, self.failed_case_count)
        if all(value is not None for value in counts):
            source, successful, failed = (int(value) for value in counts)
            if successful + failed != source:
                raise ValueError("denominator counts must sum to the total case count")
            expected_success = successful / source if source else 0.0
            expected_failure = failed / source if source else 0.0
            if self.success_rate is not None and abs(self.success_rate - expected_success) > 1e-4:
                raise ValueError("success_rate does not match denominator counts")
            if self.failure_rate is not None and abs(self.failure_rate - expected_failure) > 1e-4:
                raise ValueError("failure_rate does not match denominator counts")
        return self


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

    @model_validator(mode="after")
    def validate_case_rows(self) -> "Workflow2Aggregate":
        if self.cases and len(self.cases) != self.case_count:
            raise ValueError("workflow2 cases length must match case_count")
        if self.failed_cases and len(self.failed_cases) != self.failed_case_count:
            raise ValueError("workflow2 failed_cases length must match failed_case_count")
        return self


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

    @model_validator(mode="after")
    def validate_reader_count(self) -> "Workflow3Aggregate":
        if self.reader_count is not None and self.reader_percentiles and self.reader_count != len(self.reader_percentiles):
            raise ValueError("workflow3 reader_count must match reader_percentiles")
        return self
