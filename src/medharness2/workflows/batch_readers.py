from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.data.sample_data import load_manifest
from medharness2.generators.registry import GeneratorEntry, ReportGeneratorRegistry, _legacy_prompt
from medharness2.llm_client import LLMClient
from medharness2.schema import CaseManifest, GeneratedReport
from medharness2.tools.tool10_modelwise import modelwise_weighted
from medharness2.tools.tool12_statistics import calculate_statistics, eligible_for_statistics
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
    if limit is not None and (
        not isinstance(limit, int) or isinstance(limit, bool) or limit < 0
    ):
        raise ValueError("limit must be a non-negative integer")
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
    ocr_primary_route = cfg.model_roles.get("ocr_primary")
    allow_placeholder_report = ocr_primary_route is None and str(cfg.llm.provider).lower() == "mock"
    for row in rows:
        try:
            report_text, report_path = _resolve_report_text(
                row.report_text,
                allow_placeholder=allow_placeholder_report,
            )
            if report_text is None and (report_path is None or not report_path.exists()):
                raise FileNotFoundError(f"report text file not found: {row.report_text or '<empty>'}")
            image_path = row.derived_assets.get("primary_image") or row.volume_path or (row.image_paths[0] if row.image_paths else "")
            case_output = case_dir / f"{row.case_id}.json"
            workflow1 = run_single_case(
                report_path=report_path,
                report_text=report_text,
                image_path=image_path,
                output_path=case_output,
                case_id=row.case_id,
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
        human_evaluation = workflow1.get("human_evaluation") or {}
        human_metrics = dict(human_evaluation.get("composite_inputs") or {})
        human_provenance = _evaluation_metadata(human_evaluation)
        if human_provenance:
            human_metrics["metadata"] = human_provenance
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
    errors = ["no_cases_discovered"] if not rows else []
    result = {
        "manifest_path": str(manifest_path),
        "case_count": len(case_results),
        "failed_case_count": len(failed_cases),
        "cases": case_results,
        "failed_cases": failed_cases,
        "denominator": {
            "manifest_case_count": len(rows),
            "successful_case_count": len(case_results),
            "failed_case_count": len(failed_cases),
            "success_rate": round(len(case_results) / max(len(rows), 1), 4),
        },
        "per_reader": per_reader,
        "statistics": calculate_statistics([case["human_metrics"] for case in case_results]),
        "errors": errors,
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
    if report_text is None:
        if report_path is None or not report_path.exists():
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


def _resolve_report_text(value: str, *, allow_placeholder: bool = False) -> tuple[str | None, Path | None]:
    if not value:
        if allow_placeholder:
            return "FINDINGS: Report text unavailable.\nIMPRESSION: Report text unavailable.", None
        return None, None
    path = Path(value)
    if path.exists():
        return None, path
    if path.is_absolute() or path.suffix.lower() in {".txt", ".md", ".json", ".pdf"}:
        return None, path
    return value, None


def _mean_score(rows: list[dict[str, Any]]) -> float | None:
    values: list[float] = []
    for row in rows:
        if not eligible_for_statistics(row):
            continue
        for field in ("likert_mean", "structure_score", "finding_coverage"):
            if field not in row:
                continue
            try:
                value = float(row[field])
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            values.append((value - 1.0) / 4.0 if field == "likert_mean" and value >= 1.0 else value)
    return round(sum(values) / len(values), 6) if values else None


def _fallback_flag(value: Any) -> bool:
    """Treat only an explicit boolean False as non-fallback provenance."""
    return value is not None and value is not False


def _evaluation_metadata(evaluation: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    fallback_seen = False
    for key in ("likert", "finding_graph"):
        value = evaluation.get(key)
        if isinstance(value, dict):
            nested = value.get("_metadata") or value.get("metadata") or value.get("provenance")
            if isinstance(nested, dict):
                metadata.update(nested)
                fallback_seen = fallback_seen or _fallback_flag(nested.get("fallback_used"))
            if key == "finding_graph":
                correction = (value.get("metadata") or {}).get("llm_correction")
                if isinstance(correction, dict):
                    metadata.update(correction)
                    fallback_seen = fallback_seen or _fallback_flag(correction.get("fallback_used"))
    if isinstance(evaluation.get("metadata"), dict):
        metadata.update(evaluation["metadata"])
        fallback_seen = fallback_seen or _fallback_flag(evaluation["metadata"].get("fallback_used"))
    if fallback_seen:
        metadata["fallback_used"] = True
    return metadata
