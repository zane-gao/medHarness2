from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from medharness2.config import load_config
from medharness2.data.sample_data import prepare_sample_dataset
from medharness2.workflows.batch_readers import run_batch_readers
from medharness2.workflows.department import run_department_comparison
from medharness2.workflows.sample_full import plan_sample_full_routes, run_sample_full
from medharness2.workflows.single_case import run_single_case
from medharness2.validation.sample_run import validate_sample_run


app = FastAPI(title="medHarness2 API", version="0.1.0")


class SingleCaseRequest(BaseModel):
    report_text: str | None = None
    report_path: str | None = None
    image_path: str
    output_path: str
    modality: str | None = None
    top_n: int | None = None
    model_keys: list[str] | None = None
    config_path: str | None = None


class SampleDataRequest(BaseModel):
    sample_root: str
    output_dir: str
    limit: int | None = None
    run_ocr: bool = True
    require_real_ocr: bool = False
    force_ocr: bool = False
    config_path: str | None = None


class SampleFullRequest(BaseModel):
    sample_root: str
    output_dir: str
    limit: int | None = None
    model_keys: list[str] | None = None
    all_compatible_local_models: bool = False
    dry_run: bool = False
    run_ocr: bool = True
    require_real_ocr: bool = False
    force_ocr: bool = False
    expected_cases: int | None = None
    config_path: str | None = None


class BatchReadersRequest(BaseModel):
    manifest_path: str
    output_path: str
    model_keys: list[str] | None = None
    limit: int | None = None
    config_path: str | None = None


class DepartmentRequest(BaseModel):
    batch_result_path: str
    output_path: str


class ValidateRunRequest(BaseModel):
    output_dir: str
    expected_cases: int | None = None
    require_real_ocr: bool = False
    require_workflows: bool = True


@app.post("/workflow/single-case")
def single_case(request: SingleCaseRequest) -> dict[str, Any]:
    if bool(request.report_text) == bool(request.report_path):
        raise HTTPException(status_code=400, detail="Provide exactly one of report_text or report_path.")
    cfg = load_config(request.config_path) if request.config_path else load_config()
    with tempfile.TemporaryDirectory(prefix="medharness2_api_") as tmpdir:
        report_path = Path(request.report_path) if request.report_path else Path(tmpdir) / "report.txt"
        if request.report_text is not None:
            report_path.write_text(request.report_text, encoding="utf-8")
        result = run_single_case(
            report_path=report_path,
            image_path=Path(request.image_path),
            output_path=Path(request.output_path),
            modality=request.modality,
            top_n=request.top_n,
            model_keys=request.model_keys,
            config=cfg,
        )
    return {
        "output_path": request.output_path,
        "summary": {
            "modality": result.get("input", {}).get("modality"),
            "generated_reports": len(result.get("generated_reports") or []),
            "pairwise_comparisons": len(result.get("pairwise_comparisons") or []),
            "rankings": len(result.get("rankings") or []),
        },
        "result": result,
    }


@app.post("/workflow/sample-data")
def sample_data(request: SampleDataRequest) -> dict[str, Any]:
    cfg = load_config(request.config_path) if request.config_path else load_config()
    rows = prepare_sample_dataset(
        request.sample_root,
        request.output_dir,
        config=cfg,
        limit=request.limit,
        run_ocr=request.run_ocr,
        require_real_ocr=request.require_real_ocr,
        force_ocr=request.force_ocr,
    )
    return {
        "manifest_path": str(Path(request.output_dir) / "manifest.jsonl"),
        "case_count": len(rows),
        "warnings": sorted({warning for row in rows for warning in row.warnings}),
    }


@app.post("/workflow/sample-full")
def sample_full(request: SampleFullRequest) -> dict[str, Any]:
    cfg = load_config(request.config_path) if request.config_path else load_config()
    model_keys = ["*"] if request.all_compatible_local_models else request.model_keys
    if request.dry_run:
        result = plan_sample_full_routes(
            request.sample_root,
            request.output_dir,
            config=cfg,
            limit=request.limit,
            model_keys=model_keys,
        )
        return {
            "output_dir": request.output_dir,
            "summary": {"dry_run": True, **result["summary"]},
            "result": result,
        }
    result = run_sample_full(
        request.sample_root,
        request.output_dir,
        config=cfg,
        limit=request.limit,
        model_keys=model_keys,
        run_ocr=request.run_ocr,
        require_real_ocr=request.require_real_ocr,
        force_ocr=request.force_ocr,
        expected_cases=request.expected_cases,
    )
    return {
        "output_dir": request.output_dir,
        "summary": {
            **result["summary"],
            "validation_passed": result["validation"]["passed"],
            "validation_errors": result["validation"]["errors"],
        },
        "result": result,
    }


@app.post("/workflow/batch-readers")
def batch_readers(request: BatchReadersRequest) -> dict[str, Any]:
    cfg = load_config(request.config_path) if request.config_path else load_config()
    result = run_batch_readers(
        request.manifest_path,
        request.output_path,
        model_keys=request.model_keys,
        limit=request.limit,
        config=cfg,
    )
    return {
        "output_path": request.output_path,
        "summary": {"cases": result["case_count"], "readers": len(result["per_reader"])},
        "result": result,
    }


@app.post("/workflow/department")
def department(request: DepartmentRequest) -> dict[str, Any]:
    result = run_department_comparison(request.batch_result_path, request.output_path)
    return {
        "output_path": request.output_path,
        "summary": {"cases": result["case_count"], "readers": result["reader_count"]},
        "result": result,
    }


@app.post("/workflow/validate-run")
def validate_run(request: ValidateRunRequest) -> dict[str, Any]:
    result = validate_sample_run(
        request.output_dir,
        expected_cases=request.expected_cases,
        require_real_ocr=request.require_real_ocr,
        require_workflows=request.require_workflows,
    )
    return {"summary": {"passed": result["passed"], "errors": result["errors"]}, "result": result}
