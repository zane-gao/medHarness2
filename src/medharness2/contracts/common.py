from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SCHEMA_VERSION = "2.0"
EvidenceTier = Literal["formal_fresh", "exploratory_fresh", "artifact", "debug_fallback", "mock"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class TextSpan(ContractModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_order(self) -> "TextSpan":
        if self.end < self.start:
            raise ValueError("TextSpan.end must be greater than or equal to start")
        return self


class Measurement(ContractModel):
    value: float = Field(ge=0)
    unit: Literal["mm", "cm"]
    normalized_mm: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def normalize_measurement(self) -> "Measurement":
        expected = float(self.value * 10.0 if self.unit == "cm" else self.value)
        if self.normalized_mm is not None and abs(self.normalized_mm - expected) > 1e-6:
            raise ValueError("Measurement.normalized_mm does not match value and unit")
        object.__setattr__(self, "normalized_mm", expected)
        return self


class ModelProvenance(ContractModel):
    implementation_type: str = Field(min_length=1)
    provider: str = ""
    model: str = ""
    version: str = ""
    role: str = ""
    prompt_version: str = ""
    fallback_used: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactReference(ContractModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: str = Field(min_length=1)
    media_type: str = "application/json"
