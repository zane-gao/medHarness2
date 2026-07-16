from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, StrictInt

from medharness2.catalog import build_capability_catalog
from medharness2.control_panel import dynamic_control_panel_html
from medharness2.control_plane import RunStore
from medharness2.config import load_config
from medharness2.dashboard import build_dashboard, build_dashboard_summary
from medharness2.data.sample_data import prepare_sample_dataset
from medharness2.figures import build_figures
from medharness2.workflows.analyze_run import analyze_run
from medharness2.workflows.batch_readers import run_batch_readers
from medharness2.workflows.department import run_department_comparison
from medharness2.workflows.education import run_education_suggestions
from medharness2.workflows.experiments import build_experiment_results, experiment_registry_metrics, run_experiments
from medharness2.workflows.merge_batches import merge_batch_results
from medharness2.workflows.sample_full import plan_sample_full_routes, run_sample_full
from medharness2.workflows.single_case import run_single_case
from medharness2.run_registry import record_registry_entry
from medharness2.validation.preflight import run_sample_preflight
from medharness2.validation.sample_run import validate_sample_run


app = FastAPI(title="medHarness2 API", version="0.1.0")


def _count_or_zero(value: Any, label: str) -> int:
    if value is None:
        return 0
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


class SingleCaseRequest(BaseModel):
    case_id: str | None = None
    report_text: str | None = None
    report_path: str | None = None
    image_path: str
    output_path: str
    modality: str | None = None
    top_n: StrictInt | None = None
    model_keys: list[str] | None = None
    model_sources: list[str] | None = None
    config_path: str | None = None


class SampleDataRequest(BaseModel):
    sample_root: str
    output_dir: str
    limit: StrictInt | None = None
    run_ocr: bool = True
    require_real_ocr: bool = False
    force_ocr: bool = False
    config_path: str | None = None


class SampleFullRequest(BaseModel):
    sample_root: str
    output_dir: str
    limit: StrictInt | None = None
    model_keys: list[str] | None = None
    model_sources: list[str] | None = None
    all_compatible_local_models: bool = False
    dry_run: bool = False
    run_ocr: bool = True
    require_real_ocr: bool = False
    force_ocr: bool = False
    expected_cases: StrictInt | None = None
    config_path: str | None = None


class BatchReadersRequest(BaseModel):
    manifest_path: str
    output_path: str
    model_keys: list[str] | None = None
    model_sources: list[str] | None = None
    limit: StrictInt | None = None
    config_path: str | None = None


class DepartmentRequest(BaseModel):
    batch_result_path: str
    output_path: str


class MergeBatchesRequest(BaseModel):
    batch_result_paths: list[str]
    output_dir: str
    manifest_path: str | None = None
    expected_cases: StrictInt | None = None
    require_real_ocr: bool = False


class AnalyzeRunRequest(BaseModel):
    output_dir: str
    analysis_dir: str | None = None


class ValidateRunRequest(BaseModel):
    output_dir: str
    expected_cases: StrictInt | None = None
    require_real_ocr: bool = False
    require_workflows: bool = True


class PreflightRequest(BaseModel):
    sample_root: str
    output_path: str
    limit: StrictInt | None = None
    model_keys: list[str] | None = None
    model_sources: list[str] | None = None
    all_compatible_local_models: bool = False
    require_real_ocr: bool = False
    config_path: str | None = None


class EducationRequest(BaseModel):
    eval_report_path: str | None = None
    eval_radiologist_path: str | None = None
    output_path: str
    config_path: str | None = None


class ExperimentRunRequest(BaseModel):
    run_dir: str
    output_dir: str


class FiguresBuildRequest(BaseModel):
    experiment_dir: str
    output_dir: str


class DashboardBuildRequest(BaseModel):
    run_dir: str
    output_path: str


class RunCreateRequest(BaseModel):
    run_type: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    config_path: str = ""


def _control_store() -> RunStore:
    return RunStore(os.environ.get("MEDHARNESS2_CONTROL_DB", "outputs/control_plane.sqlite3"))


@app.get("/control-panel", response_class=HTMLResponse)
def control_panel() -> str:
    try:
        return dynamic_control_panel_html()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"control_panel_failed:{type(exc).__name__}") from exc


@app.post("/runs", status_code=201)
def create_run(request: RunCreateRequest) -> dict[str, Any]:
    try:
        return _control_store().create_run(run_type=request.run_type, inputs=request.inputs, config_path=request.config_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"run_create_failed:{type(exc).__name__}") from exc


@app.get("/runs")
def list_runs(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    try:
        return {"runs": _control_store().list_runs(limit=limit)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"run_list_failed:{type(exc).__name__}") from exc


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    try:
        return _control_store().get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"run_get_failed:{type(exc).__name__}") from exc


@app.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, Any]:
    try:
        return _control_store().cancel_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"run_cancel_failed:{type(exc).__name__}") from exc


@app.post("/runs/{run_id}/retry")
def retry_run(run_id: str) -> dict[str, Any]:
    try:
        return _control_store().retry_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"run_retry_failed:{type(exc).__name__}") from exc


@app.get("/runs/{run_id}/stages")
def run_stages(run_id: str) -> dict[str, Any]:
    run = get_run(run_id)
    return {"run_id": run_id, "stages": run["stages"]}


@app.get("/runs/{run_id}/artifacts")
def run_artifacts(run_id: str) -> dict[str, Any]:
    run = get_run(run_id)
    return {"run_id": run_id, "artifacts": run["artifacts"]}


@app.get("/experiments")
def experiment_readiness(run_dir: str) -> dict[str, Any]:
    try:
        return build_experiment_results(run_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"experiments_readiness_failed:{type(exc).__name__}") from exc


@app.get("/catalog/model-roles")
def catalog_model_roles(config_path: str | None = None) -> dict[str, Any]:
    try:
        cfg = load_config(config_path) if config_path else load_config()
        catalog = build_capability_catalog(cfg)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"catalog_model_roles_failed:{type(exc).__name__}") from exc
    return {"model_roles": (catalog.get("providers") or {}).get("model_roles") or {}}


@app.get("/catalog/tools")
def catalog_tools(config_path: str | None = None) -> dict[str, Any]:
    try:
        cfg = load_config(config_path) if config_path else load_config()
        return build_capability_catalog(cfg)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"catalog_tools_failed:{type(exc).__name__}") from exc


@app.post("/workflow/single-case")
def single_case(request: SingleCaseRequest) -> dict[str, Any]:
    if bool(request.report_text) == bool(request.report_path):
        raise HTTPException(status_code=400, detail="Provide exactly one of report_text or report_path.")
    try:
        cfg = load_config(request.config_path) if request.config_path else load_config()
        with tempfile.TemporaryDirectory(prefix="medharness2_api_") as tmpdir:
            report_path = Path(request.report_path) if request.report_path else Path(tmpdir) / "report.txt"
            if request.report_text is not None:
                report_path.write_text(request.report_text, encoding="utf-8")
            result = run_single_case(
                report_path=report_path,
                image_path=Path(request.image_path),
                output_path=Path(request.output_path),
                case_id=request.case_id,
                modality=request.modality,
                top_n=request.top_n,
                model_keys=request.model_keys,
                model_sources=request.model_sources,
                config=cfg,
            )
    except Exception as exc:
        _record_registry(
            Path(request.output_path).parent,
            stage="workflow.single-case",
            status="failed",
            inputs={"output_path": request.output_path, "case_id": request.case_id or ""},
            outputs={"result": request.output_path},
            metrics={"error_count": 1},
            warnings=[f"{type(exc).__name__}: {exc}"],
        )
        raise HTTPException(status_code=500, detail=f"single_case_failed:{type(exc).__name__}") from exc
    result_errors = list(result.get("errors") or [])
    _record_registry(
        Path(request.output_path).parent,
        stage="workflow.single-case",
        status="failed" if result_errors else "passed",
        inputs={"output_path": request.output_path, "case_id": request.case_id or ""},
        outputs={"result": request.output_path},
        metrics={"generated_report_count": len(result.get("generated_reports") or []), "error_count": len(result_errors)},
        warnings=result_errors,
    )
    return {
        "output_path": request.output_path,
        "summary": {
            "modality": result.get("input", {}).get("modality"),
            "generated_reports": len(result.get("generated_reports") or []),
            "pairwise_comparisons": len(result.get("pairwise_comparisons") or []),
            "rankings": len(result.get("rankings") or []),
            "errors": result_errors,
        },
        "result": result,
    }


@app.post("/experiments/run")
def experiments_run(request: ExperimentRunRequest) -> dict[str, Any]:
    try:
        result = run_experiments(request.run_dir, request.output_dir)
    except Exception as exc:
        for registry_dir in (request.output_dir, request.run_dir):
            _record_registry(
                registry_dir,
                stage="experiments.run",
                status="failed",
                inputs={"run_dir": request.run_dir},
                outputs={"experiment_dir": request.output_dir},
                metrics={"error_count": 1},
                warnings=[f"{type(exc).__name__}: {exc}"],
            )
        raise HTTPException(status_code=500, detail=f"experiments_run_failed:{type(exc).__name__}") from exc
    metrics = experiment_registry_metrics(result)
    outputs = {
        "results": str(Path(request.output_dir) / "results.json"),
        "results_markdown": str(Path(request.output_dir) / "results.md"),
        "summary_csv": str(Path(request.output_dir) / "experiment_summary.csv"),
    }
    _record_registry(
        request.output_dir,
        stage="experiments.run",
        status="failed" if result.get("errors") else "passed",
        inputs={"run_dir": request.run_dir},
        outputs=outputs,
        metrics=metrics,
    )
    _record_registry(
        request.run_dir,
        stage="experiments.run",
        status="failed" if result.get("errors") else "passed",
        inputs={"run_dir": request.run_dir},
        outputs={"experiment_dir": request.output_dir, **outputs},
        metrics=metrics,
    )
    return {
        "output_dir": request.output_dir,
        "summary": {"experiments": result["experiment_count"], "errors": list(result.get("errors") or [])},
        "result": result,
    }


@app.post("/figures/build")
def figures_build(request: FiguresBuildRequest) -> dict[str, Any]:
    try:
        result = build_figures(request.experiment_dir, request.output_dir)
    except Exception as exc:
        _record_registry(
            request.output_dir,
            stage="figures.build",
            status="failed",
            inputs={"experiment_dir": request.experiment_dir},
            outputs={"figure_dir": request.output_dir},
            metrics={"error_count": 1},
            warnings=[f"{type(exc).__name__}: {exc}"],
        )
        raise HTTPException(status_code=500, detail=f"figures_build_failed:{type(exc).__name__}") from exc
    metrics = {"figure_count": result["figure_count"]}
    outputs = {
        "figure_dir": request.output_dir,
        "figure_manifest": str(Path(request.output_dir) / "figure_manifest.json"),
    }
    _record_registry(
        request.output_dir,
        stage="figures.build",
        status="passed",
        inputs={"experiment_dir": request.experiment_dir},
        outputs=outputs,
        metrics=metrics,
    )
    run_dir = _experiment_run_dir(request.experiment_dir)
    if run_dir:
        _record_registry(
            run_dir,
            stage="figures.build",
            inputs={"experiment_dir": request.experiment_dir},
            outputs=outputs,
            metrics=metrics,
        )
    return {
        "output_dir": request.output_dir,
        "summary": {"figures": result["figure_count"]},
        "result": result,
    }


@app.post("/dashboard/build")
def dashboard_build(request: DashboardBuildRequest) -> dict[str, Any]:
    try:
        result = build_dashboard(request.run_dir, request.output_path)
        summary = build_dashboard_summary(request.run_dir, registry_entry_count_delta=1)
    except Exception as exc:
        _record_registry(
            request.run_dir,
            stage="dashboard.build",
            status="failed",
            inputs={"run_dir": request.run_dir},
            outputs={"dashboard": request.output_path},
            metrics={"error_count": 1},
            warnings=[f"{type(exc).__name__}: {exc}"],
        )
        raise HTTPException(status_code=500, detail=f"dashboard_build_failed:{type(exc).__name__}") from exc
    _record_registry(
        request.run_dir,
        stage="dashboard.build",
        status="passed",
        inputs={"run_dir": request.run_dir},
        outputs={"dashboard": request.output_path},
        metrics=summary,
    )
    return {
        "output_path": request.output_path,
        "summary": result["summary"],
        "result": result,
    }


@app.post("/workflow/sample-data")
def sample_data(request: SampleDataRequest) -> dict[str, Any]:
    try:
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
    except Exception as exc:
        _record_registry(
            request.output_dir,
            stage="workflow.sample-data",
            status="failed",
            inputs={"sample_root": request.sample_root},
            outputs={"manifest": str(Path(request.output_dir) / "manifest.jsonl")},
            metrics={"error_count": 1},
            warnings=[f"{type(exc).__name__}: {exc}"],
        )
        raise HTTPException(status_code=500, detail=f"sample_data_failed:{type(exc).__name__}") from exc
    errors = ["no_cases_discovered"] if not rows else []
    _record_registry(
        request.output_dir,
        stage="workflow.sample-data",
        status="failed" if errors else "passed",
        inputs={"sample_root": request.sample_root},
        outputs={
            "manifest": str(Path(request.output_dir) / "manifest.jsonl"),
            "summary": str(Path(request.output_dir) / "summary.json"),
        },
        metrics={"case_count": len(rows), "warning_count": sum(len(row.warnings) for row in rows)},
        warnings=errors,
    )
    return {
        "manifest_path": str(Path(request.output_dir) / "manifest.jsonl"),
        "case_count": len(rows),
        "errors": errors,
        "warnings": sorted({warning for row in rows for warning in row.warnings}),
    }


@app.post("/workflow/sample-full")
def sample_full(request: SampleFullRequest) -> dict[str, Any]:
    try:
        cfg = load_config(request.config_path) if request.config_path else load_config()
        model_keys = ["*"] if request.all_compatible_local_models else request.model_keys
        if request.dry_run:
            result = plan_sample_full_routes(
                request.sample_root,
                request.output_dir,
                config=cfg,
                limit=request.limit,
                model_keys=model_keys,
                model_sources=request.model_sources,
            )
        else:
            result = run_sample_full(
                request.sample_root,
                request.output_dir,
                config=cfg,
                limit=request.limit,
                model_keys=model_keys,
                model_sources=request.model_sources,
                run_ocr=request.run_ocr,
                require_real_ocr=request.require_real_ocr,
                force_ocr=request.force_ocr,
                expected_cases=request.expected_cases,
            )
    except Exception as exc:
        stage = "workflow.sample-full.dry-run" if request.dry_run else "workflow.sample-full"
        _record_registry(
            request.output_dir,
            stage=stage,
            status="failed",
            inputs={"sample_root": request.sample_root, "limit": request.limit},
            outputs={"output_dir": request.output_dir},
            metrics={"error_count": 1},
            warnings=[f"{type(exc).__name__}: {exc}"],
        )
        raise HTTPException(status_code=500, detail=f"sample_full_failed:{type(exc).__name__}") from exc
    if request.dry_run:
        summary = {"dry_run": True, **result["summary"], "errors": list(result.get("errors") or [])}
        _record_registry(
            request.output_dir,
            stage="workflow.sample-full.dry-run",
            status="passed" if summary.get("case_count") and not summary.get("errors") else "failed",
            inputs={"sample_root": request.sample_root, "limit": request.limit, "models": model_keys or []},
            outputs=result.get("paths") or {"route_plan": str(Path(request.output_dir) / "route_plan.json")},
            metrics=summary,
            warnings=list(summary.get("errors") or []),
        )
        return {
            "output_dir": request.output_dir,
            "summary": summary,
            "result": result,
        }
    validation = dict(result.get("validation") or {})
    _record_registry(
        request.output_dir,
        stage="workflow.sample-full",
        status="passed" if validation.get("passed") else "failed",
        inputs={"sample_root": request.sample_root, "limit": request.limit, "models": model_keys or []},
        outputs=dict(result.get("paths") or {}),
        metrics={**dict(result.get("summary") or {}), "validation_passed": bool(validation.get("passed"))},
        warnings=list(validation.get("errors") or []),
    )
    return {
        "output_dir": request.output_dir,
        "summary": {
            **result["summary"],
            "validation_passed": result["validation"]["passed"],
            "validation_errors": result["validation"]["errors"],
            "errors": list(result["validation"].get("errors") or []),
        },
        "result": result,
    }


@app.post("/workflow/batch-readers")
def batch_readers(request: BatchReadersRequest) -> dict[str, Any]:
    try:
        cfg = load_config(request.config_path) if request.config_path else load_config()
        result = run_batch_readers(
            request.manifest_path,
            request.output_path,
            model_keys=request.model_keys,
            model_sources=request.model_sources,
            limit=request.limit,
            config=cfg,
        )
    except Exception as exc:
        _record_registry(
            Path(request.output_path).parent,
            stage="workflow.batch-readers",
            status="failed",
            inputs={"manifest": request.manifest_path},
            outputs={"workflow2": request.output_path},
            metrics={"error_count": 1},
            warnings=[f"{type(exc).__name__}: {exc}"],
        )
        raise HTTPException(status_code=500, detail=f"batch_readers_failed:{type(exc).__name__}") from exc
    errors = list(result.get("errors") or [])
    _record_registry(
        Path(request.output_path).parent,
        stage="workflow.batch-readers",
        status="failed" if errors or _count_or_zero(result.get("failed_case_count"), "failed_case_count") else "passed",
        inputs={"manifest": request.manifest_path},
        outputs={"workflow2": request.output_path},
        metrics={"case_count": _count_or_zero(result.get("case_count"), "case_count"), "failed_case_count": _count_or_zero(result.get("failed_case_count"), "failed_case_count"), "reader_count": len(result.get("per_reader") or {})},
        warnings=errors,
    )
    return {
        "output_path": request.output_path,
        "summary": {"cases": result["case_count"], "readers": len(result["per_reader"]), "errors": list(result.get("errors") or [])},
        "result": result,
    }


@app.post("/workflow/department")
def department(request: DepartmentRequest) -> dict[str, Any]:
    try:
        result = run_department_comparison(request.batch_result_path, request.output_path)
    except Exception as exc:
        _record_registry(
            Path(request.output_path).parent,
            stage="workflow.department",
            status="failed",
            inputs={"batch_result": request.batch_result_path},
            outputs={"workflow3": request.output_path},
            metrics={"error_count": 1},
            warnings=[f"{type(exc).__name__}: {exc}"],
        )
        raise HTTPException(status_code=500, detail=f"department_failed:{type(exc).__name__}") from exc
    errors = list(result.get("errors") or [])
    _record_registry(
        Path(request.output_path).parent,
        stage="workflow.department",
        status="failed" if errors else "passed",
        inputs={"batch_result": request.batch_result_path},
        outputs={"workflow3": request.output_path},
        metrics={"case_count": _count_or_zero(result.get("case_count"), "case_count"), "reader_count": _count_or_zero(result.get("reader_count"), "reader_count")},
        warnings=errors,
    )
    # ``summary.readers`` reports readers present in the completed batch.  The
    # workflow result separately exposes ``reader_count`` for readers eligible
    # for statistical aggregation, plus ``excluded_reader_count``.
    return {
        "output_path": request.output_path,
        "summary": {
            "cases": result["case_count"],
            "readers": result.get("reader_total_count", result["reader_count"]),
            "errors": list(result.get("errors") or []),
        },
        "result": result,
    }


@app.post("/workflow/merge-batches")
def merge_batches(request: MergeBatchesRequest) -> dict[str, Any]:
    try:
        result = merge_batch_results(
            request.batch_result_paths,
            request.output_dir,
            manifest_path=request.manifest_path,
            expected_cases=request.expected_cases,
        )
        validation = validate_sample_run(
            request.output_dir,
            expected_cases=request.expected_cases,
            require_real_ocr=request.require_real_ocr,
        )
    except Exception as exc:
        _record_registry(
            request.output_dir,
            stage="workflow.merge-batches",
            status="failed",
            inputs={"batch_results": request.batch_result_paths},
            outputs={"output_dir": request.output_dir},
            metrics={"error_count": 1},
            warnings=[f"{type(exc).__name__}: {exc}"],
        )
        raise HTTPException(status_code=500, detail=f"merge_batches_failed:{type(exc).__name__}") from exc
    errors = list(validation.get("errors") or [])
    _record_registry(
        request.output_dir,
        stage="workflow.merge-batches",
        status="passed" if validation.get("passed") else "failed",
        inputs={"batch_results": request.batch_result_paths},
        outputs={"workflow2": str(Path(request.output_dir) / "workflow2.json"), "workflow3": str(Path(request.output_dir) / "workflow3.json")},
        metrics={"case_count": result["case_count"], "failed_case_count": result["failed_case_count"], "validation_passed": bool(validation.get("passed"))},
        warnings=errors,
    )
    return {
        "output_dir": request.output_dir,
        "summary": {
            "cases": result["case_count"],
            "failed_cases": result["failed_case_count"],
            "readers": len(result["per_reader"]),
            "validation_passed": validation["passed"],
            "validation_errors": validation["errors"],
            "errors": list(validation.get("errors") or []),
        },
        "result": result,
        "validation": validation,
    }


@app.post("/workflow/analyze-run")
def analyze_run_endpoint(request: AnalyzeRunRequest) -> dict[str, Any]:
    try:
        result = analyze_run(request.output_dir, request.analysis_dir)
    except Exception as exc:
        _record_registry(
            request.output_dir,
            stage="workflow.analyze-run",
            status="failed",
            inputs={"output_dir": request.output_dir},
            outputs={"analysis_dir": request.analysis_dir or str(Path(request.output_dir) / "analysis")},
            metrics={"error_count": 1},
            warnings=[f"{type(exc).__name__}: {exc}"],
        )
        raise HTTPException(status_code=500, detail=f"analyze_run_failed:{type(exc).__name__}") from exc
    errors = list(result.get("errors") or [])
    _record_registry(
        request.output_dir,
        stage="workflow.analyze-run",
        status="failed" if errors else "passed",
        inputs={"output_dir": request.output_dir},
        outputs={"analysis_dir": result.get("analysis_dir", "")},
        metrics={"case_count": _count_or_zero(result.get("case_count"), "case_count"), "error_count": len(errors)},
        warnings=errors,
    )
    return {
        "analysis_dir": result["analysis_dir"],
        "summary": {
            "cases": result["case_count"],
            "generated_reports": result["generated_report_count"],
            "quality_failed": result["quality_gate_failed_count"],
            "errors": list(result.get("errors") or []),
        },
        "result": result,
    }


@app.post("/workflow/validate-run")
def validate_run(request: ValidateRunRequest) -> dict[str, Any]:
    try:
        result = validate_sample_run(
            request.output_dir,
            expected_cases=request.expected_cases,
            require_real_ocr=request.require_real_ocr,
            require_workflows=request.require_workflows,
        )
    except Exception as exc:
        _record_registry(
            request.output_dir,
            stage="workflow.validate-run",
            status="failed",
            inputs={"output_dir": request.output_dir, "expected_cases": request.expected_cases},
            outputs={"validation": str(Path(request.output_dir) / "run_summary.json")},
            metrics={"error_count": 1},
            warnings=[f"{type(exc).__name__}: {exc}"],
        )
        raise HTTPException(status_code=500, detail=f"validate_run_failed:{type(exc).__name__}") from exc
    _record_registry(
        request.output_dir,
        stage="workflow.validate-run",
        status="passed" if result.get("passed") else "failed",
        inputs={"output_dir": request.output_dir, "expected_cases": request.expected_cases},
        outputs={"validation": str(Path(request.output_dir) / "run_summary.json")},
        metrics={"passed": bool(result.get("passed")), "error_count": len(result.get("errors") or [])},
        warnings=list(result.get("errors") or []),
    )
    return {"summary": {"passed": result["passed"], "errors": result["errors"]}, "result": result}


@app.post("/workflow/preflight")
def preflight(request: PreflightRequest) -> dict[str, Any]:
    try:
        cfg = load_config(request.config_path) if request.config_path else load_config()
        model_keys = ["*"] if request.all_compatible_local_models else request.model_keys
        result = run_sample_preflight(
            request.sample_root,
            request.output_path,
            config=cfg,
            require_real_ocr=request.require_real_ocr,
            limit=request.limit,
            model_keys=model_keys,
            model_sources=request.model_sources,
        )
    except Exception as exc:
        _record_registry(
            Path(request.output_path).parent,
            stage="workflow.preflight",
            status="failed",
            inputs={"sample_root": request.sample_root},
            outputs={"preflight": request.output_path},
            metrics={"error_count": 1},
            warnings=[f"{type(exc).__name__}: {exc}"],
        )
        raise HTTPException(status_code=500, detail=f"preflight_failed:{type(exc).__name__}") from exc
    _record_registry(
        Path(request.output_path).parent,
        stage="workflow.preflight",
        status="passed" if result.get("passed") else "failed",
        inputs={"sample_root": request.sample_root, "expected_cases": request.limit},
        outputs={"preflight": request.output_path, "route_plan": str(result.get("paths", {}).get("route_plan") or "")},
        metrics={"passed": bool(result.get("passed")), "case_count": _count_or_zero(result.get("sample", {}).get("case_count"), "case_count"), "blocker_count": len(result.get("blockers") or [])},
        warnings=list(result.get("blockers") or []),
    )
    return {
        "output_path": request.output_path,
        "summary": {
            "passed": result["passed"],
            "blockers": result["blockers"],
            "warnings": result["warnings"],
            "cases": result["sample"]["case_count"],
            "errors": list(result.get("blockers") or []),
        },
        "result": result,
    }


@app.post("/workflow/education")
def education(request: EducationRequest) -> dict[str, Any]:
    if bool(request.eval_report_path) == bool(request.eval_radiologist_path):
        raise HTTPException(status_code=400, detail="Provide exactly one of eval_report_path or eval_radiologist_path.")
    try:
        cfg = load_config(request.config_path) if request.config_path else load_config()
        result = run_education_suggestions(
            eval_report=request.eval_report_path,
            eval_radiologist=request.eval_radiologist_path,
            output_path=request.output_path,
            config=cfg,
        )
    except Exception as exc:
        _record_registry(
            Path(request.output_path).parent,
            stage="workflow.education",
            status="failed",
            inputs={
                "eval_report": request.eval_report_path or "",
                "eval_radiologist": request.eval_radiologist_path or "",
            },
            outputs={"education": request.output_path},
            metrics={"error_count": 1},
            warnings=[f"{type(exc).__name__}: {exc}"],
        )
        raise HTTPException(status_code=500, detail=f"education_failed:{type(exc).__name__}") from exc
    _record_registry(
        Path(request.output_path).parent,
        stage="workflow.education",
        inputs={
            "eval_report": request.eval_report_path or "",
            "eval_radiologist": request.eval_radiologist_path or "",
        },
        outputs={"education": request.output_path},
        metrics={
            "suggestion_count": len(result.get("suggestions") or []),
            "general_suggestion_count": len(result.get("general_suggestions") or []),
            "error_count": len(result.get("errors") or []),
        },
        status="failed" if result.get("status") in {"blocked", "blocked_insufficient_data"} else "passed",
        warnings=list(result.get("errors") or []),
    )
    return {
        "output_path": request.output_path,
        "summary": {
            "mode": result["mode"],
            "suggestions": len(result.get("suggestions") or []),
            "general_suggestions": len(result.get("general_suggestions") or []),
            "status": result.get("status"),
            "errors": list(result.get("errors") or []),
        },
        "result": result,
    }


def _record_registry(
    registry_dir: str | Path,
    *,
    stage: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    metrics: dict[str, Any],
    status: str = "passed",
    warnings: list[str] | None = None,
) -> None:
    record_registry_entry(
        registry_dir,
        command=["medharness2-api", stage],
        stage=stage,
        status=status,
        inputs=inputs,
        outputs=outputs,
        metrics=metrics,
        warnings=warnings,
    )


def _experiment_run_dir(experiment_dir: str | Path) -> str | None:
    path = Path(experiment_dir) / "results.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    run_dir = data.get("run_dir")
    return str(run_dir) if run_dir else None
