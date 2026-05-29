from __future__ import annotations

from medharness2.config import AppConfig, GeneratorConfig
from medharness2.llm_client import build_mock_client
from medharness2.tools.tool1_likert import evaluate_likert, likert_mean
from medharness2.tools.tool2_extract import extract_findings
from medharness2.tools.tool4_hazard import evaluate_hazards
from medharness2.tools.tool5_align import align_graphs, normalize_measurement_mm
from medharness2.tools.tool8_generate import generate_reports
from medharness2.tools.tool9_rank import select_top_k


def test_tool1_likert_normalizes_scores():
    client = build_mock_client({"Completeness and Accuracy": {"score": 9, "explanation": "x"}})
    result = evaluate_likert("short report", llm_client=client)
    assert result["Completeness and Accuracy"]["score"] == 5
    assert likert_mean(result) >= 1
    assert result["warning"] == "No image/volume provided"


def test_tool2_placeholder_extracts_schema_valid_graph():
    graph = extract_findings("FINDINGS: Mild right lung opacity measuring 1.2 cm.", modality="cxr")
    assert graph["backend"] == "placeholder"
    assert graph["findings"][0]["observation"] == "opacity"
    assert graph["findings"][0]["measurement"] == "1.2 cm"


def test_tool5_normalizes_units_and_aligns_approximately():
    assert normalize_measurement_mm("1.2 cm") == 12.0
    graph_a = {"findings": [{"observation": "nodule", "location": "right lung", "severity": "mild", "measurement": "1.2 cm"}]}
    graph_b = {"findings": [{"observation": "nodule", "location": "right lung", "severity": "mild", "measurement": "13 mm"}]}
    result = align_graphs(graph_a, graph_b, tolerance_mm=5.0)
    assert len(result["approximate_match"]) == 1
    assert not result["error_candidates"]


def test_tool4_adds_hazard_levels():
    result = evaluate_hazards([{"error_type": "omission_finding"}], llm_client=build_mock_client())
    assert result["errors"][0]["hazard_level"] == 4


def test_tool8_cloud_fallback_returns_report_when_no_local_generator():
    cfg = AppConfig(generator=GeneratorConfig(cloud_fallback_enabled=True, default_models=[], local_models=[]))
    reports = generate_reports("dummy.dcm", "cxr", config=cfg, llm_client=build_mock_client())
    assert len(reports) == 1
    assert reports[0].source == "cloud_fallback"
    assert reports[0].report


def test_tool9_selects_top_k():
    ranked = select_top_k(
        [
            {"model": "a", "composite_inputs": {"likert_mean": 2, "structure_score": 0.1, "finding_coverage": 0.1}},
            {"model": "b", "composite_inputs": {"likert_mean": 5, "structure_score": 1.0, "finding_coverage": 1.0}},
        ],
        top_k=1,
    )
    assert ranked[0]["model"] == "b"
    assert ranked[0]["rank"] == 1
