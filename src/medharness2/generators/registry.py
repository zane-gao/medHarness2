from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from medharness2.config import AppConfig, resolve_existing_path
from medharness2.contracts import infer_evidence_tier
from medharness2.schema import FORMAL_FRESH_SOURCES, GeneratedReport


_LEGACY_FORMAL_ROUTE_EXCLUDE = {
    "chexagent_srrg_findings",
    "chexagent_srrg_impression",
    "lingshu_srrg_findings",
    "histgen",
    "pathgenic",
}

_GENERATION_PARAMETER_FIELDS = {
    "do_sample",
    "generation_seed",
    "temperature",
    "top_p",
    "top_k",
    "repetition_penalty",
}


def _strict_positive_int(value: Any, label: str, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


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

    def __post_init__(self) -> None:
        self.max_new_tokens = _strict_positive_int(self.max_new_tokens, "max_new_tokens", 160)
        self.timeout_sec = _strict_positive_int(self.timeout_sec, "timeout_sec", 1800)
        if not self.evidence_tier:
            self.evidence_tier = infer_evidence_tier(self.source)

    def readiness_metadata(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "report_trained": self.report_trained,
            "report_training": self.report_training,
            "fresh_inference": self.fresh_inference,
            "ready": self.ready,
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
        if self.report_trained and self.fresh_inference:
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
            entries.extend(self._load_legacy_entries(config.generator.legacy_config_path))
        self.entries = {}
        for entry in entries:
            self.entries.setdefault(entry.key, entry)

    def select(
        self,
        modality: str,
        requested: list[str] | None = None,
        body_part: str | None = None,
        sources: set[str] | None = None,
    ) -> list[GeneratorEntry]:
        modality_key = _normalize_route_modality(modality)
        if (requested and "*" in requested) or (requested is None and "*" in self.config.generator.default_models):
            return self.compatible_entries(modality_key, body_part=body_part, sources=sources)
        keys = requested or self.config.generator.default_models
        selected: list[GeneratorEntry] = []
        for key in keys:
            entry = self.entries.get(key)
            if not entry:
                continue
            if sources and entry.source not in sources:
                continue
            supported = {m.lower() for m in entry.supported_modalities}
            body_supported = {part.lower() for part in entry.supported_body_parts}
            modality_ok = "unknown" in supported or modality_key in {_normalize_route_modality(item) for item in supported}
            if modality_ok:
                selected.append(entry)
        return selected

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
    ) -> GeneratedReport:
        if entry.source == "artifact_reuse":
            result = self._generate_artifact(
                entry,
                image_path=image_path,
                modality=modality,
                case_id=case_id,
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
    ) -> GeneratedReport:
        source = resolve_existing_path(entry.source_generation_jsonl) if entry.source_generation_jsonl else Path("")
        if not source.exists():
            return GeneratedReport(
                model=entry.key,
                source=entry.source,
                report="",
                modality=modality,
                warnings=["artifact_missing", str(source)],
            )
        fallback_row: dict[str, Any] | None = None
        with source.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                if fallback_row is None:
                    fallback_row = row
                row_case_id = str(row.get("case_id") or row.get("sample_id") or "")
                if case_id and row_case_id and row_case_id != str(case_id):
                    continue
                if case_id and not row_case_id:
                    # A legacy single-row artifact has no case identity; keep
                    # it compatible only when the file is unambiguously one row.
                    remainder = [item for item in f if item.strip()]
                    if remainder:
                        return GeneratedReport(
                            model=entry.key,
                            source=entry.source,
                            report="",
                            modality=modality,
                            warnings=["artifact_case_id_missing_for_multi_case_artifact"],
                            metadata={"source_generation_jsonl": str(source), "image_path": image_path},
                        )
                report = row.get("generated_text") or row.get("generated_report") or row.get("prediction_text") or row.get("Pred") or ""
                return GeneratedReport(
                    model=entry.key,
                    source=entry.source,
                    report=str(report),
                    modality=str(row.get("modality") or modality),
                    warnings=["artifact_reuse_not_fresh_inference"],
                    metadata={
                        "case_id": row.get("case_id") or row.get("sample_id"),
                        "source_generation_jsonl": str(source),
                        "image_path": image_path,
                    },
                )
        if case_id:
            return GeneratedReport(
                model=entry.key,
                source=entry.source,
                report="",
                modality=modality,
                warnings=["artifact_case_not_found", str(case_id)],
                metadata={"source_generation_jsonl": str(source), "image_path": image_path},
            )
        if fallback_row is not None:
            row = fallback_row
            report = row.get("generated_text") or row.get("generated_report") or row.get("prediction_text") or row.get("Pred") or ""
            return GeneratedReport(
                model=entry.key,
                source=entry.source,
                report=str(report),
                modality=str(row.get("modality") or modality),
                warnings=["artifact_reuse_not_fresh_inference"],
                metadata={
                    "case_id": row.get("case_id") or row.get("sample_id"),
                    "source_generation_jsonl": str(source),
                    "image_path": image_path,
                },
            )
        return GeneratedReport(model=entry.key, source=entry.source, report="", modality=modality, warnings=["artifact_empty"])

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
                _run_legacy_subprocess(cmd, entry)
            except subprocess.CalledProcessError as exc:
                return GeneratedReport(
                    model=entry.key,
                    source=entry.source,
                    report="",
                    modality=modality,
                    warnings=["legacy_generation_failed", (exc.stderr or exc.stdout)[-1000:]],
                    metadata={"cmd": _redacted_cmd(cmd)},
                )
            except subprocess.TimeoutExpired:
                return GeneratedReport(
                    model=entry.key,
                    source=entry.source,
                    report="",
                    modality=modality,
                    warnings=["legacy_generation_timeout"],
                    metadata={"cmd": _redacted_cmd(cmd)},
                )
            return self._read_legacy_output(entry, output_jsonl, modality=modality, cmd=cmd)

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
                _run_legacy_subprocess(cmd, entry)
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or "")[-1000:]
                return self._batch_failure_reports(
                    entry,
                    cases,
                    warning="legacy_batch_generation_failed",
                    detail=detail,
                    cmd=cmd,
                ) if include_failures else {}
            except subprocess.TimeoutExpired:
                return self._batch_failure_reports(
                    entry,
                    cases,
                    warning="legacy_batch_generation_timeout",
                    detail=f"timeout_sec:{entry.timeout_sec}",
                    cmd=cmd,
                ) if include_failures else {}
            reports = self._read_legacy_output_map(entry, output_jsonl, cmd=cmd)
            reference_by_case = {str(case["case_id"]): bool(case.get("reference_report")) for case in cases}
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
    def _read_legacy_output(entry: GeneratorEntry, output_jsonl: Path, *, modality: str, cmd: list[str]) -> GeneratedReport:
        if not output_jsonl.exists():
            return GeneratedReport(model=entry.key, source=entry.source, report="", modality=modality, warnings=["legacy_output_missing"])
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
                    warnings=list(row.get("warnings") or []),
                    metadata=_legacy_output_metadata(row, cmd),
                    evidence_tier=entry.evidence_tier,
                )
        return GeneratedReport(model=entry.key, source=entry.source, report="", modality=modality, warnings=["legacy_output_empty"])

    @staticmethod
    def _read_legacy_output_map(entry: GeneratorEntry, output_jsonl: Path, *, cmd: list[str]) -> dict[str, GeneratedReport]:
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
                    warnings=list(row.get("warnings") or []),
                    metadata=_legacy_output_metadata(row, cmd),
                    evidence_tier=entry.evidence_tier,
                )
        return reports

    @staticmethod
    def _load_entries(rows: list[dict[str, Any]]) -> list[GeneratorEntry]:
        entries: list[GeneratorEntry] = []
        for row in rows:
            entries.append(
                GeneratorEntry(
                    key=str(row.get("key") or row.get("name") or ""),
                    title=str(row.get("title") or row.get("key") or ""),
                    source=str(row.get("source") or "local"),
                    supported_modalities=list(row.get("supported_modalities") or ["unknown"]),
                    supported_body_parts=list(row.get("supported_body_parts") or ["unknown"]),
                    ready=bool(row.get("ready", str(row.get("source") or "") == "artifact_reuse")),
                    category=str(row.get("category") or _default_category(str(row.get("source") or "local"))),
                    report_trained=bool(row.get("report_trained", _default_report_trained(str(row.get("source") or "")))),
                    report_training=str(row.get("report_training") or ""),
                    fresh_inference=bool(row.get("fresh_inference", str(row.get("source") or "") == "medharness_cli")),
                    notes=str(row.get("notes") or ""),
                    source_generation_jsonl=_resolved_path_text(row.get("source_generation_jsonl") or ""),
                    medharness_model_key=str(row.get("medharness_model_key") or row.get("model_key") or ""),
                    python_bin=str(row.get("python_bin") or "python"),
                    python_paths=[str(path) for path in row.get("python_paths") or []],
                    script_path=_resolved_path_text(row.get("script_path") or "/data/isbi/gzp/medHarness/scripts/run_report_generation.py"),
                    config_path=_resolved_path_text(row.get("config_path") or "/data/isbi/gzp/medHarness/configs/reportgen_models.yaml"),
                    output_jsonl=str(row.get("output_jsonl") or ""),
                    device=str(row.get("device") or "cuda:0"),
                    dtype=str(row.get("dtype") or "bf16"),
                    max_new_tokens=_strict_positive_int(row.get("max_new_tokens"), "max_new_tokens", 160),
                    generation_parameters=dict(
                        row.get("generation_parameters") or {}
                    ),
                    timeout_sec=_strict_positive_int(row.get("timeout_sec"), "timeout_sec", 1800),
                    evidence_tier=str(row.get("evidence_tier") or ""),
                    model_version=str(row.get("model_version") or ""),
                    model_sha256=str(row.get("model_sha256") or ""),
                    prompt_version=str(row.get("prompt_version") or ""),
                    preprocessing_version=str(row.get("preprocessing_version") or ""),
                    formal_validation_id=str(row.get("formal_validation_id") or ""),
                )
            )
        return [entry for entry in entries if entry.key]

    @staticmethod
    def _load_legacy_entries(config_path: str | Path) -> list[GeneratorEntry]:
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
        for key, row in models.items():
            if not isinstance(row, dict) or not _is_legacy_report_generator_ready(str(key), row):
                continue
            adapter = str(row.get("adapter") or "")
            source = "artifact_reuse" if adapter == "artifact_reuse" else "medharness_cli"
            modalities = _normalize_modalities(row.get("supported_modalities") or ["unknown"])
            body_parts = [str(item).lower() for item in row.get("supported_body_parts") or ["unknown"]]
            entries.append(
                GeneratorEntry(
                    key=str(key),
                    title=str(row.get("title") or key),
                    source=source,
                    supported_modalities=modalities,
                    supported_body_parts=body_parts,
                    ready=True,
                    category=str(row.get("category") or ""),
                    report_trained=bool(row.get("report_trained", False)),
                    report_training=str(row.get("report_training") or ""),
                    fresh_inference=source != "artifact_reuse",
                    notes=str(row.get("notes") or ""),
                    source_generation_jsonl=_resolved_path_text(row.get("source_generation_jsonl") or ""),
                    medharness_model_key=str(key),
                    python_bin=str(row.get("python_bin") or "python"),
                    python_paths=[str(item) for item in row.get("python_paths") or []],
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
                )
            )
        return entries


def _resolved_path_text(path: Any) -> str:
    if not path:
        return ""
    return str(resolve_existing_path(str(path)))


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
    return subprocess.run(cmd, **kwargs)


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
    return metadata


def _legacy_input_row(
    *,
    case_id: str,
    image_path: str,
    modality: str,
    body_part: str | None,
    reference_report: str | None,
    prompt: str | None = None,
) -> dict[str, Any]:
    asset_path = str(Path(image_path).expanduser().resolve())
    return {
        "case_id": case_id,
        "modality": "xray" if modality == "cxr" else modality,
        "body_part": body_part or _default_body_part(modality),
        "image_paths": [] if _looks_like_volume(asset_path) else [asset_path],
        "volume_path": asset_path if _looks_like_volume(asset_path) else None,
        "reference_report": reference_report or "",
        "prompt": prompt or _legacy_prompt(modality, body_part),
    }


def _legacy_prompt(
    modality: str,
    body_part: str | None,
    *,
    selected_series_type: str | None = None,
    selected_series_description: str | None = None,
) -> str:
    body = (body_part or _default_body_part(modality)).lower()
    if modality == "mri" and body == "brain":
        selected = (selected_series_type or "").lower()
        description = (selected_series_description or "").lower()
        if selected == "t2" or ("t2" in description and "flair" not in description):
            return "Generate a radiology report for this brain MRI T2 scan."
        if selected == "flair" or "flair" in description:
            return "Generate a radiology report for this brain MRI FLAIR scan."
        if selected or description:
            return "Generate a radiology report for this brain MRI study."
        return "Generate a radiology report for this brain MRI FLAIR scan."
    if modality == "ct" and body in {"abdomen", "pelvis", "multi-organ"}:
        return "Generate a radiology report for this abdominal CT study."
    if modality in {"cxr", "xray", "x-ray"} and body in {"chest", "lung"}:
        return "Analyze the chest X-ray images and write a radiology report."
    return "Generate a radiology report for this study."


def _looks_like_volume(path: str) -> bool:
    return str(path).endswith((".nii", ".nii.gz", ".npy", ".npz"))


def _default_body_part(modality: str) -> str:
    if modality == "mri":
        return "brain"
    if modality == "ct":
        return "abdomen"
    return "chest"


def _is_legacy_report_generator_ready(key: str, row: dict[str, Any]) -> bool:
    if key in _LEGACY_FORMAL_ROUTE_EXCLUDE:
        return False
    if not bool(row.get("report_trained", False)):
        return False
    category = str(row.get("category") or "")
    if category not in {"ready_or_artifact", "report_trained_target"}:
        return False
    adapter = str(row.get("adapter") or "")
    if adapter == "artifact_reuse":
        return bool(row.get("source_generation_jsonl"))
    return adapter not in {"source_audit_only", "blocked_no_public_weights", "gated_waitlist", ""}


def _normalize_modalities(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        key = str(value).lower()
        result.append(key)
        if key in {"xray", "x-ray", "xr", "cr", "dx"}:
            result.append("cxr")
    return list(dict.fromkeys(result))


def _normalize_route_modality(value: Any) -> str:
    key = str(value or "").strip().lower().replace("-", "")
    if key in {"xray", "xr", "cr", "dx"}:
        return "cxr"
    if key in {"mr", "mri"}:
        return "mri"
    if key == "ct":
        return "ct"
    return key


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
