from __future__ import annotations

import json
from pathlib import Path

from medharness2.cli import main
from medharness2.config import AppConfig, GeneratorConfig
from medharness2.workflows.education import run_education_suggestions


def test_run_education_suggestions_from_workflow1(tmp_path: Path):
    workflow1 = tmp_path / "workflow1.json"
    output = tmp_path / "education.json"
    workflow1.write_text(json.dumps(_workflow1_payload(), ensure_ascii=False), encoding="utf-8")
    result = run_education_suggestions(
        eval_report=workflow1,
        output_path=output,
        config=AppConfig(generator=GeneratorConfig(default_models=[], local_models=[])),
    )
    assert output.exists()
    assert result["mode"] == "eval_report"
    assert result["status"] == "suggestions_generated"
    assert result["report_summary"]["weakest_metric"] == "Completeness and Accuracy"
    assert result["suggestions"]
    assert result["suggestions"][0]["finding_id"] == "f1"
    assert result["general_suggestions"]


def test_run_education_suggestions_from_workflow2(tmp_path: Path):
    workflow2 = tmp_path / "workflow2.json"
    output = tmp_path / "reader_education.json"
    workflow2.write_text(json.dumps(_workflow2_payload(), ensure_ascii=False), encoding="utf-8")
    result = run_education_suggestions(
        eval_radiologist=workflow2,
        output_path=output,
        config=AppConfig(generator=GeneratorConfig(default_models=[], local_models=[])),
    )
    assert result["mode"] == "eval_radiologist"
    assert result["radiologist_summary"]["radiologist_id"] == "reader_a"
    assert "Completeness and Accuracy" in result["radiologist_summary"]["weakest_metrics"]
    assert result["suggestions"][0]["metric"] == "Completeness and Accuracy"


def test_run_education_requires_exactly_one_input(tmp_path: Path):
    output = tmp_path / "education.json"
    try:
        run_education_suggestions(output_path=output)
    except ValueError as exc:
        assert "exactly one" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_cli_workflow_education_eval_report(tmp_path: Path):
    workflow1 = tmp_path / "workflow1.json"
    output = tmp_path / "education.json"
    workflow1.write_text(json.dumps(_workflow1_payload(), ensure_ascii=False), encoding="utf-8")
    code = main(["workflow", "education", "--eval-report", str(workflow1), "--output", str(output)])
    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["mode"] == "eval_report"
    assert payload["suggestions"]
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    entry = registry["entries"][-1]
    assert entry["stage"] == "workflow.education"
    assert entry["inputs"]["eval_report"] == str(workflow1)
    assert entry["outputs"]["education"] == str(output)
    assert entry["metrics"]["suggestion_count"] >= 1


def _workflow1_payload() -> dict:
    return {
        "input": {"modality": "cxr", "body_part": "chest"},
        "human_evaluation": {
            "likert": {
                "Completeness and Accuracy": {"score": 2, "explanation": "Misses important detail."},
                "Conciseness and Clarity": {"score": 4, "explanation": "Clear."},
                "Terminological Accuracy": {"score": 3, "explanation": "Acceptable."},
                "Structure and Style": {"score": 4, "explanation": "Structured."},
                "Overall Writing Quality": {"score": 4, "explanation": "Good."},
            },
            "finding_graph": {
                "findings": [
                    {
                        "id": "f1",
                        "observation": "opacity",
                        "location": "right lung",
                        "severity": "unspecified",
                        "text": "right lung opacity",
                    }
                ]
            },
            "structure": {"score": 0.55, "warnings": ["missing_impression_section"]},
            "composite_inputs": {"likert_mean": 3.4, "structure_score": 0.55, "finding_coverage": 0.1},
        },
        "generated_reports": [
            {
                "model": "maira_2",
                "source": "medharness_cli",
                "report": "FINDINGS: Right lung opacity is present. IMPRESSION: Opacity.",
                "warnings": [],
            }
        ],
        "rankings": [{"model": "maira_2", "rank": 1, "selected_top_n": True}],
        "pairwise_comparisons": [
            {
                "model": "maira_2",
                "comparison": {
                    "alignment": {
                        "error_candidates": [
                            {
                                "error_type": "incorrect_location",
                                "finding": {"id": "f1", "text": "right lung opacity"},
                            }
                        ]
                    },
                    "hazards": {
                        "errors": [
                            {
                                "error_type": "incorrect_location",
                                "finding": {"id": "f1", "text": "right lung opacity"},
                                "hazard_level": 3,
                                "explanation": "Location matters.",
                            }
                        ]
                    },
                },
            }
        ],
    }


def _workflow2_payload() -> dict:
    return {
        "case_count": 2,
        "per_reader": {
            "reader_a": {
                "case_count": 2,
                "overall_score": 0.55,
                "human_statistics": {
                    "Completeness and Accuracy": {"mean": 2.0},
                    "Conciseness and Clarity": {"mean": 4.0},
                    "Terminological Accuracy": {"mean": 3.0},
                },
            },
            "reader_b": {
                "case_count": 2,
                "overall_score": 0.8,
                "human_statistics": {
                    "Completeness and Accuracy": {"mean": 4.0},
                    "Conciseness and Clarity": {"mean": 4.2},
                    "Terminological Accuracy": {"mean": 4.0},
                },
            },
        },
    }
