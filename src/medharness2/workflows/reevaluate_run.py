from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.contracts import GeneratedReportArtifact, migrate_generated_report_v1
from medharness2.llm_client import LLMClient
from medharness2.schema import GeneratedReport
from medharness2.tools.tool10_modelwise import modelwise_weighted
from medharness2.tools.tool12_statistics import calculate_statistics
from medharness2.utils.io import read_json, read_text, write_json
from medharness2.validation.sample_run import validate_sample_run
from medharness2.workflows.department import run_department_comparison
from medharness2.workflows.single_case import run_single_case


def reevaluate_run(
    source_run_dir: str | Path,
    output_dir: str | Path,
    *,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    """Recompute evaluation artifacts from existing generated reports.

    This path does not run report generation. It reads existing Workflow 1 case
    JSON files, reuses their generated_reports, and reruns evaluation/ranking.
    """

    source = Path(source_run_dir)
    out = Path(output_dir)
    case_dir = out / "workflow2_cases"
    case_dir.mkdir(parents=True, exist_ok=True)
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    workflow2 = read_json(source / "workflow2.json")
    source_case_count = len(workflow2.get("cases") or [])
    _copy_optional_source_files(source, out)

    case_results: list[dict[str, Any]] = []
    failed_cases: list[dict[str, Any]] = []
    per_reader: dict[str, dict[str, Any]] = {}
    reused_generated_report_count = 0

    for case in workflow2.get("cases") or []:
        case_id = str(case.get("case_id") or "")
        reader = str(case.get("reader") or "unknown")
        try:
            workflow1 = _read_workflow1(source, str(case.get("workflow1_output") or ""))
            generated = _generated_reports(workflow1)
            reused_generated_report_count += len(generated)
            input_payload = dict(workflow1.get("input") or {})
            report_path = _resolve_existing(source, input_payload.get("report_path"))
            report_text = read_text(report_path) if report_path and report_path.exists() else _fallback_report_text(workflow1)
            if not report_text:
                raise ValueError("missing_report_text")
            image_path = _resolve_existing(source, input_payload.get("image_path"))
            if not image_path:
                raise ValueError(f"missing image_path for {case_id}")
            case_output = case_dir / f"{case_id}.json"
            reevaluated = run_single_case(
                report_path=report_path if report_path and report_path.exists() else None,
                report_text=report_text,
                image_path=image_path,
                output_path=case_output,
                prepared_assets=dict(input_payload.get("prepared_assets") or {}),
                modality=str(case.get("modality") or input_payload.get("modality") or "unknown"),
                body_part=str(case.get("body_part") or input_payload.get("body_part") or "unknown"),
                top_n=cfg.ranking.top_n,
                precomputed_generated_reports=generated,
                config=cfg,
                llm_client=client,
            )
        except Exception as exc:
            failed_cases.append(
                {
                    "case_id": case_id,
                    "reader": reader,
                    "error": f"{type(exc).__name__}: {exc}",
                    "source_workflow1_output": str(case.get("workflow1_output") or ""),
                }
            )
            continue

        human_evaluation = reevaluated.get("human_evaluation") or {}
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
            for item in reevaluated.get("generated_evaluations") or []
        ]
        case_result = {
            **case,
            "human_metrics": human_metrics,
            "modelwise_metrics": modelwise_weighted(generated_metrics) if generated_metrics else {},
            "workflow1_output": str(case_output),
            "source_workflow1_output": str(case.get("workflow1_output") or ""),
            "reevaluation": {
                "source_run_dir": str(source),
                "reused_generated_report_count": len(generated),
                "new_generation_count": 0,
            },
        }
        case_results.append(case_result)
        bucket = per_reader.setdefault(reader, {"cases": [], "human_metrics": [], "modelwise_metrics": []})
        bucket["cases"].append(case_id)
        bucket["human_metrics"].append(human_metrics)
        if case_result["modelwise_metrics"]:
            bucket["modelwise_metrics"].append(case_result["modelwise_metrics"])

    for reader, bucket in per_reader.items():
        bucket["case_count"] = len(bucket["cases"])
        bucket["human_statistics"] = calculate_statistics(bucket["human_metrics"])
        bucket["modelwise_statistics"] = calculate_statistics(bucket["modelwise_metrics"])
        bucket["overall_score"] = _mean_score(bucket["human_metrics"])

    result = {
        "manifest_path": str(out / "manifest.jsonl") if (out / "manifest.jsonl").exists() else str(workflow2.get("manifest_path") or ""),
        "case_count": len(case_results),
        "failed_case_count": len(failed_cases),
        "cases": case_results,
        "failed_cases": failed_cases,
        "denominator": {
                "source_case_count": source_case_count,
            "successful_case_count": len(case_results),
            "failed_case_count": len(failed_cases),
                "success_rate": round(len(case_results) / max(source_case_count, 1), 4),
        },
        "per_reader": per_reader,
        "statistics": calculate_statistics([case["human_metrics"] for case in case_results]),
        "reevaluation": {
            "source_run_dir": str(source),
            "reused_generated_report_count": reused_generated_report_count,
            "new_generation_count": 0,
        },
    }
    write_json(out / "workflow2.json", result)
    workflow3 = run_department_comparison(out / "workflow2.json", out / "workflow3.json")
    validation_options = _source_validation_options(source)
    validation = (
        validate_sample_run(
            out,
            expected_cases=validation_options["expected_cases"],
            require_real_ocr=validation_options["require_real_ocr"],
            require_workflows=True,
        )
        if (out / "manifest.jsonl").exists()
        else {
            "passed": True,
            "expected_cases": validation_options["expected_cases"],
            "require_real_ocr": validation_options["require_real_ocr"],
            "errors": [],
            "warnings": ["manifest_not_available_for_validation"],
        }
    )
    summary = {
        "paths": {
            "manifest": str(out / "manifest.jsonl") if (out / "manifest.jsonl").exists() else "",
            "workflow2": str(out / "workflow2.json"),
            "workflow3": str(out / "workflow3.json"),
            "run_summary": str(out / "run_summary.json"),
        },
        "summary": {
            "case_count": result["case_count"],
            "failed_case_count": result["failed_case_count"],
            "reader_count": len(per_reader),
            "reused_generated_report_count": reused_generated_report_count,
            "new_generation_count": 0,
        },
        "validation": validation,
        "reevaluation": {
            "source_run_dir": str(source),
            "extractor_backend": cfg.extractor.backend,
        },
    }
    write_json(out / "run_summary.json", summary)
    return {"workflow2": result, "workflow3": workflow3, "run_summary": summary, "summary": summary["summary"]}


def _read_workflow1(source: Path, value: str) -> dict[str, Any]:
    path = Path(value)
    candidates = [path] if path.is_absolute() else [source / path, path]
    for candidate in candidates:
        if candidate.exists():
            return read_json(candidate)
    raise FileNotFoundError(value)


def _generated_reports(workflow1: dict[str, Any]) -> list[GeneratedReport]:
    reports: list[GeneratedReport] = []
    legacy = str(workflow1.get("schema_version") or "") != "2.0"
    for payload in workflow1.get("generated_reports") or []:
        artifact_payload = (
            migrate_generated_report_v1(payload, legacy_reference_assisted=True)
            if legacy
            else payload
        )
        artifact = GeneratedReportArtifact.model_validate(artifact_payload)
        reports.append(
            GeneratedReport(
                model=artifact.model,
                source=artifact.source,
                report=artifact.report,
                modality=artifact.modality,
                evidence_tier=artifact.evidence_tier,
                warnings=list(artifact.warnings),
                metadata=dict(artifact.metadata),
            )
        )
    return reports


def _resolve_existing(source: Path, value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    candidates = [path] if path.is_absolute() else [path, source / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return path


def _fallback_report_text(workflow1: dict[str, Any]) -> str:
    graph = (workflow1.get("human_evaluation") or {}).get("finding_graph") or {}
    findings = graph.get("findings") or []
    text = "\n".join(
        str(item.get("source_text") or item.get("text") or "")
        for item in findings
        if item.get("source_text") or item.get("text")
    )
    return text


def _copy_optional_source_files(source: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name in ("manifest.jsonl", "summary.json"):
        src = source / name
        if src.exists():
            shutil.copy2(src, out / name)


def _source_validation_options(source: Path) -> dict[str, Any]:
    validation: dict[str, Any] = {}
    run_summary_path = source / "run_summary.json"
    if run_summary_path.exists():
        payload = read_json(run_summary_path)
        if isinstance(payload.get("validation"), dict):
            validation = dict(payload["validation"])
    return {
        "expected_cases": _optional_int(validation.get("expected_cases") if validation.get("expected_cases") is not None else validation.get("case_count")),
        "require_real_ocr": bool(validation.get("require_real_ocr", False)),
    }


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _mean_score(rows: list[dict[str, Any]]) -> float:
    values: list[float] = []
    for row in rows:
        if "likert_mean" in row:
            value = float(row["likert_mean"])
            values.append((value - 1.0) / 4.0 if value >= 1.0 else value)
        if "structure_score" in row:
            values.append(float(row["structure_score"]))
        if "finding_coverage" in row:
            values.append(float(row["finding_coverage"]))
    return round(sum(values) / len(values), 6) if values else 0.0


def _evaluation_metadata(evaluation: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    fallback_seen = False
    for key in ("likert", "finding_graph"):
        value = evaluation.get(key)
        if isinstance(value, dict):
            nested = value.get("_metadata") or value.get("metadata") or value.get("provenance")
            if isinstance(nested, dict):
                metadata.update(nested)
                fallback_seen = fallback_seen or bool(nested.get("fallback_used"))
            if key == "finding_graph":
                correction = (value.get("metadata") or {}).get("llm_correction")
                if isinstance(correction, dict):
                    metadata.update(correction)
                    fallback_seen = fallback_seen or bool(correction.get("fallback_used"))
    if isinstance(evaluation.get("metadata"), dict):
        metadata.update(evaluation["metadata"])
        fallback_seen = fallback_seen or bool(evaluation["metadata"].get("fallback_used"))
    if fallback_seen:
        metadata["fallback_used"] = True
    return metadata
