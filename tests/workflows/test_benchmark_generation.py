from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from medharness2.config import AppConfig, GeneratorConfig
from medharness2.workflows.benchmark_generation import plan_generation_benchmark, run_generation_benchmark


def _manifest(path: Path) -> Path:
    image = path.parent / "image.png"
    image.write_bytes(b"png")
    return _manifest_with_assets(
        path,
        modality="cxr",
        body_part="chest",
        image_path=image,
    )


def _manifest_with_assets(
    path: Path,
    *,
    modality: str,
    body_part: str,
    image_path: Path | None = None,
    volume_path: Path | None = None,
) -> Path:
    report = path.parent / "reference.txt"
    report.write_text("PATIENT_CANARY_9271 FINDINGS: Hidden reference answer.", encoding="utf-8")
    path.write_text(
        json.dumps(
            {
                "case_id": "case-1",
                "reader": "reader-a",
                "modality": modality,
                "body_part": body_part,
                "report_pdf": "",
                "report_text": str(report),
                "image_paths": [str(image_path)] if image_path else [],
                "volume_path": str(volume_path) if volume_path else None,
                "derived_assets": {
                    **({"primary_image": str(image_path)} if image_path else {}),
                    **({"volume_path": str(volume_path)} if volume_path else {}),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _config(evidence_tier: str) -> AppConfig:
    return AppConfig(
        generator=GeneratorConfig(
            include_legacy_ready_models=False,
            cloud_fallback_enabled=False,
            default_models=["benchmark-model"],
            local_models=[
                {
                    "key": "benchmark-model",
                    "title": "Benchmark model",
                    "source": "local_stub",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "ready": True,
                    "report_trained": True,
                    "fresh_inference": True,
                    "evidence_tier": evidence_tier,
                }
            ],
        )
    )


def test_formal_benchmark_plan_rejects_exploratory_models(tmp_path: Path):
    plan = plan_generation_benchmark(_manifest(tmp_path / "manifest.jsonl"), config=_config("exploratory_fresh"))

    assert plan["status"] == "not_ready"
    assert plan["formal_ready_case_count"] == 0
    assert plan["violations"][0]["evidence_tier"] == "exploratory_fresh"
    assert plan["blocking_violations"][0]["reason"] == "no_formal_candidate"
    assert plan["case_coverage"]["covered_case_count"] == 0
    assert plan["case_coverage"]["uncovered_case_count"] == 1


def test_formal_benchmark_plan_defaults_to_all_compatible_models(tmp_path: Path):
    config = _config("exploratory_fresh")
    config.generator.local_models.append(
        {
            "key": "second-benchmark-model",
            "title": "Second benchmark model",
            "source": "medharness_cli",
            "supported_modalities": ["cxr"],
            "supported_body_parts": ["chest"],
            "ready": True,
            "report_trained": True,
            "fresh_inference": True,
            "evidence_tier": "exploratory_fresh",
        }
    )

    plan = plan_generation_benchmark(_manifest(tmp_path / "manifest.jsonl"), config=config)

    assert {item["model"] for item in plan["cases"][0]["models"]} == {
        "benchmark-model",
        "second-benchmark-model",
    }


def test_formal_plan_separates_eligible_and_rejected_models(tmp_path: Path):
    config = _formal_config(tmp_path)
    config.generator.local_models.append(_exploratory_model())

    plan = plan_generation_benchmark(_manifest(tmp_path / "manifest.jsonl"), config=config)

    assert plan["status"] == "ready"
    assert plan["formal_ready_case_count"] == 1
    assert [item["model"] for item in plan["eligible_models"]] == [
        "benchmark-model"
    ]
    assert [item["model"] for item in plan["selected_formal_candidates"]] == [
        "benchmark-model"
    ]
    assert [item["model"] for item in plan["rejected_models"]] == [
        "exploratory-model"
    ]
    assert "non_formal_evidence_tier" in plan["rejected_models"][0]["reasons"]
    case_plan = plan["cases"][0]
    assert [item["model"] for item in case_plan["eligible_models"]] == [
        "benchmark-model"
    ]
    assert [
        item["model"] for item in case_plan["selected_formal_candidates"]
    ] == ["benchmark-model"]
    assert [item["model"] for item in case_plan["rejected_models"]] == [
        "exploratory-model"
    ]
    assert plan["case_coverage"] == {
        "covered_case_count": 1,
        "uncovered_case_count": 0,
        "coverage_rate": 1.0,
        "by_stratum": {
            "cxr/chest": {
                "case_count": 1,
                "covered_case_count": 1,
                "coverage_rate": 1.0,
            }
        },
    }


def test_formal_plan_reports_unknown_requested_model_without_hiding_valid_candidate(
    tmp_path: Path,
):
    plan = plan_generation_benchmark(
        _manifest(tmp_path / "manifest.jsonl"),
        config=_formal_config(tmp_path),
        model_keys=["benchmark-model", "missing-model"],
    )

    assert plan["status"] == "ready"
    assert [item["model"] for item in plan["selected_formal_candidates"]] == [
        "benchmark-model"
    ]
    assert [item["model"] for item in plan["rejected_models"]] == [
        "missing-model"
    ]
    assert plan["rejected_models"][0]["reasons"] == [
        "requested_model_not_found"
    ]
    assert plan["cases"][0]["rejected_models"][0]["model"] == "missing-model"
    assert any(
        violation["model"] == "missing-model"
        and violation["reason"] == "requested_model_not_found"
        for violation in plan["violations"]
    )


def test_benchmark_plan_uses_image_for_cxr_even_when_volume_exists(tmp_path: Path):
    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    volume = tmp_path / "volume.nii.gz"
    volume.write_bytes(b"nifti")
    manifest = _manifest_with_assets(
        tmp_path / "manifest.jsonl",
        modality="cxr",
        body_part="chest",
        image_path=image,
        volume_path=volume,
    )

    plan = plan_generation_benchmark(manifest, config=_config("exploratory_fresh"))

    assert plan["cases"][0]["input_asset"] == {
        "kind": "image",
        "path": str(image),
        "exists": True,
        "selection_policy": "2d_image_required",
    }


@pytest.mark.parametrize("modality", ["ct", "mri"])
def test_benchmark_plan_uses_volume_for_3d_modalities(
    tmp_path: Path,
    modality: str,
):
    image = tmp_path / "preview.png"
    image.write_bytes(b"png")
    volume = tmp_path / "volume.nii.gz"
    volume.write_bytes(b"nifti")
    manifest = _manifest_with_assets(
        tmp_path / "manifest.jsonl",
        modality=modality,
        body_part="chest" if modality == "ct" else "brain",
        image_path=image,
        volume_path=volume,
    )
    config = _config("exploratory_fresh")
    config.generator.local_models[0]["supported_modalities"] = [modality]
    config.generator.local_models[0]["supported_body_parts"] = [
        "chest" if modality == "ct" else "brain"
    ]

    plan = plan_generation_benchmark(manifest, config=config)

    assert plan["cases"][0]["input_asset"] == {
        "kind": "volume",
        "path": str(volume),
        "exists": True,
        "selection_policy": "3d_volume_required",
    }


def test_benchmark_plan_blocks_3d_case_when_volume_does_not_exist(tmp_path: Path):
    image = tmp_path / "preview.png"
    image.write_bytes(b"png")
    missing_volume = tmp_path / "missing.nii.gz"
    manifest = _manifest_with_assets(
        tmp_path / "manifest.jsonl",
        modality="ct",
        body_part="chest",
        image_path=image,
        volume_path=missing_volume,
    )
    config = _config("exploratory_fresh")
    config.generator.local_models[0]["supported_modalities"] = ["ct"]

    plan = plan_generation_benchmark(manifest, config=config)

    assert plan["status"] == "not_ready"
    assert plan["cases"][0]["input_asset"]["kind"] == "volume"
    assert plan["cases"][0]["input_asset"]["exists"] is False
    assert any(
        violation["reason"] == "input_asset_not_found"
        for violation in plan["violations"]
    )


def test_formal_benchmark_plan_rejects_self_declared_tier_without_frozen_provenance(tmp_path: Path):
    plan = plan_generation_benchmark(_manifest(tmp_path / "manifest.jsonl"), config=_config("formal_fresh"))

    assert plan["status"] == "not_ready"
    reasons = {item["reason"] for item in plan["violations"]}
    assert "unsupported_formal_source" in reasons
    assert "missing_model_sha256" in reasons
    assert "missing_formal_validation_id" in reasons


def test_formal_benchmark_run_refuses_non_formal_source(tmp_path: Path):
    with pytest.raises(ValueError, match="not formal-ready"):
        run_generation_benchmark(
            _manifest(tmp_path / "manifest.jsonl"),
            tmp_path / "out",
            config=_config("artifact"),
            formal=True,
        )


def test_formal_benchmark_runs_fresh_only_without_reference_leakage(tmp_path: Path):
    result = run_generation_benchmark(
        _manifest(tmp_path / "manifest.jsonl"),
        tmp_path / "out",
        config=_formal_config(tmp_path),
        formal=True,
    )

    assert result["schema_version"] == "2.0"
    assert result["status"] == "succeeded"
    assert result["case_count"] == 1
    assert result["result_count"] == 1
    row = json.loads((tmp_path / "out" / "benchmark_results.jsonl").read_text().splitlines()[0])
    assert row["generated_report"]["evidence_tier"] == "formal_fresh"
    assert row["reference_report_used"] is False
    assert "PATIENT_CANARY" not in json.dumps(row)
    assert "Reference report was provided" not in row["generated_report"]["report"]
    manifest_path = tmp_path / "out" / "benchmark_manifest.json"
    benchmark_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert benchmark_manifest["artifact_sha256"] == {
        "results": _file_sha256(tmp_path / "out" / "benchmark_results.jsonl"),
        "summary": _file_sha256(tmp_path / "out" / "benchmark_summary.json"),
    }


def test_formal_benchmark_run_excludes_rejected_exploratory_models(tmp_path: Path):
    config = _formal_config(tmp_path)
    config.generator.local_models.append(_exploratory_model())

    result = run_generation_benchmark(
        _manifest(tmp_path / "manifest.jsonl"),
        tmp_path / "out",
        config=config,
        formal=True,
    )

    assert result["status"] == "succeeded"
    assert result["result_count"] == 1
    assert result["model_counts"] == {"benchmark-model": 1}
    rows = [
        json.loads(line)
        for line in (tmp_path / "out" / "benchmark_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["model"] for row in rows] == ["benchmark-model"]


def test_benchmark_batches_cases_per_medharness_model(tmp_path: Path):
    manifest = _two_case_manifest(tmp_path / "manifest.jsonl")
    config, invocation_counter = _batch_formal_config(tmp_path)

    result = run_generation_benchmark(
        manifest,
        tmp_path / "out",
        config=config,
        formal=True,
    )

    assert invocation_counter.read_text(encoding="utf-8") == "1"
    assert result["status"] == "succeeded"
    assert result["result_count"] == 2
    assert result["execution_mode_counts"] == {"batch": 2}
    assert result["reference_report_used_count"] == 0
    assert result["empty_report_count"] == 0
    assert result["unique_report_count"] == 1
    assert result["unique_report_rate"] == 0.5
    assert result["latency_sec"]["count"] == 2
    assert result["latency_sec"]["min"] >= 0.0
    assert result["latency_sec"]["max"] >= result["latency_sec"]["min"]
    assert result["batch_latency_sec"]["count"] == 1
    assert result["batch_latency_sec"]["max"] == result["batch_latency_sec"]["min"]
    assert result["warning_counts"] == {}
    rows = [
        json.loads(line)
        for line in (tmp_path / "out" / "benchmark_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["case_id"] for row in rows] == ["case-1", "case-2"]
    assert {row["execution"]["mode"] for row in rows} == {"batch"}
    assert {row["execution"]["batch_size"] for row in rows} == {2}


def test_exploratory_batch_failure_is_recorded_for_every_case(tmp_path: Path):
    manifest = _two_case_manifest(tmp_path / "manifest.jsonl")
    config = _failing_batch_config(tmp_path)

    result = run_generation_benchmark(
        manifest,
        tmp_path / "out",
        config=config,
        formal=False,
    )

    assert result["status"] == "completed_with_failures"
    assert result["failure_count"] == 2
    rows = [
        json.loads(line)
        for line in (tmp_path / "out" / "benchmark_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["case_id"] for row in rows] == ["case-1", "case-2"]
    for row in rows:
        report = row["generated_report"]
        assert "legacy_batch_generation_failed" in report["warnings"]
        assert "batch boom" in report["metadata"]["batch_error"]
        assert row["execution"]["mode"] == "batch"


def _formal_config(tmp_path: Path) -> AppConfig:
    script = tmp_path / "fake_report_generator.py"
    script.write_text(
        """
import json
import sys
from pathlib import Path

input_path = Path(sys.argv[sys.argv.index('--input-jsonl') + 1])
output_path = Path(sys.argv[sys.argv.index('--output-jsonl') + 1])
row = json.loads(input_path.read_text(encoding='utf-8').splitlines()[0])
output_path.write_text(json.dumps({
    'case_id': row['case_id'],
    'model_key': 'benchmark-model',
    'modality': row['modality'],
    'generated_text': 'FINDINGS: No focal airspace disease.\\nIMPRESSION: No acute abnormality.',
    'adapter_status': 'passed',
}) + '\\n', encoding='utf-8')
""".strip()
        + "\n",
        encoding="utf-8",
    )
    legacy_config = tmp_path / "models.yaml"
    legacy_config.write_text("models: {}\n", encoding="utf-8")
    return AppConfig(
        generator=GeneratorConfig(
            include_legacy_ready_models=False,
            cloud_fallback_enabled=False,
            default_models=["benchmark-model"],
            local_models=[
                {
                    "key": "benchmark-model",
                    "title": "Benchmark model",
                    "source": "medharness_cli",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "ready": True,
                    "report_trained": True,
                    "fresh_inference": True,
                    "evidence_tier": "formal_fresh",
                    "python_bin": sys.executable,
                    "script_path": str(script),
                    "config_path": str(legacy_config),
                    "model_version": "benchmark-v1",
                    "model_sha256": "a" * 64,
                    "prompt_version": "reportgen-v1",
                    "preprocessing_version": "test-image-v1",
                    "formal_validation_id": "validation-test-v1",
                }
            ],
        )
    )


def _two_case_manifest(path: Path) -> Path:
    rows = []
    for index in (1, 2):
        image = path.parent / f"image-{index}.png"
        image.write_bytes(f"png-{index}".encode("ascii"))
        rows.append(
            {
                "case_id": f"case-{index}",
                "reader": "reader-a",
                "modality": "cxr",
                "body_part": "chest",
                "report_pdf": "",
                "report_text": "",
                "image_paths": [str(image)],
                "derived_assets": {"primary_image": str(image)},
            }
        )
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _batch_formal_config(tmp_path: Path) -> tuple[AppConfig, Path]:
    invocation_counter = tmp_path / "invocations.txt"
    script = tmp_path / "fake_batch_report_generator.py"
    script.write_text(
        f"""
import json
import sys
from pathlib import Path

counter_path = Path({str(invocation_counter)!r})
counter = int(counter_path.read_text(encoding='utf-8')) if counter_path.exists() else 0
counter_path.write_text(str(counter + 1), encoding='utf-8')
input_path = Path(sys.argv[sys.argv.index('--input-jsonl') + 1])
output_path = Path(sys.argv[sys.argv.index('--output-jsonl') + 1])
outputs = []
for line in input_path.read_text(encoding='utf-8').splitlines():
    row = json.loads(line)
    outputs.append(json.dumps({{
        'case_id': row['case_id'],
        'model_key': 'benchmark-model',
        'modality': row['modality'],
        'generated_text': 'FINDINGS: Clear lungs.\\nIMPRESSION: No acute abnormality.',
        'adapter_status': 'passed',
        'runtime': {{'fresh_inference': True, 'device': 'cuda:0', 'dtype': 'bf16'}},
    }}))
output_path.write_text('\\n'.join(outputs) + '\\n', encoding='utf-8')
""".strip()
        + "\n",
        encoding="utf-8",
    )
    legacy_config = tmp_path / "batch-models.yaml"
    legacy_config.write_text("models: {}\n", encoding="utf-8")
    config = AppConfig(
        generator=GeneratorConfig(
            include_legacy_ready_models=False,
            cloud_fallback_enabled=False,
            default_models=["benchmark-model"],
            local_models=[
                {
                    "key": "benchmark-model",
                    "title": "Benchmark model",
                    "source": "medharness_cli",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "ready": True,
                    "report_trained": True,
                    "fresh_inference": True,
                    "evidence_tier": "formal_fresh",
                    "python_bin": sys.executable,
                    "script_path": str(script),
                    "config_path": str(legacy_config),
                    "model_version": "benchmark-v1",
                    "model_sha256": "a" * 64,
                    "prompt_version": "reportgen-v1",
                    "preprocessing_version": "test-image-v1",
                    "formal_validation_id": "validation-test-v1",
                }
            ],
        )
    )
    return config, invocation_counter


def _failing_batch_config(tmp_path: Path) -> AppConfig:
    script = tmp_path / "failing_batch_report_generator.py"
    script.write_text(
        "import sys\nsys.stderr.write('batch boom')\nraise SystemExit(3)\n",
        encoding="utf-8",
    )
    legacy_config = tmp_path / "failing-batch-models.yaml"
    legacy_config.write_text("models: {}\n", encoding="utf-8")
    return AppConfig(
        generator=GeneratorConfig(
            include_legacy_ready_models=False,
            cloud_fallback_enabled=False,
            default_models=["benchmark-model"],
            local_models=[
                {
                    "key": "benchmark-model",
                    "title": "Benchmark model",
                    "source": "medharness_cli",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "ready": True,
                    "report_trained": True,
                    "fresh_inference": True,
                    "evidence_tier": "exploratory_fresh",
                    "python_bin": sys.executable,
                    "script_path": str(script),
                    "config_path": str(legacy_config),
                }
            ],
        )
    )


def _exploratory_model() -> dict:
    return {
        "key": "exploratory-model",
        "title": "Exploratory model",
        "source": "local_stub",
        "supported_modalities": ["cxr"],
        "supported_body_parts": ["chest"],
        "ready": True,
        "report_trained": True,
        "fresh_inference": True,
        "evidence_tier": "exploratory_fresh",
    }


def _file_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
