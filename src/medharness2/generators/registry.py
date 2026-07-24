from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from medharness2.config import AppConfig, resolve_existing_path
from medharness2.contracts import infer_evidence_tier
from medharness2.generators.assets import (
    available_input_capabilities as _asset_input_capabilities,
    looks_like_volume as _asset_looks_like_volume,
)
from medharness2.generators.routing import RoutePlan, build_route_plan
from medharness2.modality import normalize_modality
from medharness2.schema import FORMAL_FRESH_SOURCES, GeneratedReport
from medharness2.utils.processes import run_isolated_process


_GENERATION_PARAMETER_FIELDS = {
    "do_sample",
    "generation_seed",
    "temperature",
    "top_p",
    "top_k",
    "repetition_penalty",
}
_VALIDATION_STATES = {
    "unvalidated",
    "engineering_smoke_only",
    "exploratory",
    "formal",
    "quality_blocked",
}


def _strict_positive_int(value: Any, label: str, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _string_list(value: Any, label: str, default: list[str] | None = None) -> list[str]:
    if value is None:
        return list(default or [])
    if isinstance(value, str) or not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    return list(value)


def _strict_bool(value: Any, label: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _strict_mapping(value: Any, label: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if value is None:
        return dict(default or {})
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return dict(value)


def _strict_string_list(value: Any, label: str, default: list[str] | None = None) -> list[str]:
    if value is None:
        return list(default or [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    return list(value)


@dataclass
class GeneratorEntry:
    key: str
    title: str
    source: str
    supported_modalities: list[str]
    supported_body_parts: list[str] = field(default_factory=lambda: ["unknown"])
    ready: bool = False
    category: str = "local"
    report_trained: bool = False
    report_training: str = ""
    fresh_inference: bool = False
    notes: str = ""
    source_generation_jsonl: str = ""
    medharness_model_key: str = ""
    python_bin: str = "python"
    python_paths: list[str] = field(default_factory=list)
    script_path: str = "/data/isbi/gzp/medHarness/scripts/run_report_generation.py"
    config_path: str = "/data/isbi/gzp/medHarness/configs/reportgen_models.yaml"
    output_jsonl: str = ""
    device: str = "cuda:0"
    dtype: str = "bf16"
    max_new_tokens: int = 160
    generation_parameters: dict[str, Any] = field(default_factory=dict)
    timeout_sec: int = 1800
    evidence_tier: str = ""
    model_version: str = ""
    model_sha256: str = ""
    prompt_version: str = ""
    preprocessing_version: str = ""
    formal_validation_id: str = ""
    runtime_state: str = ""
    validation_state: str = "unvalidated"
    input_capabilities: list[str] = field(default_factory=list)
    cross_modality_allowed: bool = False
    is_universal: bool = False
    resource_status: str = ""
    quality_gate_blocked: bool = False
    blocked_reason: str = ""
    latest_evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.max_new_tokens = _strict_positive_int(self.max_new_tokens, "max_new_tokens", 160)
        self.timeout_sec = _strict_positive_int(self.timeout_sec, "timeout_sec", 1800)
        if not self.evidence_tier:
            self.evidence_tier = infer_evidence_tier(self.source)
        if not self.runtime_state:
            self.runtime_state = "runnable" if self.ready else "unavailable"
        if self.runtime_state not in {"unavailable", "preflight_only", "runnable", "smoke_verified"}:
            raise ValueError(f"Unsupported runtime_state: {self.runtime_state}")
        self.ready = self.runtime_state in {"runnable", "smoke_verified"}
        if not self.resource_status:
            self.resource_status = "ready" if self.ready else self.runtime_state
        if self.validation_state not in _VALIDATION_STATES:
            raise ValueError(f"Unsupported validation_state: {self.validation_state}")

    def readiness_metadata(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "report_trained": self.report_trained,
            "report_training": self.report_training,
            "fresh_inference": self.fresh_inference,
            "ready": self.ready,
            "runtime_state": self.runtime_state,
            "validation_state": self.validation_state,
            "input_capabilities": list(self.input_capabilities),
            "cross_modality_allowed": self.cross_modality_allowed,
            "is_universal": self.is_universal,
            "resource_status": self.resource_status,
            "quality_gate_blocked": self.quality_gate_blocked,
            "blocked_reason": self.blocked_reason,
            "latest_evidence": dict(self.latest_evidence),
            "source": self.source,
            "evidence_tier": self.evidence_tier,
            "route_role": self.route_role,
            "notes": self.notes,
            "formal_readiness_violations": self.formal_readiness_violations(),
        }

    def formal_readiness_violations(self) -> list[str]:
        violations: list[str] = []
        if self.evidence_tier != "formal_fresh":
            violations.append("non_formal_evidence_tier")
        if self.source not in FORMAL_FRESH_SOURCES:
            violations.append("unsupported_formal_source")
        if not self.ready:
            violations.append("generator_not_ready")
        if not self.fresh_inference:
            violations.append("fresh_inference_unverified")
        if not _valid_sha256(self.model_sha256):
            violations.append("missing_model_sha256")
        for field_name in ("model_version", "prompt_version", "preprocessing_version", "formal_validation_id"):
            if not str(getattr(self, field_name) or "").strip():
                violations.append(f"missing_{field_name}")
        return violations

    @property
    def route_role(self) -> str:
        if self.report_trained and self.ready and self.source != "artifact_reuse":
            return "fresh_report_trained_local"
        if self.report_trained and self.source == "artifact_reuse":
            return "artifact_report_trained_local"
        if self.ready:
            return "local_ready_non_report_trained"
        return "local_not_ready"


class ReportGeneratorRegistry:
    def __init__(self, config: AppConfig):
        self.config = config
        entries = self._load_entries(config.generator.local_models)
        if config.generator.include_legacy_ready_models:
            entries.extend(
                self._load_legacy_entries(
                    config.generator.legacy_config_path,
                    default_python_bin=config.llm.local_cli_python_bin,
                )
            )
        if config.generator.external_vlm_enabled:
            entries.append(
                GeneratorEntry(
                    key=config.generator.external_vlm_key,
                    title=config.generator.external_vlm_title,
                    source="external_vlm",
                    supported_modalities=["unknown"],
                    supported_body_parts=["unknown"],
                    runtime_state="runnable",
                    validation_state="unvalidated",
                    input_capabilities=list(config.generator.external_vlm_input_capabilities),
                    is_universal=True,
                    generation_parameters={"model_role": config.generator.external_vlm_model_role},
                )
            )
        self.entries = {}
        for entry in entries:
            self.entries.setdefault(entry.key, entry)

    def select(
        self,
        modality: str,
        requested: list[str] | None = None,
        body_part: str | None = None,
        sources: set[str] | None = None,
        *,
        image_path: str | None = None,
        prepared_assets: dict[str, Any] | None = None,
        case_id: str | None = None,
        generation_mode: str = "production",
    ) -> list[GeneratorEntry]:
        return list(
            self.plan_routes(
                modality,
                body_part=body_part,
                requested=requested,
                sources=sources,
                image_path=image_path,
                prepared_assets=prepared_assets,
                case_id=case_id,
                generation_mode=generation_mode,
            ).candidate_entries
        )

    def plan_routes(
        self,
        modality: str,
        *,
        body_part: str | None = None,
        requested: list[str] | None = None,
        sources: set[str] | None = None,
        image_path: str | None = None,
        prepared_assets: dict[str, Any] | None = None,
        case_id: str | None = None,
        generation_mode: str = "production",
    ) -> RoutePlan:
        keys = list(requested) if requested is not None else list(self.config.generator.default_models)
        requested_filter = set(keys) if keys else {"__no_models_requested__"}
        if "*" in requested_filter:
            requested_filter = set()
        artifact_excluded_reasons = {
            entry.key: reason
            for entry in self.entries.values()
            if entry.source == "artifact_reuse"
            for reason in [_artifact_route_excluded_reason(entry, case_id, generation_mode)]
            if reason is not None
        }
        return build_route_plan(
            self.entries.values(),
            modality=modality,
            body_part=body_part,
            case_id=case_id,
            generation_mode=generation_mode,
            available_input_capabilities=_available_input_capabilities(image_path, prepared_assets),
            requested=requested_filter,
            sources=sources,
            entry_excluded_reasons=artifact_excluded_reasons,
        )

    def compatible_entries(
        self,
        modality: str,
        body_part: str | None = None,
        sources: set[str] | None = None,
    ) -> list[GeneratorEntry]:
        modality_key = _normalize_route_modality(modality)
        result: list[GeneratorEntry] = []
        for entry in self.entries.values():
            if sources and entry.source not in sources:
                continue
            if not entry.ready or entry.validation_state == "quality_blocked":
                continue
            supported = {m.lower() for m in entry.supported_modalities}
            body_supported = {part.lower() for part in entry.supported_body_parts}
            modality_ok = "unknown" in supported or modality_key in {_normalize_route_modality(item) for item in supported}
            if modality_ok:
                result.append(entry)
        return sorted(
            result,
            key=lambda item: (
                item.source != "medharness_cli",
                not _body_part_ok(body_part, {part.lower() for part in item.supported_body_parts}),
                item.key,
            ),
        )

    def generate(
        self,
        entry: GeneratorEntry,
        image_path: str,
        modality: str,
        reference_report: str | None = None,
        body_part: str | None = None,
        case_id: str | None = None,
        generation_mode: str = "production",
    ) -> GeneratedReport:
        if entry.source == "artifact_reuse":
            result = self._generate_artifact(
                entry,
                image_path=image_path,
                modality=modality,
                case_id=case_id,
                generation_mode=generation_mode,
            )
        elif entry.source == "medharness_cli":
            result = self._generate_medharness_cli(
                entry,
                image_path=image_path,
                modality=modality,
                reference_report=reference_report,
                body_part=body_part,
                case_id=case_id,
            )
        else:
            result = self.generate_stub(entry, image_path=image_path, modality=modality, reference_report=reference_report)
        self._apply_entry_metadata(entry, result)
        if reference_report:
            _mark_reference_assisted(result)
        else:
            result.metadata = {**result.metadata, "reference_report_used": False}
        return result

    def generate_stub(self, entry: GeneratorEntry, image_path: str, modality: str, reference_report: str | None = None) -> GeneratedReport:
        if not entry.ready:
            return GeneratedReport(
                model=entry.key,
                source=entry.source,
                report="",
                modality=modality,
                warnings=["local_model_not_ready", entry.notes],
            )
        report = (
            "FINDINGS: No acute cardiopulmonary abnormality is identified.\n"
            "IMPRESSION: No acute disease."
        )
        if reference_report:
            report += "\nCOMPARISON: Reference report was provided for context."
        return GeneratedReport(
            model=entry.key,
            source=entry.source,
            report=report,
            modality=modality,
            warnings=[],
            metadata={"image_path": image_path},
        )

    def _generate_artifact(
        self,
        entry: GeneratorEntry,
        *,
        image_path: str,
        modality: str,
        case_id: str | None = None,
        generation_mode: str = "production",
    ) -> GeneratedReport:
        if generation_mode not in {"benchmark", "replay"}:
            return GeneratedReport(
                model=entry.key,
                source=entry.source,
                report="",
                modality=modality,
                warnings=["artifact_mode_not_enabled"],
                metadata={"generation_mode": generation_mode, "image_path": image_path},
            )
        if not case_id:
            return GeneratedReport(
                model=entry.key,
                source=entry.source,
                report="",
                modality=modality,
                warnings=["artifact_case_id_required"],
                metadata={"generation_mode": generation_mode, "image_path": image_path},
            )
        source = resolve_existing_path(entry.source_generation_jsonl) if entry.source_generation_jsonl else None
        artifact_reason = _artifact_route_excluded_reason(entry, case_id, generation_mode)
        if artifact_reason is not None:
            return GeneratedReport(
                model=entry.key,
                source=entry.source,
                report="",
                modality=modality,
                warnings=[artifact_reason],
                metadata={
                    "source_generation_jsonl": str(source or ""),
                    "image_path": image_path,
                    "generation_mode": generation_mode,
                    "case_id": case_id,
                },
            )
        assert source is not None
        matched_rows: list[dict[str, Any]] = []
        with source.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    return GeneratedReport(
                        model=entry.key,
                        source=entry.source,
                        report="",
                        modality=modality,
                        warnings=["artifact_invalid_jsonl"],
                    )
                if not isinstance(row, dict):
                    return GeneratedReport(
                        model=entry.key,
                        source=entry.source,
                        report="",
                        modality=modality,
                        warnings=["artifact_invalid_row"],
                    )
                raw_case_id = row.get("case_id")
                if not isinstance(raw_case_id, str) or not raw_case_id:
                    return GeneratedReport(
                        model=entry.key,
                        source=entry.source,
                        report="",
                        modality=modality,
                        warnings=["artifact_invalid_case_id"],
                    )
                if raw_case_id != str(case_id):
                    continue
                matched_rows.append(row)
        if not matched_rows:
            return GeneratedReport(
                model=entry.key,
                source=entry.source,
                report="",
                modality=modality,
                warnings=["artifact_case_not_found", str(case_id)],
                metadata={"source_generation_jsonl": str(source), "image_path": image_path},
            )
        if len(matched_rows) > 1:
            return GeneratedReport(
                model=entry.key,
                source=entry.source,
                report="",
                modality=modality,
                warnings=["artifact_case_id_ambiguous", str(case_id)],
                metadata={"source_generation_jsonl": str(source), "image_path": image_path},
            )
        row = matched_rows[0]
        raw_report = row.get("generated_text") or row.get("generated_report") or row.get("prediction_text") or row.get("Pred") or ""
        if not isinstance(raw_report, str):
            return GeneratedReport(model=entry.key, source=entry.source, report="", modality=modality, warnings=["artifact_invalid_report_text"])
        raw_modality = row.get("modality")
        if raw_modality is not None and not isinstance(raw_modality, str):
            return GeneratedReport(model=entry.key, source=entry.source, report="", modality=modality, warnings=["artifact_invalid_modality"])
        return GeneratedReport(
            model=entry.key,
            source=entry.source,
            report=raw_report,
            modality=raw_modality or modality,
            warnings=["artifact_reuse_not_fresh_inference"],
            metadata={
                "case_id": row.get("case_id"),
                "source_generation_jsonl": str(source),
                "image_path": image_path,
                "generation_mode": generation_mode,
            },
        )

    def _generate_medharness_cli(
        self,
        entry: GeneratorEntry,
        *,
        image_path: str,
        modality: str,
        reference_report: str | None,
        body_part: str | None,
        case_id: str | None = None,
    ) -> GeneratedReport:
        script = resolve_existing_path(entry.script_path)
        if not script.exists():
            return GeneratedReport(model=entry.key, source=entry.source, report="", modality=modality, warnings=["legacy_script_missing", str(script)])
        with tempfile.TemporaryDirectory(prefix="medharness2_legacy_") as tmpdir:
            tmp = Path(tmpdir)
            input_jsonl = tmp / "input.jsonl"
            output_jsonl = Path(entry.output_jsonl) if entry.output_jsonl else tmp / "generation.jsonl"
            runtime_config = self._write_legacy_config_overlay(entry, tmp / "reportgen_models.overlay.yaml")
            row = _legacy_input_row(
                case_id=str(case_id or "medharness2_single_case"),
                image_path=image_path,
                modality=modality,
                body_part=body_part,
                reference_report=reference_report,
                prompt=None,
            )
            input_jsonl.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            cmd = [
                _runtime_python_bin(entry.python_bin),
                str(script),
                "--config",
                str(runtime_config),
                "--model-key",
                entry.medharness_model_key or entry.key,
                "--input-jsonl",
                str(input_jsonl),
                "--output-jsonl",
                str(output_jsonl),
                "--limit",
                "1",
                "--device",
                entry.device,
                "--dtype",
                entry.dtype,
                "--max-new-tokens",
                str(entry.max_new_tokens),
            ]
            try:
                completed = _run_legacy_subprocess(cmd, entry)
            except subprocess.CalledProcessError as exc:
                return GeneratedReport(
                    model=entry.key,
                    source=entry.source,
                    report="",
                    modality=modality,
                    warnings=["legacy_generation_failed", (exc.stderr or exc.stdout)[-1000:]],
                    metadata={
                        "cmd": _redacted_cmd(cmd),
                        **_exception_process_metadata(exc),
                    },
                )
            except subprocess.TimeoutExpired as exc:
                return GeneratedReport(
                    model=entry.key,
                    source=entry.source,
                    report="",
                    modality=modality,
                    warnings=["legacy_generation_timeout"],
                    metadata={
                        "cmd": _redacted_cmd(cmd),
                        **_exception_process_metadata(exc),
                    },
                )
            return self._read_legacy_output(
                entry,
                output_jsonl,
                modality=modality,
                cmd=cmd,
                process_provenance=_completed_process_provenance(completed),
            )

    def generate_batch(
        self,
        entry: GeneratorEntry,
        cases: list[dict[str, Any]],
        *,
        include_failures: bool = False,
    ) -> dict[str, GeneratedReport]:
        if not cases:
            return {}
        if entry.source != "medharness_cli":
            return self._batch_failure_reports(
                entry,
                cases,
                warning="batch_generation_not_supported",
                detail=f"unsupported_source:{entry.source}",
            ) if include_failures else {}
        script = resolve_existing_path(entry.script_path)
        if not script.exists():
            return self._batch_failure_reports(
                entry,
                cases,
                warning="legacy_script_missing",
                detail=str(script),
            ) if include_failures else {}
        with tempfile.TemporaryDirectory(prefix="medharness2_legacy_batch_") as tmpdir:
            tmp = Path(tmpdir)
            input_jsonl = tmp / "input.jsonl"
            output_jsonl = tmp / "generation.jsonl"
            runtime_config = self._write_legacy_config_overlay(entry, tmp / "reportgen_models.overlay.yaml")
            input_rows = [
                _legacy_input_row(
                    case_id=str(case["case_id"]),
                    image_path=str(case["image_path"]),
                    modality=str(case["modality"]),
                    body_part=str(case.get("body_part") or ""),
                    reference_report=str(case.get("reference_report") or ""),
                    prompt=str(case.get("prompt") or "") or None,
                )
                for case in cases
            ]
            input_jsonl.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in input_rows),
                encoding="utf-8",
            )
            cmd = [
                _runtime_python_bin(entry.python_bin),
                str(script),
                "--config",
                str(runtime_config),
                "--model-key",
                entry.medharness_model_key or entry.key,
                "--input-jsonl",
                str(input_jsonl),
                "--output-jsonl",
                str(output_jsonl),
                "--limit",
                str(len(input_rows)),
                "--device",
                entry.device,
                "--dtype",
                entry.dtype,
                "--max-new-tokens",
                str(entry.max_new_tokens),
            ]
            try:
                completed = _run_legacy_subprocess(cmd, entry)
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or "")[-1000:]
                return self._batch_failure_reports(
                    entry,
                    cases,
                    warning="legacy_batch_generation_failed",
                    detail=detail,
                    cmd=cmd,
                    process_provenance=_value_process_provenance(exc),
                ) if include_failures else {}
            except subprocess.TimeoutExpired as exc:
                return self._batch_failure_reports(
                    entry,
                    cases,
                    warning="legacy_batch_generation_timeout",
                    detail=f"timeout_sec:{entry.timeout_sec}",
                    cmd=cmd,
                    process_provenance=_value_process_provenance(exc),
                ) if include_failures else {}
            process_provenance = _completed_process_provenance(completed)
            reports = self._read_legacy_output_map(
                entry,
                output_jsonl,
                cmd=cmd,
                process_provenance=process_provenance,
            )
            reference_by_case: dict[str, bool] = {}
            for case in cases:
                reference_report = case.get("reference_report")
                if reference_report is not None and not isinstance(reference_report, str):
                    raise ValueError("reference_report must be a string")
                reference_by_case[str(case["case_id"])] = bool(reference_report)
            if include_failures:
                missing_cases = [
                    case
                    for case in cases
                    if str(case["case_id"]) not in reports
                ]
                reports.update(
                    self._batch_failure_reports(
                        entry,
                        missing_cases,
                        warning="legacy_batch_output_missing",
                        detail="No output row was returned for this case.",
                        cmd=cmd,
                        process_provenance=process_provenance,
                    )
                )
            for case_id, report in reports.items():
                if reference_by_case.get(case_id):
                    _mark_reference_assisted(report)
                else:
                    report.metadata = {**report.metadata, "reference_report_used": False}
                self._apply_entry_metadata(entry, report)
            return reports

    @classmethod
    def _batch_failure_reports(
        cls,
        entry: GeneratorEntry,
        cases: list[dict[str, Any]],
        *,
        warning: str,
        detail: str,
        cmd: list[str] | None = None,
        process_provenance: dict[str, Any] | None = None,
    ) -> dict[str, GeneratedReport]:
        reports: dict[str, GeneratedReport] = {}
        for case in cases:
            case_id = str(case["case_id"])
            report = GeneratedReport(
                model=entry.key,
                source=entry.source,
                report="",
                modality=str(case.get("modality") or ""),
                evidence_tier=entry.evidence_tier,
                warnings=[warning],
                metadata={
                    "batch_error": detail,
                    "reference_report_used": False,
                    **({"cmd": _redacted_cmd(cmd)} if cmd else {}),
                    **(
                        {"process_provenance": process_provenance}
                        if process_provenance is not None
                        else {}
                    ),
                },
            )
            cls._apply_entry_metadata(entry, report)
            reports[case_id] = report
        return reports

    @staticmethod
    def _apply_entry_metadata(
        entry: GeneratorEntry,
        result: GeneratedReport,
    ) -> None:
        result.evidence_tier = entry.evidence_tier
        result.metadata = {
            **result.metadata,
            "evidence_tier": entry.evidence_tier,
            "fresh_inference": entry.fresh_inference,
            "model_version": entry.model_version,
            "model_sha256": entry.model_sha256,
            "prompt_version": entry.prompt_version,
            "preprocessing_version": entry.preprocessing_version,
            "formal_validation_id": entry.formal_validation_id,
            "runtime_python_paths": [
                _resolved_path_text(path) for path in entry.python_paths
            ],
            "generation_parameters": entry.generation_parameters,
        }

    @staticmethod
    def _write_legacy_config_overlay(entry: GeneratorEntry, output_path: Path) -> Path:
        source = resolve_existing_path(entry.config_path)
        if not source.exists():
            return source
        try:
            payload = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        except Exception:
            return source
        payload = _rewrite_existing_legacy_paths(payload)
        model_key = entry.medharness_model_key or entry.key
        models = payload.get("models")
        if not isinstance(models, dict) or not isinstance(models.get(model_key), dict):
            return source
        if entry.python_bin != "python":
            models[model_key]["python_bin"] = _runtime_python_bin(
                entry.python_bin
            )
        for key, value in entry.generation_parameters.items():
            if value is None:
                models[model_key].pop(key, None)
            else:
                models[model_key][key] = value
        output_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return output_path

    @staticmethod
    def _read_legacy_output(
        entry: GeneratorEntry,
        output_jsonl: Path,
        *,
        modality: str,
        cmd: list[str],
        process_provenance: dict[str, Any] | None = None,
    ) -> GeneratedReport:
        if not output_jsonl.exists():
            return GeneratedReport(
                model=entry.key,
                source=entry.source,
                report="",
                modality=modality,
                warnings=["legacy_output_missing"],
                metadata=_legacy_output_metadata({}, cmd, process_provenance),
                evidence_tier=entry.evidence_tier,
            )
        with output_jsonl.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                report = row.get("generated_text") or row.get("generated_report") or row.get("prediction_text") or row.get("Pred") or ""
                return GeneratedReport(
                    model=str(row.get("model_key") or entry.key),
                    source=entry.source,
                    report=str(report),
                    modality=str(row.get("modality") or modality),
                    warnings=_string_list(row.get("warnings"), "warnings"),
                    metadata=_legacy_output_metadata(row, cmd, process_provenance),
                    evidence_tier=entry.evidence_tier,
                )
        return GeneratedReport(
            model=entry.key,
            source=entry.source,
            report="",
            modality=modality,
            warnings=["legacy_output_empty"],
            metadata=_legacy_output_metadata({}, cmd, process_provenance),
            evidence_tier=entry.evidence_tier,
        )

    @staticmethod
    def _read_legacy_output_map(
        entry: GeneratorEntry,
        output_jsonl: Path,
        *,
        cmd: list[str],
        process_provenance: dict[str, Any] | None = None,
    ) -> dict[str, GeneratedReport]:
        if not output_jsonl.exists():
            return {}
        reports: dict[str, GeneratedReport] = {}
        with output_jsonl.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                case_id = str(row.get("case_id") or "")
                if not case_id:
                    continue
                report = row.get("generated_text") or row.get("generated_report") or row.get("prediction_text") or row.get("Pred") or ""
                reports[case_id] = GeneratedReport(
                    model=str(row.get("model_key") or entry.key),
                    source=entry.source,
                    report=str(report),
                    modality=str(row.get("modality") or ""),
                    warnings=_strict_string_list(row.get("warnings"), "warnings"),
                    metadata=_legacy_output_metadata(row, cmd, process_provenance),
                    evidence_tier=entry.evidence_tier,
                )
        return reports

    @staticmethod
    def _load_entries(rows: list[dict[str, Any]]) -> list[GeneratorEntry]:
        entries: list[GeneratorEntry] = []
        for row in rows:
            source = str(row.get("source") or "local")
            ready = _strict_bool(row.get("ready"), "ready", False)
            runtime_state = str(row.get("runtime_state") or "")
            if not runtime_state:
                if source == "artifact_reuse":
                    artifact_path = _resolved_path_text(row.get("source_generation_jsonl") or "")
                    runtime_state = "runnable" if artifact_path and Path(artifact_path).is_file() else "unavailable"
                else:
                    runtime_state = "runnable" if ready else "unavailable"
            entries.append(
                GeneratorEntry(
                    key=str(row.get("key") or row.get("name") or ""),
                    title=str(row.get("title") or row.get("key") or ""),
                    source=source,
                    supported_modalities=_string_list(row.get("supported_modalities"), "supported_modalities", ["unknown"]),
                    supported_body_parts=_string_list(row.get("supported_body_parts"), "supported_body_parts", ["unknown"]),
                    ready=ready,
                    category=str(row.get("category") or _default_category(source)),
                    report_trained=_strict_bool(row.get("report_trained"), "report_trained", _default_report_trained(source)),
                    report_training=str(row.get("report_training") or ""),
                    fresh_inference=_strict_bool(row.get("fresh_inference"), "fresh_inference", False),
                    notes=str(row.get("notes") or ""),
                    source_generation_jsonl=_resolved_path_text(row.get("source_generation_jsonl") or ""),
                    medharness_model_key=str(row.get("medharness_model_key") or row.get("model_key") or ""),
                    python_bin=str(row.get("python_bin") or "python"),
                    python_paths=_string_list(row.get("python_paths"), "python_paths"),
                    script_path=_resolved_path_text(row.get("script_path") or "/data/isbi/gzp/medHarness/scripts/run_report_generation.py"),
                    config_path=_resolved_path_text(row.get("config_path") or "/data/isbi/gzp/medHarness/configs/reportgen_models.yaml"),
                    output_jsonl=str(row.get("output_jsonl") or ""),
                    device=str(row.get("device") or "cuda:0"),
                    dtype=str(row.get("dtype") or "bf16"),
                    max_new_tokens=_strict_positive_int(row.get("max_new_tokens"), "max_new_tokens", 160),
                    generation_parameters=_strict_mapping(
                        row.get("generation_parameters"), "generation_parameters"
                    ),
                    timeout_sec=_strict_positive_int(row.get("timeout_sec"), "timeout_sec", 1800),
                    evidence_tier=str(row.get("evidence_tier") or ""),
                    model_version=str(row.get("model_version") or ""),
                    model_sha256=str(row.get("model_sha256") or ""),
                    prompt_version=str(row.get("prompt_version") or ""),
                    preprocessing_version=str(row.get("preprocessing_version") or ""),
                    formal_validation_id=str(row.get("formal_validation_id") or ""),
                    runtime_state=runtime_state,
                    validation_state=str(row.get("validation_state") or "unvalidated"),
                    input_capabilities=_strict_string_list(row.get("input_capabilities"), "input_capabilities"),
                    cross_modality_allowed=_strict_bool(row.get("cross_modality_allowed"), "cross_modality_allowed", False),
                    is_universal=_strict_bool(row.get("is_universal"), "is_universal", False),
                    resource_status=str(row.get("resource_status") or row.get("status") or ""),
                    quality_gate_blocked=_strict_bool(
                        row.get("quality_gate_blocked"), "quality_gate_blocked", False
                    ),
                    blocked_reason=str(row.get("blocked_reason") or ""),
                    latest_evidence=_strict_mapping(
                        row.get("latest_evidence"), "latest_evidence"
                    ),
                )
            )
        return [entry for entry in entries if entry.key]

    @staticmethod
    def _load_legacy_entries(
        config_path: str | Path,
        *,
        default_python_bin: str = "python",
    ) -> list[GeneratorEntry]:
        path = resolve_existing_path(config_path)
        if not path.exists():
            return []
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return []
        models = payload.get("models") or {}
        if not isinstance(models, dict):
            return []
        entries: list[GeneratorEntry] = []
        status_map = _load_legacy_status_map(path)
        for key, row in models.items():
            if not isinstance(row, dict):
                continue
            # Validate explicit booleans before readiness filtering.  Otherwise
            # values such as ``0``/``"false"`` could be silently treated as an
            # ineligible model instead of surfacing malformed configuration.
            report_trained = _strict_bool(row.get("report_trained"), "report_trained", False)
            status_payload = status_map.get(str(key), {})
            if not _is_legacy_report_generator_ready(
                str(key),
                {**row, "report_trained": report_trained},
                status_payload=status_payload,
            ):
                continue
            adapter = str(row.get("adapter") or "")
            source = "artifact_reuse" if adapter == "artifact_reuse" else "medharness_cli"
            runtime_state = str(status_payload.get("runtime_state") or row.get("runtime_state") or "unavailable")
            modalities = _normalize_modalities(
                _strict_string_list(row.get("supported_modalities"), "supported_modalities", ["unknown"])
            )
            body_parts = [
                item.lower()
                for item in _strict_string_list(
                    row.get("supported_body_parts"), "supported_body_parts", ["unknown"]
                )
            ]
            entries.append(
                GeneratorEntry(
                    key=str(key),
                    title=str(row.get("title") or key),
                    source=source,
                    supported_modalities=modalities,
                    supported_body_parts=body_parts,
                    ready=runtime_state in {"runnable", "smoke_verified"},
                    category=str(row.get("category") or ""),
                    report_trained=report_trained,
                    report_training=str(row.get("report_training") or ""),
                    fresh_inference=_strict_bool(
                        status_payload.get("fresh_inference", row.get("fresh_inference")),
                        "fresh_inference",
                        False,
                    ),
                    notes=str(row.get("notes") or ""),
                    source_generation_jsonl=_resolved_path_text(row.get("source_generation_jsonl") or ""),
                    medharness_model_key=str(key),
                    python_bin=str(
                        default_python_bin
                        if str(row.get("python_bin") or "python") == "python"
                        else row.get("python_bin")
                    ),
                    python_paths=_strict_string_list(row.get("python_paths"), "python_paths"),
                    script_path=_resolved_path_text("/data/isbi/gzp/medHarness/scripts/run_report_generation.py"),
                    config_path=str(path),
                    generation_parameters={
                        key: row.get(key)
                        for key in _GENERATION_PARAMETER_FIELDS
                        if key in row
                    },
                    evidence_tier=str(row.get("evidence_tier") or ""),
                    model_version=str(row.get("model_version") or ""),
                    model_sha256=str(row.get("model_sha256") or ""),
                    prompt_version=str(row.get("prompt_version") or ""),
                    preprocessing_version=str(row.get("preprocessing_version") or ""),
                    formal_validation_id=str(row.get("formal_validation_id") or ""),
                    runtime_state=runtime_state,
                    validation_state=str(status_payload.get("validation_state") or row.get("validation_state") or "unvalidated"),
                    input_capabilities=_strict_string_list(
                        status_payload.get("input_capabilities", row.get("input_capabilities")),
                        "input_capabilities",
                    ),
                    cross_modality_allowed=_strict_bool(
                        status_payload.get("cross_modality_allowed", row.get("cross_modality_allowed")),
                        "cross_modality_allowed",
                        False,
                    ),
                    is_universal=_strict_bool(
                        status_payload.get("is_universal", row.get("is_universal")),
                        "is_universal",
                        False,
                    ),
                    resource_status=str(status_payload.get("status") or ""),
                    quality_gate_blocked=_strict_bool(
                        status_payload.get("quality_gate_blocked"),
                        "quality_gate_blocked",
                        False,
                    ),
                    blocked_reason=str(status_payload.get("blocked_reason") or ""),
                    latest_evidence=_strict_mapping(
                        status_payload.get("latest_evidence"), "latest_evidence"
                    ),
                )
            )
        return entries


def _resolved_path_text(path: Any) -> str:
    if not path:
        return ""
    return str(resolve_existing_path(str(path)))


def _artifact_route_excluded_reason(
    entry: GeneratorEntry,
    case_id: str | None,
    generation_mode: str,
) -> str | None:
    if generation_mode not in {"benchmark", "replay"} or not case_id:
        return None
    if not entry.source_generation_jsonl:
        return "artifact_missing"
    source = resolve_existing_path(entry.source_generation_jsonl)
    if not source.is_file():
        return "artifact_missing"
    try:
        stat = source.stat()
        counts, invalid_reason = _artifact_case_index_cached(
            str(source.resolve()),
            stat.st_mtime_ns,
            stat.st_size,
        )
    except OSError:
        return "artifact_missing"
    if invalid_reason is not None:
        return invalid_reason
    count = counts.get(str(case_id), 0)
    if count == 0:
        return "artifact_case_not_found"
    if count > 1:
        return "artifact_case_id_ambiguous"
    return None


@lru_cache(maxsize=64)
def _artifact_case_index_cached(
    source_path: str,
    mtime_ns: int,
    size: int,
) -> tuple[dict[str, int], str | None]:
    del mtime_ns, size
    counts: dict[str, int] = {}
    try:
        with Path(source_path).open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    return {}, "artifact_invalid_jsonl"
                if not isinstance(row, dict):
                    return {}, "artifact_invalid_row"
                row_case_id = row.get("case_id")
                if not isinstance(row_case_id, str) or not row_case_id:
                    return {}, "artifact_invalid_case_id"
                counts[row_case_id] = counts.get(row_case_id, 0) + 1
    except OSError:
        return {}, "artifact_missing"
    return counts, None


def _runtime_python_bin(value: str) -> str:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        return value
    return str(resolve_existing_path(candidate))


def _run_legacy_subprocess(
    cmd: list[str],
    entry: GeneratorEntry,
) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {
        "check": True,
        "capture_output": True,
        "text": True,
        "timeout": entry.timeout_sec,
    }
    if entry.python_paths:
        env = os.environ.copy()
        resolved_paths = [
            str(resolve_existing_path(path).resolve())
            for path in entry.python_paths
        ]
        existing = env.get("PYTHONPATH")
        if existing:
            resolved_paths.append(existing)
        env["PYTHONPATH"] = os.pathsep.join(resolved_paths)
        kwargs["env"] = env
    return run_isolated_process(cmd, **kwargs)


def _rewrite_existing_legacy_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _rewrite_existing_legacy_paths(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rewrite_existing_legacy_paths(item) for item in value]
    if not isinstance(value, str):
        return value
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        return value
    resolved = resolve_existing_path(candidate)
    return str(resolved) if resolved != candidate else value


def _redacted_cmd(cmd: list[str]) -> list[str]:
    return [part if "token" not in part.lower() and "key" not in part.lower() else "<redacted>" for part in cmd]


def _legacy_output_metadata(
    row: dict[str, Any],
    cmd: list[str],
    process_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "cmd": _redacted_cmd(cmd),
        "adapter_status": row.get("adapter_status"),
    }
    for source_field, target_field in (
        ("runtime", "adapter_runtime"),
        ("input_assets", "adapter_input_assets"),
        ("generated_sections", "adapter_generated_sections"),
    ):
        value = row.get(source_field)
        if isinstance(value, dict):
            metadata[target_field] = value
    if row.get("raw_output") is not None:
        metadata["raw_model_output"] = str(row.get("raw_output"))
    if row.get("case_id") is not None:
        metadata["adapter_case_id"] = str(row.get("case_id"))
    if row.get("body_part") is not None:
        metadata["adapter_body_part"] = str(row.get("body_part"))
    if process_provenance is not None:
        metadata["process_provenance"] = process_provenance
    return metadata


def _completed_process_provenance(
    completed: subprocess.CompletedProcess[Any],
) -> dict[str, Any] | None:
    return _value_process_provenance(completed)


def _value_process_provenance(value: Any) -> dict[str, Any] | None:
    provenance = getattr(value, "process_provenance", None)
    return dict(provenance) if isinstance(provenance, dict) else None


def _exception_process_metadata(exc: BaseException) -> dict[str, Any]:
    provenance = _value_process_provenance(exc)
    return {"process_provenance": provenance} if provenance is not None else {}


def _legacy_input_row(
    *,
    case_id: str,
    image_path: str,
    modality: str,
    body_part: str | None,
    reference_report: str | None,
    prompt: str | None = None,
) -> dict[str, Any]:
    modality_key = normalize_modality(modality)
    asset_path = str(Path(image_path).expanduser().resolve())
    return {
        "case_id": case_id,
        # Keep the legacy CLI's xray spelling while normalizing all inputs at
        # this boundary to the same three-family route vocabulary.
        "modality": "xray" if modality_key == "cxr" else modality_key,
        "body_part": body_part or _default_body_part(modality_key),
        "image_paths": [] if _looks_like_volume(asset_path) else [asset_path],
        "volume_path": asset_path if _looks_like_volume(asset_path) else None,
        "reference_report": reference_report or "",
        "prompt": prompt or _legacy_prompt(modality_key, body_part),
    }


def _legacy_prompt(
    modality: str,
    body_part: str | None,
    *,
    selected_series_type: str | None = None,
    selected_series_description: str | None = None,
) -> str:
    modality_key = normalize_modality(modality)
    body = (body_part or _default_body_part(modality_key)).lower()
    if modality_key == "mri" and body == "brain":
        selected = (selected_series_type or "").lower()
        description = (selected_series_description or "").lower()
        if selected == "t2" or ("t2" in description and "flair" not in description):
            return "Generate a radiology report for this brain MRI T2 scan."
        if selected == "flair" or "flair" in description:
            return "Generate a radiology report for this brain MRI FLAIR scan."
        if selected or description:
            return "Generate a radiology report for this brain MRI study."
        return "Generate a radiology report for this brain MRI FLAIR scan."
    if modality_key == "ct" and body in {"abdomen", "pelvis", "multi-organ"}:
        return "Generate a radiology report for this abdominal CT study."
    if modality_key == "cxr" and body in {"chest", "lung"}:
        return "Analyze the chest X-ray images and write a radiology report."
    return "Generate a radiology report for this study."


def _looks_like_volume(path: str) -> bool:
    return _asset_looks_like_volume(path)


def _available_input_capabilities(
    image_path: str | None,
    prepared_assets: dict[str, Any] | None,
) -> set[str] | None:
    return _asset_input_capabilities(image_path, prepared_assets)


def _default_body_part(modality: str) -> str:
    modality_key = normalize_modality(modality)
    if modality_key == "mri":
        return "brain"
    if modality_key == "ct":
        return "abdomen"
    return "chest"


def _is_legacy_report_generator_ready(
    key: str,
    row: dict[str, Any],
    *,
    status_payload: dict[str, Any] | None = None,
) -> bool:
    report_trained = row.get("report_trained", False)
    if not isinstance(report_trained, bool):
        raise ValueError("report_trained must be a boolean")
    if not report_trained:
        return False
    category = str(row.get("category") or "")
    adapter = str(row.get("adapter") or "")
    if adapter == "artifact_reuse":
        source_generation_jsonl = row.get("source_generation_jsonl", "")
        if source_generation_jsonl is not None and not isinstance(source_generation_jsonl, str):
            raise ValueError("source_generation_jsonl must be a string")
        return bool(source_generation_jsonl)
    if adapter in {"source_audit_only", "blocked_no_public_weights", "gated_waitlist", ""}:
        return False
    if status_payload:
        runtime_state = str(status_payload.get("runtime_state") or "unavailable")
        return runtime_state in {"preflight_only", "runnable", "smoke_verified"}
    return category in {"ready_or_artifact", "report_trained_target"}


def _load_legacy_status_map(config_path: Path) -> dict[str, dict[str, Any]]:
    payload = load_legacy_status_export(config_path)
    models = payload.get("models") or []
    if not isinstance(models, list):
        return {}
    return {
        str(row.get("model_key")): row
        for row in models
        if isinstance(row, dict) and row.get("model_key")
    }


def load_legacy_status_export(config_path: str | Path) -> dict[str, Any]:
    path = resolve_existing_path(config_path)
    if not path.is_file():
        return {}
    source_root = path.parent.parent / "src"
    inserted = False
    if source_root.is_dir() and str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
        inserted = True
    try:
        from medharness.reportgen.status_export import build_status_export

        return build_status_export(path)
    except (ImportError, OSError, ValueError, yaml.YAMLError):
        return {}
    finally:
        if inserted:
            sys.path.remove(str(source_root))


def _normalize_modalities(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        key = str(value).lower()
        result.append(key)
        if key in {"xray", "x-ray", "xr", "cr", "dx"}:
            result.append("cxr")
    return list(dict.fromkeys(result))


def _normalize_route_modality(value: Any) -> str:
    return normalize_modality(value)


def _body_part_ok(body_part: str | None, supported: set[str]) -> bool:
    if not body_part or body_part.lower() == "unknown":
        return True
    return "unknown" in supported or body_part.lower() in supported


def _default_category(source: str) -> str:
    if source == "medharness_cli":
        return "report_trained_target"
    if source == "artifact_reuse":
        return "ready_or_artifact"
    return "local"


def _default_report_trained(source: str) -> bool:
    return source in {"artifact_reuse", "medharness_cli"}


def _mark_reference_assisted(report: GeneratedReport) -> None:
    report.evidence_tier = "debug_fallback"
    report.metadata = {**report.metadata, "reference_report_used": True, "evidence_tier": "debug_fallback"}
    if "reference_assisted_generation" not in report.warnings:
        report.warnings.append("reference_assisted_generation")


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
