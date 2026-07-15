from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.data.sample_data import load_manifest
from medharness2.generators.registry import GeneratorEntry, ReportGeneratorRegistry, _legacy_prompt
from medharness2.llm_client import LLMClient
from medharness2.schema import CaseManifest, GeneratedReport
from medharness2.tools.tool10_modelwise import modelwise_weighted
from medharness2.tools.tool12_statistics import calculate_statistics
from medharness2.utils.io import write_json
from medharness2.workflows.single_case import run_single_case


def run_batch_readers(
    manifest_path: str | Path,
    output_path: str | Path,
    *,
    model_keys: list[str] | None = None,
    model_sources: list[str] | None = None,
    limit: int | None = None,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    rows = load_manifest(manifest_path)
    if limit is not None:
        rows = rows[:limit]
    out = Path(output_path)
    case_dir = out.parent / "workflow2_cases"
    case_dir.mkdir(parents=True, exist_ok=True)
    case_results: list[dict[str, Any]] = []
    failed_cases: list[dict[str, Any]] = []
    per_reader: dict[str, dict[str, Any]] = {}
    precomputed_reports = _precompute_medharness_cli_reports(
        rows,
        config=cfg,
        model_keys=model_keys,
        model_sources=model_sources,
    )
    for row in rows:
        try:
            report_text, report_path = _resolve_report_text(row.report_text)
            image_path = row.derived_assets.get("primary_image") or row.volume_path or (row.image_paths[0] if row.image_paths else "")
            case_output = case_dir / f"{row.case_id}.json"
            workflow1 = run_single_case(
                report_path=report_path,
                report_text=report_text,
                image_path=image_path,
                output_path=case_output,
                prepared_assets={**row.derived_assets, "volume_path": row.volume_path} if row.derived_assets or row.volume_path else {},
                modality=row.modality,
                body_part=row.body_part,
                model_keys=model_keys,
                model_sources=model_sources,
                precomputed_generated_reports=precomputed_reports.get(row.case_id),
                top_n=cfg.ranking.top_n,
                config=cfg,
                llm_client=client,
            )
        except Exception as exc:
            failed_cases.append(
                {
                    "case_id": row.case_id,
                    "reader": row.reader,
                    "error": f"{type(exc).__name__}: {exc}",
                    "warnings": row.warnings,
                }
            )
            continue
        human_metrics = dict(workflow1.get("human_evaluation", {}).get("composite_inputs") or {})
        generated_metrics = [
            {
                "model": item.get("model"),
                "metrics": item.get("composite_inputs") or {},
                "metadata": _evaluation_metadata(item),
                "source": item.get("source"),
                "evidence_tier": item.get("evidence_tier"),
            }
            for item in workflow1.get("generated_evaluations") or []
        ]
        case_result = {
            "case_id": row.case_id,
            "reader": row.reader,
            "modality": row.modality,
            "body_part": row.body_part,
            "warnings": row.warnings,
            "human_metrics": human_metrics,
            "modelwise_metrics": modelwise_weighted(generated_metrics) if generated_metrics else {},
            "workflow1_output": str(case_output),
        }
        case_results.append(case_result)
        bucket = per_reader.setdefault(row.reader, {"cases": [], "human_metrics": [], "modelwise_metrics": []})
        bucket["cases"].append(row.case_id)
        bucket["human_metrics"].append(human_metrics)
        if case_result["modelwise_metrics"]:
            bucket["modelwise_metrics"].append(case_result["modelwise_metrics"])
    for reader, bucket in per_reader.items():
        bucket["case_count"] = len(bucket["cases"])
        bucket["human_statistics"] = calculate_statistics(bucket["human_metrics"])
        bucket["modelwise_statistics"] = calculate_statistics(bucket["modelwise_metrics"])
        bucket["overall_score"] = _mean_score(bucket["human_metrics"])
    result = {
        "manifest_path": str(manifest_path),
        "case_count": len(case_results),
        "failed_case_count": len(failed_cases),
        "cases": case_results,
        "failed_cases": failed_cases,
        "per_reader": per_reader,
        "statistics": calculate_statistics([case["human_metrics"] for case in case_results]),
    }
    write_json(out, result)
    return result


def _precompute_medharness_cli_reports(
    rows: list[CaseManifest],
    *,
    config: AppConfig,
    model_keys: list[str] | None,
    model_sources: list[str] | None,
) -> dict[str, list[GeneratedReport]]:
    registry = ReportGeneratorRegistry(config)
    grouped: dict[str, tuple[GeneratorEntry, list[dict[str, Any]]]] = {}
    source_filter = set(model_sources or [])
    for row in rows:
        case_input = _case_generation_input(row, include_reference=config.generator.reference_assisted_generation)
        if not case_input:
            continue
        entries = registry.select(row.modality, requested=model_keys, body_part=row.body_part, sources=source_filter)
        if not entries or any(entry.source != "medharness_cli" for entry in entries):
            continue
        for entry in entries:
            _, bucket = grouped.setdefault(entry.key, (entry, []))
            bucket.append(case_input)
    reports_by_case: dict[str, list[GeneratedReport]] = {}
    for entry, cases in grouped.values():
        generated = registry.generate_batch(entry, cases)
        for case_id, report in generated.items():
            if report.report:
                reports_by_case.setdefault(case_id, []).append(report)
    return reports_by_case


def _case_generation_input(row: CaseManifest, *, include_reference: bool) -> dict[str, Any] | None:
    report_text, report_path = _resolve_report_text(row.report_text)
    if report_text is None and report_path is not None:
        if not report_path.exists():
            return None
        report_text = report_path.read_text(encoding="utf-8")
    image_path = (
        row.derived_assets.get("volume_path")
        or row.volume_path
        or row.derived_assets.get("primary_image")
        or (row.image_paths[0] if row.image_paths else "")
    )
    if not image_path:
        return None
    return {
        "case_id": row.case_id,
        "image_path": image_path,
        "modality": row.modality,
        "body_part": row.body_part,
        "reference_report": (report_text or "") if include_reference else "",
        "prompt": _case_generation_prompt(row),
    }


def _case_generation_prompt(row: CaseManifest) -> str:
    return _legacy_prompt(
        row.modality,
        row.body_part,
        selected_series_type=str(row.derived_assets.get("selected_series_type") or ""),
        selected_series_description=str(row.derived_assets.get("selected_series_description") or ""),
    )


def _resolve_report_text(value: str) -> tuple[str | None, Path | None]:
    if not value:
        return "FINDINGS: Report text unavailable.\nIMPRESSION: Report text unavailable.", None
    path = Path(value)
    if path.exists():
        return None, path
    if path.is_absolute() or path.suffix.lower() in {".txt", ".md", ".json", ".pdf"}:
        return None, path
    return value, None


def _mean_score(rows: list[dict[str, Any]]) -> float:
    values: list[float] = []
    for row in rows:
        if "likert_mean" in row:
            values.append(float(row["likert_mean"]) / 5.0 if float(row["likert_mean"]) > 1 else float(row["likert_mean"]))
        if "structure_score" in row:
            values.append(float(row["structure_score"]))
        if "finding_coverage" in row:
            values.append(float(row["finding_coverage"]))
    return round(sum(values) / len(values), 6) if values else 0.0


def _evaluation_metadata(evaluation: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("likert", "finding_graph"):
        value = evaluation.get(key)
        if isinstance(value, dict):
            nested = value.get("_metadata") or value.get("metadata") or value.get("provenance")
            if isinstance(nested, dict):
                metadata.update(nested)
    if isinstance(evaluation.get("metadata"), dict):
        metadata.update(evaluation["metadata"])
    return metadata
