from __future__ import annotations

import json
from pathlib import Path

import pytest

from medharness2.annotation.models import AnnotationCase, CandidateReportForAnnotation, ReaderAnnotation
from medharness2.ocr_benchmark import evaluate_ocr_candidates
from medharness2.research_prep import (
    evaluate_paper_evidence_gate,
    freeze_ocr_winner,
    prepare_research_manifests,
    run_ocr_research,
)
import medharness2.research_prep as research_prep
from medharness2.annotation.analysis import analyze_pilot_annotations


def _pilot(tmp_path: Path, rows: list[dict]) -> Path:
    root = tmp_path / "pilot"
    root.mkdir()
    cases = root / "cases"
    cases.mkdir()
    for row in rows:
        relative = row.get("annotation_path")
        if not isinstance(relative, str) or not relative.startswith("cases/"):
            continue
        case = AnnotationCase(
            pilot_case_id=str(row.get("pilot_case_id") or "pilot-test"),
            source_case_sha256="a" * 64,
            modality=str(row.get("modality") or "unknown").lower(),
            body_part="unknown",
            reference_report="reference",
            candidate_reports=[
                CandidateReportForAnnotation(
                    candidate_id="candidate-01",
                    blinded_model_id="model-01",
                    report_text="candidate",
                )
            ],
            annotations={
                slot: ReaderAnnotation(reader_slot=slot)
                for slot in ("reader_a", "reader_b", "adjudication")
            },
        )
        (root / relative).write_text(case.model_dump_json(indent=2) + "\n", encoding="utf-8")
    manifest_rows = []
    for row in rows:
        normalized = dict(row)
        normalized.setdefault("body_part", "unknown")
        normalized.setdefault("candidate_count", 1)
        normalized.setdefault("status", "not_started")
        manifest_rows.append(normalized)
    (root / "manifest.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in manifest_rows), encoding="utf-8"
    )
    return root


def test_prepare_research_manifests_creates_blocked_ocr_and_paper_plans(tmp_path: Path):
    pilot = _pilot(
        tmp_path,
        [
            {"pilot_case_id": "pilot-001", "modality": "DX", "annotation_path": "cases/pilot-001.json"},
            {"pilot_case_id": "pilot-002", "modality": "CT", "annotation_path": "cases/pilot-002.json"},
            {"pilot_case_id": "pilot-003", "modality": "MR", "annotation_path": "cases/pilot-003.json"},
        ],
    )
    result = prepare_research_manifests(pilot, tmp_path / "research")
    assert result["status"] == "blocked"
    assert result["modality_coverage"] == ["ct", "cxr", "mri"]
    ocr = json.loads((tmp_path / "research" / "ocr_manifest.json").read_text())
    assert ocr["winner_status"] == "blocked"
    assert ocr["candidate_count"] == 3
    assert ocr["repeat_count"] == 2
    assert ocr["gold_source"] == "beichuan_reference_report"
    assert ocr["gold_status"] == "available_for_current_benchmark"
    assert len(ocr["runs"]) == 18
    assert ocr["runs"][0]["blocked_reasons"] == ["real_provider_run_not_available"]
    assert ocr["runs"][0]["gold_source"] == "beichuan_reference_report"
    assert ocr["benchmark_manifests"] == [
        "ocr_benchmark_repeat_1.json",
        "ocr_benchmark_repeat_2.json",
    ]
    repeat_manifest = json.loads((tmp_path / "research" / "ocr_benchmark_repeat_1.json").read_text())
    assert repeat_manifest["gold_source"] == "beichuan_reference_report"
    assert len(repeat_manifest["cases"]) == 3
    assert set(repeat_manifest["cases"][0]["candidates"]) == {
        "ocr_primary_doubao",
        "ocr_baseline_paddle",
    }
    assert set(repeat_manifest["cases"][0]["audit_candidates"]) == {"ocr_verifier_qwen"}
    benchmark_result = evaluate_ocr_candidates(
        tmp_path / "research" / "ocr_benchmark_repeat_1.json",
        tmp_path / "research" / "repeat-1-result.json",
    )
    assert benchmark_result["status"] == "blocked"
    assert benchmark_result["selection"]["status"] == "blocked"
    paper = json.loads((tmp_path / "research" / "paper_experiment_manifest.json").read_text())
    assert paper["formal_claim_allowed"] is False
    assert paper["data"]["gold_source"] == "beichuan_reference_report"
    assert paper["data"]["clinical_reader_status"] == "not_started"
    assert {item["id"] for item in paper["experiments"]} == {
        "ocr_comparison", "finding_extraction", "report_generation", "reader_and_model_evaluation"
    }


@pytest.mark.parametrize("bad", [[], "bad", True, 1])
def test_prepare_research_manifests_rejects_malformed_manifest(tmp_path: Path, bad):
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    (pilot / "manifest.jsonl").write_text(json.dumps(bad) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="pilot_manifest"):
        prepare_research_manifests(pilot, tmp_path / "research")


@pytest.mark.parametrize(
    "field,bad",
    [("pilot_case_id", ""), ("pilot_case_id", 1), ("modality", []), ("annotation_path", True)],
)
def test_prepare_research_manifests_rejects_malformed_identity_fields(tmp_path: Path, field: str, bad: object):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}],
    )
    row = {"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}
    row[field] = bad
    (pilot / "manifest.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="pilot_manifest"):
        prepare_research_manifests(pilot, tmp_path / "research")


def test_prepare_research_manifests_rejects_duplicate_identity(tmp_path: Path):
    pilot = _pilot(
        tmp_path,
        [
            {"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/a.json"},
            {"pilot_case_id": "pilot-001", "modality": "ct", "annotation_path": "cases/b.json"},
        ],
    )
    with pytest.raises(ValueError, match="duplicate_case_id"):
        prepare_research_manifests(pilot, tmp_path / "research")


def test_prepare_research_manifests_rejects_missing_annotation_case(tmp_path: Path):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/missing.json"}],
    )
    (pilot / "cases" / "missing.json").unlink()
    with pytest.raises(ValueError, match="annotation_case"):
        prepare_research_manifests(pilot, tmp_path / "research")


def test_prepare_research_manifests_rejects_annotation_case_identity_mismatch(tmp_path: Path):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}],
    )
    case_path = pilot / "cases" / "pilot-001.json"
    raw = json.loads(case_path.read_text(encoding="utf-8"))
    raw["pilot_case_id"] = "pilot-999"
    case_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="annotation_case"):
        prepare_research_manifests(pilot, tmp_path / "research")


def test_prepare_research_manifests_propagates_valid_reader_progress(tmp_path: Path):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}],
    )
    case_path = pilot / "cases" / "pilot-001.json"
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    payload["annotations"]["reader_a"]["status"] = "in_progress"
    case_path.write_text(json.dumps(payload), encoding="utf-8")
    row = json.loads((pilot / "manifest.jsonl").read_text(encoding="utf-8"))
    row["status"] = "in_progress"
    (pilot / "manifest.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

    result = prepare_research_manifests(pilot, tmp_path / "research")

    paper = json.loads((tmp_path / "research" / "paper_experiment_manifest.json").read_text())
    assert result["status"] == "blocked"
    assert paper["data"]["clinical_reader_status"] == "in_progress"


def test_run_ocr_research_blocks_without_real_provider_and_writes_no_text(tmp_path: Path):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}],
    )
    research = tmp_path / "research"
    prepare_research_manifests(pilot, research)

    result = run_ocr_research(
        pilot,
        research,
        config_path=tmp_path / "missing-config.yaml",
    )

    assert result["status"] == "blocked"
    assert "real_ocr_provider_unavailable" in result["blocked_reasons"]
    assert not list((research / "ocr_runs").rglob("*.txt"))
    sidecars = list((research / "ocr_runs").rglob("*.json"))
    assert sidecars
    assert all(json.loads(path.read_text())["status"] == "blocked" for path in sidecars)
    assert all(json.loads(path.read_text())["model_key"] in {
        "ocr_primary_doubao", "ocr_verifier_qwen", "ocr_baseline_paddle"
    } for path in sidecars)
    assert set(result["benchmark_results"]) == {"1", "2"}


def test_run_ocr_research_records_missing_source_pdf_per_case(tmp_path: Path):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}],
    )
    research = tmp_path / "research"
    prepare_research_manifests(pilot, research)

    result = run_ocr_research(pilot, research)

    assert result["status"] == "blocked"
    assert "source_pdf_missing" in result["blocked_reasons"]
    assert result["blocked_count"] > 0


def test_analyze_pilot_annotations_blocks_until_both_readers_and_adjudication_complete(tmp_path: Path):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}],
    )
    result = analyze_pilot_annotations(pilot, tmp_path / "analysis.json")
    assert result["status"] == "blocked"
    assert result["complete_case_count"] == 0
    payload = json.loads((tmp_path / "analysis.json").read_text())
    assert payload["formal_claim_allowed"] is False
    assert payload["disagreement_queue"] == []


def test_analyze_pilot_annotations_writes_blocked_artifact_for_invalid_manifest(tmp_path: Path):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}],
    )
    manifest = pilot / "manifest.jsonl"
    row = json.loads(manifest.read_text(encoding="utf-8").splitlines()[0])
    row["annotation_path"] = "../outside.json"
    manifest.write_text(json.dumps(row) + "\n", encoding="utf-8")

    output = tmp_path / "analysis.json"
    result = analyze_pilot_annotations(pilot, output)

    assert result["status"] == "blocked"
    assert result["case_count"] == 1
    assert result["complete_case_count"] == 0
    assert result["formal_claim_allowed"] is False
    assert result["reader_agreement"]["compared_case_count"] == 0
    assert result["validation"]["errors"]
    assert output.exists()


def test_analyze_pilot_annotations_emits_reader_agreement_and_disagreement_queue(tmp_path: Path):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}],
    )
    case_path = pilot / "cases/pilot-001.json"
    case = AnnotationCase.model_validate_json(case_path.read_text())
    for slot, finding_id in (("reader_a", "f-1"), ("reader_b", "f-2"), ("adjudication", "f-1")):
        case.annotations[slot] = ReaderAnnotation(
            reader_slot=slot,
            status="complete",
            findings=[],
            hazards=[],
            overall_notes="done",
            confidence=0.9,
        )
    case.annotations["reader_a"].findings = []
    case.annotations["reader_b"].findings = []
    case.annotations["reader_a"].hazards = []
    case.annotations["reader_b"].hazards = []
    case_path.write_text(case.model_dump_json(indent=2) + "\n")
    manifest = pilot / "manifest.jsonl"
    row = json.loads(manifest.read_text().splitlines()[0])
    row["status"] = "complete"
    manifest.write_text(json.dumps(row) + "\n")
    result = analyze_pilot_annotations(pilot, tmp_path / "analysis.json")
    assert result["status"] == "complete"
    assert result["complete_case_count"] == 1
    assert result["reader_agreement"]["case_exact_agreement"] == 1.0
    assert result["formal_claim_allowed"] is False
    assert result["formal_claim_reason"] == "paper_evidence_gate_not_satisfied"
    assert result["reader_agreement"]["finding_presence_kappa"]["kappa"] == 1.0


def test_evaluate_paper_evidence_gate_is_blocked_without_external_evidence(tmp_path: Path):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}],
    )
    research = tmp_path / "research"
    prepare_research_manifests(pilot, research)
    result = evaluate_paper_evidence_gate(
        research,
        tmp_path / "missing-annotation-analysis.json",
        tmp_path / "missing-experiment-results.json",
        tmp_path / "paper-gate.json",
    )
    assert result["status"] == "blocked"
    assert result["formal_claim_allowed"] is False
    assert {item["id"] for item in result["checks"]} == {
        "clinical_reader_annotation",
        "ocr_winner",
        "formal_experiments",
    }


def test_evaluate_paper_evidence_gate_fails_closed_on_malformed_inputs(tmp_path: Path):
    research = tmp_path / "research"
    research.mkdir()
    (research / "ocr_manifest.json").write_text(
        json.dumps({"status": "succeeded", "winner_status": "validated", "benchmark_results": {"1": {"status": "succeeded"}, "2": {"status": "succeeded"}}}),
        encoding="utf-8",
    )
    annotation = tmp_path / "annotation.json"
    annotation.write_text(json.dumps({"status": "complete", "case_count": "1", "complete_case_count": 1}), encoding="utf-8")
    experiments = tmp_path / "experiments.json"
    experiments.write_text(json.dumps({"experiments": "validated"}), encoding="utf-8")

    result = evaluate_paper_evidence_gate(research, annotation, experiments, tmp_path / "gate.json")

    assert result["status"] == "blocked"
    assert result["formal_claim_allowed"] is False
    assert all(item["passed"] is False for item in result["checks"] if item["id"] != "ocr_winner")
    assert (tmp_path / "gate.json").exists()


def test_evaluate_paper_evidence_gate_requires_validated_experiment_gates(tmp_path: Path):
    research = tmp_path / "research"
    research.mkdir()
    (research / "ocr_manifest.json").write_text(
        json.dumps({"status": "succeeded", "winner_status": "validated", "benchmark_results": {"1": {"status": "succeeded"}, "2": {"status": "succeeded"}}}),
        encoding="utf-8",
    )
    annotation = tmp_path / "annotation.json"
    annotation.write_text(json.dumps({"status": "complete", "case_count": 1, "complete_case_count": 1}), encoding="utf-8")
    experiments = tmp_path / "experiments.json"
    experiments.write_text(json.dumps({"experiments": [{"status": "validated"}]}), encoding="utf-8")

    result = evaluate_paper_evidence_gate(research, annotation, experiments, tmp_path / "gate.json")

    assert result["status"] == "blocked"
    formal_check = next(item for item in result["checks"] if item["id"] == "formal_experiments")
    assert formal_check["passed"] is False


def test_evaluate_paper_evidence_gate_rejects_thin_ocr_winner_claim(tmp_path: Path):
    research = tmp_path / "research"
    research.mkdir()
    (research / "ocr_manifest.json").write_text(
        json.dumps(
            {
                "status": "succeeded",
                "winner_status": "validated",
                "benchmark_results": {
                    "1": {"status": "succeeded"},
                    "2": {"status": "succeeded"},
                },
            }
        ),
        encoding="utf-8",
    )
    annotation = tmp_path / "annotation.json"
    annotation.write_text(json.dumps({"status": "complete", "case_count": 1, "complete_case_count": 1}), encoding="utf-8")
    experiments = tmp_path / "experiments.json"
    experiments.write_text(json.dumps({"experiments": []}), encoding="utf-8")

    result = evaluate_paper_evidence_gate(research, annotation, experiments, tmp_path / "gate.json")

    ocr_check = next(item for item in result["checks"] if item["id"] == "ocr_winner")
    assert ocr_check["passed"] is False


def test_evaluate_paper_evidence_gate_requires_freeze_metadata(tmp_path: Path):
    research = tmp_path / "research"
    research.mkdir()
    (research / "ocr_manifest.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "artifact_type": "ocr_research_manifest",
            "status": "succeeded",
            "winner_status": "validated",
            "winner_model": "ocr_primary_doubao",
            "freeze_id": "a" * 64,
            "gold_source": "beichuan_reference_report",
            "gold_status": "available_for_current_benchmark",
            "benchmark_results": {
                "1": {"status": "succeeded", "selection": {"status": "provisional", "primary_model": "ocr_primary_doubao"}},
                "2": {"status": "succeeded", "selection": {"status": "provisional", "primary_model": "ocr_primary_doubao"}},
            },
        }),
        encoding="utf-8",
    )
    result = evaluate_paper_evidence_gate(research, tmp_path / "missing-annotation.json", tmp_path / "missing-experiment.json", tmp_path / "gate.json")
    assert next(item for item in result["checks"] if item["id"] == "ocr_winner")["passed"] is False


def test_freeze_ocr_winner_requires_two_consistent_benchmarks(tmp_path: Path):
    research = tmp_path / "research"
    research.mkdir()
    (research / "ocr_manifest.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "artifact_type": "ocr_research_manifest",
            "status": "succeeded",
            "gold_source": "beichuan_reference_report",
            "gold_status": "available_for_current_benchmark",
            "case_count": 1,
            "candidate_count": 2,
            "benchmark_candidates": [
                {"candidate_id": "ocr_primary_doubao"},
                {"candidate_id": "ocr_baseline_paddle"},
            ],
            "repeat_count": 2,
            "runs": [
                {"pilot_case_id": "pilot-001", "candidate": {"candidate_id": "ocr_primary_doubao"}, "repeat": 1, "status": "succeeded", "quality_status": "passed"},
                {"pilot_case_id": "pilot-001", "candidate": {"candidate_id": "ocr_primary_doubao"}, "repeat": 2, "status": "succeeded", "quality_status": "passed"},
                {"pilot_case_id": "pilot-001", "candidate": {"candidate_id": "ocr_baseline_paddle"}, "repeat": 1, "status": "succeeded", "quality_status": "passed"},
                {"pilot_case_id": "pilot-001", "candidate": {"candidate_id": "ocr_baseline_paddle"}, "repeat": 2, "status": "succeeded", "quality_status": "passed"},
            ],
        }),
        encoding="utf-8",
    )
    for repeat in (1, 2):
        (research / f"ocr_benchmark_repeat_{repeat}_result.json").write_text(
            json.dumps({
                "status": "succeeded",
                "evaluated_count": 2,
                "case_count": 1,
                "blocked_items": [],
                "selection": {"status": "provisional", "primary_model": "ocr_primary_doubao"},
            }),
            encoding="utf-8",
        )

    result = freeze_ocr_winner(research)

    assert result["status"] == "frozen"
    assert result["winner_model"] == "ocr_primary_doubao"
    manifest = json.loads((research / "ocr_manifest.json").read_text())
    assert manifest["schema_version"] == "1.0"
    assert manifest["artifact_type"] == "ocr_research_manifest"
    assert manifest["winner_status"] == "frozen"
    assert len(manifest["freeze_id"]) == 64
    assert set(manifest["benchmark_results"]) == {"1", "2"}
    repeat = freeze_ocr_winner(research)
    assert repeat == result


def test_freeze_ocr_winner_rejects_case_count_or_run_identity_mismatch(tmp_path: Path):
    research = tmp_path / "research"
    research.mkdir()
    manifest = {
        "status": "succeeded",
        "gold_source": "beichuan_reference_report",
        "gold_status": "available_for_current_benchmark",
        "case_count": 2,
        "candidate_count": 1,
        "benchmark_candidates": [{"candidate_id": "ocr_primary_doubao"}],
        "repeat_count": 2,
        "runs": [
            {"pilot_case_id": "pilot-001", "candidate": {"candidate_id": "ocr_primary_doubao"}, "repeat": 1, "status": "succeeded", "quality_status": "passed"},
            {"pilot_case_id": "pilot-001", "candidate": {"candidate_id": "ocr_primary_doubao"}, "repeat": 2, "status": "succeeded", "quality_status": "passed"},
            {"pilot_case_id": "pilot-002", "candidate": {"candidate_id": "ocr_primary_doubao"}, "repeat": 1, "status": "succeeded", "quality_status": "passed"},
            # Repeat 2 for pilot-002 is intentionally absent.
        ],
    }
    (research / "ocr_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for repeat in (1, 2):
        (research / f"ocr_benchmark_repeat_{repeat}_result.json").write_text(
            json.dumps({
                "status": "succeeded", "evaluated_count": 2, "case_count": 2,
                "blocked_items": [],
                "selection": {"status": "provisional", "primary_model": "ocr_primary_doubao"},
            }),
            encoding="utf-8",
        )
    with pytest.raises(ValueError, match="ocr_manifest_run_coverage_mismatch"):
        freeze_ocr_winner(research)


def test_freeze_ocr_winner_rejects_malformed_idempotent_evidence(tmp_path: Path):
    research = tmp_path / "research"
    research.mkdir()
    manifest = {
        "status": "succeeded",
        "winner_status": "frozen",
        "winner_model": "ocr_primary_doubao",
        "freeze_id": "a" * 64,
        "freeze_version": "ocr-winner-freeze-v1",
        "freeze_evidence": {
            "benchmark_results": ["ocr_benchmark_repeat_1_result.json"],
            "evaluated_count_by_repeat": {"1": 1, "2": 1},
        },
        "gold_source": "beichuan_reference_report",
        "gold_status": "available_for_current_benchmark",
        "case_count": 1,
        "candidate_count": 1,
        "benchmark_candidates": [{"candidate_id": "ocr_primary_doubao"}],
        "repeat_count": 2,
        "runs": [
            {"pilot_case_id": "pilot-001", "candidate": {"candidate_id": "ocr_primary_doubao"}, "repeat": 1, "status": "succeeded", "quality_status": "passed"},
            {"pilot_case_id": "pilot-001", "candidate": {"candidate_id": "ocr_primary_doubao"}, "repeat": 2, "status": "succeeded", "quality_status": "passed"},
        ],
    }
    (research / "ocr_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen_ocr_manifest_incomplete"):
        freeze_ocr_winner(research)


def test_paper_gate_rejects_status_only_annotation_artifact(tmp_path: Path):
    research = tmp_path / "research"
    research.mkdir()
    (research / "ocr_manifest.json").write_text(json.dumps({}), encoding="utf-8")
    annotation = tmp_path / "annotation.json"
    annotation.write_text(json.dumps({
        "schema_version": "1.0",
        "artifact_type": "pilot_annotation_analysis",
        "status": "complete",
        "case_count": 1,
        "complete_case_count": 1,
        "validation": {"status": "complete", "case_count": 1, "complete_case_count": 1, "errors": []},
    }), encoding="utf-8")
    experiments = tmp_path / "experiments.json"
    experiments.write_text(json.dumps({"experiments": []}), encoding="utf-8")
    result = evaluate_paper_evidence_gate(research, annotation, experiments, tmp_path / "gate.json")
    assert next(item for item in result["checks"] if item["id"] == "clinical_reader_annotation")["passed"] is False


def test_freeze_ocr_winner_rejects_disagreement(tmp_path: Path):
    research = tmp_path / "research"
    research.mkdir()
    (research / "ocr_manifest.json").write_text(
        json.dumps({
            "status": "succeeded",
            "gold_source": "beichuan_reference_report",
            "gold_status": "available_for_current_benchmark",
            "case_count": 1,
            "candidate_count": 2,
            "benchmark_candidates": [
                {"candidate_id": "ocr_primary_doubao"},
                {"candidate_id": "ocr_baseline_paddle"},
            ],
            "repeat_count": 2,
            "runs": [
                {"pilot_case_id": "pilot-001", "candidate": {"candidate_id": "ocr_primary_doubao"}, "repeat": 1, "status": "succeeded", "quality_status": "passed"},
                {"pilot_case_id": "pilot-001", "candidate": {"candidate_id": "ocr_primary_doubao"}, "repeat": 2, "status": "succeeded", "quality_status": "passed"},
                {"pilot_case_id": "pilot-001", "candidate": {"candidate_id": "ocr_baseline_paddle"}, "repeat": 1, "status": "succeeded", "quality_status": "passed"},
                {"pilot_case_id": "pilot-001", "candidate": {"candidate_id": "ocr_baseline_paddle"}, "repeat": 2, "status": "succeeded", "quality_status": "passed"},
            ],
        }),
        encoding="utf-8",
    )
    for repeat, model in ((1, "ocr_primary_doubao"), (2, "ocr_baseline_paddle")):
        (research / f"ocr_benchmark_repeat_{repeat}_result.json").write_text(
            json.dumps({"status": "succeeded", "evaluated_count": 2, "case_count": 1, "blocked_items": [], "selection": {"status": "provisional", "primary_model": model}}),
            encoding="utf-8",
        )
    with pytest.raises(ValueError, match="winner_model_disagreement"):
        freeze_ocr_winner(research)


def test_freeze_ocr_winner_rejects_partial_or_blocked_benchmark(tmp_path: Path):
    research = tmp_path / "research"
    research.mkdir()
    (research / "ocr_manifest.json").write_text(
        json.dumps({
            "status": "succeeded",
            "gold_source": "beichuan_reference_report",
            "gold_status": "available_for_current_benchmark",
            "case_count": 2,
            "candidate_count": 1,
            "benchmark_candidates": [{"candidate_id": "ocr_primary_doubao"}],
            "repeat_count": 2,
            "runs": [
                {"pilot_case_id": "pilot-001", "candidate": {"candidate_id": "ocr_primary_doubao"}, "repeat": 1, "status": "succeeded", "quality_status": "passed"},
                {"pilot_case_id": "pilot-001", "candidate": {"candidate_id": "ocr_primary_doubao"}, "repeat": 2, "status": "succeeded", "quality_status": "passed"},
                {"pilot_case_id": "pilot-002", "candidate": {"candidate_id": "ocr_primary_doubao"}, "repeat": 1, "status": "succeeded", "quality_status": "passed"},
                {"pilot_case_id": "pilot-002", "candidate": {"candidate_id": "ocr_primary_doubao"}, "repeat": 2, "status": "succeeded", "quality_status": "passed"},
            ],
        }),
        encoding="utf-8",
    )
    (research / "ocr_benchmark_repeat_1_result.json").write_text(
        json.dumps({
            "status": "succeeded",
            "evaluated_count": 1,
            "case_count": 2,
            "blocked_items": ["coverage:ocr_primary_doubao"],
            "selection": {"status": "provisional", "primary_model": "ocr_primary_doubao"},
        }),
        encoding="utf-8",
    )
    (research / "ocr_benchmark_repeat_2_result.json").write_text(
        json.dumps({
            "status": "succeeded",
            "evaluated_count": 2,
            "case_count": 2,
            "blocked_items": [],
            "selection": {"status": "provisional", "primary_model": "ocr_primary_doubao"},
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ocr_benchmark_repeat_1_not_clean"):
        freeze_ocr_winner(research)


def test_freeze_ocr_winner_writes_manifest_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    research = tmp_path / "research"
    research.mkdir()
    (research / "ocr_manifest.json").write_text(
        json.dumps({
            "status": "succeeded",
            "gold_source": "beichuan_reference_report",
            "gold_status": "available_for_current_benchmark",
            "case_count": 1,
            "candidate_count": 1,
            "benchmark_candidates": [{"candidate_id": "ocr_primary_doubao"}],
            "repeat_count": 2,
            "runs": [
                {"pilot_case_id": "pilot-001", "candidate": {"candidate_id": "ocr_primary_doubao"}, "repeat": 1, "status": "succeeded", "quality_status": "passed"},
                {"pilot_case_id": "pilot-001", "candidate": {"candidate_id": "ocr_primary_doubao"}, "repeat": 2, "status": "succeeded", "quality_status": "passed"},
            ],
        }),
        encoding="utf-8",
    )
    for repeat in (1, 2):
        (research / f"ocr_benchmark_repeat_{repeat}_result.json").write_text(
            json.dumps({
                "status": "succeeded",
                "evaluated_count": 1,
                "case_count": 1,
                "blocked_items": [],
                "selection": {"status": "provisional", "primary_model": "ocr_primary_doubao"},
            }),
            encoding="utf-8",
        )
    original = research / "ocr_manifest.json"
    original_bytes = original.read_bytes()

    def fail_replace(_src: Path, _dst: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(research_prep.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        freeze_ocr_winner(research)
    assert original.read_bytes() == original_bytes


def test_run_ocr_research_blocks_unreadable_source_pdf_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}],
    )
    research = tmp_path / "research"
    prepare_research_manifests(pilot, research)
    source_pdf = tmp_path / "report.pdf"
    source_pdf.write_bytes(b"placeholder")
    monkeypatch.setattr(research_prep, "_build_source_pdf_index", lambda _root: {"a" * 64: source_pdf})

    def fail_hash(_path: Path) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr(research_prep, "_hash_file", fail_hash)

    result = run_ocr_research(pilot, research)

    assert result["status"] == "blocked"
    assert "source_pdf_unreadable" in result["blocked_reasons"]
    sidecars = list((research / "ocr_runs").rglob("*.json"))
    assert sidecars
    assert all(json.loads(path.read_text())["blocked_reasons"] == ["source_pdf_unreadable"] for path in sidecars)


def test_run_ocr_research_persists_sidecar_statuses_and_route_provenance(tmp_path: Path):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}],
    )
    research = tmp_path / "research"
    prepare_research_manifests(pilot, research)

    config = tmp_path / "ocr.yaml"
    config.write_text(
        "\n".join(
            [
                "model_roles:",
                "  ocr_primary:",
                "    provider: chat_completions",
                "    model: custom-primary",
                "    api_key_env: MISSING_PRIMARY_KEY",
                "  ocr_verifier:",
                "    provider: chat_completions",
                "    model: custom-verifier",
                "    api_key_env: MISSING_VERIFIER_KEY",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_ocr_research(pilot, research, config_path=config)

    manifest = json.loads((research / "ocr_manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_summary"]["status"] == result["status"]
    assert manifest["run_summary"]["blocked_count"] == result["blocked_count"]
    assert manifest["benchmark_results"] == result["benchmark_results"]
    runs = manifest["runs"]
    assert len(runs) == 6
    primary = next(item for item in runs if item["candidate"]["candidate_id"] == "ocr_primary_doubao")
    assert primary["candidate"]["model"] == "custom-primary"
    assert primary["status"] == "blocked"
    assert primary["blocked_reasons"] == ["source_pdf_missing"]


def test_run_ocr_research_labels_unintegrated_paddle_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}],
    )
    research = tmp_path / "research"
    prepare_research_manifests(pilot, research)
    source_pdf = tmp_path / "report.pdf"
    source_pdf.write_bytes(b"placeholder")
    monkeypatch.setattr(
        research_prep,
        "_build_source_pdf_index",
        lambda _root: {"a" * 64: source_pdf},
    )

    run_ocr_research(pilot, research)

    sidecar = research / "ocr_runs" / "repeat_1" / "pilot-001" / "ocr_baseline_paddle.json"
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["blocked_reasons"] == ["paddleocr_provider_unavailable"]


def test_run_ocr_research_uses_injected_paddle_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}],
    )
    research = tmp_path / "research"
    prepare_research_manifests(pilot, research)
    source_pdf = tmp_path / "report.pdf"
    source_pdf.write_bytes(b"placeholder")
    monkeypatch.setattr(research_prep, "_build_source_pdf_index", lambda _root: {"a" * 64: source_pdf})
    monkeypatch.setattr(
        research_prep,
        "_ocr_candidate_readiness",
        lambda _config: {
            "ocr_primary_doubao": {"ready": False, "reason": "missing_api_key"},
            "ocr_verifier_qwen": {"ready": True, "reason": ""},
            "ocr_baseline_paddle": {"ready": True, "reason": ""},
        },
    )
    monkeypatch.setattr(
        research_prep,
        "_run_paddleocr_candidate",
        lambda *args, **kwargs: {"text": "FINDINGS: normal\nIMPRESSION: normal", "warnings": [], "metadata": {"quality_status": "passed"}},
    )

    result = run_ocr_research(pilot, research)

    payload = json.loads(
        (research / "ocr_runs" / "repeat_1" / "pilot-001" / "ocr_baseline_paddle.json").read_text()
    )
    # A route being ready does not prove that this transcription was audited
    # by Qwen.  The adapter must fail closed to review_required until it
    # returns real page-level audit evidence.
    assert payload["status"] == "review_required"
    assert payload["model_key"] == "ocr_baseline_paddle"
    assert result["success_count"] == 0
    assert result["review_required_count"] == 2


def test_paddleocr_without_verifier_is_review_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}],
    )
    research = tmp_path / "research"
    prepare_research_manifests(pilot, research)
    source_pdf = tmp_path / "report.pdf"
    source_pdf.write_bytes(b"placeholder")
    monkeypatch.setattr(research_prep, "_build_source_pdf_index", lambda _root: {"a" * 64: source_pdf})
    monkeypatch.setattr(
        research_prep,
        "_ocr_candidate_readiness",
        lambda _config: {
            "ocr_primary_doubao": {"ready": False, "reason": "missing_api_key"},
            "ocr_verifier_qwen": {"ready": False, "reason": "missing_api_key"},
            "ocr_baseline_paddle": {"ready": True, "reason": ""},
        },
    )
    monkeypatch.setattr(
        research_prep,
        "_run_paddleocr_candidate",
        lambda *args, **kwargs: {"text": "FINDINGS: normal", "warnings": [], "metadata": {"quality_status": "review_required"}},
    )
    run_ocr_research(pilot, research)
    payload = json.loads((research / "ocr_runs/repeat_1/pilot-001/ocr_baseline_paddle.json").read_text())
    assert payload["status"] == "review_required"


@pytest.mark.parametrize(
    "value,expected",
    [
        ({"markdown_text": "报告文本"}, "报告文本"),
        ({"rec_texts": ["第一行", "第二行"]}, "第一行\n第二行"),
        ({"parsing_res_list": [{"block_content": "版面文本"}]}, "版面文本"),
        ([{"text": "嵌套文本"}], "嵌套文本"),
        ("直接文本", "直接文本"),
    ],
)
def test_paddleocr_text_handles_current_result_shapes(value: object, expected: str):
    assert research_prep._paddleocr_text(value) == expected


def test_paddleocr_readiness_requires_vl_pipeline(monkeypatch: pytest.MonkeyPatch):
    class FakePaddle:
        pass

    fake_module = type("FakeModule", (), {"PaddleOCR": FakePaddle})
    monkeypatch.setitem(__import__("sys").modules, "paddleocr", fake_module)
    readiness = research_prep._ocr_candidate_readiness(research_prep.load_config())
    assert readiness["ocr_baseline_paddle"] == {
        "ready": False,
        "reason": "paddleocr_provider_unavailable",
    }


def test_paddleocr_readiness_reports_runtime_missing(monkeypatch: pytest.MonkeyPatch):
    import sys

    class FakePaddleOCRVL:
        pass

    fake_module = type("FakeModule", (), {"PaddleOCRVL": FakePaddleOCRVL})
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)
    # An importable provider without PaddlePaddle cannot execute the pipeline.
    monkeypatch.setitem(sys.modules, "paddle", None)
    readiness = research_prep._ocr_candidate_readiness(research_prep.load_config())
    assert readiness["ocr_baseline_paddle"] == {
        "ready": False,
        "reason": "paddle_runtime_unavailable",
    }


def test_paddleocr_vl_dict_subclass_reads_markdown_property():
    class FakeResult(dict):
        @property
        def markdown(self):
            return {"markdown_texts": "FINDINGS: from PaddleOCR-VL"}

    assert research_prep._paddleocr_text(FakeResult(parsing_res_list=[])) == "FINDINGS: from PaddleOCR-VL"


def test_paddleocr_text_reads_official_result_markdown_export(tmp_path: Path):
    class OfficialResult:
        def save_to_markdown(self, *, save_path: Path):
            output = Path(save_path) / "page.md"
            output.write_text("FINDINGS: exported markdown", encoding="utf-8")
            return output

    assert research_prep._paddleocr_text(
        OfficialResult(), markdown_dir=tmp_path, page_index=1
    ) == "FINDINGS: exported markdown"


def test_paddleocr_text_replaces_stale_markdown_export(tmp_path: Path):
    stale = tmp_path / "page.md"
    stale.write_text("STALE OCR", encoding="utf-8")

    class OfficialResult:
        def save_to_markdown(self, *, save_path: Path):
            output = Path(save_path) / "page.md"
            output.write_text("FRESH OCR", encoding="utf-8")
            return output

    assert research_prep._paddleocr_text(OfficialResult(), markdown_dir=tmp_path) == "FRESH OCR"


def test_paddleocr_text_reads_object_parsing_block_content():
    class Block:
        content = "OBJECT BLOCK"

    assert research_prep._paddleocr_text({"parsing_res_list": [Block()]}) == "OBJECT BLOCK"


def test_paddleocr_result_empty_text_is_not_accepted():
    with pytest.raises(RuntimeError, match="paddleocr_empty_result"):
        research_prep._validate_paddleocr_result(
            {"text": "", "warnings": [], "metadata": {"quality_status": "passed"}}
        )


@pytest.mark.parametrize("audit", [{"pages": [{"status": "agree"}, "garbage"]}, {"pages": []}])
def test_malformed_paddle_audit_pages_never_pass(audit: dict[str, object]):
    assert research_prep._paddle_audit_passed(audit) is False
    assert research_prep._audit_quality_status(audit) == "blocked"


def test_paddleocr_empty_page_prevents_quality_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source_pdf = tmp_path / "report.pdf"
    source_pdf.write_bytes(b"placeholder")
    pages = [tmp_path / "page-1.png", tmp_path / "page-2.png"]
    for page in pages:
        page.write_bytes(b"page")

    class FakeEngine:
        def __init__(self):
            self.calls = 0

        def predict(self, _page):
            self.calls += 1
            return {} if self.calls == 1 else {"text": "FINDINGS: normal"}

        def close(self):
            return None

    class Verifier:
        def call(self, *_args, **_kwargs):
            return {"status": "agree"}

    fake_module = type("FakePaddleOCR", (), {"PaddleOCRVL": lambda **_kwargs: FakeEngine()})
    monkeypatch.setitem(__import__("sys").modules, "paddleocr", fake_module)
    monkeypatch.setitem(__import__("sys").modules, "paddle", type("FakePaddle", (), {}))
    monkeypatch.setattr(research_prep, "_render_pdf_pages", lambda *_args: [str(page) for page in pages])

    result = research_prep._run_paddleocr_candidate(
        source_pdf,
        case_id="pilot-001",
        output_dir=tmp_path / "cache",
        verifier_ready=True,
        verifier_client=Verifier(),
        verifier_options={},
    )

    assert result["metadata"]["quality_status"] == "review_required"


@pytest.mark.parametrize(
    "bad_result,reason",
    [
        ({"text": "text", "warnings": "not-a-list", "metadata": {"quality_status": "review_required"}}, "paddleocr_invalid_warnings"),
        ({"text": "text", "warnings": [], "metadata": "not-a-dict"}, "paddleocr_invalid_metadata"),
    ],
)
def test_run_ocr_research_blocks_malformed_paddle_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_result: object,
    reason: str,
):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}],
    )
    research = tmp_path / "research"
    prepare_research_manifests(pilot, research)
    source_pdf = tmp_path / "report.pdf"
    source_pdf.write_bytes(b"placeholder")
    monkeypatch.setattr(research_prep, "_build_source_pdf_index", lambda _root: {"a" * 64: source_pdf})
    monkeypatch.setattr(
        research_prep,
        "_ocr_candidate_readiness",
        lambda _config: {
            "ocr_primary_doubao": {"ready": False, "reason": "missing_api_key"},
            "ocr_verifier_qwen": {"ready": False, "reason": "missing_api_key"},
            "ocr_baseline_paddle": {"ready": True, "reason": ""},
        },
    )
    monkeypatch.setattr(research_prep, "_run_paddleocr_candidate", lambda *args, **kwargs: bad_result)

    run_ocr_research(pilot, research)
    payload = json.loads((research / "ocr_runs/repeat_1/pilot-001/ocr_baseline_paddle.json").read_text())
    assert payload["status"] == "blocked"
    assert payload["blocked_reasons"] == [reason]


def test_paddleocr_text_consumes_result_iterable(tmp_path: Path):
    class OfficialResult:
        def save_to_markdown(self, *, save_path: Path):
            output = Path(save_path) / "page.md"
            output.write_text("IMPRESSION: iterable result", encoding="utf-8")
            return output

    result = (item for item in [OfficialResult()])
    assert research_prep._paddleocr_text(result, markdown_dir=tmp_path) == "IMPRESSION: iterable result"


def test_run_ocr_research_rejects_unsafe_case_path(tmp_path: Path):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot/escape", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}],
    )
    with pytest.raises(ValueError, match="pilot_case_id_unsafe_path"):
        run_ocr_research(pilot, tmp_path / "research")


def test_run_ocr_research_marks_verifier_audit_without_scoring_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pilot = _pilot(
        tmp_path,
        [{"pilot_case_id": "pilot-001", "modality": "cxr", "annotation_path": "cases/pilot-001.json"}],
    )
    research = tmp_path / "research"
    prepare_research_manifests(pilot, research)
    source_pdf = tmp_path / "report.pdf"
    source_pdf.write_bytes(b"placeholder")
    monkeypatch.setattr(research_prep, "_build_source_pdf_index", lambda _root: {"a" * 64: source_pdf})
    monkeypatch.setattr(
        research_prep,
        "_ocr_candidate_readiness",
        lambda _config: {
            "ocr_primary_doubao": {"ready": True, "reason": ""},
            "ocr_verifier_qwen": {"ready": True, "reason": ""},
            "ocr_baseline_paddle": {"ready": False, "reason": "paddleocr_provider_unavailable"},
        },
    )

    class FakeResult:
        text = "FINDINGS: normal\nIMPRESSION: normal"
        warnings = []
        metadata = {"quality_status": "passed", "quality_audit": {"status": "agree"}}

    monkeypatch.setattr(research_prep, "extract_report_text", lambda *args, **kwargs: FakeResult())

    result = run_ocr_research(pilot, research)

    verifier = json.loads(
        (research / "ocr_runs" / "repeat_1" / "pilot-001" / "ocr_verifier_qwen.json").read_text()
    )
    assert verifier["status"] == "succeeded"
    assert verifier["execution_mode"] == "audit_only"
    assert verifier["model_key"] == "ocr_verifier_qwen"
    assert result["benchmark_results"]["1"]["selection"]["status"] == "blocked"
    assert any(
        "ocr_baseline_paddle" in item
        for item in result["benchmark_results"]["1"]["selection"].get("blocked_items", [])
    )


def test_source_pdf_index_accepts_project_data_sample_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    payload = {"case_id": "CASE-001", "report_path": "reports/CASE-001.txt"}
    digest = research_prep._canonical_payload_sha256(payload)
    pdf = tmp_path / "sample_data_2026-06-05" / "CR" / "CASE-001" / "report.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-test")
    workflow_case = tmp_path / "outputs" / "run" / "workflow2_cases" / "CASE-001.json"
    workflow_case.parent.mkdir(parents=True)
    workflow_case.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(research_prep, "PROJECT_ROOT", tmp_path)

    index = research_prep._build_source_pdf_index(tmp_path / "sample_data_2026-06-05")

    assert index[digest] == pdf
