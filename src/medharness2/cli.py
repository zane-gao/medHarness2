from __future__ import annotations

import argparse
from pathlib import Path

from medharness2.config import load_config
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
    parser.error("unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
