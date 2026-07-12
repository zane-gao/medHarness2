from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from medharness2.config import PROJECT_ROOT
from medharness2.contracts import CaseEvaluationArtifact, migrate_case_evaluation_v1
from medharness2.data.sample_data import load_manifest
from medharness2.tools.tool12_statistics import calculate_statistics
from medharness2.utils.io import read_json, write_json
from medharness2.workflows.department import run_department_comparison


def merge_batch_results(
    batch_result_paths: list[str | Path],
    output_dir: str | Path,
    *,
    manifest_path: str | Path | None = None,
    expected_cases: int | None = None,
) -> dict[str, Any]:
    if not batch_result_paths:
        raise ValueError("batch_result_paths_required")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    case_dir = out_dir / "workflow2_cases"
    case_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows = load_manifest(manifest_path) if manifest_path else []
    manifest_order = {row.case_id: index for index, row in enumerate(manifest_rows)}
    if manifest_path:
        shutil.copyfile(manifest_path, out_dir / "manifest.jsonl")
        write_json(out_dir / "summary.json", _summary_from_manifest(manifest_rows))

    cases_by_id: dict[str, dict[str, Any]] = {}
    failed_cases: list[dict[str, Any]] = []
    source_paths: list[str] = []
    metadata = {
        "source_batch_results": source_paths,
        "generated_report_model_counts": {},
        "generated_report_source_counts": {},
        "generated_report_warning_counts": {},
        "quality_gate_counts": {},
        "copied_workflow1_outputs": 0,
        "missing_workflow1_outputs": 0,
    }

    model_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()
    quality_counts: Counter[str] = Counter()

    for batch_path_value in batch_result_paths:
        batch_path = Path(batch_path_value)
        source_paths.append(str(batch_path))
        batch = read_json(batch_path)
        for failed in batch.get("failed_cases") or []:
            item = dict(failed)
            item["source_batch_result"] = str(batch_path)
            failed_cases.append(item)
        for case in batch.get("cases") or []:
            case_id = str(case.get("case_id") or "")
            if not case_id:
                raise ValueError(f"missing_case_id:{batch_path}")
            if case_id in cases_by_id:
                raise ValueError(f"duplicate_case:{case_id}")
            item = dict(case)
            item["source_batch_result"] = str(batch_path)
            workflow1_path = _resolve_workflow1_path(batch_path.parent, str(item.get("workflow1_output") or ""))
            if workflow1_path and workflow1_path.exists():
                target = case_dir / f"{case_id}.json"
                _write_merged_case_artifact(workflow1_path, target, case_id=case_id)
                item["workflow1_output"] = str(target)
                metadata["copied_workflow1_outputs"] += 1
                _count_workflow1(target, model_counts, source_counts, warning_counts, quality_counts)
            else:
                metadata["missing_workflow1_outputs"] += 1
            cases_by_id[case_id] = item

    if manifest_rows:
        expected_ids = set(manifest_order)
        actual_ids = set(cases_by_id)
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        if missing:
            raise ValueError(f"missing_cases:{','.join(missing)}")
        if extra:
            raise ValueError(f"extra_cases:{','.join(extra)}")

    cases = sorted(cases_by_id.values(), key=lambda item: (manifest_order.get(str(item.get("case_id")), 10**9), str(item.get("case_id"))))
    if expected_cases is not None and len(cases) != expected_cases:
        raise ValueError(f"case_count_mismatch:{len(cases)}!={expected_cases}")

    metadata["generated_report_model_counts"] = dict(sorted(model_counts.items()))
    metadata["generated_report_source_counts"] = dict(sorted(source_counts.items()))
    metadata["generated_report_warning_counts"] = dict(sorted(warning_counts.items()))
    metadata["quality_gate_counts"] = dict(sorted(quality_counts.items()))

    per_reader = _build_per_reader(cases)
    result = {
        "manifest_path": str(out_dir / "manifest.jsonl") if manifest_path else "",
        "case_count": len(cases),
        "failed_case_count": len(failed_cases),
        "cases": cases,
        "failed_cases": failed_cases,
        "per_reader": per_reader,
        "statistics": calculate_statistics([case.get("human_metrics") or {} for case in cases]),
        "merge_metadata": metadata,
    }
    write_json(out_dir / "workflow2.json", result)
    run_department_comparison(out_dir / "workflow2.json", out_dir / "workflow3.json")
    return result


def _resolve_workflow1_path(batch_dir: Path, value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    for candidate in (path, batch_dir / path, PROJECT_ROOT / path):
        if candidate.exists():
            return candidate
    return path


def _write_merged_case_artifact(source: Path, target: Path, *, case_id: str) -> None:
    payload = read_json(source)
    if payload.get("schema_version") == "2.0" and payload.get("artifact_type") == "case_evaluation":
        artifact = CaseEvaluationArtifact.model_validate(payload)
        write_json(target, artifact.model_dump(mode="json"))
        return
    write_json(target, migrate_case_evaluation_v1(payload, case_id=case_id))


def _count_workflow1(
    path: Path,
    model_counts: Counter[str],
    source_counts: Counter[str],
    warning_counts: Counter[str],
    quality_counts: Counter[str],
) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    for report in data.get("generated_reports") or []:
        model_counts[str(report.get("model") or "unknown")] += 1
        source_counts[str(report.get("source") or "unknown")] += 1
        for warning in report.get("warnings") or []:
            warning_counts[str(warning)] += 1
        quality_gate = (report.get("metadata") or {}).get("quality_gate") or {}
        if quality_gate:
            quality_counts["passed" if quality_gate.get("passed") else "failed"] += 1


def _build_per_reader(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    per_reader: dict[str, dict[str, Any]] = {}
    for case in cases:
        reader = str(case.get("reader") or "unknown")
        bucket = per_reader.setdefault(reader, {"cases": [], "human_metrics": [], "modelwise_metrics": []})
        bucket["cases"].append(case.get("case_id"))
        bucket["human_metrics"].append(case.get("human_metrics") or {})
        if case.get("modelwise_metrics"):
            bucket["modelwise_metrics"].append(case.get("modelwise_metrics") or {})
    for bucket in per_reader.values():
        bucket["case_count"] = len(bucket["cases"])
        bucket["human_statistics"] = calculate_statistics(bucket["human_metrics"])
        bucket["modelwise_statistics"] = calculate_statistics(bucket["modelwise_metrics"])
        bucket["overall_score"] = _mean_score(bucket["human_metrics"])
    return per_reader


def _mean_score(rows: list[dict[str, Any]]) -> float:
    values: list[float] = []
    for row in rows:
        if "likert_mean" in row:
            likert = float(row["likert_mean"])
            values.append(likert / 5.0 if likert > 1 else likert)
        if "structure_score" in row:
            values.append(float(row["structure_score"]))
        if "finding_coverage" in row:
            values.append(float(row["finding_coverage"]))
    return round(sum(values) / len(values), 6) if values else 0.0


def _summary_from_manifest(rows: list[Any]) -> dict[str, Any]:
    warning_counts = Counter(warning for row in rows for warning in row.warnings)
    modality_counts = Counter(row.modality for row in rows)
    body_part_counts = Counter(row.body_part for row in rows)
    return {
        "case_count": len(rows),
        "modality_counts": dict(sorted(modality_counts.items())),
        "body_part_counts": dict(sorted(body_part_counts.items())),
        "warning_counts": dict(sorted(warning_counts.items())),
        "cases_with_report_text": sum(1 for row in rows if row.report_text),
        "cases_with_primary_image": sum(1 for row in rows if row.derived_assets.get("primary_image") or row.image_paths),
        "cases_with_volume": sum(1 for row in rows if row.volume_path),
    }
