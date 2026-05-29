from __future__ import annotations

import json
from pathlib import Path

from medharness2.cli import main
from medharness2.config import load_config
from medharness2.llm_client import build_mock_client
from medharness2.modules.pairwise_report import evaluate_pairwise
from medharness2.modules.single_report import evaluate_single_report
from medharness2.workflows.single_case import run_single_case


def test_single_report_module_returns_composite_inputs():
    result = evaluate_single_report("FINDINGS: Mild right lung opacity. IMPRESSION: Mild opacity.", modality="cxr", llm_client=build_mock_client())
    assert result["composite_inputs"]["likert_mean"] > 0
    assert result["finding_graph"]["findings"]


def test_pairwise_module_returns_alignment():
    result = evaluate_pairwise(
        "FINDINGS: Mild right lung opacity. IMPRESSION: Opacity.",
        "FINDINGS: Mild right lung opacity. IMPRESSION: Opacity.",
        modality="cxr",
        llm_client=build_mock_client(),
    )
    assert result["alignment"]["metrics"]["f1"] == 1.0


def test_single_case_workflow_writes_json(tmp_path: Path):
    report = tmp_path / "human.txt"
    image = tmp_path / "dummy.dcm"
    output = tmp_path / "result.json"
    report.write_text("FINDINGS: Mild right lung opacity measuring 1.2 cm.\nIMPRESSION: Mild opacity.", encoding="utf-8")
    image.write_text("dummy", encoding="utf-8")
    result = run_single_case(report, image, output, modality="cxr", top_n=1, llm_client=build_mock_client(), config=load_config())
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["human_evaluation"]
    assert payload["generated_reports"]
    assert payload["rankings"][0]["selected_top_n"] is True
    assert result["pairwise_comparisons"]


def test_cli_single_case(tmp_path: Path):
    report = tmp_path / "human.txt"
    image = tmp_path / "dummy.dcm"
    output = tmp_path / "result.json"
    report.write_text("FINDINGS: No pneumothorax. IMPRESSION: No acute disease.", encoding="utf-8")
    image.write_text("dummy", encoding="utf-8")
    code = main(["workflow", "single-case", "--report", str(report), "--image", str(image), "--output", str(output), "--modality", "cxr", "--top-n", "1"])
    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "pairwise_comparisons" in payload
