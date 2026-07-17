from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, PrivateAttr, StrictBool

from medharness2.config import PROJECT_ROOT
from medharness2.contracts.common import ContractModel


class ValidationGate(ContractModel):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)


class ValidationEvidenceArtifact(ContractModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    media_type: str = Field(min_length=1)


class ValidationCheck(ContractModel):
    id: str = Field(min_length=1)
    passed: StrictBool
    details: str = Field(min_length=1)


class GateValidationEvidence(ContractModel):
    passed: StrictBool
    verifier: Literal["medharness2.experiments.verify"]
    verification_version: Literal["1.0"]
    evidence_artifacts: list[ValidationEvidenceArtifact] = Field(min_length=1)
    checks: list[ValidationCheck] = Field(min_length=1)
    verification_id: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExperimentProtocol(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    id: str = Field(min_length=1)
    notion_section: str = Field(min_length=1)
    research_question: str = Field(min_length=1)
    implementation: dict[str, Any]
    model_policy: dict[str, Any]
    inputs: list[str]
    outputs: list[str]
    cohort: dict[str, Any]
    primary_endpoints: list[str] = Field(min_length=1)
    secondary_endpoints: list[str] = Field(default_factory=list)
    statistics: list[str] = Field(min_length=1)
    validation_gates: list[ValidationGate] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    _source_path: Path = PrivateAttr()

    @property
    def source_path(self) -> Path:
        return self._source_path


def load_experiment_protocols(protocol_dir: str | Path | None = None) -> dict[str, ExperimentProtocol]:
    root = Path(protocol_dir) if protocol_dir else PROJECT_ROOT / "experiments" / "protocols"
    protocols: dict[str, ExperimentProtocol] = {}
    for path in sorted(root.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        protocol = ExperimentProtocol.model_validate(payload)
        protocol._source_path = path
        if protocol.id in protocols:
            raise ValueError(f"Duplicate experiment protocol id: {protocol.id}")
        protocols[protocol.id] = protocol
    if not protocols:
        raise FileNotFoundError(f"No experiment protocol YAML files found: {root}")
    return protocols


def load_validation_evidence(run_dir: str | Path) -> dict[str, Any]:
    path = Path(run_dir) / "experiment_validation.json"
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    experiments = payload.get("experiments")
    if experiments is None:
        return {}
    if not isinstance(experiments, dict):
        raise ValueError("experiments must be a mapping")
    for experiment_id, value in experiments.items():
        if not isinstance(value, dict):
            raise ValueError(f"experiments.{experiment_id} must be a mapping")
    return dict(experiments)


def evaluate_readiness(
    protocol: ExperimentProtocol,
    *,
    evidence_status: str,
    validation_evidence: dict[str, Any],
    run_dir: str | Path,
) -> dict[str, Any]:
    root = Path(run_dir)
    configured_payload = validation_evidence.get(protocol.id) or {}
    if not isinstance(configured_payload, dict):
        raise ValueError(f"{protocol.id} must be a mapping")
    configured_value = configured_payload.get("gates")
    if configured_value is None:
        configured_value = {}
    if not isinstance(configured_value, dict):
        raise ValueError(f"{protocol.id}.gates must be a mapping")
    configured = dict(configured_value)
    gates = []
    for gate in protocol.validation_gates:
        raw_row = configured.get(gate.id) or {}
        if not isinstance(raw_row, dict):
            raise ValueError(f"gates.{gate.id} must be a mapping")
        row = dict(raw_row)
        verification = _verify_gate_evidence(root, gate.id, row)
        gates.append(
            {
                "id": gate.id,
                "description": gate.description,
                **verification,
            }
        )
    if evidence_status == "missing_inputs":
        status = "not_ready"
    elif gates and all(gate["passed"] for gate in gates):
        status = "validated"
    else:
        status = "pilot"
    passed_count = sum(1 for gate in gates if gate["passed"])
    return {
        "status": status,
        "validation_gates": gates,
        "gate_summary": {"total": len(gates), "passed": passed_count, "failed": len(gates) - passed_count},
    }


def _verify_gate_evidence(root: Path, gate_id: str, row: dict[str, Any]) -> dict[str, Any]:
    raw_artifacts = row.get("evidence_artifacts")
    raw_paths = row.get("evidence_paths")
    malformed_paths = (
        (raw_artifacts is not None and (not isinstance(raw_artifacts, list) or any(not isinstance(item, dict) for item in raw_artifacts)))
        or (raw_paths is not None and (not isinstance(raw_paths, list) or any(not isinstance(path, str) for path in raw_paths)))
    )
    if malformed_paths:
        return _gate_result(False, "invalid_gate_evidence_contract", [])
    displayed_paths = [str(item.get("path") or "") for item in raw_artifacts or []] or list(raw_paths or [])
    try:
        evidence = GateValidationEvidence.model_validate(row)
    except Exception:
        return _gate_result(False, "invalid_gate_evidence_contract", displayed_paths)
    if not evidence.passed:
        return _gate_result(False, "gate_not_passed", displayed_paths, evidence.verification_id)
    if any(not check.passed for check in evidence.checks):
        return _gate_result(False, "failed_machine_check", displayed_paths, evidence.verification_id)
    if evidence.verification_id != _verification_id(row):
        return _gate_result(False, "invalid_verification_id", displayed_paths, evidence.verification_id)

    root_resolved = root.resolve()
    for artifact in evidence.evidence_artifacts:
        path = Path(artifact.path)
        resolved = path.resolve() if path.is_absolute() else (root_resolved / path).resolve()
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            return _gate_result(False, "evidence_path_outside_run", displayed_paths, evidence.verification_id)
        if not resolved.exists():
            return _gate_result(False, "evidence_missing", displayed_paths, evidence.verification_id)
        if not resolved.is_file():
            return _gate_result(False, "evidence_not_file", displayed_paths, evidence.verification_id)
        payload_bytes = resolved.read_bytes()
        if not payload_bytes:
            return _gate_result(False, "empty_evidence_file", displayed_paths, evidence.verification_id)
        if hashlib.sha256(payload_bytes).hexdigest() != artifact.sha256:
            return _gate_result(False, "evidence_sha256_mismatch", displayed_paths, evidence.verification_id)
        if artifact.media_type == "application/json":
            reason = _validate_json_evidence(payload_bytes, artifact, gate_id)
            if reason:
                return _gate_result(False, reason, displayed_paths, evidence.verification_id)
    return _gate_result(True, "passed", displayed_paths, evidence.verification_id)


def _validate_json_evidence(payload_bytes: bytes, artifact: ValidationEvidenceArtifact, gate_id: str) -> str:
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "invalid_json_evidence_contract"
    if not isinstance(payload, dict) or not payload.get("schema_version") or not payload.get("artifact_type"):
        return "invalid_json_evidence_contract"
    if str(payload["schema_version"]) != artifact.schema_version:
        return "evidence_schema_version_mismatch"
    if str(payload["artifact_type"]) != artifact.artifact_type:
        return "evidence_artifact_type_mismatch"
    if artifact.artifact_type == "experiment_gate_evidence" and str(payload.get("gate_id") or "") != gate_id:
        return "evidence_gate_id_mismatch"
    return ""


def _verification_id(row: dict[str, Any]) -> str:
    payload = dict(row)
    payload.pop("verification_id", None)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _gate_result(
    passed: bool,
    reason: str,
    evidence_paths: list[str],
    verification_id: str = "",
) -> dict[str, Any]:
    return {
        "passed": passed,
        "evidence_paths": evidence_paths,
        "verification_id": verification_id,
        "reason": reason,
    }
