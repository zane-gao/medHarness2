from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from medharness2.catalog import build_capability_catalog
from medharness2.annotation import build_pilot_annotation_package, validate_pilot_annotation_package
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
    annotation_pilot = annotation_sub.add_parser("build-pilot")
    annotation_pilot.add_argument("--run-dir", required=True)
    annotation_pilot.add_argument("--output-dir", required=True)
    annotation_pilot.add_argument("--limit", type=int, default=10)
    annotation_validate = annotation_sub.add_parser("validate")
    annotation_validate.add_argument("--package-dir", required=True)
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
    if args.command == "annotation" and args.annotation_command == "build-pilot":
        result = build_pilot_annotation_package(args.run_dir, args.output_dir, limit=args.limit)
        print(f"wrote {result['case_count']} blinded annotation cases to {args.output_dir}")
        return 0
    if args.command == "annotation" and args.annotation_command == "validate":
        result = validate_pilot_annotation_package(args.package_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] == "complete":
            return 0
        if result["status"] == "blocked":
            return 2
        return 1
    if args.command == "benchmark" and args.benchmark_command == "plan":
        cfg = load_config(args.config) if args.config else load_config("config/formal_benchmark.yaml")
        result = plan_generation_benchmark(args.manifest, config=cfg, model_keys=args.models)
        write_json(args.output, result)
        print(f"wrote benchmark plan to {args.output}; status={result['status']}")
        return 0
    if args.command == "ocr-benchmark":
        result = evaluate_ocr_candidates(args.manifest, args.output)
        print(f"wrote OCR benchmark to {args.output}; status={result['status']} evaluated={result['evaluated_count']}")
        return 0 if result["status"] == "succeeded" else 2
    if args.command == "live-smoke":
        cfg = load_config(args.config) if args.config else load_config("config/dmx_strong.yaml")
        result = run_live_judge_smoke(args.output, config=cfg, role=args.role)
        print(f"wrote live judge smoke to {args.output}; status={result['status']}")
        return 0 if result["status"] == "succeeded" else 2
    if args.command == "benchmark" and args.benchmark_command == "run":
        cfg = load_config(args.config) if args.config else load_config("config/formal_benchmark.yaml")
        result = run_generation_benchmark(
            args.manifest,
            args.output_dir,
            config=cfg,
            model_keys=args.models,
            formal=not args.exploratory,
        )
        print(f"wrote benchmark results to {args.output_dir}; status={result['status']}")
        return 0 if result.get("status") == "succeeded" else 1
    if args.command == "benchmark" and args.benchmark_command == "evaluate":
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
        print(
            f"wrote benchmark evaluation to {args.output_dir}; "
            f"status={result['status']} evaluations={result['evaluation_count']} "
            f"failures={result['failure_count']}"
        )
        return 0 if result["failure_count"] == 0 else 1
    if args.command == "models" and args.models_command == "list":
        config = load_config(args.config) if args.config else load_config()
        registry = ReportGeneratorRegistry(config)
        entries = registry.compatible_entries(args.modality, body_part=args.body_part) if args.modality else list(registry.entries.values())
        print("key\tsource\tmodalities\tbody_parts\tready\ttitle")
        for entry in entries:
            print(
                f"{entry.key}\t{entry.source}\t{','.join(entry.supported_modalities)}\t"
                f"{','.join(entry.supported_body_parts)}\t{entry.ready}\t{entry.title}"
            )
        return 0
    if args.command == "tools" and args.tools_command == "catalog":
        config = load_config(args.config) if args.config else load_config()
        result = build_capability_catalog(config)
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
            inputs={"run_dir": args.run_dir, "protocol_dir": args.protocol_dir or "experiments/protocols"},
            outputs=outputs,
            metrics=metrics,
        )
        _record_registry(
            args.run_dir,
            command=command,
            stage="experiments.run",
            inputs={"run_dir": args.run_dir, "protocol_dir": args.protocol_dir or "experiments/protocols"},
            outputs={"experiment_dir": args.output_dir, **outputs},
            metrics=metrics,
        )
        print(f"wrote medHarness2 experiment results to {Path(args.output_dir) / 'results.json'}")
        print(f"experiments={result['experiment_count']}")
        return 0
    if args.command == "figures" and args.figures_command == "build":
        result = build_figures(args.experiment_dir, args.output_dir)
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
        cfg = load_config(args.config)
        summary = build_dashboard_summary(args.run_dir, registry_entry_count_delta=1, config=cfg)
        _record_registry(
            args.run_dir,
            command=command,
            stage="dashboard.build",
            inputs={"run_dir": args.run_dir, "config": args.config or "config/default.yaml"},
            outputs={"dashboard": args.output},
            metrics=summary,
        )
        result = build_dashboard(args.run_dir, args.output, config=cfg)
        print(f"wrote medHarness2 dashboard to {args.output}")
        print(
            "cases="
            f"{result['summary']['case_count']} "
            f"tools={result['summary']['tool_count']} "
            f"experiments={result['summary']['experiment_count']}"
        )
        return 0
    if args.command == "workflow" and args.workflow == "single-case":
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
        _record_registry(
            Path(args.output).parent,
            command=command,
            stage="workflow.single-case",
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
                "generated_report_count": len(result.get("generated_reports") or []),
                "ranking_count": len(result.get("rankings") or []),
                "pairwise_count": len(result.get("pairwise_comparisons") or []),
            },
        )
        print(f"wrote medHarness2 single-case output to {args.output}")
        print(f"generated_reports={len(result['generated_reports'])} pairwise={len(result['pairwise_comparisons'])}")
        return 0
    if args.command == "workflow" and args.workflow == "sample-data":
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
        _record_registry(
            args.output_dir,
            command=command,
            stage="workflow.sample-data",
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
        return 0
    if args.command == "workflow" and args.workflow == "sample-full":
        config = load_config(args.config) if args.config else load_config()
        model_keys = _model_keys(args)
        if args.dry_run:
            result = plan_sample_full_routes(
                args.sample_root,
                args.output_dir,
                config=config,
                limit=args.limit,
                model_keys=model_keys,
                model_sources=args.model_sources,
            )
            _record_registry(
                args.output_dir,
                command=command,
                stage="workflow.sample-full.dry-run",
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
            return 0
        result = run_sample_full(
            args.sample_root,
            args.output_dir,
            config=config,
            limit=args.limit,
            model_keys=model_keys,
            model_sources=args.model_sources,
            run_ocr=not args.skip_ocr,
            require_real_ocr=args.require_real_ocr,
            force_ocr=args.force_ocr,
            expected_cases=args.expected_cases,
        )
        validation_passed = bool(result.get("validation", {}).get("passed"))
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
            outputs=dict(result.get("paths") or {}),
            metrics={
                "case_count": int(result.get("summary", {}).get("case_count", 0) or 0),
                "workflow2_case_count": int(result.get("summary", {}).get("workflow2_case_count", 0) or 0),
                "workflow2_failed_case_count": int(result.get("summary", {}).get("workflow2_failed_case_count", 0) or 0),
                "workflow3_case_count": int(result.get("summary", {}).get("workflow3_case_count", 0) or 0),
                "reader_count": int(result.get("summary", {}).get("reader_count", 0) or 0),
                "validation_passed": validation_passed,
                "validation_error_count": len(result.get("validation", {}).get("errors") or []),
            },
        )
        print(f"wrote medHarness2 sample full-run summary to {Path(args.output_dir) / 'run_summary.json'}")
        print(
            "cases="
            f"{result['summary']['case_count']} "
            f"workflow2={result['summary']['workflow2_case_count']} "
            f"validation_passed={result['validation']['passed']}"
        )
        return 0 if result["validation"]["passed"] else 1
    if args.command == "workflow" and args.workflow == "batch-readers":
        config = load_config(args.config) if args.config else load_config()
        result = run_batch_readers(
            args.manifest,
            args.output,
            model_keys=_model_keys(args),
            model_sources=args.model_sources,
            limit=args.limit,
            config=config,
        )
        failed_case_count = int(result.get("failed_case_count", 0) or 0)
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
                "case_count": int(result.get("case_count", 0) or 0),
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
            inputs={"batch_result": args.batch_result},
            outputs={"workflow3": args.output},
            metrics={
                "case_count": int(result.get("case_count", 0) or 0),
                "reader_count": int(result.get("reader_count", 0) or 0),
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
        validation = validate_sample_run(
            args.output_dir,
            expected_cases=args.expected_cases,
            require_real_ocr=args.require_real_ocr,
        )
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
        validation_passed = bool(validation.get("passed"))
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
                "case_count": int(result.get("case_count", 0) or 0),
                "failed_case_count": int(result.get("failed_case_count", 0) or 0),
                "reader_count": len(result.get("per_reader") or {}),
                "validation_passed": validation_passed,
                "validation_error_count": len(validation.get("errors") or []),
            },
        )
        print(f"wrote medHarness2 merged batch outputs to {args.output_dir}")
        print(
            "cases="
            f"{result['case_count']} "
            f"failed={result['failed_case_count']} "
            f"validation_passed={validation['passed']}"
        )
        return 0 if validation["passed"] else 1
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
        _record_registry(
            args.output_dir,
            command=command,
            stage="workflow.analyze-run",
            inputs={"output_dir": args.output_dir, "analysis_dir": args.analysis_dir or ""},
            outputs={"analysis_dir": result.get("analysis_dir", ""), **dict(result.get("artifacts") or {})},
            metrics={
                "case_count": int(result.get("case_count", 0) or 0),
                "failed_case_count": int(result.get("failed_case_count", 0) or 0),
                "reader_count": int(result.get("reader_count", 0) or 0),
                "generated_report_count": int(result.get("generated_report_count", 0) or 0),
                "ranking_count": int(result.get("ranking_count", 0) or 0),
                "pairwise_count": int(result.get("pairwise_count", 0) or 0),
                "quality_gate_failed_count": int(result.get("quality_gate_failed_count", 0) or 0),
                "error_count": len(result.get("errors") or []),
            },
        )
        print(f"wrote medHarness2 run analysis to {result['analysis_dir']}")
        print(
            "cases="
            f"{result['case_count']} "
            f"generated_reports={result['generated_report_count']} "
            f"quality_failed={result['quality_gate_failed_count']}"
        )
        return 1 if result.get("errors") else 0
    if args.command == "workflow" and args.workflow == "reevaluate-run":
        config = load_config(args.config) if args.config else load_config()
        try:
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
        summary = dict(result.get("summary") or {})
        failed_case_count = int(summary.get("failed_case_count", 0) or 0)
        workflow_errors = list(summary.get("errors") or [])
        _record_registry(
            args.output_dir,
            command=command,
            stage="workflow.reevaluate-run",
            status="failed" if (failed_case_count or workflow_errors) else "passed",
            inputs={"source_run_dir": args.source_run_dir, "output_dir": args.output_dir, "config": args.config or ""},
            outputs={
                "workflow2": str(Path(args.output_dir) / "workflow2.json"),
                "workflow3": str(Path(args.output_dir) / "workflow3.json"),
                "run_summary": str(Path(args.output_dir) / "run_summary.json"),
                "workflow2_cases": str(Path(args.output_dir) / "workflow2_cases"),
            },
            metrics={
                "case_count": int(summary.get("case_count", 0) or 0),
                "failed_case_count": failed_case_count,
                "reader_count": int(summary.get("reader_count", 0) or 0),
                "reused_generated_report_count": int(summary.get("reused_generated_report_count", 0) or 0),
                "new_generation_count": int(summary.get("new_generation_count", 0) or 0),
            },
        )
        print(f"wrote medHarness2 reevaluated run to {args.output_dir}")
        print(
            "cases="
            f"{summary.get('case_count', 0)} "
            f"reused_reports={summary.get('reused_generated_report_count', 0)} "
            f"new_generation={summary.get('new_generation_count', 0)}"
        )
        return 1 if (failed_case_count or workflow_errors) else 0
    if args.command == "workflow" and args.workflow == "validate-run":
        result = validate_sample_run(
            args.output_dir,
            expected_cases=args.expected_cases,
            require_real_ocr=args.require_real_ocr,
            require_workflows=not args.no_require_workflows,
        )
        validation_passed = bool(result.get("passed"))
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
                "case_count": int(result.get("case_count", 0) or 0),
                "manifest_count": int(result.get("manifest_count", 0) or 0),
                "failed_case_count": int(result.get("failed_case_count", 0) or 0),
                "mock_ocr_count": int(result.get("mock_ocr_count", 0) or 0),
                "real_ocr_count": int(result.get("real_ocr_count", 0) or 0),
                "error_count": len(result.get("errors") or []),
                "warning_count": len(result.get("warnings") or []),
            },
        )
        print(__import__("json").dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1
    if args.command == "workflow" and args.workflow == "preflight":
        config = load_config(args.config) if args.config else load_config()
        try:
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
        passed = bool(result.get("passed"))
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
                "route_plan": str(result.get("paths", {}).get("route_plan") or ""),
            },
            metrics={
                "passed": passed,
                "case_count": int(result.get("sample", {}).get("case_count", 0) or 0),
                "blocker_count": len(result.get("blockers") or []),
                "warning_count": len(result.get("warnings") or []),
                "fallback_count": int(result.get("routing", {}).get("cases_requiring_fallback", 0) or 0),
            },
        )
        print(f"wrote medHarness2 preflight output to {args.output}")
        print(
            "passed="
            f"{result['passed']} "
            f"cases={result['sample']['case_count']} "
            f"blockers={','.join(result['blockers']) if result['blockers'] else '-'}"
        )
        return 0 if result["passed"] else 1
    if args.command == "workflow" and args.workflow == "education":
        config = load_config(args.config) if args.config else load_config()
        result = run_education_suggestions(
            eval_report=args.eval_report,
            eval_radiologist=args.eval_radiologist,
            output_path=args.output,
            config=config,
        )
        _record_registry(
            Path(args.output).parent,
            command=command,
            stage="workflow.education",
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
