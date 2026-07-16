from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from medharness2.config import PROJECT_ROOT
from medharness2.contracts import infer_evidence_tier
from medharness2.utils.io import read_json, write_json


def analyze_run(output_dir: str | Path, analysis_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(output_dir)
    out = Path(analysis_dir) if analysis_dir else root / "analysis"
    out.mkdir(parents=True, exist_ok=True)
    workflow2 = read_json(root / "workflow2.json")
    workflow3 = read_json(root / "workflow3.json")

    case_rows: list[dict[str, Any]] = []
    model_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    modality_rows: dict[tuple[str, str], dict[str, Any]] = {}
    quality_failures: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    evidence_tier_counts: Counter[str] = Counter()
    model_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()
    generated_report_count = 0
    ranking_count = 0
    pairwise_count = 0
    quality_passed = 0
    quality_failed = 0

    for case in workflow2.get("cases") or []:
        case_id = str(case.get("case_id") or "")
        reader = str(case.get("reader") or "unknown")
        modality = str(case.get("modality") or "unknown")
        body_part = str(case.get("body_part") or "unknown")
        workflow1 = _read_workflow1(root, str(case.get("workflow1_output") or ""))
        legacy_reference_assisted = str(workflow1.get("schema_version") or "") != "2.0"
        reports = list(workflow1.get("generated_reports") or [])
        rankings = list(workflow1.get("rankings") or [])
        pairwise = list(workflow1.get("pairwise_comparisons") or [])
        ranking_count += len(rankings)
        pairwise_count += len(pairwise)
        generated_report_count += len(reports)

        models: list[str] = []
        sources: list[str] = []
        evidence_tiers: list[str] = []
        case_warnings: Counter[str] = Counter()
        case_quality_passed = 0
        case_quality_failed = 0
        selected_models = [str(item.get("model") or "") for item in rankings if item.get("selected_top_n")]

        modality_key = (modality, body_part)
        modality_row = modality_rows.setdefault(
            modality_key,
            {
                "modality": modality,
                "body_part": body_part,
                "case_count": 0,
                "generated_report_count": 0,
                "ranking_count": 0,
                "pairwise_count": 0,
                "quality_passed": 0,
                "quality_failed": 0,
                "models": Counter(),
                "sources": Counter(),
                "evidence_tiers": Counter(),
            },
        )
        modality_row["case_count"] += 1
        modality_row["generated_report_count"] += len(reports)
        modality_row["ranking_count"] += len(rankings)
        modality_row["pairwise_count"] += len(pairwise)

        selected_counter = Counter(selected_models)
        for report in reports:
            model = str(report.get("model") or "unknown")
            source = str(report.get("source") or "unknown")
            evidence_tier = str(
                report.get("evidence_tier")
                or (
                    "debug_fallback"
                    if legacy_reference_assisted and source == "medharness_cli"
                    else infer_evidence_tier(source, report.get("metadata") or {})
                )
            )
            warnings = [str(warning) for warning in report.get("warnings") or []]
            quality_gate = (report.get("metadata") or {}).get("quality_gate") or {}
            quality_status = "unknown"
            if quality_gate:
                if quality_gate.get("passed"):
                    quality_passed += 1
                    case_quality_passed += 1
                    modality_row["quality_passed"] += 1
                    quality_status = "passed"
                else:
                    quality_failed += 1
                    case_quality_failed += 1
                    modality_row["quality_failed"] += 1
                    quality_status = "failed"
                    quality_failures.append(
                        {
                            "case_id": case_id,
                            "reader": reader,
                            "modality": modality,
                            "body_part": body_part,
                            "model": model,
                            "source": source,
                            "evidence_tier": evidence_tier,
                            "warnings": ";".join(warnings),
                            "conflicts": json.dumps(quality_gate.get("conflicts") or {}, ensure_ascii=False, sort_keys=True),
                            "source_batch_result": str(case.get("source_batch_result") or ""),
                        }
                    )
            models.append(model)
            sources.append(source)
            evidence_tiers.append(evidence_tier)
            model_counts[model] += 1
            source_counts[source] += 1
            evidence_tier_counts[evidence_tier] += 1
            modality_row["models"][model] += 1
            modality_row["sources"][source] += 1
            modality_row["evidence_tiers"][evidence_tier] += 1
            for warning in warnings:
                warning_counts[warning] += 1
                case_warnings[warning] += 1
            summary_key = (model, source, evidence_tier)
            summary = model_rows.setdefault(
                summary_key,
                {
                    "model": model,
                    "source": source,
                    "evidence_tier": evidence_tier,
                    "report_count": 0,
                    "quality_passed": 0,
                    "quality_failed": 0,
                    "quality_unknown": 0,
                    "selected_top_n_count": 0,
                    "warnings": Counter(),
                },
            )
            summary["report_count"] += 1
            summary["selected_top_n_count"] += selected_counter.get(model, 0)
            if quality_status == "passed":
                summary["quality_passed"] += 1
            elif quality_status == "failed":
                summary["quality_failed"] += 1
            else:
                summary["quality_unknown"] += 1
            for warning in warnings:
                summary["warnings"][warning] += 1

        case_rows.append(
            {
                "case_id": case_id,
                "reader": reader,
                "modality": modality,
                "body_part": body_part,
                "generated_report_count": len(reports),
                "ranking_count": len(rankings),
                "pairwise_count": len(pairwise),
                "models": ";".join(dict.fromkeys(models)),
                "sources": ";".join(dict.fromkeys(sources)),
                "evidence_tiers": ";".join(dict.fromkeys(evidence_tiers)),
                "selected_top_n_models": ";".join(dict.fromkeys(selected_models)),
                "quality_passed": case_quality_passed,
                "quality_failed": case_quality_failed,
                "warnings": _format_counter(case_warnings),
                "source_batch_result": str(case.get("source_batch_result") or ""),
            }
        )

    model_summary_rows = [
        {
            "model": row["model"],
            "source": row["source"],
            "evidence_tier": row["evidence_tier"],
            "report_count": row["report_count"],
            "quality_passed": row["quality_passed"],
            "quality_failed": row["quality_failed"],
            "quality_unknown": row["quality_unknown"],
            "selected_top_n_count": row["selected_top_n_count"],
            "warnings": _format_counter(row["warnings"]),
        }
        for row in sorted(model_rows.values(), key=lambda item: (str(item["source"]), str(item["model"])))
    ]
    modality_summary_rows = [
        {
            "modality": row["modality"],
            "body_part": row["body_part"],
            "case_count": row["case_count"],
            "generated_report_count": row["generated_report_count"],
            "ranking_count": row["ranking_count"],
            "pairwise_count": row["pairwise_count"],
            "quality_passed": row["quality_passed"],
            "quality_failed": row["quality_failed"],
            "models": _format_counter(row["models"]),
            "sources": _format_counter(row["sources"]),
            "evidence_tiers": _format_counter(row["evidence_tiers"]),
        }
        for row in sorted(modality_rows.values(), key=lambda item: (str(item["modality"]), str(item["body_part"])))
    ]
    reader_summary_rows = _reader_rows(workflow2, workflow3)
    source_case_count = int(
        workflow2.get("denominator", {}).get("manifest_case_count")
        or workflow2.get("denominator", {}).get("source_case_count")
        or workflow2.get("case_count", 0)
        or 0
    )
    successful_case_count = int(workflow2.get("case_count", 0) or len(case_rows))
    failed_case_count = int(workflow2.get("failed_case_count", 0) or 0)
    result = {
        "output_dir": str(root),
        "analysis_dir": str(out),
        "case_count": int(workflow2.get("case_count", 0) or len(case_rows)),
        "failed_case_count": failed_case_count,
        "source_case_count": source_case_count,
        "successful_case_count": successful_case_count,
        "success_rate": round(successful_case_count / max(source_case_count, 1), 4),
        "failure_rate": round(failed_case_count / max(source_case_count, 1), 4),
        "reader_count": int(workflow3.get("reader_count", 0) or len(reader_summary_rows)),
        "generated_report_count": generated_report_count,
        "ranking_count": ranking_count,
        "pairwise_count": pairwise_count,
        "quality_gate_passed_count": quality_passed,
        "quality_gate_failed_count": quality_failed,
        "generated_report_model_counts": dict(sorted(model_counts.items())),
        "generated_report_source_counts": dict(sorted(source_counts.items())),
        "generated_report_evidence_tier_counts": dict(sorted(evidence_tier_counts.items())),
        "generated_report_warning_counts": dict(sorted(warning_counts.items())),
        "artifacts": {
            "case_routes_csv": str(out / "case_routes.csv"),
            "model_source_summary_csv": str(out / "model_source_summary.csv"),
            "reader_summary_csv": str(out / "reader_summary.csv"),
            "modality_body_part_summary_csv": str(out / "modality_body_part_summary.csv"),
            "quality_gate_failures_csv": str(out / "quality_gate_failures.csv"),
            "analysis_summary_json": str(out / "analysis_summary.json"),
            "analysis_summary_md": str(out / "analysis_summary.md"),
        },
    }
    _write_csv(out / "case_routes.csv", case_rows)
    _write_csv(out / "model_source_summary.csv", model_summary_rows)
    _write_csv(out / "reader_summary.csv", reader_summary_rows)
    _write_csv(out / "modality_body_part_summary.csv", modality_summary_rows)
    _write_csv(out / "quality_gate_failures.csv", quality_failures)
    write_json(out / "analysis_summary.json", result)
    (out / "analysis_summary.md").write_text(_render_markdown(result, model_summary_rows, modality_summary_rows), encoding="utf-8")
    return result


def _read_workflow1(root: Path, value: str) -> dict[str, Any]:
    path = Path(value)
    candidates = [path] if path.is_absolute() else [path, root / path, PROJECT_ROOT / path]
    for candidate in candidates:
        if candidate.exists():
            return read_json(candidate)
    return {}


def _reader_rows(workflow2: dict[str, Any], workflow3: dict[str, Any]) -> list[dict[str, Any]]:
    percentiles = dict(workflow3.get("reader_percentiles") or {})
    rows: list[dict[str, Any]] = []
    for reader, payload in sorted((workflow2.get("per_reader") or {}).items()):
        percentile = dict(percentiles.get(reader) or {})
        rows.append(
            {
                "reader": reader,
                "case_count": payload.get("case_count", percentile.get("case_count", 0)),
                "overall_score": payload.get("overall_score", percentile.get("overall_score", 0.0)),
                "percentile": percentile.get("percentile", ""),
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else ["empty"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _format_counter(counter: Counter[str]) -> str:
    return ";".join(f"{key}:{value}" for key, value in sorted(counter.items()))


def _render_markdown(result: dict[str, Any], model_rows: list[dict[str, Any]], modality_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# medHarness2 Run Analysis",
        "",
        "## Summary",
        "",
        f"- Cases: {result['case_count']}",
        f"- Failed cases: {result['failed_case_count']}",
        f"- Source cases: {result['source_case_count']}",
        f"- Success rate: {result['success_rate']:.4f}",
        f"- Failure rate: {result['failure_rate']:.4f}",
        f"- Readers: {result['reader_count']}",
        f"- Generated reports: {result['generated_report_count']}",
        f"- Rankings: {result['ranking_count']}",
        f"- Pairwise comparisons: {result['pairwise_count']}",
        f"- Quality gate failed: {result['quality_gate_failed_count']}",
        "",
        "## Source Counts",
        "",
    ]
    for source, count in result["generated_report_source_counts"].items():
        lines.append(f"- `{source}`: {count}")
    lines.extend(["", "## Evidence Tier Counts", ""])
    for tier, count in result["generated_report_evidence_tier_counts"].items():
        lines.append(f"- `{tier}`: {count}")
    lines.extend(
        [
            "",
            "## Model Source Summary",
            "",
            "| model | source | evidence tier | reports | quality failed | selected top-n |",
            "| --- | --- | --- | ---: | ---: | ---: |",
        ]
    )
    for row in model_rows:
        lines.append(
            f"| `{row['model']}` | `{row['source']}` | `{row['evidence_tier']}` | {row['report_count']} | "
            f"{row['quality_failed']} | {row['selected_top_n_count']} |"
        )
    lines.extend(["", "## Modality / Body Part Summary", "", "| modality | body_part | cases | reports | quality failed | sources |", "| --- | --- | ---: | ---: | ---: | --- |"])
    for row in modality_rows:
        lines.append(
            f"| `{row['modality']}` | `{row['body_part']}` | {row['case_count']} | "
            f"{row['generated_report_count']} | {row['quality_failed']} | `{row['sources']}` |"
        )
    lines.append("")
    return "\n".join(lines)
