from __future__ import annotations

import argparse
from pathlib import Path

from medharness2.config import load_config
from medharness2.data.sample_data import prepare_sample_dataset
from medharness2.generators.registry import ReportGeneratorRegistry
from medharness2.workflows.batch_readers import run_batch_readers
from medharness2.workflows.department import run_department_comparison
from medharness2.workflows.sample_full import plan_sample_full_routes, run_sample_full
from medharness2.workflows.single_case import run_single_case
from medharness2.validation.sample_run import validate_sample_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="medharness2", description="medHarness2 MVP CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    models = subparsers.add_parser("models")
    models_sub = models.add_subparsers(dest="models_command", required=True)
    models_list = models_sub.add_parser("list")
    models_list.add_argument("--modality")
    models_list.add_argument("--body-part")
    models_list.add_argument("--config")
    workflow = subparsers.add_parser("workflow")
    workflow_sub = workflow.add_subparsers(dest="workflow", required=True)
    single = workflow_sub.add_parser("single-case")
    single.add_argument("--report", required=True)
    single.add_argument("--image", required=True)
    single.add_argument("--output", required=True)
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
    validate = workflow_sub.add_parser("validate-run")
    validate.add_argument("--output-dir", required=True)
    validate.add_argument("--expected-cases", type=int)
    validate.add_argument("--require-real-ocr", action="store_true")
    validate.add_argument("--no-require-workflows", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
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
    if args.command == "workflow" and args.workflow == "single-case":
        config = load_config(args.config) if args.config else load_config()
        result = run_single_case(
            report_path=Path(args.report),
            image_path=Path(args.image),
            output_path=Path(args.output),
            modality=args.modality,
            top_n=args.top_n,
            model_keys=_model_keys(args),
            model_sources=args.model_sources,
            config=config,
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
        print(f"wrote medHarness2 batch-readers output to {args.output}")
        print(f"cases={result['case_count']} readers={len(result['per_reader'])}")
        return 0
    if args.command == "workflow" and args.workflow == "department":
        result = run_department_comparison(args.batch_result, args.output)
        print(f"wrote medHarness2 department output to {args.output}")
        print(f"cases={result['case_count']} readers={result['reader_count']}")
        return 0
    if args.command == "workflow" and args.workflow == "validate-run":
        result = validate_sample_run(
            args.output_dir,
            expected_cases=args.expected_cases,
            require_real_ocr=args.require_real_ocr,
            require_workflows=not args.no_require_workflows,
        )
        print(__import__("json").dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1
    parser.error("unsupported command")
    return 2


def _model_keys(args: argparse.Namespace) -> list[str] | None:
    if getattr(args, "all_compatible_local_models", False):
        return ["*"]
    return getattr(args, "models", None)


if __name__ == "__main__":
    raise SystemExit(main())
