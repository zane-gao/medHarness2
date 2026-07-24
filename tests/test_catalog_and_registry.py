from __future__ import annotations

import json
from pathlib import Path

from medharness2.catalog import build_capability_catalog
from medharness2.cli import main
from medharness2.config import AppConfig, GeneratorConfig, LLMConfig, ModelRoleConfig
from medharness2.run_registry import record_run
import pytest


def test_capability_catalog_lists_tools_models_and_providers(tmp_path: Path):
    artifact = tmp_path / "generation.jsonl"
    artifact.write_text("{}", encoding="utf-8")
    cfg = AppConfig(
        llm=LLMConfig(provider="chat_completions", model="gpt-test", api_key_env="SECRET_API_KEY"),
        generator=GeneratorConfig(
            include_legacy_ready_models=False,
            default_models=["demo_model"],
            local_models=[
                {
                    "key": "demo_model",
                    "title": "Demo report model",
                    "source": "artifact_reuse",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "source_generation_jsonl": str(artifact),
                    "report_trained": True,
                    "notes": "test model",
                }
            ],
        ),
    )
    catalog = build_capability_catalog(cfg)
    assert catalog["providers"]["llm"]["provider"] == "chat_completions"
    assert catalog["providers"]["llm"]["api_key_env"] == "SECRET_API_KEY"
    assert catalog["providers"]["llm"]["secret_values_exposed"] is False
    tool1 = next(tool for tool in catalog["tools"] if tool["id"] == "tool1_likert")
    assert tool1["implementation_type"] == "strict_llm_judge"
    assert "five-dimension" in tool1["implementation"]
    tool2 = next(tool for tool in catalog["tools"] if tool["id"] == "tool2_extract")
    assert "Registry-based CXR/CT/MRI plugins" in tool2["implementation"]
    assert "LLM correction" in tool2["implementation"]
    assert tool2["medical_model_required"] is True
    tool4 = next(tool for tool in catalog["tools"] if tool["id"] == "tool4_hazard")
    assert "schema retry" in tool4["implementation"]
    assert "provenance" in tool4["implementation"]
    assert "independent reviewer" in tool4["implementation"]
    assert "hazard_review" in tool4["outputs"]
    assert tool4["medical_model_required"] is False
    tool5 = next(tool for tool in catalog["tools"] if tool["id"] == "tool5_align")
    assert tool5["implementation_type"] == "deterministic_with_llm_audit"
    assert "maximum-weight" in tool5["implementation"]
    assert "alignment_audit" in tool5["outputs"]
    tool6 = next(tool for tool in catalog["tools"] if tool["id"] == "tool6_structure_diff")
    assert tool6["implementation_type"] == "deterministic_with_llm_assessment"
    assert "structure_audit" in tool6["outputs"]
    tool8 = next(tool for tool in catalog["tools"] if tool["id"] == "tool8_generate")
    assert tool8["implementation_type"] == "local_model_or_fallback"
    assert {"image_path", "modality"} <= set(tool8["inputs"])
    stages = {stage["id"]: stage for stage in catalog["workflow_stages"]}
    sample_full = stages["workflow.sample-full"]
    assert sample_full["development_status"] == "implemented_v1"
    assert sample_full["implementation_type"] == "workflow_orchestration"
    assert any(item["name"] == "sample_root" and item["format"] == "directory" for item in sample_full["inputs"])
    assert any(item["path_template"] == "<RUN>/run_summary.json" for item in sample_full["outputs"])
    assert sample_full["model_policy"]["medical_specialist_model"] == "preferred_for_generation"
    reeval = stages["workflow.reevaluate-run"]
    assert reeval["implementation_type"] == "deterministic_reevaluation"
    assert "reuses existing generated_reports" in reeval["implementation"]
    assert any(item["path_template"] == "<REEVAL_RUN>/workflow2.json" for item in reeval["outputs"])
    assert reeval["model_policy"]["api_model"] == "not_required"
    validation = stages["workflow.validate-run"]
    assert "optional alignment, hazard-review, and structure-audit contracts" in validation["implementation"]
    assert "canonical SHA-256 bindings" in validation["implementation"]
    assert stages["experiments.run"]["model_policy"]["general_model"] == "not_required"
    assert "auto-generates deterministic reader-level education suggestions" in stages["experiments.run"]["implementation"]
    assert any(item["path_template"] == "<RUN>/education/radiologist_summary.json" for item in stages["experiments.run"]["outputs"])
    figures = stages["figures.build"]
    assert "Fig.1" in figures["implementation"]
    assert "Fig.7" in figures["implementation"]
    assert any(item["path_template"] == "<FIG>/fig1_system_overview.svg" for item in figures["outputs"])
    assert any(item["path_template"] == "<FIG>/fig2_single_case_evidence_chain.svg" for item in figures["outputs"])
    assert any(item["path_template"] == "<FIG>/fig3_finding_graph_alignment.svg" for item in figures["outputs"])
    assert any(item["path_template"] == "<FIG>/fig4_feedback_card.svg" for item in figures["outputs"])
    assert any(item["path_template"] == "<FIG>/fig7_case_level_distribution.svg" for item in figures["outputs"])
    assert any(item["path_template"] == "<FIG>/table1_dataset_run_summary.csv" for item in figures["outputs"])
    assert any(item["path_template"] == "<FIG>/table2_metric_taxonomy.csv" for item in figures["outputs"])
    models = {model["key"]: model for model in catalog["models"]}
    assert models["demo_model"]["source"] == "artifact_reuse"
    assert models["demo_model"]["report_trained"] is True


def test_capability_catalog_exposes_full_canonical_legacy_model_statuses():
    catalog = build_capability_catalog(AppConfig())
    statuses = {row["model_key"]: row for row in catalog["model_statuses"]}

    assert catalog["model_status_summary"]["model_count"] == 390
    assert catalog["model_status_summary"]["quality_gate_blocked_count"] == 36
    assert len(statuses) == 390
    assert statuses["cosmobillian_radiologist_llama_cxr_report_generation"][
        "validation_state"
    ] == "quality_blocked"
    assert statuses["cosmobillian_radiologist_llama_cxr_report_generation"][
        "quality_gate_blocked"
    ] is True
    assert statuses["maira_2"]["latest_evidence"]["exists"] is True
    assert statuses["petar_localized_composed_report"]["output_mode"] == (
        "evidence_grounded_composed_report"
    )
    assert statuses["petar_localized_composed_report"]["quality_gate_blocked"] is True

    executable = {row["key"]: row for row in catalog["models"]}
    assert executable["maira_2"]["runtime_state"] == "smoke_verified"
    assert executable["maira_2"]["validation_state"] == "engineering_smoke_only"
    assert executable["maira_2"]["input_capabilities"] == ["image_2d"]
    assert executable["maira_2"]["latest_evidence"]["exists"] is True


def test_models_list_can_emit_all_canonical_statuses_as_json(capsys):
    rc = main(["models", "list", "--all-statuses", "--format", "json"])

    assert rc == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 390
    cosmobillian = next(
        row
        for row in rows
        if row["model_key"] == "cosmobillian_radiologist_llama_cxr_report_generation"
    )
    assert cosmobillian["quality_gate_blocked"] is True
    assert cosmobillian["blocked_reason"]


def test_capability_catalog_exposes_secret_free_model_role_routes():
    cfg = AppConfig(
        model_roles={
            "hazard_primary": ModelRoleConfig(
                provider="chat_completions",
                model="gpt-5.5",
                api_key_env="DMX_API_KEY",
                base_url="https://www.DMXAPI.cn/v1",
                max_retries=3,
            ),
            "hazard_reviewer": ModelRoleConfig(
                provider="chat_completions",
                model="claude-opus-4-8",
                api_key_env="DMX_API_KEY",
                base_url="https://www.DMXAPI.cn/v1",
                omit_temperature=True,
            ),
        }
    )

    catalog = build_capability_catalog(cfg)
    route = catalog["providers"]["model_roles"]["hazard_primary"]

    assert route["provider"] == "chat_completions"
    assert route["model"] == "gpt-5.5"
    assert route["endpoint_host"] == "www.dmxapi.cn"
    assert route["api_key_env"] == "DMX_API_KEY"
    assert route["secret_values_exposed"] is False
    assert "base_url" not in route
    assert catalog["providers"]["model_roles"]["hazard_reviewer"]["omit_temperature"] is True


def test_record_run_writes_redacted_audit_file(tmp_path: Path):
    output = record_run(
        tmp_path,
        run_id="run_test",
        command=["medharness2", "workflow", "sample-full", "--api-key", "SECRET"],
        stage="sample-full",
        status="passed",
        config={"llm": {"api_key": "SECRET", "provider": "mock"}},
        inputs={"manifest": "manifest.jsonl"},
        outputs={"workflow2": "workflow2.json"},
        metrics={"case_count": 1},
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run_test"
    assert payload["stage"] == "sample-full"
    assert payload["status"] == "passed"
    assert payload["command"][-1] == "<redacted>"
    assert payload["config"]["llm"]["api_key"] == "<redacted>"
    assert payload["metrics"]["case_count"] == 1
    assert payload["entries"][0]["stage"] == "sample-full"


def test_record_run_appends_multiple_stage_entries(tmp_path: Path):
    record_run(
        tmp_path,
        run_id="run_test",
        command=["medharness2", "tools", "catalog"],
        stage="tools.catalog",
        status="passed",
        outputs={"catalog": "outputs/capability_catalog.json"},
        metrics={"tool_count": 12},
    )
    output = record_run(
        tmp_path,
        run_id="run_test",
        command=["medharness2", "dashboard", "build"],
        stage="dashboard.build",
        status="passed",
        outputs={"dashboard": "web/control_panel.html"},
        metrics={"case_count": 52},
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["stage"] == "dashboard.build"
    assert [entry["stage"] for entry in payload["entries"]] == ["tools.catalog", "dashboard.build"]
    assert payload["entries"][0]["metrics"]["tool_count"] == 12
    assert payload["entries"][1]["outputs"]["dashboard"] == "web/control_panel.html"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("command", "not-a-list"),
        ("config", []),
        ("inputs", []),
        ("outputs", []),
        ("metrics", []),
        ("warnings", "not-a-list"),
    ],
)
def test_record_run_rejects_malformed_structured_fields(
    tmp_path: Path, field: str, value: object
):
    kwargs = {
        "run_id": "run_bad",
        "stage": "sample-full",
        "status": "failed",
        field: value,
    }
    with pytest.raises(ValueError, match=field):
        record_run(tmp_path, **kwargs)


def test_record_run_ignores_malformed_legacy_entries(tmp_path: Path):
    registry = tmp_path / "run_bad" / "run_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "entries": [
                    {"stage": "broken", "outputs": [], "warnings": "bad"},
                    {
                        "run_id": "run_bad",
                        "stage": "valid",
                        "status": "passed",
                        "created_at_utc": "",
                        "command": [],
                        "config": {},
                        "inputs": {},
                        "outputs": {},
                        "metrics": {},
                        "warnings": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    output = record_run(
        tmp_path,
        run_id="run_bad",
        stage="new",
        status="passed",
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert [entry["stage"] for entry in payload["entries"]] == ["valid", "new"]


def test_cli_tools_catalog_writes_run_registry_entry(tmp_path: Path):
    output = tmp_path / "capability_catalog.json"
    code = main(["tools", "catalog", "--output", str(output)])
    assert code == 0
    assert output.exists()
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    entry = registry["entries"][-1]
    assert entry["stage"] == "tools.catalog"
    assert entry["outputs"]["catalog"] == str(output)
    assert entry["metrics"]["tool_count"] == 12
