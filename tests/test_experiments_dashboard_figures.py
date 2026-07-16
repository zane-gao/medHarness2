from __future__ import annotations

import csv
import json
from pathlib import Path

from medharness2.cli import main
from medharness2.dashboard import _render_reader_rows, build_dashboard
from medharness2.figures import build_figures
from medharness2.workflows.experiments import run_experiments
from medharness2.workflows.experiments import _image_to_text_models, _modality_recognition, _radiologist_evaluation


def test_run_experiments_builds_six_study_results(tmp_path: Path):
    run_dir = _write_minimal_run(tmp_path / "run")
    output_dir = tmp_path / "experiments"
    result = run_experiments(run_dir, output_dir)
    assert result["experiment_count"] == 6
    assert {item["id"] for item in result["experiments"]} == {
        "radiologist_evaluation",
        "finding_extraction",
        "hazard_evaluation",
        "educational_study",
        "image_to_text_models",
        "modality_recognition",
    }
    assert (output_dir / "results.json").exists()
    assert (output_dir / "results.md").exists()
    assert (output_dir / "experiment_summary.csv").exists()


def test_radiologist_evaluation_preserves_explicit_zero_counts():
    result = _radiologist_evaluation(
        {"case_count": 0, "reader_count": 0},
        {"case_count": 3, "per_reader": {"reader": {}}},
        {"reader_percentiles": {"reader": {}}},
    )

    assert result["metrics"]["case_count"] == 0
    assert result["metrics"]["reader_count"] == 0


def test_image_to_text_models_preserves_explicit_zero_model_count(tmp_path: Path):
    (tmp_path / "analysis").mkdir()
    (tmp_path / "analysis" / "model_source_summary.csv").write_text(
        "model,source\nmodel-a,artifact\n", encoding="utf-8"
    )

    result = _image_to_text_models(
        tmp_path,
        {"generated_report_model_counts": {}, "generated_report_source_counts": {"artifact": 1}},
    )

    # Empty model-count mapping is an explicit zero from analysis; the CSV is
    # retained as evidence but must not silently change the summary count.
    assert result["metrics"]["model_count"] == 0


def test_modality_recognition_preserves_explicit_empty_counts():
    result = _modality_recognition(
        {"validation": {"summary": {"modality_counts": {}}}},
        {"cases": [{"modality": "cxr"}]},
    )

    assert result["status"] == "missing_inputs"
    assert result["metrics"]["modality_counts"] == {}


def test_run_experiments_writes_protocol_mapping_artifacts(tmp_path: Path):
    run_dir = _write_minimal_run(tmp_path / "run")
    output_dir = tmp_path / "experiments"

    result = run_experiments(run_dir, output_dir)

    protocol = result["protocol"]
    entries = {item["id"]: item for item in protocol["experiments"]}
    assert set(entries) == {
        "radiologist_evaluation",
        "finding_extraction",
        "hazard_evaluation",
        "educational_study",
        "image_to_text_models",
        "modality_recognition",
    }
    finding = entries["finding_extraction"]
    assert finding["notion_section"] == "Radiologist Finding Extraction Study"
    assert finding["implementation"]["stage"] == "experiments.run"
    assert finding["model_policy"]["medical_specialist_model"] == "preferred_candidate"
    assert finding["model_policy"]["api_model"] == "structured_deidentified_only"
    assert finding["status"] == "pilot"
    assert finding["gate_summary"]["failed"] > 0
    assert finding["current_evidence"]["metrics"]["finding_count"] == 2
    assert finding["limitations"]
    assert finding["next_steps"]
    hazard = entries["hazard_evaluation"]
    assert "weighted_kappa" in hazard["primary_endpoints"]
    assert any(gate["id"] == "clinician_hazard_gold" for gate in hazard["validation_gates"])
    assert "Synthetic schema smoke" in " ".join(hazard["limitations"])
    assert (output_dir / "experiment_protocol.json").exists()
    assert (output_dir / "experiment_protocol.md").exists()
    assert (output_dir / "experiment_protocol.csv").exists()
    protocol_json = json.loads((output_dir / "experiment_protocol.json").read_text(encoding="utf-8"))
    assert protocol_json["experiment_count"] == 6
    protocol_md = (output_dir / "experiment_protocol.md").read_text(encoding="utf-8")
    assert "Radiologist Error Hazard Evaluation Study" in protocol_md
    protocol_csv = (output_dir / "experiment_protocol.csv").read_text(encoding="utf-8")
    assert "model_policy" in protocol_csv


def test_run_experiments_generates_reader_education_outputs(tmp_path: Path):
    run_dir = _write_minimal_run(tmp_path / "run")
    output_dir = tmp_path / "experiments"
    result = run_experiments(run_dir, output_dir)
    education_output = run_dir / "education" / "radiologist_summary.json"
    educational = next(item for item in result["experiments"] if item["id"] == "educational_study")
    assert education_output.exists()
    assert educational["status"] == "pilot"
    assert educational["metrics"]["education_file_count"] >= 1
    assert educational["metrics"]["suggestion_count"] >= 1


def test_cli_experiments_run(tmp_path: Path):
    run_dir = _write_minimal_run(tmp_path / "run")
    output_dir = tmp_path / "experiments"
    code = main(["experiments", "run", "--run-dir", str(run_dir), "--output-dir", str(output_dir)])
    assert code == 0
    payload = json.loads((output_dir / "results.json").read_text(encoding="utf-8"))
    assert payload["experiment_count"] == 6
    registry = json.loads((output_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["stage"] == "experiments.run"
    assert registry["entries"][-1]["inputs"]["run_dir"] == str(run_dir)
    assert registry["entries"][-1]["metrics"]["experiment_count"] == 6
    assert registry["entries"][-1]["metrics"]["education_generation_status"] == "generated"
    assert registry["entries"][-1]["metrics"]["education_suggestion_count"] >= 1
    assert registry["entries"][-1]["outputs"]["experiment_protocol"] == str(output_dir / "experiment_protocol.json")


def test_cli_experiments_run_rejects_missing_source_run(tmp_path: Path):
    run_dir = tmp_path / "missing"
    output_dir = tmp_path / "experiments"
    code = main(["experiments", "run", "--run-dir", str(run_dir), "--output-dir", str(output_dir)])
    assert code == 1
    payload = json.loads((output_dir / "results.json").read_text(encoding="utf-8"))
    assert payload["errors"] == ["run_dir_not_found"]
    registry = json.loads((output_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"
    source_registry = json.loads((run_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert source_registry["entries"][-1]["status"] == "failed"


def test_build_figures_writes_svg_and_manifest(tmp_path: Path):
    run_dir = _write_minimal_run(tmp_path / "run")
    exp_dir = tmp_path / "experiments"
    run_experiments(run_dir, exp_dir)
    figure_dir = tmp_path / "figures"
    result = build_figures(exp_dir, figure_dir)
    assert result["figure_count"] >= 3
    assert (figure_dir / "figure_manifest.json").exists()
    assert (figure_dir / "fig6_main_results.svg").exists()


def test_build_figures_writes_notion_v1_figures_and_tables(tmp_path: Path):
    run_dir = _write_minimal_run(tmp_path / "run")
    exp_dir = tmp_path / "experiments"
    run_experiments(run_dir, exp_dir)
    figure_dir = tmp_path / "figures"
    result = build_figures(exp_dir, figure_dir)
    artifact_ids = {item["id"] for item in result["figures"]}
    assert {
        "fig7_case_level_distribution",
        "fig9_auxiliary_metrics",
        "table1_dataset_run_summary",
        "table2_metric_taxonomy",
    } <= artifact_ids
    assert (figure_dir / "fig7_case_level_distribution.svg").exists()
    assert (figure_dir / "fig9_auxiliary_metrics.svg").exists()
    assert (figure_dir / "table1_dataset_run_summary.csv").exists()
    assert (figure_dir / "table1_dataset_run_summary.md").exists()
    assert (figure_dir / "table2_metric_taxonomy.csv").exists()
    assert (figure_dir / "table2_metric_taxonomy.md").exists()
    fig7 = (figure_dir / "fig7_case_level_distribution.svg").read_text(encoding="utf-8")
    assert "Case-level distribution" in fig7
    table1 = (figure_dir / "table1_dataset_run_summary.csv").read_text(encoding="utf-8")
    assert "run_dir" in table1
    assert "case_count" in table1
    table2 = (figure_dir / "table2_metric_taxonomy.csv").read_text(encoding="utf-8")
    assert "L1" in table2
    assert "Tool 4" in table2


def test_build_figures_writes_method_figures_1_to_4(tmp_path: Path):
    run_dir = _write_minimal_run(tmp_path / "run")
    exp_dir = tmp_path / "experiments"
    run_experiments(run_dir, exp_dir)
    figure_dir = tmp_path / "figures"
    result = build_figures(exp_dir, figure_dir)
    artifact_ids = {item["id"] for item in result["figures"]}
    assert {
        "fig1_system_overview",
        "fig2_single_case_evidence_chain",
        "fig3_finding_graph_alignment",
        "fig4_feedback_card",
    } <= artifact_ids
    assert (figure_dir / "fig1_system_overview.svg").exists()
    assert (figure_dir / "fig2_single_case_evidence_chain.svg").exists()
    assert (figure_dir / "fig3_finding_graph_alignment.svg").exists()
    assert (figure_dir / "fig4_feedback_card.svg").exists()
    fig1 = (figure_dir / "fig1_system_overview.svg").read_text(encoding="utf-8")
    assert "System overview" in fig1
    assert "education feedback" in fig1
    fig4 = (figure_dir / "fig4_feedback_card.svg").read_text(encoding="utf-8")
    assert "Feedback card" in fig4
    assert "review" in fig4


def test_cli_figures_build_writes_run_registry_entries(tmp_path: Path):
    run_dir = _write_minimal_run(tmp_path / "run")
    exp_dir = tmp_path / "experiments"
    main(["experiments", "run", "--run-dir", str(run_dir), "--output-dir", str(exp_dir)])
    figure_dir = tmp_path / "figures"
    code = main(["figures", "build", "--experiment-dir", str(exp_dir), "--output-dir", str(figure_dir)])
    assert code == 0
    registry = json.loads((figure_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["stage"] == "figures.build"
    assert registry["entries"][-1]["metrics"]["figure_count"] >= 3
    run_registry = json.loads((run_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert run_registry["entries"][-1]["stage"] == "figures.build"


def test_cli_figures_build_rejects_missing_experiment_dir(tmp_path: Path):
    output = tmp_path / "figures"
    code = main(["figures", "build", "--experiment-dir", str(tmp_path / "missing"), "--output-dir", str(output)])
    assert code == 1
    registry = json.loads((output / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


def test_cli_dashboard_build_writes_static_html(tmp_path: Path):
    run_dir = _write_minimal_run(tmp_path / "run")
    output = tmp_path / "dashboard.html"
    code = main(["dashboard", "build", "--run-dir", str(run_dir), "--output", str(output)])
    assert code == 0
    html = output.read_text(encoding="utf-8")
    assert "medHarness2 Control Panel" in html
    assert "tool8_generate" in html
    assert "radiologist_evaluation" in html
    assert "Workflow Development" in html
    assert "workflow.sample-full" in html
    assert "workflow.reevaluate-run" in html
    assert "workflow_stages" in html
    assert "<th>Type</th>" in html
    assert "<th>Details</th>" in html
    assert "<th>Medical Model</th>" in html
    assert "Role-routed LLM five-dimension rubric judge" in html
    assert "strict no-mock/no-fallback production mode" in html
    assert "Registry-based CXR/CT/MRI plugins" in html
    assert "ReportGeneratorRegistry local models first" in html
    assert "Required" in html
    assert "Optional" in html
    assert "Judge/API Routing" in html
    registry = json.loads((run_dir / "run_registry.json").read_text(encoding="utf-8"))
    entry = registry["entries"][-1]
    assert entry["stage"] == "dashboard.build"
    assert entry["outputs"]["dashboard"] == str(output)
    assert entry["metrics"]["registry_entry_count"] == len(registry["entries"])
    assert "dashboard.build" in html


def test_cli_dashboard_build_rejects_missing_run_dir(tmp_path: Path):
    output = tmp_path / "dashboard.html"
    code = main(["dashboard", "build", "--run-dir", str(tmp_path / "missing"), "--output", str(output)])
    assert code == 1


def test_cli_dashboard_build_uses_model_roles_from_config(tmp_path: Path):
    run_dir = _write_minimal_run(tmp_path / "run")
    output = tmp_path / "dashboard.html"
    config = tmp_path / "dmx.yaml"
    config.write_text(
        """
model_roles:
  hazard_primary:
    provider: chat_completions
    model: gpt-5.5
    api_key_env: DMX_API_KEY
    base_url: https://www.DMXAPI.cn/v1
    max_retries: 3
""",
        encoding="utf-8",
    )

    code = main(
        ["dashboard", "build", "--run-dir", str(run_dir), "--output", str(output), "--config", str(config)]
    )

    assert code == 0
    html = output.read_text(encoding="utf-8")
    assert "hazard_primary" in html
    assert "gpt-5.5" in html
    assert "www.dmxapi.cn" in html
    assert "DMX_API_KEY" in html


def test_dashboard_shows_figure_and_table_artifacts(tmp_path: Path):
    run_dir = _write_minimal_run(tmp_path / "run")
    exp_dir = tmp_path / "experiments"
    figure_dir = tmp_path / "figures"
    output = tmp_path / "dashboard.html"
    main(["experiments", "run", "--run-dir", str(run_dir), "--output-dir", str(exp_dir)])
    main(["figures", "build", "--experiment-dir", str(exp_dir), "--output-dir", str(figure_dir)])
    code = main(["dashboard", "build", "--run-dir", str(run_dir), "--output", str(output)])
    assert code == 0
    registry = json.loads((run_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["metrics"]["figure_count"] == 11
    html = output.read_text(encoding="utf-8")
    assert "Figure Artifacts" in html
    assert "fig1_system_overview" in html
    assert "fig4_feedback_card" in html
    assert "fig7_case_level_distribution" in html
    assert "fig9_auxiliary_metrics" in html
    assert "table1_dataset_run_summary" in html
    assert "table2_metric_taxonomy" in html


def test_dashboard_shows_experiment_protocol_mapping(tmp_path: Path):
    run_dir = _write_minimal_run(tmp_path / "run")
    exp_dir = tmp_path / "experiments"
    output = tmp_path / "dashboard.html"
    main(["experiments", "run", "--run-dir", str(run_dir), "--output-dir", str(exp_dir)])

    code = main(["dashboard", "build", "--run-dir", str(run_dir), "--output", str(output)])

    assert code == 0
    html = output.read_text(encoding="utf-8")
    assert "Experiment Protocol" in html
    assert "Radiologist Finding Extraction Study" in html
    assert "Current Evidence" in html
    assert "Model/API Policy" in html
    assert "experiment_protocol" in html


def test_build_dashboard_includes_catalog_and_run_summary(tmp_path: Path):
    run_dir = _write_minimal_run(tmp_path / "run")
    registry_payload = {
        "schema_version": "1.0",
        "entries": [
            {
                "run_id": "run",
                "stage": "experiments.run",
                "status": "passed",
                "created_at_utc": "2026-07-10T00:00:00+00:00",
                "command": ["medharness2", "experiments", "run"],
                "config": {},
                "inputs": {"run_dir": str(run_dir)},
                "outputs": {"results": str(tmp_path / "experiments" / "results.json")},
                "metrics": {"experiment_count": 6},
                "warnings": [],
            }
        ],
    }
    (run_dir / "run_registry.json").write_text(json.dumps(registry_payload), encoding="utf-8")
    output = tmp_path / "dashboard.html"
    result = build_dashboard(run_dir, output)
    assert result["output_path"] == str(output)
    assert result["summary"]["case_count"] == 2
    assert result["summary"]["registry_entry_count"] == 1
    html = output.read_text(encoding="utf-8")
    assert "Run Registry" in html
    assert "experiments.run" in html
    assert "Workflow Development" in html
    assert "workflow.sample-full" in html
    assert output.exists()


def test_dashboard_does_not_render_missing_reader_score_as_zero():
    html = _render_reader_rows([
        {"reader": "missing", "case_count": "3", "overall_score": "", "percentile": ""},
        {"reader": "scored", "case_count": "3", "overall_score": "0.75", "percentile": "100"},
    ])

    assert "scored" in html
    assert "0.7500" in html
    assert "missing" not in html
    assert ">0.0000<" not in html


def test_dashboard_does_not_render_missing_percentile_as_p0():
    html = _render_reader_rows([
        {"reader": "scored", "case_count": "3", "overall_score": "0.75", "percentile": ""},
    ])

    assert "0.7500" in html
    assert "—" in html
    assert "P0" not in html


def _write_minimal_run(root: Path) -> Path:
    analysis = root / "analysis"
    cases = root / "workflow2_cases"
    analysis.mkdir(parents=True)
    cases.mkdir(parents=True)
    _write_json(
        root / "run_summary.json",
        {
            "summary": {"case_count": 2, "failed_case_count": 0, "reader_count": 2},
            "validation": {
                "passed": True,
                "case_count": 2,
                "real_ocr_count": 2,
                "mock_ocr_count": 0,
                "unknown_ocr_count": 0,
                "summary": {
                    "case_count": 2,
                    "modality_counts": {"cxr": 1, "ct": 1},
                    "body_part_counts": {"chest": 1, "head": 1},
                    "warning_counts": {},
                },
            },
        },
    )
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
                    "workflow1_output": str(cases / "case1.json"),
                    "human_metrics": {"likert_mean": 3.0, "structure_score": 0.55, "finding_coverage": 0.2},
                },
                {
                    "case_id": "case2",
                    "reader": "reader_b",
                    "modality": "ct",
                    "body_part": "head",
                    "workflow1_output": str(cases / "case2.json"),
                    "human_metrics": {"likert_mean": 4.0, "structure_score": 0.9, "finding_coverage": 0.1},
                },
            ],
            "per_reader": {
                "reader_a": {"case_count": 1, "overall_score": 0.5},
                "reader_b": {"case_count": 1, "overall_score": 0.8},
            },
        },
    )
    _write_json(
        root / "workflow3.json",
        {
            "case_count": 2,
            "reader_count": 2,
            "reader_percentiles": {
                "reader_a": {"overall_score": 0.5, "percentile": 50.0},
                "reader_b": {"overall_score": 0.8, "percentile": 100.0},
            },
            "statistics": {"readers": {"overall_score": {"mean": 0.65}}},
        },
    )
    _write_json(
        analysis / "analysis_summary.json",
        {
            "case_count": 2,
            "failed_case_count": 0,
            "reader_count": 2,
            "generated_report_count": 3,
            "ranking_count": 2,
            "pairwise_count": 2,
            "quality_gate_passed_count": 2,
            "quality_gate_failed_count": 1,
            "generated_report_source_counts": {"medharness_cli": 2, "local_vlm_fallback": 1},
            "generated_report_model_counts": {"maira_2": 1, "qwen3-vl-4b": 1, "dia_llama": 1},
        },
    )
    _write_csv(
        analysis / "reader_summary.csv",
        ["reader", "case_count", "overall_score", "percentile"],
        [["reader_a", "1", "0.5", "50.0"], ["reader_b", "1", "0.8", "100.0"]],
    )
    _write_csv(
        analysis / "model_source_summary.csv",
        ["model", "source", "report_count", "quality_passed", "quality_failed", "quality_unknown", "selected_top_n_count", "warnings"],
        [
            ["maira_2", "medharness_cli", "1", "1", "0", "0", "1", ""],
            ["qwen3-vl-4b", "local_vlm_fallback", "1", "0", "1", "0", "0", "quality_gate_failed:1"],
        ],
    )
    _write_csv(
        analysis / "modality_body_part_summary.csv",
        ["modality", "body_part", "case_count", "generated_report_count", "ranking_count", "pairwise_count", "quality_passed", "quality_failed", "models", "sources"],
        [
            ["cxr", "chest", "1", "2", "1", "1", "2", "0", "maira_2:1", "medharness_cli:2"],
            ["ct", "head", "1", "1", "1", "1", "0", "1", "qwen3-vl-4b:1", "local_vlm_fallback:1"],
        ],
    )
    _write_csv(
        analysis / "case_routes.csv",
        ["case_id", "reader", "modality", "body_part", "generated_report_count", "ranking_count", "pairwise_count", "models", "sources", "selected_top_n_models", "quality_passed", "quality_failed", "warnings"],
        [
            ["case1", "reader_a", "cxr", "chest", "2", "1", "1", "maira_2", "medharness_cli", "maira_2", "2", "0", ""],
            ["case2", "reader_b", "ct", "head", "1", "1", "1", "qwen3-vl-4b", "local_vlm_fallback", "", "0", "1", "quality_gate_failed:1"],
        ],
    )
    _write_csv(
        analysis / "quality_gate_failures.csv",
        ["case_id", "reader", "modality", "body_part", "model", "source", "warnings", "conflicts", "source_batch_result"],
        [["case2", "reader_b", "ct", "head", "qwen3-vl-4b", "local_vlm_fallback", "quality_gate_failed", "{}", ""]],
    )
    _write_json(
        cases / "case1.json",
        {
            "human_evaluation": {"finding_graph": {"backend": "cxr_rule", "findings": [{"id": "f1"}]}},
            "generated_reports": [{"model": "maira_2", "source": "medharness_cli", "warnings": [], "metadata": {"quality_gate": {"passed": True}}}],
            "pairwise_comparisons": [{"comparison": {"hazards": {"errors": [{"error_type": "omission_finding", "hazard_level": 4}]}}}],
        },
    )
    _write_json(
        cases / "case2.json",
        {
            "human_evaluation": {"finding_graph": {"backend": "placeholder", "findings": [{"id": "f1"}]}},
            "generated_reports": [{"model": "qwen3-vl-4b", "source": "local_vlm_fallback", "warnings": ["quality_gate_failed"], "metadata": {"quality_gate": {"passed": False}}}],
            "pairwise_comparisons": [],
        },
    )
    return root


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
