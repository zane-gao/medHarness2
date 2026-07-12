from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from medharness2.contracts.common import SCHEMA_VERSION, ArtifactReference, ContractModel


class RunManifest(ContractModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    artifact_type: Literal["run_manifest"] = "run_manifest"
    run_id: str = Field(min_length=1)
    run_kind: Literal["pilot", "formal", "smoke", "development"]
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    git_sha: str = ""
    config_sha256: str = ""
    dataset_manifest_sha256: str = ""
    artifacts: list[ArtifactReference] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
