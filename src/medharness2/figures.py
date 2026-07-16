from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from medharness2.utils.io import read_json, write_json


def build_figures(experiment_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    experiment_root = Path(experiment_dir)
    if not experiment_root.is_dir():
        raise ValueError("experiment_dir_not_found")
    results_path = experiment_root / "results.json"
    if not results_path.is_file():
        raise ValueError("experiment_results_not_found")
    exp = read_json(results_path)
    run_dir = Path(str(exp.get("run_dir") or ""))
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    figures = [
        _write_svg(out / "fig1_system_overview.svg", "System overview", _system_overview_labels(exp)),
        _write_svg(out / "fig2_single_case_evidence_chain.svg", "Single-case evidence chain", _single_case_labels(exp, run_dir)),
        _write_svg(out / "fig3_finding_graph_alignment.svg", "Finding graph alignment", _finding_alignment_labels(exp)),
        _write_svg(out / "fig4_feedback_card.svg", "Feedback card", _feedback_card_labels(exp)),
        _write_svg(out / "fig5_experiment_protocol.svg", "Experiment protocol", _experiment_labels(exp)),
        _write_svg(out / "fig6_main_results.svg", "Main v1 results", _main_result_labels(exp)),
        _write_svg(out / "fig7_case_level_distribution.svg", "Case-level distribution", _case_level_labels(exp, run_dir)),
        _write_svg(out / "fig8_error_hazard.svg", "Error and hazard summary", _hazard_labels(exp)),
        _write_svg(out / "fig9_auxiliary_metrics.svg", "L3 auxiliary metrics proxy", _auxiliary_metric_labels(exp)),
        _write_table(out / "table1_dataset_run_summary", "Dataset and run summary", _table1_rows(exp, run_dir)),
        _write_table(out / "table2_metric_taxonomy", "Metric taxonomy", _table2_rows()),
    ]
    result = {"schema_version": "1.0", "figure_count": len(figures), "figures": figures}
    write_json(out / "figure_manifest.json", result)
    return result


def _write_svg(path: Path, title: str, labels: list[str]) -> dict[str, Any]:
    width = 900
    height = 160 + 54 * max(1, len(labels))
    rows = []
    y = 92
    for idx, label in enumerate(labels, start=1):
        bar_width = min(680, 120 + len(label) * 5)
        rows.append(
            f'<text x="48" y="{y}" font-size="18" font-family="Arial">{idx}. {escape(label)}</text>'
            f'<rect x="48" y="{y + 12}" width="{bar_width}" height="10" fill="#0072B2"/>'
        )
        y += 54
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n'
        '<rect width="100%" height="100%" fill="white"/>\n'
        f'<text x="48" y="48" font-size="28" font-family="Arial" font-weight="700">{escape(title)}</text>\n'
        + "\n".join(rows)
        + "\n</svg>\n"
    )
    path.write_text(svg, encoding="utf-8")
    return {"id": path.stem, "path": str(path), "title": title, "format": "svg"}


def _write_table(path_without_suffix: Path, title: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    csv_path = path_without_suffix.with_suffix(".csv")
    md_path = path_without_suffix.with_suffix(".md")
    fieldnames = list(rows[0].keys()) if rows else ["field", "value"]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    lines = [f"# {title}", "", _markdown_table(fieldnames, rows), ""]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "id": path_without_suffix.name,
        "path": str(csv_path),
        "markdown_path": str(md_path),
        "title": title,
        "format": "csv+markdown",
    }


def _markdown_table(fieldnames: list[str], rows: list[dict[str, Any]]) -> str:
    header = "| " + " | ".join(fieldnames) + " |"
    divider = "| " + " | ".join("---" for _ in fieldnames) + " |"
    body = [
        "| " + " | ".join(_markdown_cell(row.get(field, "")) for field in fieldnames) + " |"
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def _experiment_labels(exp: dict[str, Any]) -> list[str]:
    return [f"{item['id']}: {item['status']}" for item in exp.get("experiments") or []]


def _system_overview_labels(exp: dict[str, Any]) -> list[str]:
    lookup = _experiment_lookup(exp)
    rad = lookup.get("radiologist_evaluation", {}).get("metrics", {})
    models = lookup.get("image_to_text_models", {}).get("metrics", {})
    return [
        "image + reference report + candidate report",
        "finding extraction -> graph alignment -> error taxonomy",
        "L1 quality, L2 clinical facts, L3 auxiliary/report-source signals",
        "review queue + education feedback",
        f"Current v1 run: {rad.get('case_count', 0)} cases, {models.get('generated_report_count', 0)} generated reports",
    ]


def _single_case_labels(exp: dict[str, Any], run_dir: Path) -> list[str]:
    rows = _read_csv(run_dir / "analysis" / "case_routes.csv") if str(run_dir) else []
    example = rows[0] if rows else {}
    case_id = example.get("case_id") or "representative case"
    return [
        f"case: {case_id}",
        "reference report -> human finding graph",
        "candidate report pool -> quality gate -> Top-N selection",
        "pairwise comparison -> alignment errors -> hazard levels",
        "Likert, structure, finding coverage and quality-gate outputs stay traceable to the case artifact",
    ]


def _finding_alignment_labels(exp: dict[str, Any]) -> list[str]:
    lookup = _experiment_lookup(exp)
    finding = lookup.get("finding_extraction", {}).get("metrics", {})
    hazard = lookup.get("hazard_evaluation", {}).get("metrics", {})
    error_counts = hazard.get("error_type_counts") or {}
    return [
        f"reference finding graph: {finding.get('finding_count', 0)} findings in v1 aggregation",
        "candidate graph alignment: matched, omitted, overcalled, location/severity mismatch",
        "anatomy and attribute evidence is represented before scoring",
        f"current error taxonomy counts: {error_counts or 'none'}",
    ]


def _feedback_card_labels(exp: dict[str, Any]) -> list[str]:
    lookup = _experiment_lookup(exp)
    education = lookup.get("educational_study", {}).get("metrics", {})
    models = lookup.get("image_to_text_models", {}).get("metrics", {})
    return [
        "overall score + sub-scores",
        "error type, hazard level, evidence sentence and suggested correction",
        f"review proxy: {models.get('quality_failed_count', 0)} quality-gate failed candidates",
        f"education suggestions available: {education.get('suggestion_count', 0)}",
        "clinician review remains required before using suggestions as validated education intervention",
    ]


def _main_result_labels(exp: dict[str, Any]) -> list[str]:
    lookup = {item["id"]: item for item in exp.get("experiments") or []}
    rad = lookup.get("radiologist_evaluation", {}).get("metrics", {})
    models = lookup.get("image_to_text_models", {}).get("metrics", {})
    modality = lookup.get("modality_recognition", {}).get("metrics", {})
    return [
        f"Cases: {rad.get('case_count', 0)}",
        f"Readers: {rad.get('reader_count', 0)}",
        f"Generated reports: {models.get('generated_report_count', 0)}",
        f"Quality-gate failures: {models.get('quality_failed_count', 0)}",
        f"Real OCR: {modality.get('real_ocr_count', 0)}",
    ]


def _case_level_labels(exp: dict[str, Any], run_dir: Path) -> list[str]:
    rows = _read_csv(run_dir / "analysis" / "case_routes.csv") if str(run_dir) else []
    if rows:
        generated = [_int(row.get("generated_report_count")) for row in rows]
        pairwise = [_int(row.get("pairwise_count")) for row in rows]
        quality_failed = [_int(row.get("quality_failed")) for row in rows]
        return [
            f"Case rows: {len(rows)}",
            f"Generated reports per case: min {min(generated)}, median {_median(generated):.1f}, max {max(generated)}",
            f"Pairwise comparisons per case: min {min(pairwise)}, median {_median(pairwise):.1f}, max {max(pairwise)}",
            f"Needs-review proxy cases: {sum(1 for value in quality_failed if value > 0)}",
            f"Quality-gate failed candidates: {sum(quality_failed)}",
        ]
    lookup = _experiment_lookup(exp)
    models = lookup.get("image_to_text_models", {}).get("metrics", {})
    rad = lookup.get("radiologist_evaluation", {}).get("metrics", {})
    return [
        f"Case rows: {rad.get('case_count', 0)}",
        f"Generated reports: {models.get('generated_report_count', 0)}",
        f"Quality-gate failures: {models.get('quality_failed_count', 0)}",
        "Needs-review proxy: unavailable without analysis/case_routes.csv",
    ]


def _hazard_labels(exp: dict[str, Any]) -> list[str]:
    hazard = next((item for item in exp.get("experiments") or [] if item["id"] == "hazard_evaluation"), {})
    metrics = hazard.get("metrics") or {}
    counts = metrics.get("error_type_counts") or {}
    if not counts:
        return ["No hazard errors found in current run artifacts"]
    return [f"{key}: {value}" for key, value in counts.items()]


def _auxiliary_metric_labels(exp: dict[str, Any]) -> list[str]:
    lookup = _experiment_lookup(exp)
    finding = lookup.get("finding_extraction", {}).get("metrics", {})
    models = lookup.get("image_to_text_models", {}).get("metrics", {})
    modality = lookup.get("modality_recognition", {}).get("metrics", {})
    education = lookup.get("educational_study", {}).get("metrics", {})
    case_count = max(1, _int(finding.get("case_count")))
    generated_count = _int(models.get("generated_report_count"))
    quality_failed = _int(models.get("quality_failed_count"))
    quality_pass_rate = 1.0 - (quality_failed / generated_count) if generated_count else 0.0
    real_ocr_rate = _int(modality.get("real_ocr_count")) / max(1, _int(modality.get("real_ocr_count")) + _int(modality.get("mock_ocr_count")) + _int(modality.get("unknown_ocr_count")))
    return [
        f"Finding density proxy: {_int(finding.get('finding_count')) / case_count:.2f} findings/case",
        f"Generation quality pass-rate proxy: {quality_pass_rate:.2%}",
        f"Real OCR coverage: {real_ocr_rate:.2%}",
        f"Education suggestion availability: {_int(education.get('suggestion_count'))} suggestions",
        "Text similarity proxies: not computed in v1 artifacts",
    ]


def _table1_rows(exp: dict[str, Any], run_dir: Path) -> list[dict[str, Any]]:
    lookup = _experiment_lookup(exp)
    rad = lookup.get("radiologist_evaluation", {}).get("metrics", {})
    models = lookup.get("image_to_text_models", {}).get("metrics", {})
    modality = lookup.get("modality_recognition", {}).get("metrics", {})
    generated_sources = models.get("source_counts") or {}
    return [
        {"field": "run_dir", "value": exp.get("run_dir") or str(run_dir), "source": "results.json", "notes": "Input run used for v1 experiment aggregation."},
        {"field": "case_count", "value": rad.get("case_count", 0), "source": "radiologist_evaluation", "notes": "Validated case count in the current run."},
        {"field": "reader_count", "value": rad.get("reader_count", 0), "source": "radiologist_evaluation", "notes": "Distinct radiologist/reader count."},
        {"field": "generated_report_count", "value": models.get("generated_report_count", 0), "source": "image_to_text_models", "notes": "Candidate reports from local/API/artifact routes."},
        {"field": "candidate_source_counts", "value": generated_sources, "source": "image_to_text_models", "notes": "Model source mix; interpret artifact/fallback routes separately."},
        {"field": "modality_counts", "value": modality.get("modality_counts", {}), "source": "modality_recognition", "notes": "Manifest/run validation modality distribution."},
        {"field": "gold_source", "value": "OCR/reference reports in run artifacts", "source": "run_summary/workflow2", "notes": "V1 engineering run, not final clinical gold-standard validation."},
    ]


def _table2_rows() -> list[dict[str, Any]]:
    return [
        {"level": "L1", "metric_or_object": "Likert report quality", "artifact_field": "human_evaluation.likert", "implementation": "Tool 1", "production_note": "Can use deterministic fallback or configured LLM/VLM judge."},
        {"level": "L1", "metric_or_object": "Report structure", "artifact_field": "human_evaluation.structure", "implementation": "Tool 3", "production_note": "Section parser is lightweight and should be strengthened for Chinese reports."},
        {"level": "L2", "metric_or_object": "Finding graph extraction", "artifact_field": "human_evaluation.finding_graph", "implementation": "Tool 2", "production_note": "CXR rule backend exists; non-CXR routes remain placeholder/proxy."},
        {"level": "L2", "metric_or_object": "Reference-candidate alignment", "artifact_field": "pairwise_comparisons[].comparison.alignment", "implementation": "Tool 5", "production_note": "Structured comparison layer for omissions, overcalls, location and severity errors."},
        {"level": "L2", "metric_or_object": "Error hazard severity", "artifact_field": "pairwise_comparisons[].comparison.hazards", "implementation": "Tool 4", "production_note": "Current v1 is rules-based hazard estimation; medical evaluator upgrade remains required."},
        {"level": "L3", "metric_or_object": "Model source and quality gate", "artifact_field": "analysis/model_source_summary.csv", "implementation": "Tool 8 + generation quality gate", "production_note": "Separates fresh local models, artifact reuse and fallback/debug routes."},
        {"level": "L3", "metric_or_object": "Top-N model selection", "artifact_field": "rankings[]", "implementation": "Tool 9", "production_note": "Uses weighted report metrics and excludes quality-gate failures from formal ranking."},
        {"level": "L3", "metric_or_object": "Reader/model summaries", "artifact_field": "workflow2.json / workflow3.json", "implementation": "Tool 10 / Tool 11 / Tool 12", "production_note": "Supports reader percentiles, modelwise and hazardwise aggregate views."},
        {"level": "Education", "metric_or_object": "Feedback suggestions", "artifact_field": "education/*.json", "implementation": "Workflow 4", "production_note": "Deterministic or LLM JSON suggestions; not yet validated as clinical education effect."},
    ]


def _experiment_lookup(exp: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in exp.get("experiments") or []}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _median(values: list[int]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[midpoint])
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def _markdown_cell(value: Any) -> str:
    return escape(value).replace("|", "\\|")


def escape(value: Any) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
