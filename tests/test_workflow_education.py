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
    class FailingClient:
        def call(self, *args, **kwargs):
            raise RuntimeError("judge unavailable")

    result = run_education_suggestions(
        eval_report=workflow1,
        output_path=output,
        config=AppConfig(generator=GeneratorConfig(default_models=[], local_models=[])),
        llm_client=FailingClient(),
    )
    assert output.exists()
    assert result["mode"] == "eval_report"
    assert result["status"] == "suggestions_generated"
    assert result["report_summary"]["weakest_metric"] == "Completeness and Accuracy"
    assert result["suggestions"]
    assert result["suggestions"][0]["finding_id"] == "f1"
    assert result["general_suggestions"]
    assert result["metadata"]["source"] == "deterministic_fallback"
    assert result["metadata"]["fallback_used"] is True


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
    assert result["metadata"]["source"] == "mock_judge"
    assert result["metadata"]["fallback_used"] is True


def test_education_blocks_missing_reader_statistics_instead_of_inventing_weak_metric(tmp_path: Path):
    workflow2 = tmp_path / "workflow2.json"
    workflow2.write_text(json.dumps({"case_count": 1, "per_reader": {"reader_a": {"case_count": 1}}}), encoding="utf-8")
    result = run_education_suggestions(
        eval_radiologist=workflow2,
        output_path=tmp_path / "education.json",
        config=AppConfig(generator=GeneratorConfig(default_models=[], local_models=[])),
    )
    assert result["status"] == "blocked_insufficient_data"
    assert result["suggestions"] == []
    assert result["metadata"]["blocked_reasons"] == ["missing_reader_statistics"]


def test_education_derives_reader_statistics_from_case_metrics(tmp_path: Path):
    workflow2 = tmp_path / "workflow2.json"
    workflow2.write_text(
        json.dumps({
            "case_count": 2,
            "cases": [
                {"reader": "reader_a", "human_metrics": {"finding_coverage": 0.2}},
                {"reader": "reader_b", "human_metrics": {"finding_coverage": 0.9}},
            ],
            "per_reader": {"reader_a": {"case_count": 1}, "reader_b": {"case_count": 1}},
        }),
        encoding="utf-8",
    )
    result = run_education_suggestions(
        eval_radiologist=workflow2,
        output_path=tmp_path / "education.json",
        config=AppConfig(generator=GeneratorConfig(default_models=[], local_models=[])),
    )
    assert result["status"] == "suggestions_generated"
    assert result["radiologist_summary"]["weakest_metrics"] == ["finding_coverage"]


def test_education_marks_missing_peer_statistics_without_zero_baseline(tmp_path: Path):
    workflow2 = tmp_path / "workflow2.json"
    workflow2.write_text(json.dumps({"case_count": 1, "per_reader": {"reader_a": {"case_count": 1, "human_statistics": {"Completeness": {"mean": 2.0}}}}}), encoding="utf-8")
    result = run_education_suggestions(
        eval_radiologist=workflow2,
        output_path=tmp_path / "education.json",
        config=AppConfig(generator=GeneratorConfig(default_models=[], local_models=[])),
    )
    assert result["status"] == "suggestions_generated"
    assert result["suggestions"]
    assert result["radiologist_summary"]["peer_gaps"]["Completeness"] is None
    assert result["metadata"]["peer_baseline_available"] is False
    assert result["metadata"]["limitations"] == ["missing_peer_statistics"]


def test_run_education_requires_exactly_one_input(tmp_path: Path):
    output = tmp_path / "education.json"
    try:
        run_education_suggestions(output_path=output)
    except ValueError as exc:
        assert "exactly one" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_education_fallback_is_explicitly_marked(tmp_path: Path):
    output = tmp_path / "education.json"
    (tmp_path / "workflow2.json").write_text(json.dumps(_workflow2_payload()), encoding="utf-8")
    class FailingClient:
        def call(self, *args, **kwargs):
            raise RuntimeError("judge unavailable")

    result = run_education_suggestions(
        eval_radiologist=tmp_path / "workflow2.json",
        output_path=output,
        config=AppConfig(generator=GeneratorConfig(default_models=[], local_models=[])),
        llm_client=FailingClient(),
    )
    assert result["metadata"]["fallback_used"] is True


def test_education_real_client_is_marked_as_llm_judge(tmp_path: Path):
    output = tmp_path / "education.json"
    (tmp_path / "workflow2.json").write_text(json.dumps(_workflow2_payload()), encoding="utf-8")

    class RealisticClient:
        class Config:
            class LLM:
                provider = "chat_completions"
            llm = LLM()

        config = Config()

        def call(self, *args, **kwargs):
            return json.dumps(kwargs["response_json"], ensure_ascii=False)

    result = run_education_suggestions(
        eval_radiologist=tmp_path / "workflow2.json",
        output_path=output,
        llm_client=RealisticClient(),
    )
    assert result["metadata"]["source"] == "llm_judge"
    assert result["metadata"]["fallback_used"] is False


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


def test_cli_workflow_education_returns_nonzero_when_blocked(tmp_path: Path):
    workflow2 = tmp_path / "workflow2.json"
    output = tmp_path / "education.json"
    workflow2.write_text(json.dumps({"case_count": 1, "per_reader": {"reader_a": {"case_count": 1}}}), encoding="utf-8")

    code = main(["workflow", "education", "--eval-radiologist", str(workflow2), "--output", str(output)])

    assert code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked_insufficient_data"
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


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


def test_education_blocks_report_when_all_likert_scores_missing(tmp_path: Path):
    payload = _workflow1_payload()
    payload["human_evaluation"]["likert"] = {}
    source = tmp_path / "workflow1.json"
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = run_education_suggestions(
        eval_report=source,
        output_path=tmp_path / "education.json",
        config=AppConfig(generator=GeneratorConfig(default_models=[], local_models=[])),
    )

    assert result["status"] == "blocked_insufficient_data"
    assert result["report_summary"]["overall_score"] is None
    assert result["report_summary"]["weakest_metric"] is None
    assert result["metadata"]["blocked_reasons"] == ["missing_likert_statistics"]


def test_education_ignores_missing_and_invalid_likert_scores_without_zero_filling(tmp_path: Path):
    payload = _workflow1_payload()
    payload["human_evaluation"]["likert"] = {
        "Completeness and Accuracy": {"score": None},
        "Conciseness and Clarity": {"score": "bad"},
        "Terminological Accuracy": {"score": 4},
        "Structure and Style": {},
        "Overall Writing Quality": {"score": 2},
    }
    source = tmp_path / "workflow1.json"
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = run_education_suggestions(
        eval_report=source,
        output_path=tmp_path / "education.json",
        config=AppConfig(generator=GeneratorConfig(default_models=[], local_models=[])),
    )

    assert result["status"] == "suggestions_generated"
    assert result["report_summary"]["weakest_metric"] == "Overall Writing Quality"
    assert result["report_summary"]["weakest_score"] == 2
    assert result["report_summary"]["overall_score"] == 3.0
