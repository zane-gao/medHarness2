from __future__ import annotations

from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.data.sample_data import build_sample_manifest
from medharness2.data.sample_data import prepare_sample_dataset
from medharness2.generators.registry import ReportGeneratorRegistry
from medharness2.llm_client import LLMClient
from medharness2.utils.io import write_json
from medharness2.validation.sample_run import validate_sample_run
from medharness2.workflows.batch_readers import run_batch_readers
from medharness2.workflows.department import run_department_comparison


def plan_sample_full_routes(
    sample_root: str | Path,
    output_dir: str | Path,
    *,
    config: AppConfig | None = None,
    limit: int | None = None,
    model_keys: list[str] | None = None,
    model_sources: list[str] | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_manifest_path = out_dir / "route_plan.manifest.raw.jsonl"
    rows = build_sample_manifest(sample_root, raw_manifest_path)
    if limit is not None:
        rows = rows[:limit]
    registry = ReportGeneratorRegistry(cfg)
    cases: list[dict[str, Any]] = []
    local_candidate_count = 0
    fallback_count = 0
    for row in rows:
        entries = registry.select(
            row.modality,
            requested=model_keys,
            body_part=row.body_part,
            sources=set(model_sources or []),
        )
        if entries:
            local_candidate_count += 1
        else:
            fallback_count += 1
        cases.append(
            {
                "case_id": row.case_id,
                "reader": row.reader,
                "modality": row.modality,
                "body_part": row.body_part,
                "compatible_model_keys": [entry.key for entry in entries],
                "compatible_model_sources": {entry.key: entry.source for entry in entries},
                "fallback_needed": not entries,
                "warnings": row.warnings,
            }
        )
    result = {
        "sample_root": str(sample_root),
        "output_dir": str(out_dir),
        "paths": {
            "raw_manifest": str(raw_manifest_path),
            "route_plan": str(out_dir / "route_plan.json"),
        },
        "summary": {
            "case_count": len(cases),
            "cases_with_local_candidates": local_candidate_count,
            "cases_requiring_fallback": fallback_count,
        },
        "cases": cases,
    }
    write_json(out_dir / "route_plan.json", result)
    return result


def run_sample_full(
    sample_root: str | Path,
    output_dir: str | Path,
    *,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
    limit: int | None = None,
    model_keys: list[str] | None = None,
    model_sources: list[str] | None = None,
    run_ocr: bool = True,
    require_real_ocr: bool = False,
    force_ocr: bool = False,
    expected_cases: int | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = prepare_sample_dataset(
        sample_root,
        out_dir,
        config=cfg,
        llm_client=llm_client,
        limit=limit,
        run_ocr=run_ocr,
        require_real_ocr=require_real_ocr,
        force_ocr=force_ocr,
    )
    manifest_path = out_dir / "manifest.jsonl"
    workflow2_path = out_dir / "workflow2.json"
    workflow3_path = out_dir / "workflow3.json"
    batch = run_batch_readers(
        manifest_path,
        workflow2_path,
        model_keys=model_keys,
        model_sources=model_sources,
        config=cfg,
        llm_client=llm_client,
    )
    department = run_department_comparison(workflow2_path, workflow3_path)
    validation = validate_sample_run(
        out_dir,
        expected_cases=expected_cases if expected_cases is not None else len(rows),
        require_real_ocr=require_real_ocr,
    )
    result = {
        "sample_root": str(sample_root),
        "output_dir": str(out_dir),
        "paths": {
            "manifest": str(manifest_path),
            "summary": str(out_dir / "summary.json"),
            "workflow2": str(workflow2_path),
            "workflow3": str(workflow3_path),
            "run_summary": str(out_dir / "run_summary.json"),
        },
        "summary": {
            "case_count": len(rows),
            "workflow2_case_count": int(batch.get("case_count", 0)),
            "workflow2_failed_case_count": int(batch.get("failed_case_count", 0)),
            "workflow3_case_count": int(department.get("case_count", 0)),
            "reader_count": int(department.get("reader_count", 0)),
        },
        "validation": validation,
    }
    write_json(out_dir / "run_summary.json", result)
    return result
