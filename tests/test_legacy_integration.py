from __future__ import annotations

import json
import subprocess
from pathlib import Path

from medharness2.config import AppConfig, GeneratorConfig, LLMConfig, load_config
from medharness2.generators.registry import ReportGeneratorRegistry
from medharness2.llm_client import LLMClient
from medharness2.tools.tool2_extract import extract_findings
from medharness2.tools.tool8_generate import generate_reports
from medharness2.workflows.batch_readers import run_batch_readers


def test_artifact_generator_reads_existing_jsonl(tmp_path: Path):
    artifact = tmp_path / "generation.jsonl"
    artifact.write_text(
        json.dumps(
            {
                "case_id": "case-a",
                "model_key": "chexagent",
                "generated_report": "FINDINGS: No pneumothorax. IMPRESSION: Normal chest.",
                "modality": "xray",
                "body_part": "chest",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            default_models=["chexagent"],
            local_models=[
                {
                    "key": "chexagent",
                    "source": "artifact_reuse",
                    "supported_modalities": ["xray", "cxr"],
                    "source_generation_jsonl": str(artifact),
                }
            ],
        )
    )
    reports = generate_reports("image.png", "cxr", config=cfg)
    assert reports[0].model == "chexagent"
    assert "No pneumothorax" in reports[0].report
    assert reports[0].source == "artifact_reuse"


def test_fallback_records_failed_local_generation_attempt(tmp_path: Path):
    missing_artifact = tmp_path / "missing.jsonl"
    cfg = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=True,
            default_models=["missing_artifact"],
            local_models=[
                {
                    "key": "missing_artifact",
                    "source": "artifact_reuse",
                    "supported_modalities": ["xray", "cxr"],
                    "source_generation_jsonl": str(missing_artifact),
                }
            ],
        )
    )
    reports = generate_reports("image.png", "cxr", config=cfg, llm_client=LLMClient(cfg))
    assert reports[0].source == "cloud_fallback"
    assert reports[0].metadata["local_attempts"][0]["model"] == "missing_artifact"
    assert "artifact_missing" in reports[0].metadata["local_attempts"][0]["warnings"]


def test_legacy_cli_generator_invokes_medharness_script(monkeypatch, tmp_path: Path):
    output_jsonl = tmp_path / "legacy_out.jsonl"
    legacy_config = tmp_path / "legacy_models.yaml"
    legacy_config.write_text(
        "models:\n"
        "  maira_2:\n"
        "    python_bin: /stale/bin/python\n",
        encoding="utf-8",
    )

    def fake_run(cmd, check, capture_output, text, timeout):
        assert cmd[0] == "/opt/isolated/bin/python"
        assert "/data/isbi/gzp/medHarness/scripts/run_report_generation.py" in cmd
        config_path = Path(cmd[cmd.index("--config") + 1])
        assert config_path != legacy_config
        assert "/opt/isolated/bin/python" in config_path.read_text(encoding="utf-8")
        input_path = Path(cmd[cmd.index("--input-jsonl") + 1])
        input_row = json.loads(input_path.read_text(encoding="utf-8"))
        assert Path(input_row["image_paths"][0]).is_absolute()
        out_index = cmd.index("--output-jsonl") + 1
        Path(cmd[out_index]).write_text(
            json.dumps({"model_key": "maira_2", "generated_text": "FINDINGS: Clear lungs.", "modality": "xray"})
            + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cfg = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            default_models=["maira_2"],
            local_models=[
                {
                    "key": "maira_2",
                    "source": "medharness_cli",
                    "supported_modalities": ["xray", "cxr"],
                    "medharness_model_key": "maira_2",
                    "python_bin": "/opt/isolated/bin/python",
                    "config_path": str(legacy_config),
                    "output_jsonl": str(output_jsonl),
                    "ready": True,
                }
            ],
        )
    )
    reports = generate_reports("image.png", "cxr", reference_report="human report", config=cfg)
    assert reports[0].model == "maira_2"
    assert reports[0].source == "medharness_cli"
    assert reports[0].report == "FINDINGS: Clear lungs."


def test_legacy_cli_generator_uses_brain_mri_prompt_for_braingemma(monkeypatch, tmp_path: Path):
    seen_prompt = ""

    def fake_run(cmd, check, capture_output, text, timeout):
        nonlocal seen_prompt
        input_path = Path(cmd[cmd.index("--input-jsonl") + 1])
        output_path = Path(cmd[cmd.index("--output-jsonl") + 1])
        input_row = json.loads(input_path.read_text(encoding="utf-8"))
        seen_prompt = input_row["prompt"]
        output_path.write_text(
            json.dumps({"model_key": "brain_gemma3d", "generated_text": "FINDINGS: Brain MRI report.", "modality": "mri"})
            + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    volume = tmp_path / "brain.nii.gz"
    volume.write_text("volume", encoding="utf-8")
    cfg = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=False,
            default_models=["brain_gemma3d"],
            local_models=[
                {
                    "key": "brain_gemma3d",
                    "source": "medharness_cli",
                    "supported_modalities": ["mri"],
                    "supported_body_parts": ["brain"],
                    "medharness_model_key": "brain_gemma3d",
                    "ready": True,
                }
            ],
        )
    )
    reports = generate_reports(str(volume), "mri", body_part="brain", reference_report="human report", config=cfg)
    assert reports[0].model == "brain_gemma3d"
    assert "brain MRI FLAIR" in seen_prompt


def test_batch_reader_uses_selected_mri_series_prompt_for_legacy_cli(monkeypatch, tmp_path: Path):
    script = tmp_path / "run_report_generation.py"
    script.write_text("# fake legacy script\n", encoding="utf-8")
    legacy_config = tmp_path / "reportgen_models.yaml"
    legacy_config.write_text("models:\n  brain_gemma3d:\n    python_bin: python\n", encoding="utf-8")
    report = tmp_path / "report.txt"
    volume = tmp_path / "brain.nii.gz"
    report.write_text("FINDINGS: Brain lesion. IMPRESSION: Brain lesion.", encoding="utf-8")
    volume.write_text("volume", encoding="utf-8")
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "case_id": "case1",
                "reader": "doc_a",
                "modality": "mri",
                "body_part": "brain",
                "report_text": str(report),
                "image_paths": [],
                "volume_path": str(volume),
                "derived_assets": {
                    "volume_path": str(volume),
                    "selected_series_type": "t2",
                    "selected_series_description": "T2_FSE_8mm",
                },
                "warnings": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    seen_prompts: list[str] = []

    def fake_run(cmd, check, capture_output, text, timeout):
        input_path = Path(cmd[cmd.index("--input-jsonl") + 1])
        output_path = Path(cmd[cmd.index("--output-jsonl") + 1])
        input_row = json.loads(input_path.read_text(encoding="utf-8"))
        seen_prompts.append(input_row["prompt"])
        output_path.write_text(
            json.dumps(
                {
                    "case_id": input_row["case_id"],
                    "model_key": "brain_gemma3d",
                    "generated_text": "FINDINGS: Brain MRI report.",
                    "modality": "mri",
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
            cloud_fallback_enabled=False,
            default_models=["brain_gemma3d"],
            include_legacy_ready_models=False,
            local_models=[
                {
                    "key": "brain_gemma3d",
                    "source": "medharness_cli",
                    "supported_modalities": ["mri"],
                    "supported_body_parts": ["brain"],
                    "medharness_model_key": "brain_gemma3d",
                    "script_path": str(script),
                    "config_path": str(legacy_config),
                    "ready": True,
                }
            ],
        ),
    )
    result = run_batch_readers(manifest, tmp_path / "workflow2.json", config=cfg, model_keys=["brain_gemma3d"], model_sources=["medharness_cli"])
    assert result["failed_case_count"] == 0
    assert seen_prompts == ["Generate a radiology report for this brain MRI T2 scan."]


def test_legacy_prompt_uses_generic_brain_mri_for_unknown_series():
    from medharness2.generators.registry import _legacy_prompt

    assert (
        _legacy_prompt(
            "mri",
            "brain",
            selected_series_type="largest",
            selected_series_description="FGR",
        )
        == "Generate a radiology report for this brain MRI study."
    )


def test_registry_discovers_ready_legacy_report_generation_models():
    registry = ReportGeneratorRegistry(AppConfig())
    keys = set(registry.entries)
    assert {"maira_2", "chexagent_srrg_findings_full", "medgemma_srrg_findings", "brain_gemma3d"} <= keys
    cxr = {entry.key for entry in registry.compatible_entries("cxr", body_part="chest")}
    assert {"maira_2", "chexagent_srrg_findings_full", "chexagent_srrg_impression_full"} <= cxr
    assert "brain_gemma3d" not in cxr
    brain_mri = {entry.key for entry in registry.compatible_entries("mri", body_part="brain")}
    assert "brain_gemma3d" in brain_mri


def test_registry_exposes_legacy_model_readiness_metadata():
    registry = ReportGeneratorRegistry(AppConfig())
    maira = registry.entries["maira_2"]
    assert maira.report_trained is True
    assert maira.category == "report_trained_target"
    assert maira.fresh_inference is True
    assert maira.readiness_metadata()["route_role"] == "fresh_report_trained_local"
    assert "CXR findings" in maira.report_training

    chexagent = registry.entries["chexagent"]
    assert chexagent.fresh_inference is False
    assert chexagent.readiness_metadata()["route_role"] == "artifact_report_trained_local"


def test_registry_excludes_legacy_quality_blocked_models_from_formal_routes():
    registry = ReportGeneratorRegistry(AppConfig())
    cxr_models = {entry.key for entry in registry.compatible_entries("cxr", body_part="chest")}
    assert "chexagent_srrg_findings_full" in cxr_models
    assert "lingshu_srrg_impression" in cxr_models
    assert "chexagent_srrg_findings" not in cxr_models
    assert "lingshu_srrg_findings" not in cxr_models
    assert "qwen25vl_7b_instruct" not in registry.entries


def test_registry_star_selects_all_compatible_local_generators():
    registry = ReportGeneratorRegistry(AppConfig())
    selected = {entry.key for entry in registry.select("cxr", requested=["*"], body_part="chest")}
    assert "maira_2" in selected
    assert "chexagent_srrg_findings_full" in selected
    assert "brain_gemma3d" not in selected


def test_registry_filters_all_compatible_by_source():
    registry = ReportGeneratorRegistry(AppConfig())
    selected = {entry.key: entry.source for entry in registry.select("cxr", requested=["*"], body_part="chest", sources={"artifact_reuse"})}
    assert "chexagent" in selected
    assert "llava_rad" in selected
    assert "maira_2" not in selected
    assert set(selected.values()) == {"artifact_reuse"}


def test_default_config_uses_maira2_compatible_python_bin():
    registry = ReportGeneratorRegistry(load_config())
    assert registry.entries["maira_2"].python_bin == "/data/miniconda3/envs/deepseek_2/bin/python"


def test_cxr_rule_extractor_marks_negated_observation_absent():
    graph = extract_findings("FINDINGS: There is no pneumothorax. Mild right lung opacity.", modality="cxr", backend="cxr_rule")
    pneumothorax = [item for item in graph["findings"] if item["observation"] == "pneumothorax"][0]
    assert pneumothorax["certainty"] == "absent"
    assert graph["backend"] == "cxr_rule"
    assert graph["coverage"] > 0


def test_openai_extract_text_and_json_payload(monkeypatch):
    calls = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {
                    "output": [
                        {
                            "content": [
                                {"type": "output_text", "text": "{\"ok\": true}"}
                            ]
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = LLMClient(AppConfig(llm=LLMConfig(provider="openai", model="gpt-test", max_retries=1)))
    result = client.call("return json", response_format="json")
    assert result == "{\"ok\": true}"
    assert calls["body"]["text"]["format"]["type"] == "json_object"


def test_pat_file_is_gitignored():
    ignore_file = Path(".gitignore").read_text(encoding="utf-8")
    assert "docs/pat.txt" in ignore_file
