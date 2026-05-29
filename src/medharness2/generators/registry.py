from __future__ import annotations

from dataclasses import dataclass
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
                )
            )
        return [entry for entry in entries if entry.key]
