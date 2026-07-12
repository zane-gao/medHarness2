from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, load_config, resolve_existing_path
from medharness2.data.sample_data import load_manifest
from medharness2.generators.registry import GeneratorEntry, ReportGeneratorRegistry
from medharness2.privacy import ExternalPayloadPolicy
from medharness2.schema import GeneratedReport, require_formal_fresh_reports
from medharness2.tools.quality_gate import apply_generation_quality_gate
from medharness2.utils.io import write_json


def plan_generation_benchmark(
    manifest_path: str | Path,
    *,
    config: AppConfig | None = None,
    model_keys: list[str] | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    rows = load_manifest(manifest_path)
    registry = ReportGeneratorRegistry(cfg)
    cases: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    blocking_violations: list[dict[str, Any]] = []
    eligible_model_stats: dict[str, dict[str, Any]] = {}
    rejected_model_stats: dict[str, dict[str, Any]] = {}
    stratum_coverage: dict[str, dict[str, int]] = {}
    formal_ready_case_count = 0
    for case in rows:
        entries = registry.select(
            case.modality,
            requested=model_keys or ["*"],
            body_part=case.body_part,
        )
        case_blocking_violations: list[dict[str, Any]] = []
        case_model_violations: list[dict[str, Any]] = []
        eligible_models: list[dict[str, Any]] = []
        rejected_models: list[dict[str, Any]] = []
        input_asset = _case_input_asset(case, cfg)
        if not input_asset["path"]:
            case_blocking_violations.append(
                {
                    "case_id": case.case_id,
                    "model": "",
                    "evidence_tier": "none",
                    "reason": "missing_input_asset",
                    "asset_kind": input_asset["kind"],
                }
            )
        elif not input_asset["exists"]:
            case_blocking_violations.append(
                {
                    "case_id": case.case_id,
                    "model": "",
                    "evidence_tier": "none",
                    "reason": "input_asset_not_found",
                    "asset_kind": input_asset["kind"],
                    "path": input_asset["path"],
                }
            )
        if not entries:
            case_blocking_violations.append(
                {
                    "case_id": case.case_id,
                    "model": "",
                    "evidence_tier": "none",
                    "reason": "no_compatible_model",
                }
            )
        for rejected in _requested_model_rejections(
            registry,
            entries,
            model_keys,
        ):
            rejected_models.append(rejected)
            stats = rejected_model_stats.setdefault(
                str(rejected["model"]),
                {
                    **{
                        key: value
                        for key, value in rejected.items()
                        if key != "reasons"
                    },
                    "case_ids": set(),
                    "reasons": set(),
                },
            )
            stats["case_ids"].add(case.case_id)
            stats["reasons"].update(rejected["reasons"])
            for reason in rejected["reasons"]:
                case_model_violations.append(
                    {
                        "case_id": case.case_id,
                        "model": rejected["model"],
                        "evidence_tier": rejected["evidence_tier"],
                        "reason": reason,
                    }
                )
        for entry in entries:
            model = _model_plan_row(entry)
            reasons = entry.formal_readiness_violations()
            if not reasons:
                eligible_models.append(model)
                stats = eligible_model_stats.setdefault(
                    entry.key,
                    {**model, "case_ids": set()},
                )
                stats["case_ids"].add(case.case_id)
                continue
            rejected_models.append({**model, "reasons": reasons})
            stats = rejected_model_stats.setdefault(
                entry.key,
                {**model, "case_ids": set(), "reasons": set()},
            )
            stats["case_ids"].add(case.case_id)
            stats["reasons"].update(reasons)
            for reason in reasons:
                case_model_violations.append(
                    {
                        "case_id": case.case_id,
                        "model": entry.key,
                        "evidence_tier": entry.evidence_tier,
                        "reason": reason,
                    }
                )
        if entries and not eligible_models:
            case_blocking_violations.append(
                {
                    "case_id": case.case_id,
                    "model": "",
                    "evidence_tier": "none",
                    "reason": "no_formal_candidate",
                }
            )
        formal_ready = bool(eligible_models) and not case_blocking_violations
        if formal_ready:
            formal_ready_case_count += 1
        violations.extend(case_model_violations)
        violations.extend(case_blocking_violations)
        blocking_violations.extend(case_blocking_violations)
        stratum = f"{case.modality}/{case.body_part}"
        stratum_stats = stratum_coverage.setdefault(
            stratum,
            {"case_count": 0, "covered_case_count": 0},
        )
        stratum_stats["case_count"] += 1
        stratum_stats["covered_case_count"] += int(formal_ready)
        cases.append(
            {
                "case_id": case.case_id,
                "modality": case.modality,
                "body_part": case.body_part,
                "input_asset": input_asset,
                "models": [_model_plan_row(entry) for entry in entries],
                "eligible_models": eligible_models,
                "rejected_models": rejected_models,
                "selected_formal_candidates": eligible_models,
                "blocking_violations": case_blocking_violations,
                "formal_ready": formal_ready,
            }
        )
    eligible_model_rows = [
        {
            **{key: value for key, value in stats.items() if key != "case_ids"},
            "compatible_case_count": len(stats["case_ids"]),
        }
        for _, stats in sorted(eligible_model_stats.items())
    ]
    rejected_model_rows = [
        {
            **{
                key: value
                for key, value in stats.items()
                if key not in {"case_ids", "reasons"}
            },
            "compatible_case_count": len(stats["case_ids"]),
            "reasons": sorted(stats["reasons"]),
        }
        for _, stats in sorted(rejected_model_stats.items())
    ]
    coverage_by_stratum = {
        stratum: {
            **stats,
            "coverage_rate": round(
                stats["covered_case_count"] / stats["case_count"],
                6,
            ),
        }
        for stratum, stats in sorted(stratum_coverage.items())
    }
    case_count = len(rows)
    case_coverage = {
        "covered_case_count": formal_ready_case_count,
        "uncovered_case_count": case_count - formal_ready_case_count,
        "coverage_rate": round(formal_ready_case_count / case_count, 6)
        if case_count
        else 0.0,
        "by_stratum": coverage_by_stratum,
    }
    return {
        "schema_version": "2.0",
        "artifact_type": "generation_benchmark_plan",
        "status": "ready" if rows and formal_ready_case_count == case_count else "not_ready",
        "case_count": case_count,
        "formal_ready_case_count": formal_ready_case_count,
        "eligible_models": eligible_model_rows,
        "rejected_models": rejected_model_rows,
        "selected_formal_candidates": eligible_model_rows,
        "case_coverage": case_coverage,
        "blocking_violations": blocking_violations,
        "violations": violations,
        "cases": cases,
    }


def run_generation_benchmark(
    manifest_path: str | Path,
    output_dir: str | Path,
    *,
    config: AppConfig | None = None,
    model_keys: list[str] | None = None,
    formal: bool = True,
) -> dict[str, Any]:
    cfg = config or load_config()
    manifest = Path(manifest_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    plan = plan_generation_benchmark(manifest, config=cfg, model_keys=model_keys)
    if formal and plan["status"] != "ready":
        raise ValueError(
            "Generation benchmark is not formal-ready: "
            f"{plan['blocking_violations']}"
        )
    rows = load_manifest(manifest)
    registry = ReportGeneratorRegistry(cfg)
    privacy = ExternalPayloadPolicy(cfg.privacy)
    indexed_results: list[tuple[int, int, dict[str, Any]]] = []
    plan_cases = {str(case["case_id"]): case for case in plan["cases"]}
    model_jobs: dict[str, dict[str, Any]] = {}
    for case_index, case in enumerate(rows):
        case_plan = plan_cases[case.case_id]
        selected_model_keys = (
            [
                str(model["model"])
                for model in case_plan["selected_formal_candidates"]
            ]
            if formal
            else model_keys or ["*"]
        )
        entries = registry.select(
            case.modality,
            requested=selected_model_keys,
            body_part=case.body_part,
        )
        input_asset = case_plan["input_asset"]
        if not input_asset["exists"] or not Path(str(input_asset["path"])).is_file():
            raise ValueError(
                f"Benchmark input asset unavailable for case {case.case_id}: "
                f"{input_asset}"
            )
        for model_index, entry in enumerate(entries):
            bucket = model_jobs.setdefault(
                entry.key,
                {"entry": entry, "jobs": []},
            )
            bucket["jobs"].append(
                {
                    "case_index": case_index,
                    "model_index": model_index,
                    "case": case,
                    "input_asset": input_asset,
                }
            )

    for bucket in model_jobs.values():
        entry = bucket["entry"]
        jobs = bucket["jobs"]
        if entry.source == "medharness_cli":
            started = time.monotonic()
            generated_by_case = registry.generate_batch(
                entry,
                [
                    {
                        "case_id": job["case"].case_id,
                        "image_path": job["input_asset"]["path"],
                        "modality": job["case"].modality,
                        "body_part": job["case"].body_part,
                        "reference_report": "",
                    }
                    for job in jobs
                ],
                include_failures=True,
            )
            batch_latency_sec = round(time.monotonic() - started, 4)
            for job in jobs:
                case = job["case"]
                generated = generated_by_case.get(case.case_id)
                if generated is None:
                    generated = _missing_batch_report(entry, case.modality)
                latency_sec = _adapter_latency(generated, batch_latency_sec)
                result = _benchmark_result(
                    case=case,
                    entry=entry,
                    generated=generated,
                    input_asset=job["input_asset"],
                    latency_sec=latency_sec,
                    execution={
                        "mode": "batch",
                        "batch_size": len(jobs),
                        "batch_latency_sec": batch_latency_sec,
                    },
                    formal=formal,
                    privacy=privacy,
                )
                indexed_results.append(
                    (job["case_index"], job["model_index"], result)
                )
            continue

        for job in jobs:
            case = job["case"]
            started = time.monotonic()
            generated = registry.generate(
                entry,
                str(job["input_asset"]["path"]),
                case.modality,
                reference_report=None,
                body_part=case.body_part,
            )
            latency_sec = round(time.monotonic() - started, 4)
            result = _benchmark_result(
                case=case,
                entry=entry,
                generated=generated,
                input_asset=job["input_asset"],
                latency_sec=latency_sec,
                execution={
                    "mode": "single",
                    "batch_size": 1,
                    "batch_latency_sec": latency_sec,
                },
                formal=formal,
                privacy=privacy,
            )
            indexed_results.append(
                (job["case_index"], job["model_index"], result)
            )

    results = [
        result
        for _, _, result in sorted(
            indexed_results,
            key=lambda item: (item[0], item[1]),
        )
    ]
    failures = sum(row["status"] == "failed" for row in results)
    results_path = output / "benchmark_results.jsonl"
    results_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in results),
        encoding="utf-8",
    )
    tier_counts = Counter(str(row["generated_report"]["evidence_tier"]) for row in results)
    model_counts = Counter(str(row["model"]) for row in results)
    execution_mode_counts = Counter(str(row["execution"]["mode"]) for row in results)
    report_texts = [str(row["generated_report"].get("report") or "").strip() for row in results]
    warning_counts = Counter(
        str(warning)
        for row in results
        for warning in row["generated_report"].get("warnings") or []
    )
    batch_latencies_by_model = {
        str(row["model"]): float(row["execution"]["batch_latency_sec"])
        for row in results
        if row["execution"].get("mode") == "batch"
        and isinstance(row["execution"].get("batch_latency_sec"), (int, float))
    }
    summary = {
        "schema_version": "2.0",
        "artifact_type": "generation_benchmark_summary",
        "status": "succeeded" if results and failures == 0 else "completed_with_failures" if results else "failed",
        "mode": "formal" if formal else "exploratory",
        "case_count": len(rows),
        "result_count": len(results),
        "failure_count": failures,
        "model_counts": dict(sorted(model_counts.items())),
        "evidence_tier_counts": dict(sorted(tier_counts.items())),
        "execution_mode_counts": dict(sorted(execution_mode_counts.items())),
        "reference_report_used_count": sum(bool(row.get("reference_report_used")) for row in results),
        "empty_report_count": sum(not report for report in report_texts),
        "unique_report_count": len({report for report in report_texts if report}),
        "unique_report_rate": round(
            len({report for report in report_texts if report}) / len(report_texts),
            6,
        )
        if report_texts
        else 0.0,
        "latency_sec": _numeric_summary(
            [float(row["latency_sec"]) for row in results]
        ),
        "batch_latency_sec": _numeric_summary(
            list(batch_latencies_by_model.values())
        ),
        "warning_counts": dict(sorted(warning_counts.items())),
        "results_path": str(results_path),
    }
    summary_path = output / "benchmark_summary.json"
    write_json(summary_path, summary)
    benchmark_manifest = {
        "schema_version": "2.0",
        "artifact_type": "generation_benchmark_manifest",
        "mode": summary["mode"],
        "source_policy": "formal_fresh_only" if formal else "mixed_exploratory",
        "input_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "config_sha256": hashlib.sha256(_stable_json(asdict(cfg)).encode("utf-8")).hexdigest(),
        "plan": plan,
        "artifacts": {
            "results": str(results_path),
            "summary": str(summary_path),
        },
        "artifact_sha256": {
            "results": _file_sha256(results_path),
            "summary": _file_sha256(summary_path),
        },
    }
    write_json(output / "benchmark_manifest.json", benchmark_manifest)
    return summary


def _benchmark_result(
    *,
    case: Any,
    entry: GeneratorEntry,
    generated: GeneratedReport,
    input_asset: dict[str, Any],
    latency_sec: float,
    execution: dict[str, Any],
    formal: bool,
    privacy: ExternalPayloadPolicy,
) -> dict[str, Any]:
    generated = apply_generation_quality_gate(
        generated,
        modality=case.modality,
        body_part=case.body_part,
    )
    if formal:
        require_formal_fresh_reports([generated])
    scan = privacy.scan(generated.report)
    if not scan.allowed:
        generated.report = privacy.deidentify_clinical_text(generated.report)
        generated.warnings.append("generated_report_privacy_redacted")
    status = "succeeded" if bool(generated.report.strip()) else "failed"
    image_path = str(input_asset["path"])
    return {
        "schema_version": "2.0",
        "artifact_type": "generation_benchmark_result",
        "case_id": case.case_id,
        "modality": case.modality,
        "body_part": case.body_part,
        "model": entry.key,
        "status": status,
        "latency_sec": round(latency_sec, 4),
        "execution": execution,
        "input_asset_sha256": _asset_hash(image_path),
        "input_asset_kind": input_asset["kind"],
        "input_asset_selection_policy": input_asset["selection_policy"],
        "reference_report_used": False,
        "generated_report": generated.to_json(),
    }


def _missing_batch_report(entry: GeneratorEntry, modality: str) -> GeneratedReport:
    report = GeneratedReport(
        model=entry.key,
        source=entry.source,
        report="",
        modality=modality,
        evidence_tier=entry.evidence_tier,
        warnings=["legacy_batch_output_missing"],
        metadata={"reference_report_used": False},
    )
    ReportGeneratorRegistry._apply_entry_metadata(entry, report)
    return report


def _adapter_latency(generated: GeneratedReport, fallback: float) -> float:
    runtime = generated.metadata.get("adapter_runtime") or {}
    if isinstance(runtime, dict):
        value = runtime.get("latency_sec")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return fallback


def _model_plan_row(entry: GeneratorEntry) -> dict[str, Any]:
    return {
        "model": entry.key,
        "source": entry.source,
        "evidence_tier": entry.evidence_tier,
        "ready": entry.ready,
        "fresh_inference": entry.fresh_inference,
        "model_version": entry.model_version,
        "model_sha256": entry.model_sha256,
        "prompt_version": entry.prompt_version,
        "preprocessing_version": entry.preprocessing_version,
        "formal_validation_id": entry.formal_validation_id,
        "generation_parameters": entry.generation_parameters,
    }


def _requested_model_rejections(
    registry: ReportGeneratorRegistry,
    selected_entries: list[GeneratorEntry],
    model_keys: list[str] | None,
) -> list[dict[str, Any]]:
    if not model_keys or "*" in model_keys:
        return []
    selected_keys = {entry.key for entry in selected_entries}
    rejected: list[dict[str, Any]] = []
    for key in dict.fromkeys(model_keys):
        if key in selected_keys:
            continue
        entry = registry.entries.get(key)
        if entry is None:
            rejected.append(
                {
                    "model": key,
                    "source": "",
                    "evidence_tier": "none",
                    "ready": False,
                    "fresh_inference": False,
                    "model_version": "",
                    "model_sha256": "",
                    "prompt_version": "",
                    "preprocessing_version": "",
                    "formal_validation_id": "",
                    "generation_parameters": {},
                    "reasons": ["requested_model_not_found"],
                }
            )
            continue
        rejected.append(
            {
                **_model_plan_row(entry),
                "reasons": ["requested_model_incompatible"],
            }
        )
    return rejected


def _case_input_asset(case: Any, config: AppConfig) -> dict[str, Any]:
    modality = str(case.modality or "").strip().lower()
    if modality in {"ct", "mr", "mri"}:
        kind = "volume"
        selection_policy = "3d_volume_required"
        raw_path = (case.derived_assets or {}).get("volume_path") or case.volume_path
    else:
        kind = "image"
        selection_policy = "2d_image_required"
        raw_path = (case.derived_assets or {}).get("primary_image") or (
            case.image_paths[0] if case.image_paths else ""
        )
    resolved = _resolve_input_asset_path(str(raw_path or ""), config)
    return {
        "kind": kind,
        "path": str(resolved) if resolved else "",
        "exists": bool(resolved and resolved.is_file()),
        "selection_policy": selection_policy,
    }


def _resolve_input_asset_path(path_text: str, config: AppConfig) -> Path | None:
    if not path_text:
        return None
    candidate = resolve_existing_path(path_text)
    if candidate.exists():
        return candidate.resolve()
    if not candidate.is_absolute():
        project_candidate = resolve_existing_path(config.project_root / candidate)
        if project_candidate.exists():
            return project_candidate.resolve()
    return candidate


def _asset_hash(path_text: str) -> str:
    path = Path(path_text)
    if path.exists() and path.is_file():
        return _file_sha256(path)
    return hashlib.sha256(path_text.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": round(sum(values) / len(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }
