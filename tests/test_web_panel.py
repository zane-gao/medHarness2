from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "web"))
import build_panel


def test_extract_git_state_reports_branch_sha_and_dirty(tmp_path):
    state = build_panel.extract_git_state()

    assert set(state) >= {"branch", "sha", "short_sha", "dirty"}
    assert state["branch"]
    assert len(state["sha"]) == 40
    assert state["short_sha"] == state["sha"][:7]
    assert isinstance(state["dirty"], bool)


def test_extract_project_status_uses_real_yaml():
    path = Path("docs/project_status.yaml")
    status = build_panel.extract_project_status(path)

    assert status["release_readiness"] == "pilot_only"
    assert status["baseline"]["case_count"] == 52
    assert "control_panel" in status["workstreams"]


def test_extract_project_status_rejects_missing_or_invalid_ledgers(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_panel.extract_project_status(tmp_path / "missing.yaml")

    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("pilot_only\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        build_panel.extract_project_status(scalar)

    missing = tmp_path / "missing_workstreams.yaml"
    missing.write_text("release_readiness: pilot_only\n", encoding="utf-8")
    with pytest.raises(ValueError, match="workstreams"):
        build_panel.extract_project_status(missing)


def test_extract_workstreams_includes_release_readiness(tmp_path):
    path = tmp_path / "project_status.yaml"
    path.write_text(
        "release_readiness: pilot_only\nworkstreams: {}\n",
        encoding="utf-8",
    )

    assert build_panel.extract_workstreams(path)["release_readiness"] == "pilot_only"


def test_extract_workstreams_preserves_nested_yaml_values(tmp_path):
    path = tmp_path / "project_status.yaml"
    path.write_text(
        """updated_at: '2026-07-14'
current_phase: 'pilot: only'
workstreams:
  control_panel:
    status: in_progress
    summary: 'keep: quoted value'
""",
        encoding="utf-8",
    )

    workstreams = build_panel.extract_workstreams(path)

    assert workstreams["phase"] == "pilot: only"
    assert workstreams["workstreams"]["control_panel"]["summary"] == "keep: quoted value"


def test_source_health_distinguishes_required_and_optional_files(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run_summary.json").write_text("{}", encoding="utf-8")

    health = build_panel.source_health({"core_run": run_dir / "run_summary.json", "optional": run_dir / "optional.json"}, root=tmp_path)

    assert health["core_run"] == {"path": "run/run_summary.json", "available": True}
    assert health["optional"] == {"path": "run/optional.json", "available": False}


def test_require_core_run_raises_when_summary_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_panel.require_core_run(tmp_path)


def test_require_core_run_checks_all_core_inputs(tmp_path):
    (tmp_path / "run_summary.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="analysis_summary.json"):
        build_panel.require_core_run(tmp_path)


def test_build_data_exposes_project_meta_and_source_health(tmp_path, monkeypatch):
    run_dir = Path("outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_v2_qualityfix_20260710")
    monkeypatch.setattr(build_panel, "STATUS_YAML", Path("docs/project_status.yaml"))

    data = build_panel.build_data(run_dir)

    assert "project_meta" in data
    assert data["project_meta"]["status"]["release_readiness"] == "pilot_only"
    assert "source_health" in data
    assert data["source_health"]["core_run"]["available"] is True
    assert set(data["source_health"]) >= {"core_run", "dmx_evaluation", "generation_benchmark", "ocr_audit", "experiment_results", "pilot10_manifest"}
    assert "source_case_count" in data["kpi"]
    assert "failure_rate" in data["kpi"]


def test_extract_pilot10_uses_annotation_validator_for_completion(tmp_path):
    package = tmp_path / "pilot10"
    cases = package / "cases"
    cases.mkdir(parents=True)
    (package / "manifest.jsonl").write_text(
        '{"pilot_case_id":"pilot-001","modality":"cxr","body_part":"chest","annotation_path":"cases/pilot-001.json","status":"not_started"}\n',
        encoding="utf-8",
    )
    (cases / "pilot-001.json").write_text(
        '{"schema_version":"2.0","artifact_type":"clinical_annotation_case","pilot_case_id":"pilot-001",'
        '"source_case_sha256":"' + 'a' * 64 + '","modality":"cxr","body_part":"chest","reference_report":"",'
        '"candidate_reports":[],"annotations":{"reader_a":{"reader_slot":"reader_a","status":"not_started",'
        '"findings":[],"hazards":[],"overall_notes":"","confidence":null},"reader_b":{"reader_slot":"reader_b",'
        '"status":"not_started","findings":[],"hazards":[],"overall_notes":"","confidence":null},'
        '"adjudication":{"reader_slot":"adjudication","status":"not_started","findings":[],"hazards":[],'
        '"overall_notes":"","confidence":null}}}\n',
        encoding="utf-8",
    )

    result = build_panel.extract_pilot10(package / "manifest.jsonl")

    assert result["done"] == 0
    assert result["validation_status"] == "not_started"
