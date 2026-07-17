from __future__ import annotations

import json
from pathlib import Path

import pytest

from medharness2.annotation.models import AnnotationCase, CandidateReportForAnnotation, ReaderAnnotation
from medharness2.research_prep import prepare_research_manifests


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
    (root / "manifest.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
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
    assert ocr["gold_source"] == "beichuan_reference_report"
    assert ocr["gold_status"] == "available_for_current_benchmark"
    assert len(ocr["runs"]) == 18
    assert ocr["runs"][0]["blocked_reasons"] == ["real_provider_run_not_available"]
    assert ocr["runs"][0]["gold_source"] == "beichuan_reference_report"
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
