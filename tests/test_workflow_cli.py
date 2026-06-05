from __future__ import annotations

import json
from pathlib import Path

from medharness2.cli import main
from medharness2.config import AppConfig, GeneratorConfig, load_config
from medharness2.llm_client import build_mock_client
from medharness2.modules.pairwise_report import evaluate_pairwise
from medharness2.modules.single_report import evaluate_single_report
from medharness2.schema import GeneratedReport
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


def test_pairwise_aligns_candidate_against_human_reference():
    result = evaluate_pairwise(
        "FINDINGS: Mild right lung opacity. No pneumothorax.",
        "FINDINGS: Mild right lung opacity. Small pleural effusion.",
        modality="cxr",
        llm_client=build_mock_client(),
    )
    error_types = [item["error_type"] for item in result["alignment"]["error_candidates"]]
    assert "false_finding" in error_types
    assert "omission_finding" in error_types
    assert result["alignment"]["candidate_only"][0]["observation"] == "effusion"


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


def test_single_case_quality_gate_blocks_off_domain_generated_report(tmp_path: Path):
    report = tmp_path / "human.txt"
    image = tmp_path / "brain.nii.gz"
    output = tmp_path / "result.json"
    report.write_text("FINDINGS: Brain MRI without acute infarct. IMPRESSION: No acute intracranial abnormality.", encoding="utf-8")
    image.write_text("dummy", encoding="utf-8")
    generated = GeneratedReport(
        model="brain_gemma3d",
        source="medharness_cli",
        report="Findings: A left hip radiograph shows sclerosis of the femoral head.",
        modality="mri",
    )
    result = run_single_case(
        report_path=report,
        image_path=image,
        output_path=output,
        modality="mri",
        body_part="brain",
        precomputed_generated_reports=[generated],
        config=AppConfig(generator=GeneratorConfig(default_models=[], local_models=[])),
        llm_client=build_mock_client(),
    )
    blocked = result["generated_reports"][0]
    assert "quality_gate_failed" in blocked["warnings"]
    assert "body_part_mismatch" in blocked["warnings"]
    assert "modality_mismatch" in blocked["warnings"]
    assert blocked["metadata"]["quality_gate"]["passed"] is False
    assert result["rankings"] == []
    assert result["pairwise_comparisons"] == []


def test_single_case_quality_gate_keeps_matching_cxr_report(tmp_path: Path):
    report = tmp_path / "human.txt"
    image = tmp_path / "chest.png"
    output = tmp_path / "result.json"
    report.write_text("FINDINGS: No pneumothorax. IMPRESSION: Normal chest.", encoding="utf-8")
    image.write_text("dummy", encoding="utf-8")
    generated = GeneratedReport(
        model="chexagent_srrg_findings_full",
        source="medharness_cli",
        report="FINDINGS: Lungs are clear. No pleural effusion or pneumothorax.",
        modality="cxr",
    )
    result = run_single_case(
        report_path=report,
        image_path=image,
        output_path=output,
        modality="cxr",
        body_part="chest",
        top_n=1,
        precomputed_generated_reports=[generated],
        config=AppConfig(generator=GeneratorConfig(default_models=[], local_models=[])),
        llm_client=build_mock_client(),
    )
    kept = result["generated_reports"][0]
    assert kept["metadata"]["quality_gate"]["passed"] is True
    assert "quality_gate_failed" not in kept["warnings"]
    assert result["rankings"][0]["model"] == "chexagent_srrg_findings_full"
    assert len(result["pairwise_comparisons"]) == 1


def test_single_case_fallback_uses_primary_image_instead_of_volume(tmp_path: Path):
    report = tmp_path / "human.txt"
    primary = tmp_path / "contact_sheet.png"
    volume = tmp_path / "volume.nii.gz"
    output = tmp_path / "result.json"
    report.write_text("FINDINGS: Head CT without hemorrhage. IMPRESSION: No acute abnormality.", encoding="utf-8")
    primary.write_bytes(b"\x89PNG\r\n\x1a\n")
    volume.write_text("volume", encoding="utf-8")

    class RecordingClient:
        def __init__(self):
            self.generation_image_path = None

        def call(self, prompt, image_path=None, **kwargs):
            if kwargs.get("response_json") is not None:
                return json.dumps(kwargs["response_json"])
            if prompt.startswith("Generate a concise radiology report"):
                self.generation_image_path = image_path
                return "FINDINGS: No acute intracranial hemorrhage. IMPRESSION: No acute abnormality."
            return "{}"

    client = RecordingClient()
    cfg = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=True,
            default_models=[],
            local_models=[],
            include_legacy_ready_models=False,
        )
    )
    run_single_case(
        report_path=report,
        image_path=primary,
        output_path=output,
        prepared_assets={"primary_image": str(primary), "volume_path": str(volume)},
        modality="ct",
        body_part="head",
        config=cfg,
        llm_client=client,
    )
    assert client.generation_image_path == str(primary)


def test_cli_sample_full(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    (case_dir / "Y1").write_text("dummy", encoding="utf-8")
    (sample_root / "CR" / "CR001" / "report.pdf").write_text("dummy pdf", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "llm:",
                "  provider: mock",
                "extractor:",
                "  backend: placeholder",
                "generator:",
                "  cloud_fallback_enabled: true",
                "  default_models: []",
                "  local_models: []",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "run"
    code = main(
        [
            "workflow",
            "sample-full",
            "--sample-root",
            str(sample_root),
            "--output-dir",
            str(output_dir),
            "--limit",
            "1",
            "--expected-cases",
            "1",
            "--config",
            str(config_path),
        ]
    )
    assert code == 0
    payload = json.loads((output_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert payload["validation"]["passed"] is True


def test_cli_sample_full_dry_run_all_compatible(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    (case_dir / "Y1").write_text("dummy", encoding="utf-8")
    (sample_root / "CR" / "CR001" / "report.pdf").write_text("dummy pdf", encoding="utf-8")
    output_dir = tmp_path / "run"
    code = main(
        [
            "workflow",
            "sample-full",
            "--sample-root",
            str(sample_root),
            "--output-dir",
            str(output_dir),
            "--limit",
            "1",
            "--dry-run",
            "--all-compatible-local-models",
        ]
    )
    assert code == 0
    route_plan = json.loads((output_dir / "route_plan.json").read_text(encoding="utf-8"))
    assert "maira_2" in route_plan["cases"][0]["compatible_model_keys"]
    assert not (output_dir / "workflow2.json").exists()


def test_cli_sample_full_dry_run_filters_model_source(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    (case_dir / "Y1").write_text("dummy", encoding="utf-8")
    (sample_root / "CR" / "CR001" / "report.pdf").write_text("dummy pdf", encoding="utf-8")
    output_dir = tmp_path / "run"
    code = main(
        [
            "workflow",
            "sample-full",
            "--sample-root",
            str(sample_root),
            "--output-dir",
            str(output_dir),
            "--limit",
            "1",
            "--dry-run",
            "--all-compatible-local-models",
            "--model-source",
            "artifact_reuse",
        ]
    )
    assert code == 0
    route_plan = json.loads((output_dir / "route_plan.json").read_text(encoding="utf-8"))
    assert "chexagent" in route_plan["cases"][0]["compatible_model_keys"]
    assert "maira_2" not in route_plan["cases"][0]["compatible_model_keys"]


def test_cli_models_list_shows_local_ready_generators(capsys):
    code = main(["models", "list", "--modality", "cxr", "--body-part", "chest"])
    captured = capsys.readouterr()
    assert code == 0
    assert "maira_2" in captured.out
    assert "chexagent_srrg_findings_full" in captured.out
    assert "brain_gemma3d" not in captured.out


def test_cli_preflight_returns_nonzero_when_real_ocr_is_blocked(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    (case_dir / "Y1").write_text("dummy", encoding="utf-8")
    (sample_root / "CR" / "CR001" / "report.pdf").write_text("dummy pdf", encoding="utf-8")
    output = tmp_path / "preflight.json"
    code = main(
        [
            "workflow",
            "preflight",
            "--sample-root",
            str(sample_root),
            "--output",
            str(output),
            "--limit",
            "1",
            "--require-real-ocr",
            "--all-compatible-local-models",
        ]
    )
    assert code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "real_ocr_required_but_provider_is_mock" in payload["blockers"]
