from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import medharness2.api as api_module
from medharness2.api import _count_or_zero, _result_bool, _result_mapping, _result_string_list, app


def test_api_registry_counts_reject_invalid_values():
    import pytest

    for bad in (True, 1.5, -1, "2"):
        with pytest.raises(ValueError, match="count"):
            _count_or_zero(bad, "count")


@pytest.mark.parametrize("bad", ["bad", [], ["x"], 7, True])
def test_api_result_mapping_rejects_malformed_values(bad):
    with pytest.raises(ValueError, match="payload"):
        _result_mapping(bad, "payload")


@pytest.mark.parametrize("bad", ["bad", {}, [1], 7, True])
def test_api_result_string_list_rejects_malformed_values(bad):
    with pytest.raises(ValueError, match="warnings"):
        _result_string_list(bad, "warnings")


@pytest.mark.parametrize("bad", ["true", 1, 0, [], {}])
def test_api_result_bool_rejects_implicit_coercion(bad):
    with pytest.raises(ValueError, match="passed"):
        _result_bool(bad, "passed")


@pytest.mark.parametrize(
    ("route", "payload", "function_name", "malformed", "detail_prefix"),
    [
        (
            "/workflow/sample-full",
            {"sample_root": "samples", "output_dir": "sample-full"},
            "run_sample_full",
            {"summary": "bad", "paths": {}, "validation": {}},
            "sample_full_failed",
        ),
        (
            "/workflow/validate-run",
            {"output_dir": "validate"},
            "validate_sample_run",
            {"passed": "true", "errors": []},
            "validate_run_failed",
        ),
        (
            "/workflow/preflight",
            {"sample_root": "samples", "output_path": "preflight.json"},
            "run_sample_preflight",
            {"paths": {}, "sample": {}, "passed": 1, "blockers": [], "warnings": []},
            "preflight_failed",
        ),
    ],
)
def test_api_rejects_malformed_workflow_results(
    tmp_path: Path, monkeypatch, route, payload, function_name, malformed, detail_prefix
):
    payload = {
        key: str(tmp_path / value) if key in {"output_dir", "output_path"} else value
        for key, value in payload.items()
    }
    monkeypatch.setattr(api_module, function_name, lambda *args, **kwargs: malformed)
    response = TestClient(app, raise_server_exceptions=False).post(route, json=payload)
    assert response.status_code == 500
    assert response.json()["detail"] == f"{detail_prefix}:ValueError"
    registry_dir = Path(payload.get("output_dir") or payload["output_path"])
    if route == "/workflow/preflight":
        registry_dir = registry_dir.parent
    registry = json.loads((registry_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


def test_api_single_case_rejects_malformed_result(tmp_path: Path, monkeypatch):
    output_path = tmp_path / "single.json"
    monkeypatch.setattr(
        api_module,
        "run_single_case",
        lambda *args, **kwargs: {
            "input": "bad",
            "generated_reports": "bad",
            "generated_evaluations": [],
            "rankings": [],
            "pairwise_comparisons": [],
            "errors": [],
        },
    )
    response = TestClient(app, raise_server_exceptions=False).post(
        "/workflow/single-case",
        json={"report_text": "report", "image_path": "image.dcm", "output_path": str(output_path)},
    )
    assert response.status_code == 500
    assert response.json()["detail"] == "single_case_failed:ValueError"
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


def test_api_experiments_run_rejects_malformed_result(tmp_path: Path, monkeypatch):
    output_dir = tmp_path / "experiments"
    monkeypatch.setattr(
        api_module,
        "run_experiments",
        lambda *args, **kwargs: {"experiment_count": "1", "experiments": [], "errors": "bad"},
    )
    response = TestClient(app, raise_server_exceptions=False).post(
        "/experiments/run",
        json={"run_dir": str(tmp_path / "run"), "output_dir": str(output_dir)},
    )
    assert response.status_code == 500
    assert response.json()["detail"] == "experiments_run_failed:ValueError"
    registry = json.loads((output_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


@pytest.mark.parametrize(
    ("route", "payload", "function_name", "malformed", "detail_prefix", "registry_dir_key"),
    [
        (
            "/workflow/batch-readers",
            {"manifest_path": "manifest.jsonl", "output_path": "batch.json"},
            "run_batch_readers",
            {"case_count": 1, "failed_case_count": 0, "per_reader": {}, "errors": "bad"},
            "batch_readers_failed",
            "output_path",
        ),
        (
            "/workflow/department",
            {"batch_result_path": "batch.json", "output_path": "department.json"},
            "run_department_comparison",
            {"case_count": 1, "reader_count": 1, "errors": "bad"},
            "department_failed",
            "output_path",
        ),
        (
            "/workflow/analyze-run",
            {"output_dir": "run", "analysis_dir": "analysis"},
            "analyze_run",
            {"analysis_dir": "analysis", "case_count": 1, "generated_report_count": 1, "quality_gate_failed_count": 0, "errors": "bad"},
            "analyze_run_failed",
            "output_dir",
        ),
    ],
)
def test_api_rejects_malformed_remaining_workflow_results(
    tmp_path: Path, monkeypatch, route, payload, function_name, malformed, detail_prefix, registry_dir_key
):
    payload = {
        key: str(tmp_path / value) if key in {"output_dir", "output_path", "analysis_dir"} else value
        for key, value in payload.items()
    }
    monkeypatch.setattr(api_module, function_name, lambda *args, **kwargs: malformed)
    response = TestClient(app, raise_server_exceptions=False).post(route, json=payload)
    assert response.status_code == 500
    assert response.json()["detail"] == f"{detail_prefix}:ValueError"
    registry_dir = Path(payload[registry_dir_key])
    if route != "/workflow/analyze-run":
        registry_dir = registry_dir.parent
    registry = json.loads((registry_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


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
    assert body["summary"]["pairwise_comparisons"] == 0
    assert body["summary"]["rankings"] == 0
    assert body["summary"]["modality"] == "cxr"
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["generated_reports"]
    assert payload["generated_reports"][0]["metadata"]["quality_gate"]["passed"] is False


def test_api_single_case_preserves_explicit_case_id(tmp_path: Path):
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
    response = TestClient(app).post(
        "/workflow/single-case",
        json={
            "case_id": "api-case-id",
            "report_text": "FINDINGS: No pneumothorax. IMPRESSION: Normal.",
            "image_path": "tests/fixtures/dummy.dcm",
            "output_path": str(output_path),
            "modality": "cxr",
            "top_n": 1,
            "config_path": str(config_path),
        },
    )

    assert response.status_code == 200
    assert response.json()["result"]["case_id"] == "api-case-id"
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["case_id"] == "api-case-id"
    assert payload["input"]["case_id"] == "api-case-id"


def test_api_single_case_surfaces_no_generated_reports_in_summary_and_registry(tmp_path: Path):
    config_path = tmp_path / "no_generator.yaml"
    config_path.write_text(
        "llm:\n  provider: mock\ngenerator:\n  cloud_fallback_enabled: false\n  default_models: []\n  local_models: []\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "api_result.json"
    response = TestClient(app).post(
        "/workflow/single-case",
        json={
            "report_text": "FINDINGS: Normal. IMPRESSION: Normal.",
            "image_path": "tests/fixtures/dummy.dcm",
            "output_path": str(output_path),
            "modality": "cxr",
            "config_path": str(config_path),
        },
    )
    assert response.status_code == 200
    assert response.json()["summary"]["errors"] == ["no_generated_reports"]
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


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
    assert json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))["entries"][-1]["stage"] == "workflow.batch-readers"
    dept_output = tmp_path / "workflow3.json"
    response = client.post(
        "/workflow/department",
        json={"batch_result_path": str(batch_output), "output_path": str(dept_output)},
    )
    assert response.status_code == 200
    assert response.json()["summary"]["readers"] == 1
    assert json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))["entries"][-1]["stage"] == "workflow.department"


def test_api_sample_data_writes_registry_failure_for_empty_sample(tmp_path: Path):
    output_dir = tmp_path / "sample_run"
    response = TestClient(app).post(
        "/workflow/sample-data",
        json={"sample_root": str(tmp_path / "missing"), "output_dir": str(output_dir)},
    )

    assert response.status_code == 200
    assert response.json()["errors"] == ["no_cases_discovered"]
    registry = json.loads((output_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


def test_api_sample_data_returns_structured_failure_for_malformed_config(tmp_path: Path):
    config_path = tmp_path / "malformed.yaml"
    config_path.write_text("- not-a-mapping\n", encoding="utf-8")
    output_dir = tmp_path / "sample_run"
    response = TestClient(app, raise_server_exceptions=False).post(
        "/workflow/sample-data",
        json={
            "sample_root": str(tmp_path / "sample"),
            "output_dir": str(output_dir),
            "config_path": str(config_path),
        },
    )
    assert response.status_code == 500
    assert response.json()["detail"] == "sample_data_failed:ValueError"
    registry = json.loads((output_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


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


def test_api_workflow_failures_return_http_500_and_failed_registry(tmp_path: Path, monkeypatch):
    cases = [
        ("/workflow/batch-readers", {"manifest_path": str(tmp_path / "manifest.jsonl"), "output_path": str(tmp_path / "batch.json")}, "run_batch_readers", "batch_readers_failed"),
        ("/workflow/department", {"batch_result_path": str(tmp_path / "batch.json"), "output_path": str(tmp_path / "department.json")}, "run_department_comparison", "department_failed"),
        ("/workflow/analyze-run", {"output_dir": str(tmp_path / "analyze")}, "analyze_run", "analyze_run_failed"),
        ("/workflow/validate-run", {"output_dir": str(tmp_path / "validate")}, "validate_sample_run", "validate_run_failed"),
        ("/workflow/education", {"eval_report_path": str(tmp_path / "eval.json"), "output_path": str(tmp_path / "education.json")}, "run_education_suggestions", "education_failed"),
    ]
    for route, payload, function_name, detail_prefix in cases:
        monkeypatch.setattr(api_module, function_name, lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
        response = TestClient(app, raise_server_exceptions=False).post(route, json=payload)
        assert response.status_code == 500
        assert response.json()["detail"] == f"{detail_prefix}:RuntimeError"
        registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
        assert registry["entries"][-1]["status"] == "failed"
        assert registry["entries"][-1]["stage"].startswith("workflow.")


def test_api_remaining_workflow_failures_return_http_500_and_failed_registry(tmp_path: Path, monkeypatch):
    cases = [
        ("/workflow/single-case", {"report_text": "report", "image_path": "image.dcm", "output_path": str(tmp_path / "single.json")}, "run_single_case", "single_case_failed", tmp_path),
        ("/experiments/run", {"run_dir": str(tmp_path / "run"), "output_dir": str(tmp_path / "experiments")}, "run_experiments", "experiments_run_failed", tmp_path / "experiments"),
        ("/workflow/sample-full", {"sample_root": str(tmp_path / "samples"), "output_dir": str(tmp_path / "sample-full")}, "run_sample_full", "sample_full_failed", tmp_path / "sample-full"),
    ]
    for route, payload, function_name, detail_prefix, registry_dir in cases:
        monkeypatch.setattr(api_module, function_name, lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
        response = TestClient(app, raise_server_exceptions=False).post(route, json=payload)
        assert response.status_code == 500
        assert response.json()["detail"] == f"{detail_prefix}:RuntimeError"
        registry = json.loads((registry_dir / "run_registry.json").read_text(encoding="utf-8"))
        assert registry["entries"][-1]["status"] == "failed"


def test_api_merge_batches(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    report_text = tmp_path / "ocr" / "case1.txt"
    report_text.parent.mkdir(parents=True)
    report_text.write_text("FINDINGS: Test report. IMPRESSION: Test.", encoding="utf-8")
    _write_json(report_text.with_suffix(".ocr.json"), {"case_id": "case1", "method": "vlm_ocr", "provider": "local_hf_vlm"})
    manifest.write_text(
        json.dumps(
            {
                "case_id": "case1",
                "reader": "reader_a",
                "modality": "cxr",
                "body_part": "chest",
                "report_text": str(report_text),
                "image_paths": [str(tmp_path / "image.png")],
                "derived_assets": {"primary_image": str(tmp_path / "image.png")},
                "warnings": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    workflow1 = tmp_path / "batch" / "workflow2_cases" / "case1.json"
    _write_json(
        workflow1,
        {
            "generated_reports": [{"model": "maira_2", "source": "medharness_cli", "warnings": [], "metadata": {"quality_gate": {"passed": True}}}],
            "rankings": [{"model": "maira_2", "score": 0.8, "selected_top_n": True}],
            "pairwise_comparisons": [{"model": "maira_2"}],
        },
    )
    batch_result = tmp_path / "batch" / "workflow2.json"
    _write_json(
        batch_result,
        {
            "case_count": 1,
            "failed_case_count": 0,
            "cases": [
                {
                    "case_id": "case1",
                    "reader": "reader_a",
                    "modality": "cxr",
                    "body_part": "chest",
                    "warnings": [],
                    "human_metrics": {"likert_mean": 4.0},
                    "modelwise_metrics": {"likert_mean": 4.0, "model_count": 1},
                    "workflow1_output": str(workflow1),
                }
            ],
            "failed_cases": [],
        },
    )
    output_dir = tmp_path / "merged"
    client = TestClient(app)
    response = client.post(
        "/workflow/merge-batches",
        json={
            "batch_result_paths": [str(batch_result)],
            "output_dir": str(output_dir),
            "manifest_path": str(manifest),
            "expected_cases": 1,
            "require_real_ocr": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["validation_passed"] is True
    assert body["summary"]["cases"] == 1
    assert (output_dir / "workflow3.json").exists()
    assert json.loads((output_dir / "run_registry.json").read_text(encoding="utf-8"))["entries"][-1]["stage"] == "workflow.merge-batches"
    response = client.post(
        "/workflow/analyze-run",
        json={"output_dir": str(output_dir), "analysis_dir": str(tmp_path / "analysis")},
    )
    assert response.status_code == 200
    assert response.json()["summary"]["generated_reports"] == 1
    assert (tmp_path / "analysis" / "analysis_summary.md").exists()


def test_api_preflight_reports_blockers(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    (case_dir / "Y1").write_text("dummy", encoding="utf-8")
    (sample_root / "CR" / "CR001" / "report.pdf").write_text("dummy pdf", encoding="utf-8")
    output = tmp_path / "preflight.json"
    client = TestClient(app)
    response = client.post(
        "/workflow/preflight",
        json={
            "sample_root": str(sample_root),
            "output_path": str(output),
            "limit": 1,
            "require_real_ocr": True,
            "all_compatible_local_models": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["passed"] is False
    assert "real_ocr_required_but_provider_is_mock" in body["summary"]["blockers"]
    assert output.exists()
    assert json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))["entries"][-1]["status"] == "failed"


def test_api_preflight_returns_structured_failure_for_missing_sample_root(tmp_path: Path):
    output = tmp_path / "preflight.json"
    response = TestClient(app).post(
        "/workflow/preflight",
        json={"sample_root": str(tmp_path / "missing"), "output_path": str(output)},
    )

    assert response.status_code == 500
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


def test_api_preflight_returns_structured_failure_for_malformed_config(tmp_path: Path):
    config_path = tmp_path / "malformed.yaml"
    config_path.write_text("- not-a-mapping\n", encoding="utf-8")
    output = tmp_path / "preflight.json"
    response = TestClient(app, raise_server_exceptions=False).post(
        "/workflow/preflight",
        json={
            "sample_root": str(tmp_path / "sample"),
            "output_path": str(output),
            "config_path": str(config_path),
        },
    )
    assert response.status_code == 500
    assert response.json()["detail"] == "preflight_failed:ValueError"
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


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


def test_api_sample_full_dry_run_all_compatible(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    (case_dir / "Y1").write_text("dummy", encoding="utf-8")
    (sample_root / "CR" / "CR001" / "report.pdf").write_text("dummy pdf", encoding="utf-8")
    output_dir = tmp_path / "run"
    client = TestClient(app)
    response = client.post(
        "/workflow/sample-full",
        json={
            "sample_root": str(sample_root),
            "output_dir": str(output_dir),
            "limit": 1,
            "dry_run": True,
            "all_compatible_local_models": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["dry_run"] is True
    assert body["summary"]["cases_with_local_candidates"] == 1
    assert "maira_2" in body["result"]["cases"][0]["compatible_model_keys"]
    assert not (output_dir / "workflow2.json").exists()
    registry = json.loads((output_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["stage"] == "workflow.sample-full.dry-run"
    assert registry["entries"][-1]["status"] == "passed"


def test_api_sample_full_dry_run_filters_model_source(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    (case_dir / "Y1").write_text("dummy", encoding="utf-8")
    (sample_root / "CR" / "CR001" / "report.pdf").write_text("dummy pdf", encoding="utf-8")
    output_dir = tmp_path / "run"
    client = TestClient(app)
    response = client.post(
        "/workflow/sample-full",
        json={
            "sample_root": str(sample_root),
            "output_dir": str(output_dir),
            "limit": 1,
            "dry_run": True,
            "all_compatible_local_models": True,
            "model_sources": ["artifact_reuse"],
        },
    )
    assert response.status_code == 200
    keys = response.json()["result"]["cases"][0]["compatible_model_keys"]
    assert "chexagent" in keys
    assert "maira_2" not in keys


def test_api_catalog_tools_returns_provider_without_secret_values():
    client = TestClient(app)
    response = client.get("/catalog/tools")
    assert response.status_code == 200
    body = response.json()
    assert body["providers"]["llm"]["secret_values_exposed"] is False
    assert any(tool["id"] == "tool8_generate" for tool in body["tools"])
    assert body["models"]


def test_api_workflow_education_eval_report(tmp_path: Path):
    workflow1 = tmp_path / "workflow1.json"
    output = tmp_path / "education.json"
    _write_json(
        workflow1,
        {
            "human_evaluation": {
                "likert": {
                    "Completeness and Accuracy": {"score": 2, "explanation": "Missing detail."},
                    "Conciseness and Clarity": {"score": 4, "explanation": "Clear."},
                    "Terminological Accuracy": {"score": 4, "explanation": "Good."},
                    "Structure and Style": {"score": 4, "explanation": "Good."},
                    "Overall Writing Quality": {"score": 4, "explanation": "Good."},
                },
                "finding_graph": {"findings": [{"id": "f1", "observation": "opacity", "text": "opacity"}]},
                "structure": {"score": 0.55},
            },
            "pairwise_comparisons": [],
            "generated_reports": [],
            "rankings": [],
        },
    )
    client = TestClient(app)
    response = client.post(
        "/workflow/education",
        json={"eval_report_path": str(workflow1), "output_path": str(output)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["mode"] == "eval_report"
    assert body["summary"]["suggestions"] >= 1
    assert output.exists()


def test_api_outputs_write_run_registry_entries(tmp_path: Path):
    run_dir = tmp_path / "run"
    _write_json(run_dir / "run_summary.json", {"summary": {"case_count": 1, "reader_count": 1}})
    client = TestClient(app)

    experiment_dir = tmp_path / "experiments"
    response = client.post("/experiments/run", json={"run_dir": str(run_dir), "output_dir": str(experiment_dir)})
    assert response.status_code == 200
    experiment_registry = json.loads((experiment_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert experiment_registry["entries"][-1]["stage"] == "experiments.run"
    assert experiment_registry["entries"][-1]["metrics"]["experiment_count"] == 6
    assert experiment_registry["entries"][-1]["metrics"]["education_generation_status"] == "skipped_missing_workflow2"
    assert experiment_registry["entries"][-1]["metrics"]["education_suggestion_count"] == 0
    run_registry = json.loads((run_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert run_registry["entries"][-1]["stage"] == "experiments.run"

    figure_dir = tmp_path / "figures"
    response = client.post("/figures/build", json={"experiment_dir": str(experiment_dir), "output_dir": str(figure_dir)})
    assert response.status_code == 200
    figure_registry = json.loads((figure_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert figure_registry["entries"][-1]["stage"] == "figures.build"
    run_registry = json.loads((run_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert run_registry["entries"][-1]["stage"] == "figures.build"

    dashboard = tmp_path / "control_panel.html"
    response = client.post("/dashboard/build", json={"run_dir": str(run_dir), "output_path": str(dashboard)})
    assert response.status_code == 200
    run_registry = json.loads((run_dir / "run_registry.json").read_text(encoding="utf-8"))
    dashboard_entry = run_registry["entries"][-1]
    assert dashboard_entry["stage"] == "dashboard.build"
    assert dashboard_entry["metrics"]["registry_entry_count"] == len(run_registry["entries"])
    dashboard_html = dashboard.read_text(encoding="utf-8")
    assert "Run Registry" in dashboard_html
    assert "dashboard.build" in dashboard_html

    workflow1 = tmp_path / "workflow1.json"
    education_output = tmp_path / "education.json"
    _write_json(
        workflow1,
        {
            "human_evaluation": {
                "likert": {
                    "Completeness and Accuracy": {"score": 4, "explanation": "Adequate."},
                },
                "finding_graph": {"findings": [{"id": "f1", "observation": "opacity", "text": "opacity"}]},
                "structure": {"score": 1.0},
            }
        },
    )
    response = client.post(
        "/workflow/education",
        json={"eval_report_path": str(workflow1), "output_path": str(education_output)},
    )
    assert response.status_code == 200
    education_registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    assert education_registry["entries"][-1]["stage"] == "workflow.education"


def test_api_dashboard_build_marks_registry_failed_when_render_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_dir = tmp_path / "run"
    _write_json(run_dir / "run_summary.json", {"summary": {"case_count": 1}})
    output = tmp_path / "dashboard.html"

    def fail_render(*args, **kwargs):
        raise RuntimeError("render_failed")

    monkeypatch.setattr("medharness2.api.build_dashboard", fail_render)
    response = TestClient(app).post(
        "/dashboard/build",
        json={"run_dir": str(run_dir), "output_path": str(output)},
    )

    assert response.status_code == 500
    registry = json.loads((run_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


def test_api_figures_build_marks_registry_failed_when_render_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    experiment_dir = tmp_path / "experiments"
    experiment_dir.mkdir()
    output_dir = tmp_path / "figures"

    def fail_render(*args, **kwargs):
        raise RuntimeError("figure_render_failed")

    monkeypatch.setattr("medharness2.api.build_figures", fail_render)
    response = TestClient(app).post(
        "/figures/build",
        json={"experiment_dir": str(experiment_dir), "output_dir": str(output_dir)},
    )

    assert response.status_code == 500
    registry = json.loads((output_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


def test_api_experiments_run_surfaces_missing_source_as_failed_registry(tmp_path: Path):
    output_dir = tmp_path / "experiments"
    response = TestClient(app).post(
        "/experiments/run",
        json={"run_dir": str(tmp_path / "missing"), "output_dir": str(output_dir)},
    )
    assert response.status_code == 200
    assert response.json()["summary"]["errors"] == ["run_dir_not_found"]
    registry = json.loads((output_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

@pytest.mark.parametrize("field", ["top_n", "limit", "expected_cases"])
@pytest.mark.parametrize("bad", [True, 1.5, "2"])
def test_api_request_models_reject_implicit_integer_coercion(field, bad):
    from medharness2.api import (
        BatchReadersRequest,
        MergeBatchesRequest,
        SampleDataRequest,
        SampleFullRequest,
        SingleCaseRequest,
        ValidateRunRequest,
    )

    models = {
        "top_n": (SingleCaseRequest, {"image_path": "x", "output_path": "y"}),
        "limit": (SampleDataRequest, {"sample_root": "x", "output_dir": "y"}),
        "expected_cases": (SampleFullRequest, {"sample_root": "x", "output_dir": "y"}),
    }
    model, payload = models[field]
    with pytest.raises(Exception):
        model.model_validate({**payload, field: bad})
