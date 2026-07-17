from __future__ import annotations

import json
from pathlib import Path
import pytest

from medharness2.annotation import AnnotationCase, build_pilot_annotation_package, validate_pilot_annotation_package
from pydantic import ValidationError
from medharness2.annotation.models import HazardAnnotation
from medharness2.cli import main
from medharness2.privacy import ExternalPayloadPolicy


def _write_run(root: Path) -> Path:
    case_dir = root / "workflow2_cases"
    reports = root / "reports"
    case_dir.mkdir(parents=True)
    reports.mkdir()
    cases = []
    strata = [
        ("cxr", "chest"),
        ("ct", "chest"),
        ("ct", "abdomen"),
        ("ct", "head"),
        ("mri", "brain"),
    ]
    for index in range(12):
        modality, body_part = strata[index % len(strata)]
        case_id = f"REAL_CASE_{index:03d}"
        report = reports / f"{case_id}.txt"
        report.write_text(
            "医院影像报告\n姓名：张三\n住院号：26041983\n检查时间：2026-05-27\n"
            "检查所见：右上肺见8 mm结节。\n诊断印象：右上肺结节。\n"
            "报告医生：李医生\nPATIENT_CANARY_9271\n",
            encoding="utf-8",
        )
        case_path = case_dir / f"{case_id}.json"
        case_path.write_text(
            json.dumps(
                {
                    "input": {
                        "report_path": str(report),
                        "modality": modality,
                        "body_part": body_part,
                    },
                    "human_evaluation": {"finding_graph": {"findings": []}},
                    "generated_reports": [
                        {
                            "model": "secret-model-name",
                            "source": "medharness_cli",
                            "report": "FINDINGS: An 8 mm right upper lobe nodule. IMPRESSION: Pulmonary nodule.",
                            "modality": modality,
                            "warnings": [],
                            "metadata": {},
                        }
                    ],
                    "generated_evaluations": [],
                    "rankings": [],
                    "pairwise_comparisons": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        cases.append({"case_id": case_id, "workflow1_output": str(case_path)})
    (root / "workflow2.json").write_text(json.dumps({"cases": cases}), encoding="utf-8")
    return root


def test_build_pilot_annotation_package_is_blinded_valid_and_deidentified(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    output_dir = tmp_path / "pilot10"

    result = build_pilot_annotation_package(run_dir, output_dir, limit=10)

    assert result["case_count"] == 10
    manifest = [json.loads(line) for line in (output_dir / "manifest.jsonl").read_text().splitlines()]
    assert len(manifest) == 10
    assert len({(row["modality"], row["body_part"]) for row in manifest}) == 5
    policy = ExternalPayloadPolicy()
    for row in manifest:
        path = output_dir / row["annotation_path"]
        raw = path.read_text(encoding="utf-8")
        case = AnnotationCase.model_validate_json(raw)
        assert case.source_case_sha256 and len(case.source_case_sha256) == 64
        assert "REAL_CASE" not in raw
        assert "secret-model-name" not in raw
        assert "PATIENT_CANARY" not in raw
        assert "姓名" not in raw
        assert policy.scan(raw).allowed is True
        assert case.candidate_reports[0].blinded_model_id.startswith("model-")
        assert set(case.annotations) == {"reader_a", "reader_b", "adjudication"}


def test_cli_build_pilot_rejects_missing_or_empty_source_run(tmp_path: Path):
    output_dir = tmp_path / "pilot10"
    code = main(["annotation", "build-pilot", "--run-dir", str(tmp_path / "missing"), "--output-dir", str(output_dir)])
    assert code == 1
    empty = tmp_path / "empty"
    empty.mkdir()
    code = main(["annotation", "build-pilot", "--run-dir", str(empty), "--output-dir", str(output_dir)])
    assert code == 1


def test_pilot_privacy_scan_ignores_cryptographic_provenance_hash(tmp_path: Path, monkeypatch):
    run_dir = _write_run(tmp_path / "run")
    monkeypatch.setattr(
        "medharness2.annotation.pilot._source_case_sha256",
        lambda payload: "123456789012345678" + "a" * 46,
    )

    result = build_pilot_annotation_package(run_dir, tmp_path / "pilot10", limit=1)

    assert result["case_count"] == 1


def test_annotation_schema_is_exported_with_package(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    output_dir = tmp_path / "pilot10"

    build_pilot_annotation_package(run_dir, output_dir, limit=10)

    schema = json.loads((output_dir / "annotation.schema.json").read_text(encoding="utf-8"))
    assert schema["title"] == "AnnotationCase"


@pytest.mark.parametrize("bad", [0, 1, "false", "true", [], {}])
def test_hazard_annotation_rejects_implicit_boolean(bad):
    with pytest.raises(ValidationError):
        HazardAnnotation.model_validate(
            {
                "error_id": "e1",
                "candidate_id": "candidate-1",
                "error_type": "other",
                "hazard_level": 3,
                "clinically_significant": bad,
                "rationale": "test",
            }
        )


def test_validate_pilot_annotation_package_reports_not_started_without_fabricating_completion(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    output_dir = tmp_path / "pilot10"
    build_pilot_annotation_package(run_dir, output_dir, limit=3)

    result = validate_pilot_annotation_package(output_dir)

    assert result["status"] == "not_started"
    assert result["case_count"] == 3
    assert result["complete_case_count"] == 0
    assert result["not_started_case_count"] == 3
    assert result["errors"] == []
    assert main(["annotation", "validate", "--package-dir", str(output_dir)]) == 1


def test_validate_pilot_annotation_package_blocks_adjudication_before_both_readers(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    output_dir = tmp_path / "pilot10"
    build_pilot_annotation_package(run_dir, output_dir, limit=1)
    case_path = output_dir / "cases" / "pilot-001.json"
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    payload["annotations"]["adjudication"]["status"] = "complete"
    case_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    manifest = json.loads((output_dir / "manifest.jsonl").read_text(encoding="utf-8"))
    manifest["status"] = "in_progress"
    (output_dir / "manifest.jsonl").write_text(json.dumps(manifest, ensure_ascii=False) + "\n", encoding="utf-8")

    result = validate_pilot_annotation_package(output_dir)

    assert result["status"] == "blocked"
    assert "case:pilot-001:adjudication_before_readers" in result["errors"]


def test_validate_pilot_annotation_package_rejects_paths_outside_cases_and_unlisted_files(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    output_dir = tmp_path / "pilot10"
    build_pilot_annotation_package(run_dir, output_dir, limit=1)
    outside = tmp_path / "outside.json"
    outside.write_text((output_dir / "cases" / "pilot-001.json").read_text(encoding="utf-8"), encoding="utf-8")
    extra = output_dir / "cases" / "extra.json"
    extra.write_text((output_dir / "cases" / "pilot-001.json").read_text(encoding="utf-8"), encoding="utf-8")
    row = json.loads((output_dir / "manifest.jsonl").read_text(encoding="utf-8"))
    row["annotation_path"] = "../outside.json"
    (output_dir / "manifest.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

    result = validate_pilot_annotation_package(output_dir)

    assert result["status"] == "blocked"
    assert "case:pilot-001:annotation_path_outside_cases" in result["errors"]
    assert "case:cases/extra.json:unlisted_file" in result["errors"]


def test_validate_pilot_annotation_package_rejects_duplicate_ids_and_paths(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    output_dir = tmp_path / "pilot10"
    build_pilot_annotation_package(run_dir, output_dir, limit=1)
    row = json.loads((output_dir / "manifest.jsonl").read_text(encoding="utf-8"))
    (output_dir / "manifest.jsonl").write_text(
        "\n".join(json.dumps(row) for _ in range(2)) + "\n", encoding="utf-8"
    )

    result = validate_pilot_annotation_package(output_dir)

    assert result["status"] == "blocked"
    assert any(error.startswith("manifest:pilot-001:duplicate_case_id:") for error in result["errors"])
    assert any(error.startswith("manifest:pilot-001:duplicate_annotation_path:") for error in result["errors"])


def test_build_pilot_annotation_package_cleans_stale_case_files_on_rebuild(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    output_dir = tmp_path / "pilot10"
    build_pilot_annotation_package(run_dir, output_dir, limit=3)
    build_pilot_annotation_package(run_dir, output_dir, limit=1)

    result = validate_pilot_annotation_package(output_dir)

    assert result["status"] == "not_started"
    assert result["case_count"] == 1
    assert result["errors"] == []
    assert sorted(path.name for path in (output_dir / "cases").glob("*.json")) == ["pilot-001.json"]


def test_build_pilot_annotation_package_refuses_rebuild_after_annotation_started(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    output_dir = tmp_path / "pilot10"
    build_pilot_annotation_package(run_dir, output_dir, limit=1)
    case_path = output_dir / "cases" / "pilot-001.json"
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    payload["annotations"]["reader_a"]["status"] = "in_progress"
    case_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    try:
        build_pilot_annotation_package(run_dir, output_dir, limit=1)
    except ValueError as exc:
        assert "annotation started" in str(exc)
    else:
        raise AssertionError("rebuild must not delete started annotation work")

    assert case_path.exists()


def test_build_pilot_annotation_package_rejects_missing_workflow1_reference(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    workflow2_path = run_dir / "workflow2.json"
    workflow2 = json.loads(workflow2_path.read_text(encoding="utf-8"))
    workflow2["cases"][0]["workflow1_output"] = str(run_dir / "workflow2_cases" / "missing.json")
    workflow2_path.write_text(json.dumps(workflow2), encoding="utf-8")

    try:
        build_pilot_annotation_package(run_dir, tmp_path / "pilot10", limit=1)
    except ValueError as exc:
        message = str(exc)
        assert "REAL_CASE_000" in message
        assert "workflow1_output" in message
        assert "missing.json" in message
    else:
        raise AssertionError("missing workflow1 reference must fail explicitly")


def test_build_pilot_annotation_package_rejects_unreadable_workflow1_reference(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    workflow2_path = run_dir / "workflow2.json"
    workflow2 = json.loads(workflow2_path.read_text(encoding="utf-8"))
    invalid_path = run_dir / "workflow2_cases" / "invalid.json"
    invalid_path.write_text("not json", encoding="utf-8")
    workflow2["cases"][0]["workflow1_output"] = str(invalid_path)
    workflow2_path.write_text(json.dumps(workflow2), encoding="utf-8")

    try:
        build_pilot_annotation_package(run_dir, tmp_path / "pilot10", limit=1)
    except ValueError as exc:
        message = str(exc)
        assert "REAL_CASE_000" in message
        assert "workflow1_output" in message
        assert "invalid.json" in message
    else:
        raise AssertionError("unreadable workflow1 reference must fail explicitly")


def test_build_pilot_annotation_package_rejects_missing_clinical_reference_report(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    missing = run_dir / "reports" / "missing.txt"
    for case_path in (run_dir / "workflow2_cases").glob("*.json"):
        payload = json.loads(case_path.read_text(encoding="utf-8"))
        payload["input"]["report_path"] = str(missing)
        case_path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        build_pilot_annotation_package(run_dir, tmp_path / "pilot10", limit=1)
    except ValueError as exc:
        message = str(exc)
        assert "REAL_CASE_" in message
        assert "reference report does not exist" in message
        assert "missing.txt" in message
    else:
        raise AssertionError("missing clinical reference report must fail explicitly")


def test_build_pilot_annotation_package_rejects_empty_clinical_reference_report(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    empty_report = run_dir / "reports" / "empty.txt"
    empty_report.write_text("\n", encoding="utf-8")
    for case_path in (run_dir / "workflow2_cases").glob("*.json"):
        payload = json.loads(case_path.read_text(encoding="utf-8"))
        payload["input"]["report_path"] = str(empty_report)
        case_path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        build_pilot_annotation_package(run_dir, tmp_path / "pilot10", limit=1)
    except ValueError as exc:
        assert "REAL_CASE_" in str(exc)
        assert "reference report is empty" in str(exc)
    else:
        raise AssertionError("empty clinical reference report must fail explicitly")


def test_build_pilot_annotation_package_rejects_case_without_candidates(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    for case_path in (run_dir / "workflow2_cases").glob("*.json"):
        payload = json.loads(case_path.read_text(encoding="utf-8"))
        payload["generated_reports"] = []
        case_path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        build_pilot_annotation_package(run_dir, tmp_path / "pilot10", limit=1)
    except ValueError as exc:
        assert "has no generated_reports" in str(exc)
    else:
        raise AssertionError("case without candidates must fail explicitly")


def test_validate_pilot_annotation_package_blocks_empty_reference_and_candidate_text(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    output_dir = tmp_path / "pilot10"
    build_pilot_annotation_package(run_dir, output_dir, limit=1)
    case_path = output_dir / "cases" / "pilot-001.json"
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    payload["reference_report"] = "  "
    payload["candidate_reports"][0]["report_text"] = ""
    case_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = validate_pilot_annotation_package(output_dir)

    assert result["status"] == "blocked"
    assert "case:pilot-001:empty_reference_report" in result["errors"]
    assert "case:pilot-001:empty_candidate_report:candidate-01" in result["errors"]


def test_validate_pilot_annotation_package_blocks_duplicate_candidate_ids(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    output_dir = tmp_path / "pilot10"
    build_pilot_annotation_package(run_dir, output_dir, limit=1)
    case_path = output_dir / "cases" / "pilot-001.json"
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    payload["candidate_reports"].append(dict(payload["candidate_reports"][0]))
    payload["candidate_reports"][1]["blinded_model_id"] = "model-01"
    case_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    manifest = json.loads((output_dir / "manifest.jsonl").read_text(encoding="utf-8"))
    manifest["candidate_count"] = 2
    (output_dir / "manifest.jsonl").write_text(json.dumps(manifest, ensure_ascii=False) + "\n", encoding="utf-8")

    result = validate_pilot_annotation_package(output_dir)

    assert result["status"] == "blocked"
    assert "case:pilot-001:duplicate_candidate_id" in result["errors"]
    assert "case:pilot-001:duplicate_blinded_model_id" in result["errors"]


def test_pilot_source_hash_binds_case_content_not_only_case_id(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    first_output = tmp_path / "pilot-first"
    build_pilot_annotation_package(run_dir, first_output, limit=1)
    first = json.loads((first_output / "cases" / "pilot-001.json").read_text(encoding="utf-8"))

    for source_case in (run_dir / "workflow2_cases").glob("*.json"):
        payload = json.loads(source_case.read_text(encoding="utf-8"))
        payload["generated_reports"][0]["report"] += " Additional finding."
        source_case.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    second_output = tmp_path / "pilot-second"
    build_pilot_annotation_package(run_dir, second_output, limit=1)
    second = json.loads((second_output / "cases" / "pilot-001.json").read_text(encoding="utf-8"))

    assert first["source_case_sha256"] != second["source_case_sha256"]
