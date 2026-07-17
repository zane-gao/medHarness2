from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from medharness2.catalog import build_capability_catalog
from medharness2.annotation import (
    build_pilot_annotation_package,
    export_reader_annotation_package,
    import_reader_annotation_package,
    validate_pilot_annotation_package,
    analyze_pilot_annotations,
)
from medharness2.research_prep import evaluate_paper_evidence_gate, freeze_ocr_winner, prepare_research_manifests, run_ocr_research
from medharness2.config import load_config
from medharness2.contracts import export_json_schemas, migrate_run_case_artifacts
from medharness2.dashboard import build_dashboard, build_dashboard_summary
from medharness2.data.sample_data import prepare_sample_dataset
from medharness2.figures import build_figures
from medharness2.generators.registry import ReportGeneratorRegistry
from medharness2.workflows.batch_readers import run_batch_readers
from medharness2.workflows.benchmark_evaluation import evaluate_generation_benchmark
from medharness2.workflows.benchmark_generation import plan_generation_benchmark, run_generation_benchmark
from medharness2.workflows.analyze_run import analyze_run
from medharness2.workflows.department import run_department_comparison
from medharness2.workflows.merge_batches import merge_batch_results
from medharness2.workflows.reevaluate_run import reevaluate_run
from medharness2.workflows.sample_full import plan_sample_full_routes, run_sample_full
from medharness2.workflows.single_case import run_single_case
from medharness2.workflows.education import run_education_suggestions
from medharness2.ocr_benchmark import evaluate_ocr_candidates
from medharness2.workflows.experiments import experiment_registry_metrics, run_experiments
from medharness2.run_registry import record_registry_entry
from medharness2.validation.preflight import run_sample_preflight
from medharness2.validation.live_smoke import run_live_judge_smoke
from medharness2.validation.sample_run import validate_sample_run
from medharness2.utils.io import write_json


def _count_or_zero(value: object, label: str) -> int:
    if value is None:
        return 0
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _result_mapping(value: object, label: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _result_mapping_list(value: object, label: str) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be a list of objects")
    return value


def _result_string_list(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    return value


def _result_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="medharness2", description="medHarness2 MVP CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    schemas = subparsers.add_parser("schemas")
    schemas_sub = schemas.add_subparsers(dest="schemas_command", required=True)
    schemas_export = schemas_sub.add_parser("export")
    schemas_export.add_argument("--output-dir", required=True)
    schemas_migrate = schemas_sub.add_parser("migrate-run")
    schemas_migrate.add_argument("--source-run-dir", required=True)
    schemas_migrate.add_argument("--output-dir", required=True)
    annotation = subparsers.add_parser("annotation")
    annotation_sub = annotation.add_subparsers(dest="annotation_command", required=True)
    annotation_pilot = annotation_sub.add_parser("build-pilot", aliases=["prepare-pilot"])
    annotation_pilot.add_argument("--run-dir", required=True)
    annotation_pilot.add_argument("--output-dir", required=True)
    annotation_pilot.add_argument("--limit", type=int, default=10)
    annotation_validate = annotation_sub.add_parser("validate")
    annotation_validate.add_argument("--package-dir", required=True)
    annotation_export = annotation_sub.add_parser("export-reader")
    annotation_export.add_argument("--package-dir", required=True)
    annotation_export.add_argument("--output-dir", required=True)
    annotation_export.add_argument("--reader", choices=["reader_a", "reader_b"], required=True)
    annotation_import = annotation_sub.add_parser("import-reader")
    annotation_import.add_argument("--package-dir", required=True)
    annotation_import.add_argument("--reader-package-dir", required=True)
    annotation_import.add_argument("--reader", choices=["reader_a", "reader_b"], required=True)
    annotation_analyze = annotation_sub.add_parser("analyze")
    annotation_analyze.add_argument("--package-dir", required=True)
    annotation_analyze.add_argument("--output", required=True)
    research = subparsers.add_parser("research")
    research_sub = research.add_subparsers(dest="research_command", required=True)
    research_prepare = research_sub.add_parser("prepare-manifests")
    research_prepare.add_argument("--pilot-dir", required=True)
    research_prepare.add_argument("--output-dir", required=True)
    research_run_ocr = research_sub.add_parser("run-ocr")
    research_run_ocr.add_argument("--pilot-dir", required=True)
    research_run_ocr.add_argument("--research-dir", required=True)
    research_run_ocr.add_argument("--config")
    research_run_ocr.add_argument("--source-root")
    research_run_ocr.add_argument("--force", action="store_true")
    research_paper_gate = research_sub.add_parser("paper-gate")
    research_paper_gate.add_argument("--research-dir", required=True)
    research_paper_gate.add_argument("--annotation-analysis", required=True)
    research_paper_gate.add_argument("--experiment-results", required=True)
    research_paper_gate.add_argument("--output", required=True)
    research_freeze = research_sub.add_parser("freeze-ocr-winner")
    research_freeze.add_argument("--research-dir", required=True)
    benchmark = subparsers.add_parser("benchmark")
    benchmark_sub = benchmark.add_subparsers(dest="benchmark_command", required=True)
    benchmark_plan = benchmark_sub.add_parser("plan")
    benchmark_plan.add_argument("--manifest", required=True)
    benchmark_plan.add_argument("--output", required=True)
    benchmark_plan.add_argument("--model", action="append", dest="models")
    benchmark_plan.add_argument("--config")
    benchmark_run = benchmark_sub.add_parser("run")
    benchmark_run.add_argument("--manifest", required=True)
    benchmark_run.add_argument("--output-dir", required=True)
    benchmark_run.add_argument("--model", action="append", dest="models")
    benchmark_run.add_argument("--config")
    benchmark_run.add_argument("--exploratory", action="store_true")
    benchmark_evaluate = benchmark_sub.add_parser("evaluate")
    benchmark_evaluate.add_argument("--benchmark-dir", required=True)
    benchmark_evaluate.add_argument("--manifest", required=True)
    benchmark_evaluate.add_argument("--output-dir", required=True)
    benchmark_evaluate.add_argument("--config")
    benchmark_evaluate.add_argument(
        "--no-resume",
        action="store_false",
        dest="resume",
        default=True,
    )
    ocr_benchmark = subparsers.add_parser("ocr-benchmark")
    ocr_benchmark.add_argument("--manifest", required=True)
    ocr_benchmark.add_argument("--output", required=True)
    live_smoke = subparsers.add_parser("live-smoke")
    live_smoke.add_argument("--output", required=True)
    live_smoke.add_argument("--config")
    live_smoke.add_argument("--role", default="general_judge")
    models = subparsers.add_parser("models")
    models_sub = models.add_subparsers(dest="models_command", required=True)
    models_list = models_sub.add_parser("list")
    models_list.add_argument("--modality")
    models_list.add_argument("--body-part")
    models_list.add_argument("--config")
    tools = subparsers.add_parser("tools")
    tools_sub = tools.add_subparsers(dest="tools_command", required=True)
    tools_catalog = tools_sub.add_parser("catalog")
    tools_catalog.add_argument("--output")
    tools_catalog.add_argument("--config")
    experiments = subparsers.add_parser("experiments")
    experiments_sub = experiments.add_subparsers(dest="experiments_command", required=True)
    experiments_run = experiments_sub.add_parser("run")
    experiments_run.add_argument("--run-dir", required=True)
    experiments_run.add_argument("--output-dir", required=True)
    experiments_run.add_argument("--protocol-dir")
    figures = subparsers.add_parser("figures")
    figures_sub = figures.add_subparsers(dest="figures_command", required=True)
    figures_build = figures_sub.add_parser("build")
    figures_build.add_argument("--experiment-dir", required=True)
    figures_build.add_argument("--output-dir", required=True)
    dashboard = subparsers.add_parser("dashboard")
    dashboard_sub = dashboard.add_subparsers(dest="dashboard_command", required=True)
    dashboard_build = dashboard_sub.add_parser("build")
    dashboard_build.add_argument("--run-dir", required=True)
    dashboard_build.add_argument("--output", required=True)
    dashboard_build.add_argument("--config")
    workflow = subparsers.add_parser("workflow")
    workflow_sub = workflow.add_subparsers(dest="workflow", required=True)
    single = workflow_sub.add_parser("single-case")
    single.add_argument("--report", required=True)
    single.add_argument("--image", required=True)
    single.add_argument("--output", required=True)
    single.add_argument("--case-id")
    single.add_argument("--modality")
    single.add_argument("--top-n", type=int)
    single.add_argument("--model", action="append", dest="models")
    single.add_argument("--model-source", action="append", dest="model_sources")
    single.add_argument("--all-compatible-local-models", action="store_true")
    single.add_argument("--config")
    sample = workflow_sub.add_parser("sample-data")
    sample.add_argument("--sample-root", required=True)
    sample.add_argument("--output-dir", required=True)
    sample.add_argument("--limit", type=int)
    sample.add_argument("--skip-ocr", action="store_true")
    sample.add_argument("--require-real-ocr", action="store_true")
    sample.add_argument("--force-ocr", action="store_true")
    sample.add_argument("--config")
    sample_full = workflow_sub.add_parser("sample-full")
    sample_full.add_argument("--sample-root", required=True)
    sample_full.add_argument("--output-dir", required=True)
    sample_full.add_argument("--limit", type=int)
    sample_full.add_argument("--skip-ocr", action="store_true")
    sample_full.add_argument("--require-real-ocr", action="store_true")
    sample_full.add_argument("--force-ocr", action="store_true")
    sample_full.add_argument("--expected-cases", type=int)
    sample_full.add_argument("--model", action="append", dest="models")
    sample_full.add_argument("--model-source", action="append", dest="model_sources")
    sample_full.add_argument("--all-compatible-local-models", action="store_true")
    sample_full.add_argument("--dry-run", action="store_true")
    sample_full.add_argument("--config")
    batch = workflow_sub.add_parser("batch-readers")
    batch.add_argument("--manifest", required=True)
    batch.add_argument("--output", required=True)
    batch.add_argument("--limit", type=int)
    batch.add_argument("--model", action="append", dest="models")
    batch.add_argument("--model-source", action="append", dest="model_sources")
    batch.add_argument("--all-compatible-local-models", action="store_true")
    batch.add_argument("--config")
    department = workflow_sub.add_parser("department")
    department.add_argument("--batch-result", required=True)
    department.add_argument("--output", required=True)
    merge = workflow_sub.add_parser("merge-batches")
    merge.add_argument("--batch-result", action="append", required=True, dest="batch_results")
    merge.add_argument("--output-dir", required=True)
    merge.add_argument("--manifest")
    merge.add_argument("--expected-cases", type=int)
    merge.add_argument("--require-real-ocr", action="store_true")
    analyze = workflow_sub.add_parser("analyze-run")
    analyze.add_argument("--output-dir", required=True)
    analyze.add_argument("--analysis-dir")
    reevaluate = workflow_sub.add_parser("reevaluate-run")
    reevaluate.add_argument("--source-run-dir", required=True)
    reevaluate.add_argument("--output-dir", required=True)
    reevaluate.add_argument("--config")
    validate = workflow_sub.add_parser("validate-run")
    validate.add_argument("--output-dir", required=True)
    validate.add_argument("--expected-cases", type=int)
    validate.add_argument("--require-real-ocr", action="store_true")
    validate.add_argument("--no-require-workflows", action="store_true")
    preflight = workflow_sub.add_parser("preflight")
    preflight.add_argument("--sample-root", required=True)
    preflight.add_argument("--output", required=True)
    preflight.add_argument("--limit", type=int)
    preflight.add_argument("--model", action="append", dest="models")
    preflight.add_argument("--model-source", action="append", dest="model_sources")
    preflight.add_argument("--all-compatible-local-models", action="store_true")
    preflight.add_argument("--require-real-ocr", action="store_true")
    preflight.add_argument("--config")
    education = workflow_sub.add_parser("education")
    education_group = education.add_mutually_exclusive_group(required=True)
    education_group.add_argument("--eval-report")
    education_group.add_argument("--eval-radiologist")
    education.add_argument("--output", required=True)
    education.add_argument("--config")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = ["medharness2", *(argv if argv is not None else sys.argv[1:])]
    if args.command == "schemas" and args.schemas_command == "export":
        result = export_json_schemas(args.output_dir)
        print(f"wrote {len(result['schemas'])} medHarness2 schemas to {args.output_dir}")
        return 0
    if args.command == "schemas" and args.schemas_command == "migrate-run":
        result = migrate_run_case_artifacts(args.source_run_dir, args.output_dir)
        print(f"migrated {result['case_count']} case artifacts; errors={result['error_count']}")
        return 0 if result["error_count"] == 0 else 1
    if args.command == "annotation" and args.annotation_command in {"build-pilot", "prepare-pilot"}:
        try:
            result = build_pilot_annotation_package(args.run_dir, args.output_dir, limit=args.limit)
        except Exception as exc:
            print(f"medHarness2 annotation build-pilot failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {result['case_count']} blinded annotation cases to {args.output_dir}")
        return 0 if result["case_count"] else 1
    if args.command == "annotation" and args.annotation_command == "validate":
        result = validate_pilot_annotation_package(args.package_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] == "complete":
            return 0
        if result["status"] == "blocked":
            return 2
        return 1
    if args.command == "annotation" and args.annotation_command == "export-reader":
        try:
            result = export_reader_annotation_package(args.package_dir, args.output_dir, reader_slot=args.reader)
        except Exception as exc:
            print(f"medHarness2 annotation export-reader failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "annotation" and args.annotation_command == "import-reader":
        try:
            result = import_reader_annotation_package(
                args.package_dir, args.reader_package_dir, reader_slot=args.reader
            )
        except Exception as exc:
            print(f"medHarness2 annotation import-reader failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "annotation" and args.annotation_command == "analyze":
        try:
            result = analyze_pilot_annotations(args.package_dir, args.output)
        except Exception as exc:
            print(f"medHarness2 annotation analyze failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "complete" else 2
    if args.command == "research" and args.research_command == "prepare-manifests":
        try:
            result = prepare_research_manifests(args.pilot_dir, args.output_dir)
        except Exception as exc:
            print(f"medHarness2 research prepare-manifests failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        # Preparing manifests is a successful setup operation even though the
        # generated research gates intentionally start as blocked/pending until
        # real provider or reader evidence is supplied.  Execution commands
        # (for example ``research run-ocr``) retain non-zero exits for blocked
        # evidence; setup must remain composable in automation.
        return 0
    if args.command == "research" and args.research_command == "run-ocr":
        try:
            result = run_ocr_research(
                args.pilot_dir,
                args.research_dir,
                config_path=args.config,
                source_root=args.source_root,
                force=args.force,
            )
        except Exception as exc:
            result = {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": _exception_warning(exc),
            }
            print(f"medHarness2 research run-ocr failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "succeeded" else 2
    if args.command == "research" and args.research_command == "paper-gate":
        try:
            result = evaluate_paper_evidence_gate(
                args.research_dir,
                args.annotation_analysis,
                args.experiment_results,
                args.output,
            )
        except Exception as exc:
            print(f"medHarness2 research paper-gate failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "passed" else 2
    if args.command == "research" and args.research_command == "freeze-ocr-winner":
        try:
            result = freeze_ocr_winner(args.research_dir)
        except Exception as exc:
            print(f"medHarness2 research freeze-ocr-winner failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") == "frozen" else 2
    if args.command == "benchmark" and args.benchmark_command == "plan":
        try:
            cfg = load_config(args.config) if args.config else load_config("config/formal_benchmark.yaml")
            result = plan_generation_benchmark(args.manifest, config=cfg, model_keys=args.models)
        except Exception as exc:
            result = {
                "schema_version": "1.0",
                "artifact_type": "generation_benchmark_plan",
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": _exception_warning(exc),
            }
            write_json(args.output, result)
            print(f"medHarness2 benchmark plan failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        write_json(args.output, result)
        print(f"wrote benchmark plan to {args.output}; status={result['status']}")
        return 0 if result["status"] == "ready" else 1
    if args.command == "ocr-benchmark":
        result = evaluate_ocr_candidates(args.manifest, args.output)
        print(f"wrote OCR benchmark to {args.output}; status={result['status']} evaluated={result['evaluated_count']}")
        return 0 if result["status"] == "succeeded" else 2
    if args.command == "live-smoke":
        try:
            cfg = load_config(args.config) if args.config else load_config("config/dmx_strong.yaml")
            result = run_live_judge_smoke(args.output, config=cfg, role=args.role)
        except Exception as exc:
            result = {
                "schema_version": "1.0",
                "artifact_type": "live_judge_smoke",
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": _exception_warning(exc),
            }
            write_json(args.output, result)
            print(f"medHarness2 live-smoke failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print(f"wrote live judge smoke to {args.output}; status={result['status']}")
        return 0 if result["status"] == "succeeded" else 2
    if args.command == "benchmark" and args.benchmark_command == "run":
        try:
            cfg = load_config(args.config) if args.config else load_config("config/formal_benchmark.yaml")
            result = run_generation_benchmark(
                args.manifest,
                args.output_dir,
                config=cfg,
                model_keys=args.models,
                formal=not args.exploratory,
            )
        except Exception as exc:
            result = {
                "schema_version": "1.0",
                "artifact_type": "generation_benchmark_summary",
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": _exception_warning(exc),
            }
            output_dir = Path(args.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            write_json(output_dir / "benchmark_summary.json", result)
            print(f"medHarness2 benchmark run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(f"wrote benchmark results to {args.output_dir}; status={result['status']}")
        return 0 if result.get("status") == "succeeded" else 1
    if args.command == "benchmark" and args.benchmark_command == "evaluate":
        try:
            cfg = load_config(args.config) if args.config else load_config("config/dmx_strong.yaml")
            result = evaluate_generation_benchmark(
                args.benchmark_dir,
                args.manifest,
                args.output_dir,
                config=cfg,
                resume=args.resume,
                progress_callback=lambda event: print(
                    json.dumps(event, ensure_ascii=False),
                    flush=True,
                ),
            )
        except Exception as exc:
            result = {
                "schema_version": "1.0",
                "artifact_type": "generation_benchmark_evaluation_summary",
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": _exception_warning(exc),
            }
            output_dir = Path(args.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            write_json(output_dir / "benchmark_evaluation_summary.json", result)
            print(f"medHarness2 benchmark evaluate failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(
            f"wrote benchmark evaluation to {args.output_dir}; "
            f"status={result['status']} evaluations={result['evaluation_count']} "
            f"failures={result['failure_count']}"
        )
        return 0 if result["failure_count"] == 0 else 1
    if args.command == "models" and args.models_command == "list":
        try:
            config = load_config(args.config) if args.config else load_config()
            registry = ReportGeneratorRegistry(config)
        except Exception as exc:
            print(f"medHarness2 models list failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        entries = registry.compatible_entries(args.modality, body_part=args.body_part) if args.modality else list(registry.entries.values())
        print("key\tsource\tmodalities\tbody_parts\tready\ttitle")
        for entry in entries:
            print(
                f"{entry.key}\t{entry.source}\t{','.join(entry.supported_modalities)}\t"
                f"{','.join(entry.supported_body_parts)}\t{entry.ready}\t{entry.title}"
            )
        return 0
    if args.command == "tools" and args.tools_command == "catalog":
        try:
            config = load_config(args.config) if args.config else load_config()
            result = build_capability_catalog(config)
        except Exception as exc:
            result = {
                "schema_version": "1.0",
                "artifact_type": "capability_catalog",
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": _exception_warning(exc),
            }
            if args.output:
                write_json(args.output, result)
                _record_registry(
                    Path(args.output).parent,
                    command=command,
                    stage="tools.catalog",
                    status="failed",
                    inputs={"config": args.config or ""},
                    outputs={"catalog": args.output},
                    metrics={"error_count": 1, "exception_type": type(exc).__name__},
                    warnings=[_exception_warning(exc)],
                )
            print(f"medHarness2 tools catalog failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        if args.output:
            write_json(args.output, result)
            _record_registry(
                Path(args.output).parent,
                command=command,
                stage="tools.catalog",
                inputs={"config": args.config or ""},
                outputs={"catalog": args.output},
                metrics={"tool_count": len(result.get("tools") or []), "model_count": len(result.get("models") or [])},
            )
            print(f"wrote medHarness2 capability catalog to {args.output}")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "experiments" and args.experiments_command == "run":
        result = run_experiments(args.run_dir, args.output_dir, protocol_dir=args.protocol_dir)
        metrics = experiment_registry_metrics(result)
        outputs = {
            "results": str(Path(args.output_dir) / "results.json"),
            "results_markdown": str(Path(args.output_dir) / "results.md"),
            "summary_csv": str(Path(args.output_dir) / "experiment_summary.csv"),
            "experiment_protocol": str(Path(args.output_dir) / "experiment_protocol.json"),
            "experiment_protocol_markdown": str(Path(args.output_dir) / "experiment_protocol.md"),
            "experiment_protocol_csv": str(Path(args.output_dir) / "experiment_protocol.csv"),
        }
        _record_registry(
            args.output_dir,
            command=command,
            stage="experiments.run",
            status="failed" if result.get("errors") else "passed",
            inputs={"run_dir": args.run_dir, "protocol_dir": args.protocol_dir or "experiments/protocols"},
            outputs=outputs,
            metrics=metrics,
        )
        _record_registry(
            args.run_dir,
            command=command,
            stage="experiments.run",
            status="failed" if result.get("errors") else "passed",
            inputs={"run_dir": args.run_dir, "protocol_dir": args.protocol_dir or "experiments/protocols"},
            outputs={"experiment_dir": args.output_dir, **outputs},
            metrics=metrics,
        )
        print(f"wrote medHarness2 experiment results to {Path(args.output_dir) / 'results.json'}")
        print(f"experiments={result['experiment_count']}")
        return 1 if result.get("errors") else 0
    if args.command == "figures" and args.figures_command == "build":
        try:
            result = build_figures(args.experiment_dir, args.output_dir)
        except Exception as exc:
            _record_registry(
                args.output_dir,
                command=command,
                stage="figures.build",
                status="failed",
                inputs={"experiment_dir": args.experiment_dir},
                outputs={"figure_dir": args.output_dir},
                metrics={"error_count": 1},
                warnings=[_exception_warning(exc)],
            )
            print(f"medHarness2 figures build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        metrics = {"figure_count": result["figure_count"]}
        outputs = {
            "figure_dir": args.output_dir,
            "figure_manifest": str(Path(args.output_dir) / "figure_manifest.json"),
        }
        _record_registry(
            args.output_dir,
            command=command,
            stage="figures.build",
            inputs={"experiment_dir": args.experiment_dir},
            outputs=outputs,
            metrics=metrics,
        )
        experiment_results = Path(args.experiment_dir) / "results.json"
        if experiment_results.exists():
            try:
                run_dir = json.loads(experiment_results.read_text(encoding="utf-8")).get("run_dir")
            except Exception:
                run_dir = None
            if run_dir:
                _record_registry(
                    run_dir,
                    command=command,
                    stage="figures.build",
                    inputs={"experiment_dir": args.experiment_dir},
                    outputs=outputs,
                    metrics=metrics,
                )
        print(f"wrote medHarness2 figures to {args.output_dir}")
        print(f"figures={result['figure_count']}")
        return 0
    if args.command == "dashboard" and args.dashboard_command == "build":
        try:
            cfg = load_config(args.config)
            summary = build_dashboard_summary(args.run_dir, registry_entry_count_delta=1, config=cfg)
            result = build_dashboard(args.run_dir, args.output, config=cfg)
        except Exception as exc:
            _record_registry(
                args.run_dir,
                command=command,
                stage="dashboard.build",
                status="failed",
                inputs={"run_dir": args.run_dir, "config": args.config or "config/default.yaml"},
                outputs={"dashboard": args.output},
                metrics={"error_count": 1, "exception_type": type(exc).__name__},
                warnings=[_exception_warning(exc)],
            )
            print(f"medHarness2 dashboard build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        _record_registry(
            args.run_dir,
            command=command,
            stage="dashboard.build",
            inputs={"run_dir": args.run_dir, "config": args.config or "config/default.yaml"},
            outputs={"dashboard": args.output},
            metrics=summary,
        )
        print(f"wrote medHarness2 dashboard to {args.output}")
        print(
            "cases="
            f"{result['summary']['case_count']} "
            f"tools={result['summary']['tool_count']} "
            f"experiments={result['summary']['experiment_count']}"
        )
        return 0
    if args.command == "workflow" and args.workflow == "single-case":
        try:
            config = load_config(args.config) if args.config else load_config()
            result = run_single_case(
                report_path=Path(args.report),
                image_path=Path(args.image),
                output_path=Path(args.output),
                case_id=args.case_id,
                modality=args.modality,
                top_n=args.top_n,
                model_keys=_model_keys(args),
                model_sources=args.model_sources,
                config=config,
            )
        except Exception as exc:
            _record_registry(
                Path(args.output).parent,
                command=command,
                stage="workflow.single-case",
                status="failed",
                inputs={
                    "report": args.report,
                    "image": args.image,
                    "modality": args.modality or "",
                    "case_id": args.case_id or "",
                    "config": args.config or "",
                },
                outputs={"result": args.output},
                metrics={"error_count": 1, "exception_type": type(exc).__name__},
                warnings=[_exception_warning(exc)],
            )
            print(f"medHarness2 single-case failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        try:
            result = _result_mapping(result, "single_case.result")
            generated_reports = _result_mapping_list(result.get("generated_reports"), "single_case.generated_reports")
            rankings = _result_mapping_list(result.get("rankings"), "single_case.rankings")
            pairwise_comparisons = _result_mapping_list(
                result.get("pairwise_comparisons"), "single_case.pairwise_comparisons"
            )
            errors = _result_string_list(result.get("errors"), "single_case.errors")
        except Exception as exc:
            _record_registry(
                Path(args.output).parent,
                command=command,
                stage="workflow.single-case",
                status="failed",
                inputs={"report": args.report, "image": args.image},
                outputs={"result": args.output},
                metrics={"error_count": 1, "exception_type": type(exc).__name__},
                warnings=[_exception_warning(exc)],
            )
            print(f"medHarness2 single-case failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        _record_registry(
            Path(args.output).parent,
            command=command,
            stage="workflow.single-case",
            status="failed" if errors else "passed",
            inputs={
                "report": args.report,
                "image": args.image,
                "modality": args.modality or "",
                "case_id": args.case_id or "",
                "top_n": args.top_n,
                "models": _model_keys(args) or [],
                "model_sources": args.model_sources or [],
                "config": args.config or "",
            },
            outputs={"result": args.output},
            metrics={
                "generated_report_count": len(generated_reports),
                "ranking_count": len(rankings),
                "pairwise_count": len(pairwise_comparisons),
            },
        )
        print(f"wrote medHarness2 single-case output to {args.output}")
        print(f"generated_reports={len(generated_reports)} pairwise={len(pairwise_comparisons)}")
        return 1 if errors else 0
    if args.command == "workflow" and args.workflow == "sample-data":
        try:
            config = load_config(args.config) if args.config else load_config()
            rows = prepare_sample_dataset(
                args.sample_root,
                args.output_dir,
                config=config,
                limit=args.limit,
                run_ocr=not args.skip_ocr,
                require_real_ocr=args.require_real_ocr,
                force_ocr=args.force_ocr,
            )
        except Exception as exc:
            _record_registry(
                args.output_dir, command=command, stage="workflow.sample-data", status="failed",
                inputs={"sample_root": args.sample_root, "config": args.config or ""},
                outputs={"manifest": str(Path(args.output_dir) / "manifest.jsonl")},
                metrics={"error_count": 1, "exception_type": type(exc).__name__},
                warnings=[_exception_warning(exc)],
            )
            print(f"medHarness2 sample-data failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        _record_registry(
            args.output_dir,
            command=command,
            stage="workflow.sample-data",
            status="passed" if rows else "failed",
            inputs={
                "sample_root": args.sample_root,
                "limit": args.limit,
                "skip_ocr": args.skip_ocr,
                "require_real_ocr": args.require_real_ocr,
                "force_ocr": args.force_ocr,
                "config": args.config or "",
            },
            outputs={
                "manifest": str(Path(args.output_dir) / "manifest.jsonl"),
                "raw_manifest": str(Path(args.output_dir) / "manifest.raw.jsonl"),
                "summary": str(Path(args.output_dir) / "summary.json"),
            },
            metrics={
                "case_count": len(rows),
                "warning_count": sum(len(row.warnings) for row in rows),
            },
        )
        print(f"wrote medHarness2 sample manifest to {Path(args.output_dir) / 'manifest.jsonl'}")
        print(f"cases={len(rows)}")
        return 0 if rows else 1
    if args.command == "workflow" and args.workflow == "sample-full":
        try:
            config = load_config(args.config) if args.config else load_config()
            model_keys = _model_keys(args)
            if args.dry_run:
                result = plan_sample_full_routes(
                    args.sample_root, args.output_dir, config=config, limit=args.limit,
                    model_keys=model_keys, model_sources=args.model_sources,
                )
            else:
                result = run_sample_full(
                    args.sample_root, args.output_dir, config=config, limit=args.limit,
                    model_keys=model_keys, model_sources=args.model_sources,
                    run_ocr=not args.skip_ocr, require_real_ocr=args.require_real_ocr,
                    force_ocr=args.force_ocr, expected_cases=args.expected_cases,
                )
        except Exception as exc:
            stage = "workflow.sample-full.dry-run" if args.dry_run else "workflow.sample-full"
            _record_registry(
                args.output_dir, command=command, stage=stage, status="failed",
                inputs={"sample_root": args.sample_root, "config": args.config or ""},
                outputs={"output_dir": args.output_dir},
                metrics={"error_count": 1, "exception_type": type(exc).__name__},
                warnings=[_exception_warning(exc)],
            )
            print(f"medHarness2 sample-full failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        if args.dry_run:
            _record_registry(
                args.output_dir,
                command=command,
                stage="workflow.sample-full.dry-run",
                status="passed" if result["summary"]["case_count"] else "failed",
                inputs={
                    "sample_root": args.sample_root,
                    "limit": args.limit,
                    "models": model_keys or [],
                    "model_sources": args.model_sources or [],
                    "config": args.config or "",
                },
                outputs=result.get("paths") or {"route_plan": str(Path(args.output_dir) / "route_plan.json")},
                metrics=dict(result.get("summary") or {}),
            )
            print(f"wrote medHarness2 sample route plan to {Path(args.output_dir) / 'route_plan.json'}")
            print(
                "cases="
                f"{result['summary']['case_count']} "
                f"local_candidates={result['summary']['cases_with_local_candidates']} "
                f"fallback={result['summary']['cases_requiring_fallback']}"
            )
            return 0 if result["summary"]["case_count"] else 1
        try:
            result = _result_mapping(result, "sample_full.result")
            result_summary = _result_mapping(result.get("summary"), "sample_full.summary")
            result_validation = _result_mapping(result.get("validation"), "sample_full.validation")
            validation_passed = _result_bool(result_validation.get("passed"), "sample_full.validation.passed")
            validation_errors = _result_string_list(result_validation.get("errors"), "sample_full.validation.errors")
            result_paths = _result_mapping(result.get("paths"), "sample_full.paths")
        except Exception as exc:
            _record_registry(
                args.output_dir, command=command, stage="workflow.sample-full", status="failed",
                inputs={"sample_root": args.sample_root, "config": args.config or ""},
                outputs={"output_dir": args.output_dir},
                metrics={"error_count": 1, "exception_type": type(exc).__name__},
                warnings=[_exception_warning(exc)],
            )
            print(f"medHarness2 sample-full failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        _record_registry(
            args.output_dir,
            command=command,
            stage="workflow.sample-full",
            status="passed" if validation_passed else "failed",
            inputs={
                "sample_root": args.sample_root,
                "limit": args.limit,
                "skip_ocr": args.skip_ocr,
                "require_real_ocr": args.require_real_ocr,
                "force_ocr": args.force_ocr,
                "expected_cases": args.expected_cases,
                "models": model_keys or [],
                "model_sources": args.model_sources or [],
                "config": args.config or "",
            },
            outputs=result_paths,
            metrics={
                "case_count": _count_or_zero(result_summary.get("case_count"), "case_count"),
                "workflow2_case_count": _count_or_zero(result_summary.get("workflow2_case_count"), "workflow2_case_count"),
                "workflow2_failed_case_count": _count_or_zero(result_summary.get("workflow2_failed_case_count"), "workflow2_failed_case_count"),
                "workflow3_case_count": _count_or_zero(result_summary.get("workflow3_case_count"), "workflow3_case_count"),
                "reader_count": _count_or_zero(result_summary.get("reader_count"), "reader_count"),
                "validation_passed": validation_passed,
                "validation_error_count": len(validation_errors),
            },
        )
        print(f"wrote medHarness2 sample full-run summary to {Path(args.output_dir) / 'run_summary.json'}")
        print(
            "cases="
            f"{result_summary['case_count']} "
            f"workflow2={result_summary['workflow2_case_count']} "
            f"validation_passed={validation_passed}"
        )
        return 0 if validation_passed else 1
    if args.command == "workflow" and args.workflow == "batch-readers":
        try:
            config = load_config(args.config) if args.config else load_config()
            result = run_batch_readers(
                args.manifest, args.output, model_keys=_model_keys(args),
                model_sources=args.model_sources, limit=args.limit, config=config,
            )
        except Exception as exc:
            _record_registry(
                Path(args.output).parent, command=command, stage="workflow.batch-readers", status="failed",
                inputs={"manifest": args.manifest, "config": args.config or ""},
                outputs={"workflow2": args.output},
                metrics={"error_count": 1, "exception_type": type(exc).__name__},
                warnings=[_exception_warning(exc)],
            )
            print(f"medHarness2 batch-readers failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        failed_case_count = _count_or_zero(result.get("failed_case_count"), "failed_case_count")
        workflow_errors = list(result.get("errors") or [])
        _record_registry(
            Path(args.output).parent,
            command=command,
            stage="workflow.batch-readers",
            status="failed" if failed_case_count or workflow_errors else "passed",
            inputs={
                "manifest": args.manifest,
                "limit": args.limit,
                "models": _model_keys(args) or [],
                "model_sources": args.model_sources or [],
                "config": args.config or "",
            },
            outputs={
                "workflow2": args.output,
                "workflow2_cases": str(Path(args.output).parent / "workflow2_cases"),
            },
            metrics={
                "case_count": _count_or_zero(result.get("case_count"), "case_count"),
                "failed_case_count": failed_case_count,
                "reader_count": len(result.get("per_reader") or {}),
            },
        )
        print(f"wrote medHarness2 batch-readers output to {args.output}")
        print(f"cases={result['case_count']} readers={len(result['per_reader'])}")
        return 1 if failed_case_count or workflow_errors else 0
    if args.command == "workflow" and args.workflow == "department":
        result = run_department_comparison(args.batch_result, args.output)
        workflow_errors = list(result.get("errors") or [])
        _record_registry(
            Path(args.output).parent,
            command=command,
            stage="workflow.department",
            status="failed" if workflow_errors else "passed",
            inputs={"batch_result": args.batch_result},
            outputs={"workflow3": args.output},
            metrics={
                "case_count": _count_or_zero(result.get("case_count"), "case_count"),
                "reader_count": _count_or_zero(result.get("reader_count"), "reader_count"),
                "error_count": len(workflow_errors),
            },
        )
        print(f"wrote medHarness2 department output to {args.output}")
        print(f"cases={result['case_count']} readers={result['reader_count']}")
        return 1 if workflow_errors else 0
    if args.command == "workflow" and args.workflow == "merge-batches":
        try:
            result = merge_batch_results(
                args.batch_results,
                args.output_dir,
                manifest_path=args.manifest,
                expected_cases=args.expected_cases,
            )
        except Exception as exc:
            _record_registry(
                args.output_dir,
                command=command,
                stage="workflow.merge-batches",
                status="failed",
                inputs={
                    "batch_results": args.batch_results,
                    "manifest": args.manifest or "",
                    "expected_cases": args.expected_cases,
                    "require_real_ocr": args.require_real_ocr,
                },
                outputs={"output_dir": args.output_dir},
                metrics={"exception_type": type(exc).__name__},
                warnings=[_exception_warning(exc)],
            )
            print(f"medHarness2 merge-batches failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        try:
            validation = _result_mapping(
                validate_sample_run(
                    args.output_dir,
                    expected_cases=args.expected_cases,
                    require_real_ocr=args.require_real_ocr,
                ),
                "merge_batches.validation",
            )
            validation_passed = _result_bool(validation.get("passed"), "merge_batches.validation.passed")
            validation_errors = _result_string_list(validation.get("errors"), "merge_batches.validation.errors")
        except Exception as exc:
            _record_registry(
                args.output_dir, command=command, stage="workflow.merge-batches", status="failed",
                inputs={"batch_results": args.batch_results, "manifest": args.manifest or ""},
                outputs={"output_dir": args.output_dir},
                metrics={"error_count": 1, "exception_type": type(exc).__name__},
                warnings=[_exception_warning(exc)],
            )
            print(f"medHarness2 merge-batches failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        summary = {
            "paths": {
                "manifest": str(Path(args.output_dir) / "manifest.jsonl") if args.manifest else "",
                "workflow2": str(Path(args.output_dir) / "workflow2.json"),
                "workflow3": str(Path(args.output_dir) / "workflow3.json"),
                "run_summary": str(Path(args.output_dir) / "run_summary.json"),
            },
            "summary": {
                "case_count": result["case_count"],
                "failed_case_count": result["failed_case_count"],
                "reader_count": len(result["per_reader"]),
            },
            "validation": validation,
            "merge_metadata": result.get("merge_metadata") or {},
        }
        write_json(Path(args.output_dir) / "run_summary.json", summary)
        _record_registry(
            args.output_dir,
            command=command,
            stage="workflow.merge-batches",
            status="passed" if validation_passed else "failed",
            inputs={
                "batch_results": args.batch_results,
                "manifest": args.manifest or "",
                "expected_cases": args.expected_cases,
                "require_real_ocr": args.require_real_ocr,
            },
            outputs={**summary["paths"], "run_summary": str(Path(args.output_dir) / "run_summary.json")},
            metrics={
                "case_count": _count_or_zero(result.get("case_count"), "case_count"),
                "failed_case_count": _count_or_zero(result.get("failed_case_count"), "failed_case_count"),
                "reader_count": len(result.get("per_reader") or {}),
                "validation_passed": validation_passed,
                "validation_error_count": len(validation_errors),
            },
        )
        print(f"wrote medHarness2 merged batch outputs to {args.output_dir}")
        print(
            "cases="
            f"{result['case_count']} "
            f"failed={result['failed_case_count']} "
            f"validation_passed={validation_passed}"
        )
        return 0 if validation_passed else 1
    if args.command == "workflow" and args.workflow == "analyze-run":
        try:
            result = analyze_run(args.output_dir, args.analysis_dir)
        except Exception as exc:
            _record_registry(
                args.output_dir,
                command=command,
                stage="workflow.analyze-run",
                status="failed",
                inputs={"output_dir": args.output_dir, "analysis_dir": args.analysis_dir or ""},
                outputs={"analysis_dir": args.analysis_dir or str(Path(args.output_dir) / "analysis")},
                metrics={"exception_type": type(exc).__name__},
                warnings=[_exception_warning(exc)],
            )
            print(f"medHarness2 analyze-run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        try:
            result = _result_mapping(result, "analyze_run.result")
            analysis_dir = result.get("analysis_dir")
            if not isinstance(analysis_dir, str):
                raise ValueError("analyze_run.analysis_dir must be a string")
            counts = {
                name: _count_or_zero(result.get(name), name)
                for name in (
                    "case_count",
                    "failed_case_count",
                    "reader_count",
                    "generated_report_count",
                    "ranking_count",
                    "pairwise_count",
                    "quality_gate_failed_count",
                )
            }
            errors = _result_string_list(result.get("errors"), "analyze_run.errors")
            artifacts = _result_mapping(result.get("artifacts"), "analyze_run.artifacts")
        except Exception as exc:
            _record_registry(
                args.output_dir,
                command=command,
                stage="workflow.analyze-run",
                status="failed",
                inputs={"output_dir": args.output_dir, "analysis_dir": args.analysis_dir or ""},
                outputs={"analysis_dir": args.analysis_dir or str(Path(args.output_dir) / "analysis")},
                metrics={"exception_type": type(exc).__name__},
                warnings=[_exception_warning(exc)],
            )
            print(f"medHarness2 analyze-run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        _record_registry(
            args.output_dir,
            command=command,
            stage="workflow.analyze-run",
            status="failed" if errors else "passed",
            inputs={"output_dir": args.output_dir, "analysis_dir": args.analysis_dir or ""},
            outputs={"analysis_dir": analysis_dir, **artifacts},
            metrics={
                **counts,
                "error_count": len(errors),
            },
        )
        print(f"wrote medHarness2 run analysis to {analysis_dir}")
        print(
            "cases="
            f"{counts['case_count']} "
            f"generated_reports={counts['generated_report_count']} "
            f"quality_failed={counts['quality_gate_failed_count']}"
        )
        return 1 if errors else 0
    if args.command == "workflow" and args.workflow == "reevaluate-run":
        try:
            config = load_config(args.config) if args.config else load_config()
            result = reevaluate_run(args.source_run_dir, args.output_dir, config=config)
        except Exception as exc:
            _record_registry(
                args.output_dir,
                command=command,
                stage="workflow.reevaluate-run",
                status="failed",
                inputs={"source_run_dir": args.source_run_dir, "output_dir": args.output_dir, "config": args.config or ""},
                outputs={
                    "workflow2": str(Path(args.output_dir) / "workflow2.json"),
                    "workflow3": str(Path(args.output_dir) / "workflow3.json"),
                    "run_summary": str(Path(args.output_dir) / "run_summary.json"),
                },
                metrics={"exception_type": type(exc).__name__},
                warnings=[_exception_warning(exc)],
            )
            print(f"medHarness2 reevaluate-run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        run_summary = dict(result.get("run_summary") or {})
        summary = dict(run_summary.get("summary") or result.get("summary") or {})
        failed_case_count = _count_or_zero(summary.get("failed_case_count"), "failed_case_count")
        workflow_errors = list(summary.get("errors") or [])
        validation = dict(run_summary.get("validation") or {})
        validation_failed = validation.get("passed") is False
        if validation_failed:
            workflow_errors.extend(str(item) for item in validation.get("errors") or [])
        _record_registry(
            args.output_dir,
            command=command,
            stage="workflow.reevaluate-run",
            status="failed" if (failed_case_count or workflow_errors or validation_failed) else "passed",
            inputs={"source_run_dir": args.source_run_dir, "output_dir": args.output_dir, "config": args.config or ""},
            outputs={
                "workflow2": str(Path(args.output_dir) / "workflow2.json"),
                "workflow3": str(Path(args.output_dir) / "workflow3.json"),
                "run_summary": str(Path(args.output_dir) / "run_summary.json"),
                "workflow2_cases": str(Path(args.output_dir) / "workflow2_cases"),
            },
            metrics={
                "case_count": _count_or_zero(summary.get("case_count"), "case_count"),
                "failed_case_count": failed_case_count,
                "reader_count": _count_or_zero(summary.get("reader_count"), "reader_count"),
                "reused_generated_report_count": _count_or_zero(summary.get("reused_generated_report_count"), "reused_generated_report_count"),
                "new_generation_count": _count_or_zero(summary.get("new_generation_count"), "new_generation_count"),
            },
        )
        print(f"wrote medHarness2 reevaluated run to {args.output_dir}")
        print(
            "cases="
            f"{summary.get('case_count', 0)} "
            f"reused_reports={summary.get('reused_generated_report_count', 0)} "
            f"new_generation={summary.get('new_generation_count', 0)}"
        )
        return 1 if (failed_case_count or workflow_errors or validation_failed) else 0
    if args.command == "workflow" and args.workflow == "validate-run":
        try:
            result = validate_sample_run(
                args.output_dir,
                expected_cases=args.expected_cases,
                require_real_ocr=args.require_real_ocr,
                require_workflows=not args.no_require_workflows,
            )
            result = _result_mapping(result, "validate_run.result")
            validation_passed = _result_bool(result.get("passed"), "validate_run.passed")
            validation_errors = _result_string_list(result.get("errors"), "validate_run.errors")
            validation_warnings = _result_string_list(result.get("warnings"), "validate_run.warnings")
        except Exception as exc:
            _record_registry(
                args.output_dir, command=command, stage="workflow.validate-run", status="failed",
                inputs={"output_dir": args.output_dir, "expected_cases": args.expected_cases},
                outputs={}, metrics={"error_count": 1}, warnings=[_exception_warning(exc)],
            )
            print(f"medHarness2 validate-run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        _record_registry(
            args.output_dir,
            command=command,
            stage="workflow.validate-run",
            status="passed" if validation_passed else "failed",
            inputs={
                "output_dir": args.output_dir,
                "expected_cases": args.expected_cases,
                "require_real_ocr": args.require_real_ocr,
                "require_workflows": not args.no_require_workflows,
            },
            outputs={},
            metrics={
                "passed": validation_passed,
                "case_count": _count_or_zero(result.get("case_count"), "case_count"),
                "manifest_count": _count_or_zero(result.get("manifest_count"), "manifest_count"),
                "failed_case_count": _count_or_zero(result.get("failed_case_count"), "failed_case_count"),
                "mock_ocr_count": _count_or_zero(result.get("mock_ocr_count"), "mock_ocr_count"),
                "real_ocr_count": _count_or_zero(result.get("real_ocr_count"), "real_ocr_count"),
                "error_count": len(validation_errors),
                "warning_count": len(validation_warnings),
            },
        )
        print(__import__("json").dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1
    if args.command == "workflow" and args.workflow == "preflight":
        try:
            config = load_config(args.config) if args.config else load_config()
            result = run_sample_preflight(
                args.sample_root,
                args.output,
                config=config,
                require_real_ocr=args.require_real_ocr,
                limit=args.limit,
                model_keys=_model_keys(args),
                model_sources=args.model_sources,
            )
        except Exception as exc:
            _record_registry(
                Path(args.output).parent,
                command=command,
                stage="workflow.preflight",
                status="failed",
                inputs={
                    "sample_root": args.sample_root,
                    "limit": args.limit,
                    "require_real_ocr": args.require_real_ocr,
                    "models": _model_keys(args) or [],
                    "model_sources": args.model_sources or [],
                    "config": args.config or "",
                },
                outputs={"preflight": args.output},
                metrics={"exception_type": type(exc).__name__},
                warnings=[_exception_warning(exc)],
            )
            print(f"medHarness2 preflight failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        try:
            result = _result_mapping(result, "preflight.result")
            passed = _result_bool(result.get("passed"), "preflight.passed")
            sample = _result_mapping(result.get("sample"), "preflight.sample")
            paths = _result_mapping(result.get("paths"), "preflight.paths")
            blockers = _result_string_list(result.get("blockers"), "preflight.blockers")
            warnings = _result_string_list(result.get("warnings"), "preflight.warnings")
            routing = _result_mapping(result.get("routing"), "preflight.routing")
        except Exception as exc:
            _record_registry(
                Path(args.output).parent,
                command=command,
                stage="workflow.preflight",
                status="failed",
                inputs={"sample_root": args.sample_root, "limit": args.limit},
                outputs={"preflight": args.output},
                metrics={"error_count": 1},
                warnings=[_exception_warning(exc)],
            )
            print(f"medHarness2 preflight failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        _record_registry(
            Path(args.output).parent,
            command=command,
            stage="workflow.preflight",
            status="passed" if passed else "failed",
            inputs={
                "sample_root": args.sample_root,
                "limit": args.limit,
                "require_real_ocr": args.require_real_ocr,
                "models": _model_keys(args) or [],
                "model_sources": args.model_sources or [],
                "config": args.config or "",
            },
            outputs={
                "preflight": args.output,
                    "route_plan": str(paths.get("route_plan") or ""),
            },
            metrics={
                "passed": passed,
                    "case_count": _count_or_zero(sample.get("case_count"), "case_count"),
                    "blocker_count": len(blockers),
                    "warning_count": len(warnings),
                    "fallback_count": _count_or_zero(routing.get("cases_requiring_fallback"), "cases_requiring_fallback"),
            },
        )
        print(f"wrote medHarness2 preflight output to {args.output}")
        print(
            "passed="
            f"{result['passed']} "
                f"cases={sample['case_count']} "
                f"blockers={','.join(blockers) if blockers else '-'}"
        )
        return 0 if result["passed"] else 1
    if args.command == "workflow" and args.workflow == "education":
        try:
            config = load_config(args.config) if args.config else load_config()
            result = run_education_suggestions(
                eval_report=args.eval_report,
                eval_radiologist=args.eval_radiologist,
                output_path=args.output,
                config=config,
            )
        except Exception as exc:
            _record_registry(
                Path(args.output).parent,
                command=command,
                stage="workflow.education",
                status="failed",
                inputs={"eval_report": args.eval_report or "", "eval_radiologist": args.eval_radiologist or "", "config": args.config or ""},
                outputs={"education": args.output},
                metrics={"error_count": 1, "exception_type": type(exc).__name__},
                warnings=[_exception_warning(exc)],
            )
            print(f"medHarness2 education failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        _record_registry(
            Path(args.output).parent,
            command=command,
            stage="workflow.education",
            status="failed" if result.get("status") in {"blocked", "blocked_insufficient_data"} else "passed",
            inputs={"eval_report": args.eval_report or "", "eval_radiologist": args.eval_radiologist or ""},
            outputs={"education": args.output},
            metrics={
                "suggestion_count": len(result.get("suggestions") or []),
                "general_suggestion_count": len(result.get("general_suggestions") or []),
                "status": result.get("status", ""),
            },
        )
        print(f"wrote medHarness2 education suggestions to {args.output}")
        print(f"mode={result['mode']} suggestions={len(result.get('suggestions') or [])}")
        return 0 if result.get("status") not in {"blocked", "blocked_insufficient_data"} else 1
    parser.error("unsupported command")
    return 2


def _model_keys(args: argparse.Namespace) -> list[str] | None:
    if getattr(args, "all_compatible_local_models", False):
        return ["*"]
    return getattr(args, "models", None)


def _record_registry(
    registry_dir: str | Path,
    *,
    command: list[str],
    stage: str,
    status: str = "passed",
    inputs: dict,
    outputs: dict,
    metrics: dict,
    warnings: list[str] | None = None,
) -> None:
    record_registry_entry(
        registry_dir,
        command=command,
        stage=stage,
        status=status,
        inputs=inputs,
        outputs=outputs,
        metrics=metrics,
        warnings=warnings,
    )


def _exception_warning(exc: Exception) -> str:
    message = f"{type(exc).__name__}: {exc}"
    return message[:1000]


if __name__ == "__main__":
    raise SystemExit(main())
