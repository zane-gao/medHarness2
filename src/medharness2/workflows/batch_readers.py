from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
import json
import math
from pathlib import Path
from threading import Semaphore
import time
from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.data.sample_data import load_manifest
from medharness2.generators.assets import select_input_asset
from medharness2.generators.registry import GeneratorEntry, ReportGeneratorRegistry, _legacy_prompt
from medharness2.llm_client import LLMClient
from medharness2.modality import normalize_modality
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
    generation_mode: str = "benchmark",
    top_n: int | None = None,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    if limit is not None and (
        not isinstance(limit, int) or isinstance(limit, bool) or limit < 0
    ):
        raise ValueError("limit must be a non-negative integer")
    if generation_mode not in {"benchmark", "replay", "production"}:
        raise ValueError("generation_mode must be one of: benchmark, replay, production.")
    if top_n is not None and (
        not isinstance(top_n, int) or isinstance(top_n, bool) or top_n < 1
    ):
        raise ValueError("top_n must be a positive integer")
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
    precomputed_reports = precompute_medharness_cli_reports(
        rows,
        config=cfg,
        model_keys=model_keys,
        model_sources=model_sources,
        generation_mode=generation_mode,
    )
    for row in rows:
        try:
            report_text: str | None = None
            report_path: Path | None = None
            if generation_mode != "production":
                report_text, report_path = _resolve_report_text(
                    row.report_text,
                )
                if report_path is not None and not report_path.exists():
                    raise FileNotFoundError(f"report text file not found: {row.report_text or '<empty>'}")
            image_path = _case_display_image(row)
            if not image_path:
                raise ValueError("case has no image, contact sheet, or volume asset")
            case_output = case_dir / f"{row.case_id}.json"
            workflow1 = run_single_case(
                report_path=report_path,
                report_text=report_text,
                image_path=image_path,
                output_path=case_output,
                case_id=row.case_id,
                prepared_assets=_case_prepared_assets(row),
                modality=row.modality,
                body_part=row.body_part,
                model_keys=model_keys,
                model_sources=model_sources,
                precomputed_generated_reports=precomputed_reports.get(row.case_id),
                top_n=top_n if top_n is not None else cfg.ranking.top_n,
                config=cfg,
                llm_client=client,
                generation_mode=generation_mode,
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
        candidate_reports = _strict_object_list(
            workflow1.get("candidate_reports"),
            "candidate_reports",
        )
        candidate_failures = _strict_object_list(
            workflow1.get("candidate_failures"),
            "candidate_failures",
        )
        top_k_reports = _strict_object_list(
            workflow1.get("top_k_reports"),
            "top_k_reports",
        )
        fusion_report = _strict_object(workflow1.get("fusion_report"), "fusion_report")
        if not candidate_reports:
            failed_cases.append(
                {
                    "case_id": row.case_id,
                    "reader": row.reader,
                    "error": "no_candidate_generated",
                    "warnings": row.warnings,
                    "candidate_failure_count": len(candidate_failures),
                    "workflow1_output": str(case_output),
                }
            )
            continue
        human_evaluation = workflow1.get("human_evaluation")
        if human_evaluation is not None and not isinstance(human_evaluation, dict):
            raise ValueError("human_evaluation must be an object or null")
        reference_available = human_evaluation is not None
        case_result = {
            "case_id": row.case_id,
            "reader": row.reader,
            "modality": row.modality,
            "body_part": row.body_part,
            "warnings": row.warnings,
            "generation_mode": (
                "production_reference_free" if generation_mode == "production" else generation_mode
            ),
            "candidate_report_count": len(candidate_reports),
            "candidate_failure_count": len(candidate_failures),
            "top_k_report_count": len(top_k_reports),
            "fusion_status": str(fusion_report.get("fusion_status") or ""),
            "reference_available": reference_available,
            "reference_evaluated": reference_available,
            "workflow1_output": str(case_output),
        }
        human_metrics: dict[str, Any] | None = None
        modelwise_metrics: dict[str, Any] = {}
        if human_evaluation is not None:
            human_metrics = _strict_object(
                human_evaluation.get("composite_inputs"),
                "human_evaluation.composite_inputs",
            )
            human_provenance = _evaluation_metadata(human_evaluation)
            if human_provenance:
                human_metrics["metadata"] = human_provenance
            generated_evaluations = _strict_object_list(
                workflow1.get("generated_evaluations"),
                "generated_evaluations",
            )
            generated_metrics = [
                {
                    "model": item.get("model"),
                    "metrics": _strict_object(
                        item.get("composite_inputs"),
                        "generated_evaluations.composite_inputs",
                    ),
                    "metadata": _evaluation_metadata(item),
                    "source": item.get("source"),
                    "evidence_tier": item.get("evidence_tier"),
                }
                for item in generated_evaluations
            ]
            modelwise_metrics = modelwise_weighted(generated_metrics) if generated_metrics else {}
            case_result["human_metrics"] = human_metrics
            case_result["modelwise_metrics"] = modelwise_metrics
        case_results.append(case_result)
        bucket = per_reader.setdefault(row.reader, _empty_reader_bucket())
        bucket["cases"].append(row.case_id)
        bucket["candidate_report_count"] += case_result["candidate_report_count"]
        bucket["candidate_failure_count"] += case_result["candidate_failure_count"]
        bucket["top_k_report_count"] += case_result["top_k_report_count"]
        if case_result["fusion_status"] == "succeeded":
            bucket["fusion_succeeded_case_count"] += 1
        if reference_available and human_metrics is not None:
            bucket["reference_available_case_count"] += 1
            bucket["reference_evaluated_case_count"] += 1
            bucket["human_metrics"].append(human_metrics)
            if modelwise_metrics:
                bucket["modelwise_metrics"].append(modelwise_metrics)
    for reader, bucket in per_reader.items():
        bucket["case_count"] = len(bucket["cases"])
        bucket["fusion_success_rate"] = round(
            bucket["fusion_succeeded_case_count"] / max(bucket["case_count"], 1),
            4,
        )
        bucket["human_statistics"] = (
            calculate_statistics(bucket["human_metrics"]) if bucket["human_metrics"] else {}
        )
        bucket["modelwise_statistics"] = (
            calculate_statistics(bucket["modelwise_metrics"])
            if bucket["modelwise_metrics"]
            else {}
        )
        bucket["overall_score"] = _mean_score(bucket["human_metrics"])
    errors = ["no_cases_discovered"] if not rows else []
    generation_summary = {
        "candidate_report_count": sum(case["candidate_report_count"] for case in case_results),
        "candidate_failure_count": sum(case["candidate_failure_count"] for case in case_results),
        "top_k_report_count": sum(case["top_k_report_count"] for case in case_results),
        "fusion_succeeded_case_count": sum(
            1 for case in case_results if case["fusion_status"] == "succeeded"
        ),
    }
    reference_available_case_count = sum(
        int(case["reference_available"]) for case in case_results
    )
    reference_evaluated_case_count = sum(
        int(case["reference_evaluated"]) for case in case_results
    )
    human_metric_rows = [
        case["human_metrics"]
        for case in case_results
        if isinstance(case.get("human_metrics"), dict)
    ]
    result = {
        "artifact_type": (
            "production_batch_report_generation"
            if generation_mode == "production"
            else f"{generation_mode}_batch_report_generation"
        ),
        "generation_mode": generation_mode,
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
            "reference_available_case_count": reference_available_case_count,
            "reference_evaluated_case_count": reference_evaluated_case_count,
        },
        "per_reader": per_reader,
        "generation_summary": generation_summary,
        "statistics": calculate_statistics(human_metric_rows) if human_metric_rows else {},
        "errors": errors,
    }
    if generation_mode == "production":
        result["production_summary"] = generation_summary
    write_json(out, result)
    return result


def precompute_medharness_cli_reports(
    rows: list[CaseManifest],
    *,
    config: AppConfig,
    model_keys: list[str] | None,
    model_sources: list[str] | None,
    generation_mode: str,
) -> dict[str, list[GeneratedReport]]:
    registry = ReportGeneratorRegistry(config)
    grouped: dict[str, tuple[GeneratorEntry, list[dict[str, Any]]]] = {}
    source_filter = set(model_sources or [])
    for row in rows:
        case_input = _case_generation_input(
            row,
            include_reference=(
                config.generator.reference_assisted_generation
                and generation_mode != "production"
            ),
            require_reference=False,
        )
        if not case_input:
            continue
        prepared_assets = {
            **row.derived_assets,
            **({"volume_path": row.volume_path} if row.volume_path else {}),
        }
        entries = registry.select(
            row.modality,
            requested=model_keys,
            body_part=row.body_part,
            sources=source_filter,
            image_path=str(case_input["image_path"]),
            prepared_assets=prepared_assets,
            case_id=row.case_id,
            generation_mode=generation_mode,
        )
        for entry in entries:
            if entry.source != "medharness_cli":
                continue
            selected_asset = select_input_asset(
                _case_display_image(row),
                prepared_assets,
                entry.input_capabilities,
            )
            if entry.input_capabilities and selected_asset is None:
                continue
            model_case_input = dict(case_input)
            if selected_asset is not None:
                model_case_input.update(
                    {
                        "image_path": selected_asset.path,
                        "input_asset_kind": selected_asset.kind,
                        "input_asset_capability": selected_asset.capability,
                        "input_asset_sha256": selected_asset.sha256,
                        "input_asset_size_bytes": selected_asset.size_bytes,
                    }
                )
            _, bucket = grouped.setdefault(entry.key, (entry, []))
            bucket.append(model_case_input)
    batch_groups = sorted(grouped.values(), key=lambda item: item[0].key)
    device_semaphores = {
        device: Semaphore(config.generator.local_max_workers)
        for device in {str(entry.device or "local") for entry, _ in batch_groups}
    }
    generated_by_model: dict[str, dict[str, GeneratedReport]] = {}
    worker_count = min(config.generator.candidate_max_workers, len(batch_groups))
    if worker_count:
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="report-batch-model") as executor:
            futures: dict[Future[dict[str, GeneratedReport]], tuple[GeneratorEntry, list[dict[str, Any]]]] = {
                executor.submit(
                    _generate_model_batch,
                    registry,
                    entry,
                    cases,
                    device_semaphores[str(entry.device or "local")],
                ): (entry, cases)
                for entry, cases in batch_groups
            }
            for future in as_completed(futures):
                entry, cases = futures[future]
                try:
                    generated_by_model[entry.key] = future.result()
                except Exception as exc:
                    generated_by_model[entry.key] = _batch_exception_reports(entry, cases, exc)

    reports_by_case: dict[str, list[GeneratedReport]] = {}
    for entry, cases in batch_groups:
        generated = generated_by_model.get(entry.key, {})
        for case in cases:
            case_id = str(case["case_id"])
            report = generated.get(case_id)
            if report is None:
                report = GeneratedReport(
                    model=entry.key,
                    source=entry.source,
                    report="",
                    modality=str(case.get("modality") or ""),
                    evidence_tier=entry.evidence_tier,
                    warnings=["legacy_batch_output_missing"],
                    metadata={"reference_report_used": False},
                )
            report.metadata = {
                **report.metadata,
                "generator_key": entry.key,
                "case_id": case_id,
                "fresh_inference": bool(report.report.strip()),
                **(
                    {
                        "input_asset": str(case["image_path"]),
                        "input_asset_kind": str(case["input_asset_kind"]),
                        "input_asset_capability": str(case["input_asset_capability"]),
                        "input_asset_sha256": str(case["input_asset_sha256"]),
                        "input_asset_size_bytes": int(case["input_asset_size_bytes"]),
                    }
                    if case.get("input_asset_kind")
                    else {}
                ),
                "reference_report_used": False
                if generation_mode == "production"
                else report.metadata.get("reference_report_used", False),
            }
            if case_id:
                reports_by_case.setdefault(case_id, []).append(report)
    return reports_by_case


def _generate_model_batch(
    registry: ReportGeneratorRegistry,
    entry: GeneratorEntry,
    cases: list[dict[str, Any]],
    semaphore: Semaphore,
) -> dict[str, GeneratedReport]:
    with semaphore:
        started = time.monotonic()
        reports = registry.generate_batch(entry, cases, include_failures=True)
        elapsed_sec = round(time.monotonic() - started, 4)
        execution = {
            "mode": "batch",
            "batch_size": len(cases),
            "batch_latency_sec": elapsed_sec,
        }
        for report in reports.values():
            report.metadata = {
                **report.metadata,
                "execution_attempted": True,
                "batch_execution": execution,
            }
        return reports


def _batch_exception_reports(
    entry: GeneratorEntry,
    cases: list[dict[str, Any]],
    exc: Exception,
) -> dict[str, GeneratedReport]:
    return {
        str(case["case_id"]): GeneratedReport(
            model=entry.key,
            source=entry.source,
            report="",
            modality=str(case.get("modality") or ""),
            evidence_tier=entry.evidence_tier,
            warnings=["legacy_batch_generation_exception", type(exc).__name__],
            metadata={
                "batch_error": str(exc),
                "execution_attempted": True,
                "batch_execution": {
                    "mode": "batch",
                    "batch_size": len(cases),
                    "batch_latency_sec": 0.0,
                },
                "reference_report_used": False,
            },
        )
        for case in cases
    }


def _case_generation_input(
    row: CaseManifest,
    *,
    include_reference: bool,
    require_reference: bool,
) -> dict[str, Any] | None:
    report_text = ""
    if include_reference or require_reference:
        resolved_report, report_path = _resolve_report_text(row.report_text)
        if resolved_report is None:
            if report_path is None or not report_path.exists():
                if not require_reference:
                    resolved_report = ""
                else:
                    return None
            else:
                resolved_report = report_path.read_text(encoding="utf-8")
        if resolved_report is None:
            return None
        report_text = resolved_report
    image_path = _case_local_generation_image(row)
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


def _case_prepared_assets(row: CaseManifest) -> dict[str, Any]:
    assets = dict(row.derived_assets)
    if row.volume_path:
        assets.setdefault("volume_path", row.volume_path)
    return assets


def _case_display_image(row: CaseManifest) -> str:
    assets = row.derived_assets
    return str(
        assets.get("contact_sheet")
        or assets.get("primary_image")
        or row.volume_path
        or assets.get("volume_path")
        or (row.image_paths[0] if row.image_paths else "")
        or ""
    )


def _case_local_generation_image(row: CaseManifest) -> str:
    assets = row.derived_assets
    feature_candidates = (
        assets.get("feature_path"),
        assets.get("wsi_feature_path"),
        assets.get("h5_feature_path"),
        assets.get("histgen_feature_path"),
    )
    feature_path = next((str(candidate) for candidate in feature_candidates if candidate), "")
    if feature_path:
        return feature_path
    if normalize_modality(row.modality) == "cxr":
        candidates = (
            assets.get("primary_image"),
            assets.get("contact_sheet"),
            row.image_paths[0] if row.image_paths else "",
            row.volume_path,
            assets.get("volume_path"),
        )
    else:
        candidates = (
            row.volume_path,
            assets.get("volume_path"),
            assets.get("contact_sheet"),
            assets.get("primary_image"),
            row.image_paths[0] if row.image_paths else "",
        )
    return next((str(candidate) for candidate in candidates if candidate), "")


def _case_generation_prompt(row: CaseManifest) -> str:
    return _legacy_prompt(
        row.modality,
        row.body_part,
        selected_series_type=str(row.derived_assets.get("selected_series_type") or ""),
        selected_series_description=str(row.derived_assets.get("selected_series_description") or ""),
    )


def _resolve_report_text(value: str) -> tuple[str | None, Path | None]:
    if not value:
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


def _strict_object(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return dict(value)


def _strict_object_list(value: Any, label: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be a list of objects")
    return [dict(item) for item in value]


def _empty_reader_bucket() -> dict[str, Any]:
    return {
        "cases": [],
        "candidate_report_count": 0,
        "candidate_failure_count": 0,
        "top_k_report_count": 0,
        "fusion_succeeded_case_count": 0,
        "reference_available_case_count": 0,
        "reference_evaluated_case_count": 0,
        "human_metrics": [],
        "modelwise_metrics": [],
    }
