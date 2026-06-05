from __future__ import annotations

import json
from pathlib import Path

from medharness2.validation.sample_run import validate_sample_run


def test_validate_sample_run_passes_complete_mock_run(tmp_path: Path):
    _write_run(tmp_path, warning_counts={"mock_ocr_used": 2}, failed_case_count=0)
    result = validate_sample_run(tmp_path, expected_cases=2)
    assert result["passed"] is True
    assert result["case_count"] == 2
    assert result["mock_ocr_count"] == 2


def test_validate_sample_run_fails_when_real_ocr_required_but_mock_used(tmp_path: Path):
    _write_run(tmp_path, warning_counts={"mock_ocr_used": 1}, failed_case_count=0)
    result = validate_sample_run(tmp_path, expected_cases=2, require_real_ocr=True)
    assert result["passed"] is False
    assert "mock_ocr_used" in result["errors"]


def test_validate_sample_run_fails_when_real_ocr_provenance_is_unknown(tmp_path: Path):
    _write_run(tmp_path, warning_counts={}, failed_case_count=0)
    result = validate_sample_run(tmp_path, expected_cases=2, require_real_ocr=True)
    assert result["passed"] is False
    assert "ocr_provenance_unknown" in result["errors"]


def test_validate_sample_run_accepts_real_ocr_metadata(tmp_path: Path):
    _write_run(tmp_path, warning_counts={}, failed_case_count=0, ocr_provider="openai")
    result = validate_sample_run(tmp_path, expected_cases=2, require_real_ocr=True)
    assert result["passed"] is True
    assert result["real_ocr_count"] == 2


def test_validate_sample_run_reports_missing_workflow_outputs(tmp_path: Path):
    _write_json(tmp_path / "summary.json", {"case_count": 1, "warning_counts": {}})
    _write_manifest(tmp_path / "manifest.jsonl", 1)
    result = validate_sample_run(tmp_path, expected_cases=1)
    assert result["passed"] is False
    assert "missing_workflow2_json" in result["errors"]
    assert "missing_workflow3_json" in result["errors"]


def test_validate_sample_run_accepts_subset_workflow_without_summary(tmp_path: Path):
    _write_manifest(tmp_path / "manifest.jsonl", 2, with_report_text=True)
    for i in range(2):
        _write_json(tmp_path / "ocr" / f"case{i}.ocr.json", {"case_id": f"case{i}", "method": "vlm_ocr", "provider": "local_hf_vlm"})
    _write_json(tmp_path / "workflow2.json", {"case_count": 2, "failed_case_count": 0, "per_reader": {"r": {}}})
    _write_json(tmp_path / "workflow3.json", {"case_count": 2, "reader_count": 1, "reader_percentiles": {"r": {}}})

    result = validate_sample_run(tmp_path, expected_cases=2, require_real_ocr=True)

    assert result["passed"] is True
    assert "missing_summary_json" not in result["errors"]
    assert "missing_summary_json" in result["warnings"]
    assert result["summary"]["case_count"] == 2


def _write_run(path: Path, *, warning_counts: dict[str, int], failed_case_count: int, ocr_provider: str | None = None) -> None:
    _write_json(path / "summary.json", {"case_count": 2, "warning_counts": warning_counts})
    _write_manifest(path / "manifest.jsonl", 2, with_report_text=True)
    if ocr_provider:
        for i in range(2):
            _write_json(path / "ocr" / f"case{i}.ocr.json", {"case_id": f"case{i}", "method": "vlm_ocr", "provider": ocr_provider})
    _write_json(path / "workflow2.json", {"case_count": 2 - failed_case_count, "failed_case_count": failed_case_count, "per_reader": {"r": {}}})
    _write_json(path / "workflow3.json", {"case_count": 2 - failed_case_count, "reader_count": 1, "reader_percentiles": {"r": {}}})


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_manifest(path: Path, count: int, *, with_report_text: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "case_id": f"case{i}",
            "reader": "r",
            "modality": "cxr",
            "body_part": "chest",
            "report_text": str(path.parent / "ocr" / f"case{i}.txt") if with_report_text else "",
            "warnings": [],
        }
        for i in range(count)
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
