from __future__ import annotations

import json
from pathlib import Path

from medharness2.cli import main
from medharness2.validation.sample_run import validate_sample_run
from medharness2.workflows.merge_batches import merge_batch_results


def test_merge_batch_results_builds_unified_workflow_outputs(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    _write_manifest(manifest, ["case1", "case2"])
    batch1 = _write_batch(tmp_path / "batch1", "case1", "reader_a", "maira_2", "medharness_cli")
    batch2 = _write_batch(tmp_path / "batch2", "case2", "reader_b", "qwen3-vl-4b", "local_vlm_fallback")
    output_dir = tmp_path / "merged"

    result = merge_batch_results([batch1, batch2], output_dir, manifest_path=manifest, expected_cases=2)

    assert result["case_count"] == 2
    assert result["failed_case_count"] == 0
    assert set(result["per_reader"]) == {"reader_a", "reader_b"}
    assert (output_dir / "manifest.jsonl").exists()
    assert (output_dir / "summary.json").exists()
    assert (output_dir / "workflow2.json").exists()
    assert (output_dir / "workflow3.json").exists()
    assert (output_dir / "workflow2_cases" / "case1.json").exists()
    assert result["merge_metadata"]["generated_report_source_counts"] == {"local_vlm_fallback": 1, "medharness_cli": 1}
    validation = validate_sample_run(output_dir, expected_cases=2, require_real_ocr=True)
    assert validation["passed"] is True


def test_merge_batch_results_rejects_missing_manifest_coverage(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    _write_manifest(manifest, ["case1", "case2"])
    batch1 = _write_batch(tmp_path / "batch1", "case1", "reader_a", "maira_2", "medharness_cli")

    try:
        merge_batch_results([batch1], tmp_path / "merged", manifest_path=manifest, expected_cases=2)
    except ValueError as exc:
        assert "missing_cases" in str(exc)
    else:
        raise AssertionError("merge_batch_results should reject incomplete coverage")


def test_cli_merge_batches(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    _write_manifest(manifest, ["case1"])
    batch = _write_batch(tmp_path / "batch", "case1", "reader_a", "maira_2", "medharness_cli")
    output_dir = tmp_path / "merged"

    code = main(
        [
            "workflow",
            "merge-batches",
            "--manifest",
            str(manifest),
            "--batch-result",
            str(batch),
            "--output-dir",
            str(output_dir),
            "--expected-cases",
            "1",
            "--require-real-ocr",
        ]
    )

    assert code == 0
    run_summary = json.loads((output_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert run_summary["validation"]["passed"] is True


def _write_manifest(path: Path, case_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, case_id in enumerate(case_ids):
        report_text = path.parent / "ocr" / f"{case_id}.txt"
        report_text.parent.mkdir(parents=True, exist_ok=True)
        report_text.write_text("FINDINGS: Test report. IMPRESSION: Test.", encoding="utf-8")
        _write_json(report_text.with_suffix(".ocr.json"), {"case_id": case_id, "method": "vlm_ocr", "provider": "local_hf_vlm"})
        rows.append(
            {
                "case_id": case_id,
                "reader": f"reader_{index}",
                "modality": "cxr",
                "body_part": "chest",
                "report_text": str(report_text),
                "image_paths": [str(path.parent / f"{case_id}.png")],
                "derived_assets": {"primary_image": str(path.parent / f"{case_id}.png")},
                "warnings": [],
            }
        )
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _write_batch(root: Path, case_id: str, reader: str, model: str, source: str) -> Path:
    workflow1 = root / "workflow2_cases" / f"{case_id}.json"
    _write_json(
        workflow1,
        {
            "generated_reports": [{"model": model, "source": source, "warnings": [], "metadata": {"quality_gate": {"passed": True}}}],
            "rankings": [{"model": model, "score": 0.8, "selected_top_n": True}],
            "pairwise_comparisons": [{"model": model, "alignment": {"metrics": {"f1": 1.0}}}],
        },
    )
    batch = root / "workflow2.json"
    _write_json(
        batch,
        {
            "manifest_path": str(root / "manifest.jsonl"),
            "case_count": 1,
            "failed_case_count": 0,
            "cases": [
                {
                    "case_id": case_id,
                    "reader": reader,
                    "modality": "cxr",
                    "body_part": "chest",
                    "warnings": [],
                    "human_metrics": {"likert_mean": 4.0, "structure_score": 0.5},
                    "modelwise_metrics": {"likert_mean": 4.0, "structure_score": 0.5, "model_count": 1},
                    "workflow1_output": str(workflow1),
                }
            ],
            "failed_cases": [],
            "per_reader": {},
            "statistics": {},
        },
    )
    return batch


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
