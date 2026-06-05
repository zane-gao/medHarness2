from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from medharness2.api import app


def test_api_single_case_accepts_report_text(tmp_path: Path):
    config_path = tmp_path / "api_config.yaml"
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
    output_path = tmp_path / "api_result.json"
    client = TestClient(app)
    response = client.post(
        "/workflow/single-case",
        json={
            "report_text": "FINDINGS: No pneumothorax. IMPRESSION: No acute disease.",
            "image_path": "tests/fixtures/dummy.dcm",
            "output_path": str(output_path),
            "modality": "cxr",
            "top_n": 1,
            "config_path": str(config_path),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["output_path"] == str(output_path)
    assert body["summary"]["generated_reports"] == 1
    assert body["summary"]["pairwise_comparisons"] == 1
    assert body["summary"]["modality"] == "cxr"
    assert output_path.exists()
    assert json.loads(output_path.read_text(encoding="utf-8"))["generated_reports"]


def test_api_single_case_requires_report_text_or_path(tmp_path: Path):
    client = TestClient(app)
    response = client.post(
        "/workflow/single-case",
        json={
            "image_path": "tests/fixtures/dummy.dcm",
            "output_path": str(tmp_path / "api_result.json"),
            "modality": "cxr",
        },
    )
    assert response.status_code == 400


def test_api_batch_readers_and_department(tmp_path: Path):
    config_path = tmp_path / "api_config.yaml"
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
    report = tmp_path / "report.txt"
    image = tmp_path / "image.dcm"
    report.write_text("FINDINGS: No pneumothorax. IMPRESSION: Normal.", encoding="utf-8")
    image.write_text("dummy", encoding="utf-8")
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "case_id": "case1",
                "reader": "reader_a",
                "modality": "cxr",
                "body_part": "chest",
                "report_text": str(report),
                "image_paths": [str(image)],
                "derived_assets": {"primary_image": str(image)},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    client = TestClient(app)
    batch_output = tmp_path / "workflow2.json"
    response = client.post(
        "/workflow/batch-readers",
        json={
            "manifest_path": str(manifest),
            "output_path": str(batch_output),
            "limit": 1,
            "config_path": str(config_path),
        },
    )
    assert response.status_code == 200
    assert response.json()["summary"]["cases"] == 1
    dept_output = tmp_path / "workflow3.json"
    response = client.post(
        "/workflow/department",
        json={"batch_result_path": str(batch_output), "output_path": str(dept_output)},
    )
    assert response.status_code == 200
    assert response.json()["summary"]["readers"] == 1


def test_api_validate_run(tmp_path: Path):
    _write_json(tmp_path / "summary.json", {"case_count": 1, "warning_counts": {}})
    (tmp_path / "manifest.jsonl").write_text(
        json.dumps({"case_id": "case1", "reader": "reader_a", "modality": "cxr", "body_part": "chest"}) + "\n",
        encoding="utf-8",
    )
    _write_json(tmp_path / "workflow2.json", {"case_count": 1, "failed_case_count": 0})
    _write_json(tmp_path / "workflow3.json", {"case_count": 1, "reader_count": 1})
    client = TestClient(app)
    response = client.post("/workflow/validate-run", json={"output_dir": str(tmp_path), "expected_cases": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["passed"] is True
    assert body["result"]["case_count"] == 1


def test_api_sample_full(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    (case_dir / "Y1").write_text("dummy", encoding="utf-8")
    (sample_root / "CR" / "CR001" / "report.pdf").write_text("dummy pdf", encoding="utf-8")
    config_path = tmp_path / "api_config.yaml"
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
    client = TestClient(app)
    response = client.post(
        "/workflow/sample-full",
        json={
            "sample_root": str(sample_root),
            "output_dir": str(output_dir),
            "limit": 1,
            "expected_cases": 1,
            "config_path": str(config_path),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["validation_passed"] is True
    assert body["result"]["summary"]["workflow2_case_count"] == 1
    assert (output_dir / "run_summary.json").exists()


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
