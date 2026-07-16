from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from medharness2.config import AppConfig, GeneratorConfig, LLMConfig, ModelRoleConfig
from medharness2.tools.tool10_modelwise import modelwise_weighted
from medharness2.tools.tool11_hazardwise import hazardwise_weighted
from medharness2.tools.tool12_statistics import calculate_statistics, percentile_rank, correct_pvalues_holm, compare_metric_groups
from medharness2.tools.tool6_structure_diff import compare_structure
from medharness2.tools.tool9_rank import select_top_k
from medharness2.workflows.batch_readers import run_batch_readers
from medharness2.workflows.department import run_department_comparison
from medharness2.workflows.batch_readers import _mean_score as batch_mean_score
from medharness2.workflows.batch_readers import _evaluation_metadata
from medharness2.workflows.reevaluate_run import _mean_score as reevaluate_mean_score
from medharness2.workflows.merge_batches import _mean_score as merge_mean_score
from medharness2.workflows.sample_full import plan_sample_full_routes, run_sample_full


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
    assert "model_count" not in result


def test_tool10_excludes_fallback_rows_from_weighted_metrics():
    rows = [
        {"model": "real", "metrics": {"precision": 1.0}, "metadata": {"fallback_used": False}},
        {"model": "fallback", "metrics": {"precision": 0.0}, "metadata": {"fallback_used": True}},
    ]
    result = modelwise_weighted(rows)
    assert result["precision"] == pytest.approx(1.0)
    assert result["_provenance"]["eligible_count"] == 1
    assert result["_provenance"]["fallback_count"] == 1


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


def test_tool11_excludes_incomplete_hazard_rows_instead_of_defaulting_to_lowest_risk():
    result = hazardwise_weighted(
        [
            {"error_type": "false_finding", "metrics": {"error_rate": 0.2}},
            {"hazard_level": 1, "metrics": {"error_rate": 0.2}},
            {"error_type": "false_finding", "hazard_level": 4, "metrics": {"error_rate": 0.2}},
        ]
    )

    assert len(result) == 1
    assert result[0]["hazard_level"] == 4


def test_tool11_excludes_fallback_hazard_rows():
    rows = [
        {
            "error_type": "false_finding",
            "hazard_level": 5,
            "metrics": {"error_rate": 0.1},
            "provenance": {"fallback_used": True},
        },
        {
            "error_type": "false_finding",
            "hazard_level": 2,
            "metrics": {"error_rate": 0.2},
            "provenance": {"fallback_used": False},
        },
    ]
    result = hazardwise_weighted(rows)
    assert len(result) == 1
    assert result[0]["metrics"]["error_rate"] == pytest.approx(0.25)


def test_tool12_statistics_and_percentile_rank():
    stats = calculate_statistics([{"score": 0.5}, {"score": 0.7}, {"score": 0.9}])
    assert stats["score"]["mean"] == pytest.approx(0.7)
    assert stats["score"]["n"] == 3
    assert percentile_rank(0.7, [0.5, 0.7, 0.9]) == pytest.approx(50.0)


def test_statistics_ignore_bookkeeping_fields():
    stats = calculate_statistics([{"score": 0.5, "model_count": 2}, {"score": 0.7, "model_count": 3}])
    assert set(stats) == {"score"}


def test_statistics_include_reader_overall_score_with_ci():
    stats = calculate_statistics([{"overall_score": 0.2}, {"overall_score": 0.8}])
    assert stats["overall_score"]["n"] == 2
    assert stats["overall_score"]["mean"] == pytest.approx(0.5)
    assert stats["overall_score"]["ci_lower"] is not None


def test_statistics_ignore_nested_fallback_provenance():
    stats = calculate_statistics(
        [
            {"score": 1.0, "metadata": {"fallback_used": True}},
            {"score": 0.5, "metadata": {"fallback_used": False}},
        ]
    )
    assert stats["score"]["n"] == 1
    assert stats["score"]["mean"] == pytest.approx(0.5)


def test_human_provenance_merge_keeps_any_fallback_signal():
    metadata = _evaluation_metadata(
        {
            "likert": {"_metadata": {"source": "mock_judge", "fallback_used": True}},
            "finding_graph": {
                "metadata": {
                    "llm_correction": {
                        "source": "llm_extractor",
                        "fallback_used": False,
                    }
                }
            },
        }
    )
    assert metadata["fallback_used"] is True


def test_statistics_excludes_fallback_rows_and_reports_single_sample_uncertainty():
    stats = calculate_statistics([
        {"score": 0.9, "metadata": {"fallback_used": False}},
        {"score": 0.1, "metadata": {"fallback_used": True}},
    ])
    assert stats["score"]["n"] == 1
    assert stats["score"]["mean"] == pytest.approx(0.9)
    assert stats["score"]["ci_lower"] is None
    assert stats["score"]["ci_upper"] is None


def test_statistics_exposes_group_test_and_holm_correction():
    comparison = compare_metric_groups([0.9, 0.8, 0.85], [0.4, 0.5, 0.45])
    assert comparison["n_a"] == 3
    assert comparison["n_b"] == 3
    assert 0.0 <= comparison["p_value"] <= 1.0
    corrected = correct_pvalues_holm({"a": 0.01, "b": 0.04, "c": 0.2})
    assert corrected["a"] <= corrected["b"] <= corrected["c"]


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), -float("inf")])
def test_statistics_ignores_non_finite_metric_values(bad_value: float):
    """Non-finite model output must not crash or poison aggregate statistics."""
    stats = calculate_statistics([{"score": bad_value}, {"score": 0.5}])

    assert stats["score"]["n"] == 1
    assert stats["score"]["mean"] == pytest.approx(0.5)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), -float("inf")])
def test_tool9_excludes_non_finite_candidates_from_ranking(bad_value: float):
    ranked = select_top_k(
        [
            {
                "model": "bad",
                "composite_inputs": {
                    "likert_mean": bad_value,
                    "structure_score": 0.5,
                    "finding_coverage": 0.5,
                },
            },
            {
                "model": "ok",
                "composite_inputs": {
                    "likert_mean": 4.0,
                    "structure_score": 0.5,
                    "finding_coverage": 0.5,
                },
            },
        ],
        top_k=2,
    )

    assert [row["model"] for row in ranked] == ["ok"]


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), -float("inf")])
def test_tool10_ignores_non_finite_metric_values(bad_value: float):
    result = modelwise_weighted(
        [
            {"model": "bad", "metrics": {"score": bad_value}},
            {"model": "ok", "metrics": {"score": 0.5}},
        ]
    )

    assert result["score"] == pytest.approx(0.5)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), -float("inf")])
def test_compare_metric_groups_ignores_non_finite_observations(bad_value: float):
    comparison = compare_metric_groups([bad_value, 0.5], [0.4, 0.3])

    assert comparison["n_a"] == 1
    assert comparison["n_b"] == 2
    assert comparison["method"] == "insufficient_data"
    assert comparison["p_value"] == 1.0


def test_holm_treats_non_finite_p_values_as_non_significant():
    corrected = correct_pvalues_holm({"invalid": float("nan"), "valid": 0.01})

    assert corrected["invalid"] == 1.0
    assert corrected["valid"] == pytest.approx(0.02)


def test_workflow_mean_scores_use_same_likert_normalization():
    rows = [{"likert_mean": 1.0}, {"likert_mean": 5.0}]
    expected = pytest.approx(0.5)
    assert batch_mean_score(rows) == expected
    assert reevaluate_mean_score(rows) == expected
    assert merge_mean_score(rows) == expected


def test_workflow_mean_scores_exclude_fallback_rows_and_block_when_all_fallback():
    rows = [
        {
            "likert_mean": 5.0,
            "structure_score": 1.0,
            "finding_coverage": 1.0,
            "metadata": {"fallback_used": True},
        },
        {"likert_mean": 1.0, "structure_score": 0.0, "finding_coverage": 0.0},
    ]
    for scorer in (batch_mean_score, reevaluate_mean_score, merge_mean_score):
        assert scorer(rows) == pytest.approx(0.0)
        assert scorer([rows[0]]) is None


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
    # The mock judge is provenance-ineligible; do not turn its scores into
    # reader percentiles or a fabricated zero-valued aggregate.
    assert dept["reader_percentiles"] == {}
    assert dept["statistics"]["readers"] == {}
    assert dept["excluded_reader_count"] == 2
    assert set(dept["comparisons"]["excluded_readers"]) == {"doc_a", "doc_b"}
    assert dept["denominator"]["success_rate"] == 1.0
    assert dept["denominator"]["failure_rate"] == 0.0


def test_department_propagates_failed_case_denominator(tmp_path: Path):
    batch_path = tmp_path / "workflow2.json"
    batch_path.write_text(
        json.dumps(
            {
                "case_count": 1,
                "failed_case_count": 2,
                "cases": [{"case_id": "ok", "modelwise_metrics": {"precision": 1.0}}],
                "failed_cases": [{"case_id": "bad1"}, {"case_id": "bad2"}],
                "per_reader": {"reader": {"case_count": 1, "overall_score": 0.75}},
                "denominator": {"manifest_case_count": 3, "successful_case_count": 1, "failed_case_count": 2},
            }
        ),
        encoding="utf-8",
    )
    result = run_department_comparison(batch_path, tmp_path / "workflow3.json")
    assert result["denominator"]["manifest_case_count"] == 3
    assert result["denominator"]["successful_case_count"] == 1
    assert result["denominator"]["failed_case_count"] == 2
    assert result["denominator"]["source_case_count"] == 3
    assert result["denominator"]["success_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert result["denominator"]["failure_rate"] == pytest.approx(2 / 3, abs=1e-4)


def test_department_excludes_reader_with_missing_overall_score_instead_of_zero_filling(tmp_path: Path):
    batch_path = tmp_path / "workflow2.json"
    batch_path.write_text(
        json.dumps({
            "case_count": 1,
            "failed_case_count": 0,
            "cases": [],
            "per_reader": {
                "complete": {"case_count": 1, "overall_score": 0.8},
                "missing": {"case_count": 1},
            },
        }),
        encoding="utf-8",
    )

    result = run_department_comparison(batch_path, tmp_path / "workflow3.json")

    assert result["statistics"]["readers"]["overall_score"]["n"] == 1
    assert result["reader_count"] == 1
    assert result["excluded_reader_count"] == 1
    assert result["comparisons"]["doctor_group"]["scores"] == {"complete": 0.8}
    assert result["comparisons"]["excluded_readers"] == {"missing": "missing_overall_score"}


def test_batch_readers_batches_medharness_cli_generation(monkeypatch, tmp_path: Path):
    script = tmp_path / "run_report_generation.py"
    script.write_text("# fake legacy script\n", encoding="utf-8")
    legacy_config = tmp_path / "reportgen_models.yaml"
    legacy_config.write_text("models:\n  fake_fresh:\n    python_bin: python\n", encoding="utf-8")
    report1 = tmp_path / "r1.txt"
    report2 = tmp_path / "r2.txt"
    image1 = tmp_path / "i1.png"
    image2 = tmp_path / "i2.png"
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
    calls: list[list[str]] = []

    def fake_run(cmd, check, capture_output, text, timeout):
        input_path = Path(cmd[cmd.index("--input-jsonl") + 1])
        output_path = Path(cmd[cmd.index("--output-jsonl") + 1])
        input_rows = [json.loads(line) for line in input_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        calls.append([row["case_id"] for row in input_rows])
        output_path.write_text(
            "\n".join(
                json.dumps(
                    {
                        "case_id": row["case_id"],
                        "model_key": "fake_fresh",
                        "generated_text": f"FINDINGS: Fresh report for {row['case_id']}.",
                        "modality": row["modality"],
                        "body_part": row["body_part"],
                        "warnings": [],
                        "adapter_status": "passed",
                    }
                )
                for row in input_rows
            )
            + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cfg = AppConfig(
        llm=LLMConfig(provider="mock"),
        generator=GeneratorConfig(
            cloud_fallback_enabled=True,
            default_models=["fake_fresh"],
            include_legacy_ready_models=False,
            local_models=[
                {
                    "key": "fake_fresh",
                    "source": "medharness_cli",
                    "supported_modalities": ["xray", "cxr"],
                    "supported_body_parts": ["chest"],
                    "medharness_model_key": "fake_fresh",
                    "script_path": str(script),
                    "config_path": str(legacy_config),
                    "ready": True,
                }
            ],
        ),
    )
    output = tmp_path / "workflow2.json"
    result = run_batch_readers(manifest, output, config=cfg, model_keys=["fake_fresh"], model_sources=["medharness_cli"])
    assert calls == [["case1", "case2"]]
    assert result["failed_case_count"] == 0
    for case in result["cases"]:
        workflow1 = json.loads(Path(case["workflow1_output"]).read_text(encoding="utf-8"))
        assert workflow1["generated_reports"][0]["model"] == "fake_fresh"
        assert workflow1["generated_reports"][0]["source"] == "medharness_cli"


def test_batch_readers_preserves_mixed_generator_sources(monkeypatch, tmp_path: Path):
    script = tmp_path / "run_report_generation.py"
    script.write_text("# fake legacy script\n", encoding="utf-8")
    legacy_config = tmp_path / "reportgen_models.yaml"
    legacy_config.write_text("models:\n  fake_fresh:\n    python_bin: python\n", encoding="utf-8")
    artifact = tmp_path / "artifact.jsonl"
    artifact.write_text(json.dumps({"generated_text": "FINDINGS: Artifact report.", "modality": "xray"}) + "\n", encoding="utf-8")
    report = tmp_path / "report.txt"
    image = tmp_path / "image.png"
    report.write_text("FINDINGS: No pneumothorax. IMPRESSION: Normal.", encoding="utf-8")
    image.write_text("dummy", encoding="utf-8")
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "case_id": "case1",
                "reader": "doc_a",
                "modality": "cxr",
                "body_part": "chest",
                "report_text": str(report),
                "image_paths": [str(image)],
                "derived_assets": {"primary_image": str(image)},
                "warnings": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_run(cmd, check, capture_output, text, timeout):
        input_path = Path(cmd[cmd.index("--input-jsonl") + 1])
        output_path = Path(cmd[cmd.index("--output-jsonl") + 1])
        input_row = json.loads(input_path.read_text(encoding="utf-8"))
        output_path.write_text(
            json.dumps(
                {
                    "case_id": input_row["case_id"],
                    "model_key": "fake_fresh",
                    "generated_text": "FINDINGS: Fresh report.",
                    "modality": input_row["modality"],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cfg = AppConfig(
        llm=LLMConfig(provider="mock"),
        generator=GeneratorConfig(
            cloud_fallback_enabled=True,
            default_models=["fake_fresh", "fake_artifact"],
            include_legacy_ready_models=False,
            local_models=[
                {
                    "key": "fake_fresh",
                    "source": "medharness_cli",
                    "supported_modalities": ["xray", "cxr"],
                    "supported_body_parts": ["chest"],
                    "medharness_model_key": "fake_fresh",
                    "script_path": str(script),
                    "config_path": str(legacy_config),
                    "ready": True,
                },
                {
                    "key": "fake_artifact",
                    "source": "artifact_reuse",
                    "supported_modalities": ["xray", "cxr"],
                    "supported_body_parts": ["chest"],
                    "source_generation_jsonl": str(artifact),
                },
            ],
        ),
    )
    output = tmp_path / "workflow2.json"
    result = run_batch_readers(manifest, output, config=cfg)
    workflow1 = json.loads(Path(result["cases"][0]["workflow1_output"]).read_text(encoding="utf-8"))
    assert {report["model"] for report in workflow1["generated_reports"]} == {"fake_fresh", "fake_artifact"}


def test_batch_readers_continues_when_case_workflow_fails(tmp_path: Path):
    missing_report = tmp_path / "missing.txt"
    image = tmp_path / "image.dcm"
    image.write_text("dummy", encoding="utf-8")
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "case_id": "bad_case",
                "reader": "doc_a",
                "modality": "cxr",
                "body_part": "chest",
                "report_text": str(missing_report),
                "image_paths": [str(image)],
                "derived_assets": {"primary_image": str(image)},
                "warnings": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = AppConfig(
        llm=LLMConfig(provider="mock"),
        generator=GeneratorConfig(cloud_fallback_enabled=True, default_models=[], local_models=[]),
    )
    output = tmp_path / "workflow2.json"
    result = run_batch_readers(manifest, output, config=cfg)
    assert result["case_count"] == 0
    assert result["failed_case_count"] == 1
    assert result["failed_cases"][0]["case_id"] == "bad_case"
    assert "FileNotFoundError" in result["failed_cases"][0]["error"]


def test_batch_readers_does_not_placeholder_when_real_ocr_role_is_configured(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "case_id": "missing",
                "reader": "doc_a",
                "modality": "cxr",
                "body_part": "chest",
                "report_text": "",
                "image_paths": [],
                "derived_assets": {},
                "warnings": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = AppConfig(
        llm=LLMConfig(provider="mock"),
        model_roles={"ocr_primary": ModelRoleConfig(provider="chat_completions", model="ocr-model")},
        generator=GeneratorConfig(cloud_fallback_enabled=True, default_models=[], local_models=[]),
    )
    result = run_batch_readers(manifest, tmp_path / "workflow2.json", config=cfg)
    assert result["case_count"] == 0
    assert result["failed_case_count"] == 1
    assert "FileNotFoundError" in result["failed_cases"][0]["error"]


def test_sample_full_workflow_orchestrates_manifest_batch_department_and_validation(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    image_path = case_dir / "Y1"
    image_path.write_text("dummy", encoding="utf-8")
    report_pdf = sample_root / "CR" / "CR001" / "report.pdf"
    report_pdf.write_text("dummy pdf", encoding="utf-8")
    output_dir = tmp_path / "run"
    cfg = AppConfig(
        llm=LLMConfig(provider="mock"),
        generator=GeneratorConfig(cloud_fallback_enabled=True, default_models=[], local_models=[]),
    )
    result = run_sample_full(
        sample_root,
        output_dir,
        config=cfg,
        limit=1,
        expected_cases=1,
    )
    assert result["summary"]["case_count"] == 1
    assert result["summary"]["workflow2_case_count"] == 1
    assert result["summary"]["workflow3_case_count"] == 1
    assert result["validation"]["passed"] is True
    assert Path(result["paths"]["manifest"]).exists()
    assert Path(result["paths"]["workflow2"]).exists()
    assert Path(result["paths"]["workflow3"]).exists()
    assert Path(result["paths"]["run_summary"]).exists()
    payload = json.loads(Path(result["paths"]["run_summary"]).read_text(encoding="utf-8"))
    assert payload["validation"]["passed"] is True


def test_sample_full_dry_run_plans_all_compatible_local_models_without_outputs(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    image_path = case_dir / "Y1"
    image_path.write_text("dummy", encoding="utf-8")
    report_pdf = sample_root / "CR" / "CR001" / "report.pdf"
    report_pdf.write_text("dummy pdf", encoding="utf-8")
    output_dir = tmp_path / "run"
    result = plan_sample_full_routes(
        sample_root,
        output_dir,
        config=AppConfig(),
        limit=1,
        model_keys=["*"],
    )
    assert result["summary"]["case_count"] == 1
    assert result["summary"]["cases_with_local_candidates"] == 1
    assert result["summary"]["fresh_local_candidate_count"] >= 1
    assert "maira_2" in result["cases"][0]["compatible_model_keys"]
    readiness = result["cases"][0]["compatible_model_readiness"]["maira_2"]
    assert readiness["report_trained"] is True
    assert readiness["fresh_inference"] is True
    assert readiness["route_role"] == "fresh_report_trained_local"
    assert Path(result["paths"]["route_plan"]).exists()
    assert not (output_dir / "workflow2.json").exists()


def test_sample_full_dry_run_filters_local_models_by_source(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    (case_dir / "Y1").write_text("dummy", encoding="utf-8")
    (sample_root / "CR" / "CR001" / "report.pdf").write_text("dummy pdf", encoding="utf-8")
    output_dir = tmp_path / "run"
    result = plan_sample_full_routes(
        sample_root,
        output_dir,
        config=AppConfig(),
        limit=1,
        model_keys=["*"],
        model_sources=["artifact_reuse"],
    )
    keys = result["cases"][0]["compatible_model_keys"]
    assert "chexagent" in keys
    assert "llava_rad" in keys
    assert "maira_2" not in keys
    assert set(result["cases"][0]["compatible_model_sources"].values()) == {"artifact_reuse"}
