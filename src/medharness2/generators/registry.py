from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from medharness2.config import AppConfig
from medharness2.schema import GeneratedReport


@dataclass
class GeneratorEntry:
    key: str
    title: str
    source: str
    supported_modalities: list[str]
    ready: bool = False
    notes: str = ""
    source_generation_jsonl: str = ""
    medharness_model_key: str = ""
    script_path: str = "/data/isbi/gzp/medHarness/scripts/run_report_generation.py"
    config_path: str = "/data/isbi/gzp/medHarness/configs/reportgen_models.yaml"
    output_jsonl: str = ""
    device: str = "cuda:0"
    dtype: str = "bf16"
    max_new_tokens: int = 160
    timeout_sec: int = 1800


class ReportGeneratorRegistry:
    def __init__(self, config: AppConfig):
        self.config = config
        self.entries = {entry.key: entry for entry in self._load_entries(config.generator.local_models)}

    def select(self, modality: str, requested: list[str] | None = None) -> list[GeneratorEntry]:
        keys = requested or self.config.generator.default_models
        selected: list[GeneratorEntry] = []
        for key in keys:
            entry = self.entries.get(key)
            if not entry:
                continue
            supported = {m.lower() for m in entry.supported_modalities}
            if "unknown" in supported or modality.lower() in supported:
                selected.append(entry)
        return selected

    def generate(self, entry: GeneratorEntry, image_path: str, modality: str, reference_report: str | None = None) -> GeneratedReport:
        if entry.source == "artifact_reuse":
            return self._generate_artifact(entry, image_path=image_path, modality=modality)
        if entry.source == "medharness_cli":
            return self._generate_medharness_cli(entry, image_path=image_path, modality=modality, reference_report=reference_report)
        return self.generate_stub(entry, image_path=image_path, modality=modality, reference_report=reference_report)

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

    def _generate_artifact(self, entry: GeneratorEntry, *, image_path: str, modality: str) -> GeneratedReport:
        source = Path(entry.source_generation_jsonl)
        if not source.exists():
            return GeneratedReport(
                model=entry.key,
                source=entry.source,
                report="",
                modality=modality,
                warnings=["artifact_missing", str(source)],
            )
        with source.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
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
    ) -> GeneratedReport:
        script = Path(entry.script_path)
        if not script.exists():
            return GeneratedReport(model=entry.key, source=entry.source, report="", modality=modality, warnings=["legacy_script_missing", str(script)])
        with tempfile.TemporaryDirectory(prefix="medharness2_legacy_") as tmpdir:
            tmp = Path(tmpdir)
            input_jsonl = tmp / "input.jsonl"
            output_jsonl = Path(entry.output_jsonl) if entry.output_jsonl else tmp / "generation.jsonl"
            row = {
                "case_id": "medharness2_single_case",
                "modality": "xray" if modality == "cxr" else modality,
                "body_part": "chest",
                "image_paths": [image_path],
                "reference_report": reference_report or "",
                "prompt": "Generate a radiology report for this study.",
            }
            input_jsonl.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            cmd = [
                "python",
                str(script),
                "--config",
                entry.config_path,
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
                subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=entry.timeout_sec)
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
                    metadata={"cmd": _redacted_cmd(cmd), "adapter_status": row.get("adapter_status")},
                )
        return GeneratedReport(model=entry.key, source=entry.source, report="", modality=modality, warnings=["legacy_output_empty"])

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
                    ready=bool(row.get("ready", False)),
                    notes=str(row.get("notes") or ""),
                    source_generation_jsonl=str(row.get("source_generation_jsonl") or ""),
                    medharness_model_key=str(row.get("medharness_model_key") or row.get("model_key") or ""),
                    script_path=str(row.get("script_path") or "/data/isbi/gzp/medHarness/scripts/run_report_generation.py"),
                    config_path=str(row.get("config_path") or "/data/isbi/gzp/medHarness/configs/reportgen_models.yaml"),
                    output_jsonl=str(row.get("output_jsonl") or ""),
                    device=str(row.get("device") or "cuda:0"),
                    dtype=str(row.get("dtype") or "bf16"),
                    max_new_tokens=int(row.get("max_new_tokens") or 160),
                    timeout_sec=int(row.get("timeout_sec") or 1800),
                )
            )
        return [entry for entry in entries if entry.key]


def _redacted_cmd(cmd: list[str]) -> list[str]:
    return [part if "token" not in part.lower() and "key" not in part.lower() else "<redacted>" for part in cmd]
