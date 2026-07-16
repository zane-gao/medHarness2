from __future__ import annotations

from fastapi.testclient import TestClient

from medharness2.api import app


def test_run_control_api_and_dynamic_panel(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDHARNESS2_CONTROL_DB", str(tmp_path / "control.sqlite3"))
    client = TestClient(app)

    response = client.post(
        "/runs",
        json={"run_type": "formal_benchmark", "inputs": {"manifest": "manifest.jsonl"}},
    )
    assert response.status_code == 201
    run = response.json()
    run_id = run["run_id"]

    assert client.get("/runs").json()["runs"][0]["run_id"] == run_id
    assert client.get(f"/runs/{run_id}").json()["status"] == "queued"
    assert client.post(f"/runs/{run_id}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/runs/{run_id}/retry").json()["status"] == "queued"
    assert client.get(f"/runs/{run_id}/stages").status_code == 200
    assert client.get(f"/runs/{run_id}/artifacts").status_code == 200

    panel = client.get("/control-panel")
    assert panel.status_code == 200
    assert "medHarness2 Control Panel" in panel.text
    assert "fetch('/runs')" in panel.text
    assert "Experiment Gates" in panel.text
    assert "Model/API Routing" in panel.text
    assert "Run Details" in panel.text


def test_control_api_exposes_model_roles_and_experiment_readiness(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDHARNESS2_CONTROL_DB", str(tmp_path / "control.sqlite3"))
    client = TestClient(app)

    roles = client.get("/catalog/model-roles", params={"config_path": "config/dmx_strong.yaml"})
    assert roles.status_code == 200
    assert roles.json()["model_roles"]["hazard_primary"]["model"] == "gpt-5.6-terra"

    run_dir = "outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_tool2_v1"
    experiments = client.get("/experiments", params={"run_dir": run_dir})
    assert experiments.status_code == 200
    assert {item["status"] for item in experiments.json()["experiments"]} == {"pilot"}


def test_catalog_api_returns_structured_failure_for_missing_config(tmp_path):
    client = TestClient(app, raise_server_exceptions=False)
    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("- not-a-mapping\n", encoding="utf-8")
    config_path = str(malformed)

    roles = client.get("/catalog/model-roles", params={"config_path": config_path})
    assert roles.status_code == 500
    assert roles.json()["detail"] == "catalog_model_roles_failed:ValueError"

    tools = client.get("/catalog/tools", params={"config_path": config_path})
    assert tools.status_code == 500
    assert tools.json()["detail"] == "catalog_tools_failed:ValueError"
