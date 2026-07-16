from __future__ import annotations

import pytest

from medharness2.control_plane import RunStore


def test_run_store_lifecycle_persists_runs_stages_and_artifacts(tmp_path):
    store = RunStore(tmp_path / "control.sqlite3")
    run = store.create_run(run_type="formal_benchmark", inputs={"manifest": "manifest.jsonl"})

    assert run["status"] == "queued"
    store.transition_run(run["run_id"], "running")
    stage = store.start_stage(run["run_id"], "preflight")
    store.finish_stage(stage["stage_id"], status="succeeded", metrics={"case_count": 10})
    store.add_artifact(
        run["run_id"],
        stage="preflight",
        name="preflight",
        path="outputs/preflight.json",
        schema_version="2.0",
        sha256="a" * 64,
    )
    store.transition_run(run["run_id"], "succeeded")

    detail = store.get_run(run["run_id"])
    assert detail["status"] == "succeeded"
    assert detail["stages"][0]["metrics"] == {"case_count": 10}
    assert detail["artifacts"][0]["sha256"] == "a" * 64
    assert RunStore(tmp_path / "control.sqlite3").get_run(run["run_id"])["status"] == "succeeded"


def test_run_store_rejects_invalid_state_transition(tmp_path):
    store = RunStore(tmp_path / "control.sqlite3")
    run = store.create_run(run_type="sample_full", inputs={})

    with pytest.raises(ValueError, match="queued -> succeeded"):
        store.transition_run(run["run_id"], "succeeded")


def test_cancelled_run_can_be_requeued(tmp_path):
    store = RunStore(tmp_path / "control.sqlite3")
    run = store.create_run(run_type="sample_full", inputs={})

    store.cancel_run(run["run_id"])
    retried = store.retry_run(run["run_id"])

    assert retried["status"] == "queued"
    assert retried["retry_count"] == 1


@pytest.mark.parametrize("bad", [True, 1.5, "10", 0, -1, 1001])
def test_run_store_list_runs_rejects_implicit_or_out_of_range_limits(tmp_path, bad):
    store = RunStore(tmp_path / "control.sqlite3")
    with pytest.raises(ValueError, match="limit"):
        store.list_runs(limit=bad)
