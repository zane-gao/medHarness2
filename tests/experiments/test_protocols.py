from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from medharness2.experiment_protocols import evaluate_readiness, load_experiment_protocols, load_validation_evidence
from medharness2.workflows.experiments import build_experiment_results


def test_six_notion_protocols_load_from_yaml():
    protocols = load_experiment_protocols()

    assert set(protocols) == {
        "radiologist_evaluation",
        "finding_extraction",
        "hazard_evaluation",
        "educational_study",
        "image_to_text_models",
        "modality_recognition",
    }
    for protocol in protocols.values():
        assert protocol.source_path.suffix == ".yaml"
        assert protocol.validation_gates
        assert protocol.primary_endpoints


def test_missing_inputs_are_not_ready(tmp_path: Path):
    result = build_experiment_results(tmp_path)

    assert {item["status"] for item in result["experiments"]} == {"not_ready"}


def test_available_unvalidated_evidence_is_pilot():
    run_dir = Path("outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_tool2_v1")

    result = build_experiment_results(run_dir)

    assert result["experiment_count"] == 6
    assert {item["status"] for item in result["experiments"]} == {"pilot"}
    assert all(item["gate_summary"]["failed"] > 0 for item in result["experiments"])


def test_experiment_becomes_validated_only_when_all_gates_have_evidence(tmp_path: Path):
    run_dir = _minimal_radiologist_run(tmp_path / "run")
    protocols = load_experiment_protocols()
    protocol = protocols["radiologist_evaluation"]
    evidence = {}
    for gate in protocol.validation_gates:
        path = run_dir / "validation" / f"{gate.id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "artifact_type": "experiment_gate_evidence",
                    "gate_id": gate.id,
                    "result": {"complete": True},
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        evidence[gate.id] = _verified_gate(run_dir, path, gate.id)
    (run_dir / "experiment_validation.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "experiments": {"radiologist_evaluation": {"gates": evidence}},
            }
        ),
        encoding="utf-8",
    )

    result = build_experiment_results(run_dir)
    by_id = {item["id"]: item for item in result["experiments"]}

    assert by_id["radiologist_evaluation"]["status"] == "validated"
    assert by_id["radiologist_evaluation"]["gate_summary"]["failed"] == 0


def test_empty_json_evidence_cannot_validate_an_experiment(tmp_path: Path):
    run_dir = _minimal_radiologist_run(tmp_path / "run")
    protocol = load_experiment_protocols()["radiologist_evaluation"]
    evidence = {}
    for gate in protocol.validation_gates:
        path = run_dir / "validation" / f"{gate.id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        evidence[gate.id] = _verified_gate(run_dir, path, gate.id)
    (run_dir / "experiment_validation.json").write_text(
        json.dumps({"experiments": {"radiologist_evaluation": {"gates": evidence}}}),
        encoding="utf-8",
    )

    result = build_experiment_results(run_dir)
    item = next(row for row in result["experiments"] if row["id"] == "radiologist_evaluation")

    assert item["status"] == "pilot"
    assert {gate["reason"] for gate in item["validation_gates"]} == {"invalid_json_evidence_contract"}


def test_tampered_gate_evidence_hash_stays_pilot(tmp_path: Path):
    run_dir = _minimal_radiologist_run(tmp_path / "run")
    protocol = load_experiment_protocols()["radiologist_evaluation"]
    evidence = {}
    for gate in protocol.validation_gates:
        path = run_dir / "validation" / f"{gate.id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"schema_version": "1.0", "artifact_type": "experiment_gate_evidence", "gate_id": gate.id}),
            encoding="utf-8",
        )
        evidence[gate.id] = _verified_gate(run_dir, path, gate.id)
    first_gate = protocol.validation_gates[0]
    first_path = run_dir / "validation" / f"{first_gate.id}.json"
    first_path.write_text(first_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    (run_dir / "experiment_validation.json").write_text(
        json.dumps({"experiments": {"radiologist_evaluation": {"gates": evidence}}}),
        encoding="utf-8",
    )

    result = build_experiment_results(run_dir)
    item = next(row for row in result["experiments"] if row["id"] == "radiologist_evaluation")

    assert item["status"] == "pilot"
    by_gate = {gate["id"]: gate for gate in item["validation_gates"]}
    assert by_gate[first_gate.id]["reason"] == "evidence_sha256_mismatch"


def test_passing_flag_without_existing_evidence_path_stays_pilot(tmp_path: Path):
    run_dir = _minimal_radiologist_run(tmp_path / "run")
    protocol = load_experiment_protocols()["radiologist_evaluation"]
    evidence = {
        gate.id: {"passed": True, "evidence_paths": ["validation/missing.json"]}
        for gate in protocol.validation_gates
    }
    (run_dir / "experiment_validation.json").write_text(
        json.dumps({"experiments": {"radiologist_evaluation": {"gates": evidence}}}),
        encoding="utf-8",
    )

    result = build_experiment_results(run_dir)
    item = next(row for row in result["experiments"] if row["id"] == "radiologist_evaluation")

    assert item["status"] == "pilot"


@pytest.mark.parametrize("payload", [{"experiments": []}, {"experiments": {"radiologist_evaluation": []}}])
def test_validation_evidence_rejects_non_mapping_sections(tmp_path: Path, payload):
    (tmp_path / "experiment_validation.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="experiments"):
        load_validation_evidence(tmp_path)


def test_readiness_rejects_non_mapping_gate_payload(tmp_path: Path):
    protocol = load_experiment_protocols()["radiologist_evaluation"]
    with pytest.raises(ValueError, match="gates"):
        evaluate_readiness(
            protocol,
            evidence_status="available",
            validation_evidence={protocol.id: {"gates": []}},
            run_dir=tmp_path,
        )


@pytest.mark.parametrize("field", ["evidence_artifacts", "evidence_paths"])
@pytest.mark.parametrize("bad", ["bad", 7, True, {"path": "x"}, ["bad"]])
def test_readiness_rejects_malformed_evidence_path_fields(tmp_path: Path, field: str, bad: object):
    protocol = load_experiment_protocols()["radiologist_evaluation"]
    gates = {gate.id: {field: bad} for gate in protocol.validation_gates}
    result = evaluate_readiness(
        protocol,
        evidence_status="available",
        validation_evidence={protocol.id: {"gates": gates}},
        run_dir=tmp_path,
    )
    assert all(gate["reason"] == "invalid_gate_evidence_contract" for gate in result["validation_gates"])


def _minimal_radiologist_run(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "workflow2.json").write_text(
        json.dumps(
            {
                "case_count": 1,
                "per_reader": {"reader-a": {"case_count": 1}},
                "cases": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "workflow3.json").write_text(
        json.dumps({"reader_percentiles": {"reader-a": {"percentile": 100}}}),
        encoding="utf-8",
    )
    analysis = root / "analysis"
    analysis.mkdir()
    (analysis / "analysis_summary.json").write_text(
        json.dumps({"case_count": 1, "reader_count": 1}),
        encoding="utf-8",
    )
    return root


def _verified_gate(run_dir: Path, evidence_path: Path, gate_id: str) -> dict:
    row = {
        "passed": True,
        "verifier": "medharness2.experiments.verify",
        "verification_version": "1.0",
        "evidence_artifacts": [
            {
                "path": str(evidence_path.relative_to(run_dir)),
                "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                "schema_version": "1.0",
                "artifact_type": "experiment_gate_evidence",
                "media_type": "application/json",
            }
        ],
        "checks": [
            {
                "id": f"{gate_id}_machine_check",
                "passed": True,
                "details": "Machine-verifiable gate evidence is complete.",
            }
        ],
    }
    row["verification_id"] = hashlib.sha256(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return row
