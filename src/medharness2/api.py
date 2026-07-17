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


def _result_mapping(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _result_string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    return value


def _result_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
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
        result = _result_mapping(result, "single_case.result")
        _result_mapping(result.get("input"), "single_case.input")
        _result_string_list(result.get("errors"), "single_case.errors")
        for field in ("generated_reports", "generated_evaluations", "rankings", "pairwise_comparisons"):
            value = result.get(field)
            if value is not None and not isinstance(value, list):
                raise ValueError(f"single_case.{field} must be a list")
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
    result_errors = _result_string_list(result.get("errors"), "single_case.errors")
    result_input = _result_mapping(result.get("input"), "single_case.input")
    generated_reports = result.get("generated_reports") or []
    generated_evaluations = result.get("generated_evaluations") or []
    rankings = result.get("rankings") or []
    pairwise_comparisons = result.get("pairwise_comparisons") or []
    _record_registry(
        Path(request.output_path).parent,
        stage="workflow.single-case",
        status="failed" if result_errors else "passed",
        inputs={"output_path": request.output_path, "case_id": request.case_id or ""},
        outputs={"result": request.output_path},
        metrics={"generated_report_count": len(generated_reports), "error_count": len(result_errors)},
        warnings=result_errors,
    )
    return {
        "output_path": request.output_path,
        "summary": {
            "modality": result_input.get("modality"),
            "generated_reports": len(generated_reports),
            "pairwise_comparisons": len(pairwise_comparisons),
            "rankings": len(rankings),
            "errors": result_errors,
        },
        "result": result,
    }


@app.post("/experiments/run")
def experiments_run(request: ExperimentRunRequest) -> dict[str, Any]:
    try:
        result = run_experiments(request.run_dir, request.output_dir)
        result = _result_mapping(result, "experiments.result")
        _count_or_zero(result.get("experiment_count"), "experiment_count")
        experiments = result.get("experiments")
        if not isinstance(experiments, list):
            raise ValueError("experiments.experiments must be a list")
        _result_string_list(result.get("errors"), "experiments.errors")
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
    errors = _result_string_list(result.get("errors"), "experiments.errors")
    metrics = experiment_registry_metrics(result)
    outputs = {
        "results": str(Path(request.output_dir) / "results.json"),
        "results_markdown": str(Path(request.output_dir) / "results.md"),
        "summary_csv": str(Path(request.output_dir) / "experiment_summary.csv"),
    }
    _record_registry(
        request.output_dir,
        stage="experiments.run",
        status="failed" if errors else "passed",
        inputs={"run_dir": request.run_dir},
        outputs=outputs,
        metrics=metrics,
    )
    _record_registry(
        request.run_dir,
        stage="experiments.run",
        status="failed" if errors else "passed",
        inputs={"run_dir": request.run_dir},
        outputs={"experiment_dir": request.output_dir, **outputs},
        metrics=metrics,
    )
    return {
        "output_dir": request.output_dir,
        "summary": {"experiments": result["experiment_count"], "errors": errors},
        "result": result,
    }


@app.post("/figures/build")
def figures_build(request: FiguresBuildRequest) -> dict[str, Any]:
    try:
        result = build_figures(request.experiment_dir, request.output_dir)
        result = _result_mapping(result, "figures.result")
        figure_count = _count_or_zero(result.get("figure_count"), "figure_count")
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
    metrics = {"figure_count": figure_count}
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
        "summary": {"figures": figure_count},
        "result": result,
    }


@app.post("/dashboard/build")
def dashboard_build(request: DashboardBuildRequest) -> dict[str, Any]:
    try:
        result = build_dashboard(request.run_dir, request.output_path)
        summary = build_dashboard_summary(request.run_dir, registry_entry_count_delta=1)
        result = _result_mapping(result, "dashboard.result")
        result_summary = _result_mapping(result.get("summary"), "dashboard.summary")
        summary = _result_mapping(summary, "dashboard.registry_summary")
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
        "summary": result_summary,
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
        result = _result_mapping(result, "sample_full.result")
        result_summary = _result_mapping(result.get("summary"), "sample_full.summary")
        result_paths = _result_mapping(result.get("paths"), "sample_full.paths")
        if request.dry_run:
            _result_string_list(result.get("errors"), "sample_full.errors")
        else:
            result_validation = _result_mapping(result.get("validation"), "sample_full.validation")
            _result_bool(result_validation.get("passed"), "sample_full.validation.passed")
            _result_string_list(result_validation.get("errors"), "sample_full.validation.errors")
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
        summary = {"dry_run": True, **result_summary, "errors": _result_string_list(result.get("errors"), "sample_full.errors")}
        _record_registry(
            request.output_dir,
            stage="workflow.sample-full.dry-run",
            status="passed" if summary.get("case_count") and not summary.get("errors") else "failed",
            inputs={"sample_root": request.sample_root, "limit": request.limit, "models": model_keys or []},
            outputs=result_paths or {"route_plan": str(Path(request.output_dir) / "route_plan.json")},
            metrics=summary,
            warnings=list(summary.get("errors") or []),
        )
        return {
            "output_dir": request.output_dir,
            "summary": summary,
            "result": result,
        }
    validation = _result_mapping(result.get("validation"), "sample_full.validation")
    _record_registry(
        request.output_dir,
        stage="workflow.sample-full",
        status="passed" if validation.get("passed") else "failed",
        inputs={"sample_root": request.sample_root, "limit": request.limit, "models": model_keys or []},
        outputs=result_paths,
        metrics={**result_summary, "validation_passed": _result_bool(validation.get("passed"), "sample_full.validation.passed")},
        warnings=_result_string_list(validation.get("errors"), "sample_full.validation.errors"),
    )
    return {
        "output_dir": request.output_dir,
        "summary": {
            **result_summary,
            "validation_passed": _result_bool(validation.get("passed"), "sample_full.validation.passed"),
            "validation_errors": _result_string_list(validation.get("errors"), "sample_full.validation.errors"),
            "errors": _result_string_list(validation.get("errors"), "sample_full.validation.errors"),
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
        result = _result_mapping(result, "batch_readers.result")
        case_count = _count_or_zero(result.get("case_count"), "case_count")
        failed_case_count = _count_or_zero(result.get("failed_case_count"), "failed_case_count")
        per_reader = _result_mapping(result.get("per_reader"), "batch_readers.per_reader")
        errors = _result_string_list(result.get("errors"), "batch_readers.errors")
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
    _record_registry(
        Path(request.output_path).parent,
        stage="workflow.batch-readers",
        status="failed" if errors or failed_case_count else "passed",
        inputs={"manifest": request.manifest_path},
        outputs={"workflow2": request.output_path},
        metrics={"case_count": case_count, "failed_case_count": failed_case_count, "reader_count": len(per_reader)},
        warnings=errors,
    )
    return {
        "output_path": request.output_path,
        "summary": {"cases": case_count, "readers": len(per_reader), "errors": errors},
        "result": result,
    }


@app.post("/workflow/department")
def department(request: DepartmentRequest) -> dict[str, Any]:
    try:
        result = run_department_comparison(request.batch_result_path, request.output_path)
        result = _result_mapping(result, "department.result")
        case_count = _count_or_zero(result.get("case_count"), "case_count")
        reader_count = _count_or_zero(result.get("reader_count"), "reader_count")
        reader_total_count = _count_or_zero(result.get("reader_total_count"), "reader_total_count") if result.get("reader_total_count") is not None else reader_count
        errors = _result_string_list(result.get("errors"), "department.errors")
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
    _record_registry(
        Path(request.output_path).parent,
        stage="workflow.department",
        status="failed" if errors else "passed",
        inputs={"batch_result": request.batch_result_path},
        outputs={"workflow3": request.output_path},
        metrics={"case_count": case_count, "reader_count": reader_count},
        warnings=errors,
    )
    # ``summary.readers`` reports readers present in the completed batch.  The
    # workflow result separately exposes ``reader_count`` for readers eligible
    # for statistical aggregation, plus ``excluded_reader_count``.
    return {
        "output_path": request.output_path,
        "summary": {
            "cases": case_count,
            "readers": reader_total_count,
            "errors": errors,
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
        result = _result_mapping(result, "merge_batches.result")
        merge_case_count = _count_or_zero(result.get("case_count"), "case_count")
        merge_failed_case_count = _count_or_zero(result.get("failed_case_count"), "failed_case_count")
        merge_per_reader = _result_mapping(result.get("per_reader"), "merge_batches.per_reader")
        validation = _result_mapping(validation, "merge_batches.validation")
        validation_passed = _result_bool(validation.get("passed"), "merge_batches.validation.passed")
        validation_errors = _result_string_list(validation.get("errors"), "merge_batches.validation.errors")
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
    _record_registry(
        request.output_dir,
        stage="workflow.merge-batches",
        status="passed" if validation_passed else "failed",
        inputs={"batch_results": request.batch_result_paths},
        outputs={"workflow2": str(Path(request.output_dir) / "workflow2.json"), "workflow3": str(Path(request.output_dir) / "workflow3.json")},
        metrics={"case_count": merge_case_count, "failed_case_count": merge_failed_case_count, "validation_passed": validation_passed},
        warnings=validation_errors,
    )
    return {
        "output_dir": request.output_dir,
        "summary": {
            "cases": merge_case_count,
            "failed_cases": merge_failed_case_count,
            "readers": len(merge_per_reader),
            "validation_passed": validation_passed,
            "validation_errors": validation_errors,
            "errors": validation_errors,
        },
        "result": result,
        "validation": validation,
    }


@app.post("/workflow/analyze-run")
def analyze_run_endpoint(request: AnalyzeRunRequest) -> dict[str, Any]:
    try:
        result = analyze_run(request.output_dir, request.analysis_dir)
        result = _result_mapping(result, "analyze_run.result")
        analysis_dir = result.get("analysis_dir")
        if not isinstance(analysis_dir, str):
            raise ValueError("analyze_run.analysis_dir must be a string")
        case_count = _count_or_zero(result.get("case_count"), "case_count")
        generated_report_count = _count_or_zero(result.get("generated_report_count"), "generated_report_count")
        quality_gate_failed_count = _count_or_zero(result.get("quality_gate_failed_count"), "quality_gate_failed_count")
        errors = _result_string_list(result.get("errors"), "analyze_run.errors")
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
    _record_registry(
        request.output_dir,
        stage="workflow.analyze-run",
        status="failed" if errors else "passed",
        inputs={"output_dir": request.output_dir},
        outputs={"analysis_dir": analysis_dir},
        metrics={"case_count": case_count, "error_count": len(errors)},
        warnings=errors,
    )
    return {
        "analysis_dir": analysis_dir,
        "summary": {
            "cases": case_count,
            "generated_reports": generated_report_count,
            "quality_failed": quality_gate_failed_count,
            "errors": errors,
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
        result = _result_mapping(result, "validate_run.result")
        passed = _result_bool(result.get("passed"), "validate_run.passed")
        errors = _result_string_list(result.get("errors"), "validate_run.errors")
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
        status="passed" if passed else "failed",
        inputs={"output_dir": request.output_dir, "expected_cases": request.expected_cases},
        outputs={"validation": str(Path(request.output_dir) / "run_summary.json")},
        metrics={"passed": passed, "error_count": len(errors)},
        warnings=errors,
    )
    return {"summary": {"passed": passed, "errors": errors}, "result": result}


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
        result = _result_mapping(result, "preflight.result")
        paths = _result_mapping(result.get("paths"), "preflight.paths")
        sample = _result_mapping(result.get("sample"), "preflight.sample")
        passed = _result_bool(result.get("passed"), "preflight.passed")
        blockers = _result_string_list(result.get("blockers"), "preflight.blockers")
        warnings = _result_string_list(result.get("warnings"), "preflight.warnings")
        case_count = _count_or_zero(sample.get("case_count"), "case_count")
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
        status="passed" if passed else "failed",
        inputs={"sample_root": request.sample_root, "expected_cases": request.limit},
        outputs={"preflight": request.output_path, "route_plan": str(paths.get("route_plan") or "")},
        metrics={"passed": passed, "case_count": case_count, "blocker_count": len(blockers)},
        warnings=blockers,
    )
    return {
        "output_path": request.output_path,
        "summary": {
            "passed": passed,
            "blockers": blockers,
            "warnings": warnings,
            "cases": case_count,
            "errors": blockers,
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
