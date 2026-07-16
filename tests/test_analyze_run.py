from __future__ import annotations

import csv
import json
from pathlib import Path

from medharness2.cli import main
from medharness2.workflows.analyze_run import analyze_run


def test_analyze_run_writes_csv_and_markdown_outputs(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    analysis_dir = tmp_path / "analysis"

    result = analyze_run(run_dir, analysis_dir)

    assert result["case_count"] == 2
    assert result["source_case_count"] == 2
    assert result["successful_case_count"] == 2
    assert result["success_rate"] == 1.0
    assert result["failure_rate"] == 0.0
    assert result["generated_report_count"] == 3
    assert result["quality_gate_failed_count"] == 1
    assert result["generated_report_evidence_tier_counts"] == {
        "artifact": 1,
        "debug_fallback": 2,
    }
    assert (analysis_dir / "case_routes.csv").exists()
    assert (analysis_dir / "model_source_summary.csv").exists()
    assert (analysis_dir / "reader_summary.csv").exists()
    assert (analysis_dir / "modality_body_part_summary.csv").exists()
    assert (analysis_dir / "quality_gate_failures.csv").exists()
    assert (analysis_dir / "analysis_summary.md").exists()
    case_rows = _read_csv(analysis_dir / "case_routes.csv")
    assert case_rows[0]["case_id"] == "case1"
    assert case_rows[0]["models"] == "maira_2"
    model_rows = _read_csv(analysis_dir / "model_source_summary.csv")
    by_model = {(row["model"], row["source"]): row for row in model_rows}
    assert by_model[("dia_llama", "artifact_reuse")]["quality_failed"] == "1"
    assert by_model[("dia_llama", "artifact_reuse")]["evidence_tier"] == "artifact"
    failure_rows = _read_csv(analysis_dir / "quality_gate_failures.csv")
    assert failure_rows[0]["case_id"] == "case2"
    assert "body_part_mismatch" in failure_rows[0]["warnings"]
    markdown = (analysis_dir / "analysis_summary.md").read_text(encoding="utf-8")
    assert "medHarness2 Run Analysis" in markdown
    assert "local_vlm_fallback" in markdown


def test_cli_analyze_run(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    analysis_dir = tmp_path / "analysis"

    code = main(["workflow", "analyze-run", "--output-dir", str(run_dir), "--analysis-dir", str(analysis_dir)])

    assert code == 0
    summary = json.loads((analysis_dir / "analysis_summary.json").read_text(encoding="utf-8"))
    assert summary["case_count"] == 2
    assert summary["generated_report_source_counts"]["local_vlm_fallback"] == 1
    registry = json.loads((run_dir / "run_registry.json").read_text(encoding="utf-8"))
    entry = registry["entries"][-1]
    assert entry["stage"] == "workflow.analyze-run"
    assert entry["outputs"]["analysis_summary_json"] == str(analysis_dir / "analysis_summary.json")
    assert entry["metrics"]["generated_report_count"] == 3


def test_cli_analyze_run_records_failed_registry_on_exception(tmp_path: Path):
    run_dir = tmp_path / "missing_workflow_outputs"
    run_dir.mkdir()

    code = main(["workflow", "analyze-run", "--output-dir", str(run_dir)])

    assert code == 1
    registry = json.loads((run_dir / "run_registry.json").read_text(encoding="utf-8"))
    entry = registry["entries"][-1]
    assert entry["stage"] == "workflow.analyze-run"
    assert entry["status"] == "failed"
    assert entry["metrics"]["exception_type"] == "FileNotFoundError"
    assert "workflow2.json" in entry["warnings"][0]


def _write_run(root: Path) -> Path:
    root.mkdir(parents=True)
    manifest_rows = [
        {"case_id": "case1", "reader": "reader_a", "modality": "cxr", "body_part": "chest", "report_text": "ocr/case1.txt", "warnings": []},
        {"case_id": "case2", "reader": "reader_b", "modality": "ct", "body_part": "head", "report_text": "ocr/case2.txt", "warnings": []},
    ]
    (root / "manifest.jsonl").write_text("\n".join(json.dumps(row) for row in manifest_rows) + "\n", encoding="utf-8")
    _write_json(root / "summary.json", {"case_count": 2, "warning_counts": {}})
    _write_json(
        root / "workflow2.json",
        {
            "case_count": 2,
            "failed_case_count": 0,
            "cases": [
                {
                    "case_id": "case1",
                    "reader": "reader_a",
                    "modality": "cxr",
                    "body_part": "chest",
                    "human_metrics": {"likert_mean": 4.0, "structure_score": 0.6},
                    "modelwise_metrics": {"likert_mean": 4.5, "model_count": 1},
                    "workflow1_output": str(root / "workflow2_cases" / "case1.json"),
                },
                {
                    "case_id": "case2",
                    "reader": "reader_b",
                    "modality": "ct",
                    "body_part": "head",
                    "human_metrics": {"likert_mean": 3.0, "structure_score": 0.5},
                    "modelwise_metrics": {"likert_mean": 2.0, "model_count": 2},
                    "workflow1_output": str(root / "workflow2_cases" / "case2.json"),
                },
            ],
            "failed_cases": [],
            "per_reader": {
                "reader_a": {"case_count": 1, "overall_score": 0.8},
                "reader_b": {"case_count": 1, "overall_score": 0.6},
            },
        },
    )
    _write_json(
        root / "workflow3.json",
        {
            "case_count": 2,
            "reader_count": 2,
            "reader_percentiles": {
                "reader_a": {"overall_score": 0.8, "percentile": 100.0, "case_count": 1},
                "reader_b": {"overall_score": 0.6, "percentile": 50.0, "case_count": 1},
            },
        },
    )
    _write_json(
        root / "workflow2_cases" / "case1.json",
        {
            "generated_reports": [{"model": "maira_2", "source": "medharness_cli", "warnings": [], "metadata": {"quality_gate": {"passed": True}}}],
            "rankings": [{"model": "maira_2", "rank": 1, "score": 0.8, "selected_top_n": True}],
            "pairwise_comparisons": [{"model": "maira_2"}],
        },
    )
    _write_json(
        root / "workflow2_cases" / "case2.json",
        {
            "generated_reports": [
                {"model": "qwen3-vl-4b", "source": "local_vlm_fallback", "warnings": ["local_vlm_fallback_used"], "metadata": {"quality_gate": {"passed": True}}},
                {
                    "model": "dia_llama",
                    "source": "artifact_reuse",
                    "warnings": ["quality_gate_failed", "body_part_mismatch"],
                    "metadata": {"quality_gate": {"passed": False, "warnings": ["body_part_mismatch"], "conflicts": {"body_part": ["lung"]}}},
                },
            ],
            "rankings": [{"model": "qwen3-vl-4b", "rank": 1, "score": 0.7, "selected_top_n": True}],
            "pairwise_comparisons": [{"model": "qwen3-vl-4b"}],
        },
    )
    return root


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
