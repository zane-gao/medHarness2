from __future__ import annotations

import json
from pathlib import Path

import pytest

from medharness2.config import AppConfig, GeneratorConfig, LLMConfig
from medharness2.tools.tool10_modelwise import modelwise_weighted
from medharness2.tools.tool11_hazardwise import hazardwise_weighted
from medharness2.tools.tool12_statistics import calculate_statistics, percentile_rank
from medharness2.tools.tool6_structure_diff import compare_structure
from medharness2.workflows.batch_readers import run_batch_readers
from medharness2.workflows.department import run_department_comparison


def test_tool6_compares_report_structure():
    result = compare_structure(
        "FINDINGS: Clear lungs.\nIMPRESSION: Normal.",
        "Findings only without an impression section.",
    )
    assert result["score_a"] > result["score_b"]
    assert "impression" in result["section_diff"]


def test_tool10_modelwise_weighted_uses_named_weights():
    rows = [
        {"model": "a", "metrics": {"precision": 0.5, "recall": 1.0}},
        {"model": "b", "metrics": {"precision": 1.0, "recall": 0.0}},
    ]
    result = modelwise_weighted(rows, weights={"a": 1.0, "b": 3.0})
    assert result["precision"] == pytest.approx(0.875)
    assert result["recall"] == pytest.approx(0.25)
    assert result["model_count"] == 2


def test_tool11_applies_hazard_weights_to_numeric_metrics():
    rows = [
        {"error_type": "false_finding", "hazard_level": 3, "metrics": {"error_rate": 0.2}},
        {"error_type": "omission_finding", "hazard_level": 1, "metrics": {"error_rate": 0.4}},
    ]
    result = hazardwise_weighted(rows, hazard_weights={"false_finding": {"3": 2.0}})
    assert result[0]["metrics"]["error_rate"] == pytest.approx(0.4)
    assert result[0]["hazard_weight"] == 2.0
    assert result[1]["metrics"]["error_rate"] == pytest.approx(0.4)
    assert result[1]["hazard_weight"] == 1.0


def test_tool12_statistics_and_percentile_rank():
    stats = calculate_statistics([{"score": 0.5}, {"score": 0.7}, {"score": 0.9}])
    assert stats["score"]["mean"] == pytest.approx(0.7)
    assert stats["score"]["n"] == 3
    assert percentile_rank(0.7, [0.5, 0.7, 0.9]) == pytest.approx(66.666, rel=1e-3)


def test_batch_readers_and_department_workflows(tmp_path: Path):
    report1 = tmp_path / "r1.txt"
    report2 = tmp_path / "r2.txt"
    image1 = tmp_path / "i1.dcm"
    image2 = tmp_path / "i2.dcm"
    report1.write_text("FINDINGS: No pneumothorax. IMPRESSION: Normal.", encoding="utf-8")
    report2.write_text("FINDINGS: Mild right lung opacity. IMPRESSION: Opacity.", encoding="utf-8")
    image1.write_text("dummy", encoding="utf-8")
    image2.write_text("dummy", encoding="utf-8")
    manifest = tmp_path / "manifest.jsonl"
    rows = [
        {
            "case_id": "case1",
            "reader": "doc_a",
            "modality": "cxr",
            "body_part": "chest",
            "report_text": str(report1),
            "image_paths": [str(image1)],
            "derived_assets": {"primary_image": str(image1)},
            "warnings": [],
        },
        {
            "case_id": "case2",
            "reader": "doc_b",
            "modality": "cxr",
            "body_part": "chest",
            "report_text": str(report2),
            "image_paths": [str(image2)],
            "derived_assets": {"primary_image": str(image2)},
            "warnings": [],
        },
    ]
    manifest.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    cfg = AppConfig(
        llm=LLMConfig(provider="mock"),
        generator=GeneratorConfig(cloud_fallback_enabled=True, default_models=[], local_models=[]),
    )
    batch_output = tmp_path / "workflow2.json"
    batch = run_batch_readers(manifest, batch_output, limit=2, config=cfg)
    assert batch_output.exists()
    assert set(batch["per_reader"]) == {"doc_a", "doc_b"}
    assert batch["cases"][0]["workflow1_output"]
    dept_output = tmp_path / "workflow3.json"
    dept = run_department_comparison(batch_output, dept_output)
    assert dept_output.exists()
    assert dept["statistics"]
    assert dept["reader_percentiles"]
