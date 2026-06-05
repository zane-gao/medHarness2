from __future__ import annotations

import json
import subprocess
from pathlib import Path

from medharness2.config import AppConfig, LLMConfig
from medharness2.validation.preflight import run_sample_preflight


def test_preflight_blocks_mock_ocr_when_real_ocr_required(tmp_path: Path):
    sample_root = _write_minimal_sample(tmp_path)
    output = tmp_path / "preflight.json"
    result = run_sample_preflight(
        sample_root,
        output,
        config=AppConfig(llm=LLMConfig(provider="mock")),
        require_real_ocr=True,
        limit=1,
        model_keys=["*"],
    )
    assert output.exists()
    assert result["passed"] is False
    assert "real_ocr_required_but_provider_is_mock" in result["blockers"]
    assert result["sample"]["case_count"] == 1
    assert result["routing"]["cases_with_local_candidates"] == 1


def test_preflight_reports_missing_local_vlm_ocr_model(monkeypatch, tmp_path: Path):
    sample_root = _write_minimal_sample(tmp_path)
    output = tmp_path / "preflight.json"
    script = tmp_path / "run_report_generation.py"
    script.write_text("# fake runner\n", encoding="utf-8")
    legacy_config = tmp_path / "reportgen_models.yaml"
    legacy_config.write_text("models: {}\n", encoding="utf-8")

    def fake_run(cmd, check, capture_output, text, timeout):
        assert "--dry-run" in cmd
        return subprocess.CompletedProcess(
            cmd,
            2,
            stdout=json.dumps(
                {
                    "model_key": "qwen25vl_7b_instruct",
                    "status": "debug_asset_missing",
                    "missing_paths": ["/missing/qwen"],
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_sample_preflight(
        sample_root,
        output,
        config=AppConfig(
            llm=LLMConfig(
                provider="local_vlm_cli",
                model="qwen25vl_7b_instruct",
                local_cli_script=str(script),
                local_cli_config_path=str(legacy_config),
                local_cli_timeout_sec=30,
            )
        ),
        require_real_ocr=True,
        limit=1,
        model_keys=["*"],
    )
    assert result["passed"] is False
    assert "local_vlm_cli_model_unavailable" in result["blockers"]
    assert result["ocr"]["provider"] == "local_vlm_cli"
    assert result["ocr"]["dry_run"]["status"] == "debug_asset_missing"


def test_preflight_accepts_present_local_hf_vlm_ocr_model(tmp_path: Path):
    sample_root = _write_minimal_sample(tmp_path)
    model_dir = tmp_path / "qwen3-vl-4b"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "preprocessor_config.json").write_text("{}", encoding="utf-8")
    (model_dir / "tokenizer_config.json").write_text("{}", encoding="utf-8")
    (model_dir / "model.safetensors").write_bytes(b"weights")
    result = run_sample_preflight(
        sample_root,
        tmp_path / "preflight.json",
        config=AppConfig(
            llm=LLMConfig(
                provider="local_hf_vlm",
                model="qwen3-vl-4b",
                local_hf_model_path=str(model_dir),
            )
        ),
        require_real_ocr=True,
        limit=1,
        model_keys=["*"],
    )
    assert result["passed"] is True
    assert result["ocr"]["provider"] == "local_hf_vlm"
    assert result["ocr"]["status"] == "ready"


def _write_minimal_sample(tmp_path: Path) -> Path:
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    (case_dir / "Y1").write_text("dummy", encoding="utf-8")
    (sample_root / "CR" / "CR001" / "report.pdf").write_text("dummy pdf", encoding="utf-8")
    return sample_root
