from __future__ import annotations

import argparse
from pathlib import Path

from medharness2.config import load_config
from medharness2.data.sample_data import prepare_sample_dataset
from medharness2.workflows.batch_readers import run_batch_readers
from medharness2.workflows.department import run_department_comparison
from medharness2.workflows.single_case import run_single_case


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="medharness2", description="medHarness2 MVP CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    workflow = subparsers.add_parser("workflow")
    workflow_sub = workflow.add_subparsers(dest="workflow", required=True)
    single = workflow_sub.add_parser("single-case")
    single.add_argument("--report", required=True)
    single.add_argument("--image", required=True)
    single.add_argument("--output", required=True)
    single.add_argument("--modality")
    single.add_argument("--top-n", type=int)
    single.add_argument("--model", action="append", dest="models")
    single.add_argument("--config")
    sample = workflow_sub.add_parser("sample-data")
    sample.add_argument("--sample-root", required=True)
    sample.add_argument("--output-dir", required=True)
    sample.add_argument("--limit", type=int)
    sample.add_argument("--skip-ocr", action="store_true")
    sample.add_argument("--config")
    batch = workflow_sub.add_parser("batch-readers")
    batch.add_argument("--manifest", required=True)
    batch.add_argument("--output", required=True)
    batch.add_argument("--limit", type=int)
    batch.add_argument("--model", action="append", dest="models")
    batch.add_argument("--config")
    department = workflow_sub.add_parser("department")
    department.add_argument("--batch-result", required=True)
    department.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "workflow" and args.workflow == "single-case":
        config = load_config(args.config) if args.config else load_config()
        result = run_single_case(
            report_path=Path(args.report),
            image_path=Path(args.image),
            output_path=Path(args.output),
            modality=args.modality,
            top_n=args.top_n,
            model_keys=args.models,
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
        )
        print(f"wrote medHarness2 sample manifest to {Path(args.output_dir) / 'manifest.jsonl'}")
        print(f"cases={len(rows)}")
        return 0
    if args.command == "workflow" and args.workflow == "batch-readers":
        config = load_config(args.config) if args.config else load_config()
        result = run_batch_readers(
            args.manifest,
            args.output,
            model_keys=args.models,
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
    parser.error("unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
