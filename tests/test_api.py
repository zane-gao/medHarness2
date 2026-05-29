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
