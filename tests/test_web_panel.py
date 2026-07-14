from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "web"))
import build_panel


def test_extract_git_state_reports_branch_sha_and_dirty(tmp_path):
    state = build_panel.extract_git_state(tmp_path)

    assert set(state) >= {"branch", "sha", "dirty"}
    assert state["branch"] is None or isinstance(state["branch"], str)
    assert state["sha"] is None or isinstance(state["sha"], str)
    assert isinstance(state["dirty"], bool)


def test_extract_project_status_uses_real_yaml():
    path = Path("docs/project_status.yaml")
    status = build_panel.extract_project_status(path)

    assert status["release_readiness"] == "pilot_only"
    assert status["baseline"]["case_count"] == 52
    assert "control_panel" in status["workstreams"]


def test_source_health_distinguishes_required_and_optional_files(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run_summary.json").write_text("{}", encoding="utf-8")

    health = build_panel.source_health(run_dir, [run_dir / "optional.json"])

    assert health["core_run"]["status"] == "present"
    assert health["optional.json"]["status"] == "missing"


def test_require_core_run_raises_when_summary_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_panel.require_core_run(tmp_path)


def test_build_data_exposes_project_meta_and_source_health(tmp_path, monkeypatch):
    run_dir = Path("outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_v2_qualityfix_20260710")
    monkeypatch.setattr(build_panel, "STATUS_YAML", Path("docs/project_status.yaml"))

    data = build_panel.build_data(run_dir)

    assert "project_meta" in data
    assert data["project_meta"]["release_readiness"] == "pilot_only"
    assert "source_health" in data
    assert data["source_health"]["core_run"]["status"] == "present"
