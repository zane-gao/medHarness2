from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from medharness2.contracts import HazardResult
from medharness2.validation.sample_run import validate_sample_run


def test_validate_sample_run_passes_complete_mock_run(tmp_path: Path):
    _write_run(tmp_path, warning_counts={"mock_ocr_used": 2}, failed_case_count=0)
    result = validate_sample_run(tmp_path, expected_cases=2)
    assert result["passed"] is True
    assert result["case_count"] == 2
    assert result["mock_ocr_count"] == 2


def test_validate_sample_run_fails_when_real_ocr_required_but_mock_used(tmp_path: Path):
    _write_run(tmp_path, warning_counts={"mock_ocr_used": 1}, failed_case_count=0)
    result = validate_sample_run(tmp_path, expected_cases=2, require_real_ocr=True)
    assert result["passed"] is False
    assert "mock_ocr_used" in result["errors"]


def test_validate_sample_run_fails_when_real_ocr_provenance_is_unknown(tmp_path: Path):
    _write_run(tmp_path, warning_counts={}, failed_case_count=0)
    result = validate_sample_run(tmp_path, expected_cases=2, require_real_ocr=True)
    assert result["passed"] is False
    assert "ocr_provenance_unknown" in result["errors"]


def test_validate_sample_run_accepts_real_ocr_metadata(tmp_path: Path):
    _write_run(tmp_path, warning_counts={}, failed_case_count=0, ocr_provider="openai")
    result = validate_sample_run(tmp_path, expected_cases=2, require_real_ocr=True)
    assert result["passed"] is True
    assert result["real_ocr_count"] == 2


def test_validate_sample_run_rejects_unknown_vlm_provider(tmp_path: Path):
    _write_run(tmp_path, warning_counts={}, failed_case_count=0, ocr_provider="future_magic_provider")
    result = validate_sample_run(tmp_path, expected_cases=2, require_real_ocr=True)
    assert result["passed"] is False
    assert "ocr_provenance_unknown" in result["errors"]
    assert result["unknown_ocr_count"] == 2


def test_validate_sample_run_reports_missing_workflow_outputs(tmp_path: Path):
    _write_json(tmp_path / "summary.json", {"case_count": 1, "warning_counts": {}})
    _write_manifest(tmp_path / "manifest.jsonl", 1)
    result = validate_sample_run(tmp_path, expected_cases=1)
    assert result["passed"] is False
    assert "missing_workflow2_json" in result["errors"]
    assert "missing_workflow3_json" in result["errors"]


def test_validate_sample_run_accepts_subset_workflow_without_summary(tmp_path: Path):
    _write_manifest(tmp_path / "manifest.jsonl", 2, with_report_text=True)
    for i in range(2):
        _write_json(tmp_path / "ocr" / f"case{i}.ocr.json", {"case_id": f"case{i}", "method": "vlm_ocr", "provider": "local_hf_vlm"})
    _write_json(tmp_path / "workflow2.json", {"case_count": 2, "failed_case_count": 0, "per_reader": {"r": {}}})
    _write_json(tmp_path / "workflow3.json", {"case_count": 2, "reader_count": 1, "reader_percentiles": {"r": {}}})

    result = validate_sample_run(tmp_path, expected_cases=2, require_real_ocr=True)

    assert result["passed"] is True
    assert "missing_summary_json" not in result["errors"]
    assert "missing_summary_json" in result["warnings"]
    assert result["summary"]["case_count"] == 2


def test_validate_sample_run_rejects_invalid_nested_case_artifact_contract(tmp_path: Path):
    _write_run(tmp_path, warning_counts={}, failed_case_count=1)
    _write_json(
        tmp_path / "workflow2_cases" / "case0.json",
        {
            "schema_version": "2.0",
            "artifact_type": "case_evaluation",
            "case_id": "case0",
            "input": {},
            "human_evaluation": {
                "finding_graph": {
                    "schema_version": "2.0",
                    "artifact_type": "finding_graph",
                    "modality": "cxr",
                    "backend": "cxr_rule",
                    "findings": [{"id": "legacy-f1"}],
                }
            },
            "generated_reports": [],
            "generated_evaluations": [],
            "rankings": [],
            "pairwise_comparisons": [],
        },
    )

    result = validate_sample_run(tmp_path, expected_cases=2)

    assert result["passed"] is False
    assert any(error.startswith("invalid_case_artifact_contract:case0.json:finding_graph") for error in result["errors"])
    assert result["artifact_contracts"]["checked"] is True
    assert result["artifact_contracts"]["invalid_count"] == 1


@pytest.mark.parametrize(
    "audit_field",
    ["alignment_audit", "hazard_review", "structure_audit"],
)
def test_validate_sample_run_rejects_invalid_optional_audit_contract(
    tmp_path: Path,
    audit_field: str,
):
    _write_single_case_run(tmp_path, comparison={audit_field: {}})

    result = validate_sample_run(tmp_path, expected_cases=1)

    assert result["passed"] is False
    assert any(
        error.startswith(
            f"invalid_case_artifact_contract:case0.json:{audit_field}:ValidationError"
        )
        for error in result["errors"]
    )
    assert result["artifact_contracts"]["invalid_count"] == 1


def test_validate_sample_run_counts_valid_optional_audit_contracts(tmp_path: Path):
    _write_single_case_run(tmp_path, comparison=_valid_audited_comparison())

    result = validate_sample_run(tmp_path, expected_cases=1)

    assert result["passed"] is True
    assert result["artifact_contracts"]["alignment_audit_count"] == 1
    assert result["artifact_contracts"]["hazard_review_count"] == 1
    assert result["artifact_contracts"]["structure_audit_count"] == 1


def test_validate_sample_run_checks_cases_compatibility_directory(tmp_path: Path):
    _write_single_case_run(tmp_path, comparison={})
    (tmp_path / "workflow2_cases").rename(tmp_path / "cases")

    result = validate_sample_run(tmp_path, expected_cases=1)

    assert result["passed"] is True
    assert result["artifact_contracts"]["checked"] is True
    assert result["artifact_contracts"]["case_file_count"] == 1
    assert result["artifact_contracts"]["valid_count"] == 1


def test_validate_sample_run_reports_malformed_nested_artifact_without_crashing(
    tmp_path: Path,
):
    _write_single_case_run(tmp_path, comparison={})
    case_path = tmp_path / "workflow2_cases" / "case0.json"
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    payload["generated_evaluations"] = [{"evaluation": "bad"}]
    _write_json(case_path, payload)

    result = validate_sample_run(tmp_path, expected_cases=1)

    assert result["passed"] is False
    assert any(
        error.startswith(
            "invalid_case_artifact_contract:case0.json:"
            "generated_evaluations[0].evaluation:not_object"
        )
        for error in result["errors"]
    )
    assert result["artifact_contracts"]["invalid_count"] == 1


@pytest.mark.parametrize(
    ("audit_field", "hash_field"),
    [
        ("alignment_audit", "alignment_sha256"),
        ("hazard_review", "primary_result_sha256"),
        ("structure_audit", "structure_diff_sha256"),
    ],
)
def test_validate_sample_run_rejects_audit_hash_mismatch(
    tmp_path: Path,
    audit_field: str,
    hash_field: str,
):
    comparison = _valid_audited_comparison()
    comparison[audit_field][hash_field] = "f" * 64
    _write_single_case_run(tmp_path, comparison=comparison)

    result = validate_sample_run(tmp_path, expected_cases=1)

    assert result["passed"] is False
    assert any(
        error.startswith(
            f"invalid_case_artifact_contract:case0.json:{audit_field}:hash_mismatch"
        )
        for error in result["errors"]
    )


def _write_run(path: Path, *, warning_counts: dict[str, int], failed_case_count: int, ocr_provider: str | None = None) -> None:
    _write_json(path / "summary.json", {"case_count": 2, "warning_counts": warning_counts})
    _write_manifest(path / "manifest.jsonl", 2, with_report_text=True)
    if ocr_provider:
        for i in range(2):
            _write_json(path / "ocr" / f"case{i}.ocr.json", {"case_id": f"case{i}", "method": "vlm_ocr", "provider": ocr_provider})
    _write_json(path / "workflow2.json", {"case_count": 2 - failed_case_count, "failed_case_count": failed_case_count, "per_reader": {"r": {}}})
    _write_json(path / "workflow3.json", {"case_count": 2 - failed_case_count, "reader_count": 1, "reader_percentiles": {"r": {}}})


def _write_single_case_run(path: Path, *, comparison: dict) -> None:
    _write_json(path / "summary.json", {"case_count": 1, "warning_counts": {}})
    _write_manifest(path / "manifest.jsonl", 1)
    _write_json(
        path / "workflow2.json",
        {"case_count": 1, "failed_case_count": 0, "per_reader": {"r": {}}},
    )
    _write_json(
        path / "workflow3.json",
        {"case_count": 1, "reader_count": 1, "reader_percentiles": {"r": {}}},
    )
    _write_json(
        path / "workflow2_cases" / "case0.json",
        {
            "schema_version": "2.0",
            "artifact_type": "case_evaluation",
            "case_id": "case0",
            "input": {},
            "human_evaluation": {},
            "generated_reports": [],
            "generated_evaluations": [],
            "rankings": [],
            "pairwise_comparisons": [{"comparison": comparison}],
        },
    )


def _valid_audited_comparison() -> dict:
    provenance = {
        "implementation_type": "llm_json",
        "provider": "dmx",
        "model": "test-model",
        "version": "2.0",
        "role": "test_role",
        "prompt_version": "test-v1",
        "fallback_used": False,
        "metadata": {},
    }
    alignment = {"matched": [], "error_candidates": [], "metrics": {"f1": 1.0}}
    hazards = HazardResult.model_validate(
        {
            "schema_version": "2.0",
            "artifact_type": "hazard_result",
            "errors": [],
            "provenance": provenance,
            "metadata": {},
        }
    ).model_dump(mode="json")
    structure_diff = {
        "artifact_type": "structure_diff",
        "metric_version": "tool6-structure-v2",
        "score_delta": 0.0,
    }
    return {
        "alignment": alignment,
        "alignment_audit": {
            "schema_version": "2.0",
            "artifact_type": "alignment_audit",
            "alignment_sha256": _json_sha256(alignment),
            "auditor_provenance": provenance,
            "verdict": "pass",
            "confidence": 0.9,
            "summary": "No alignment issue found.",
            "issues": [],
            "primary_preserved": True,
            "requires_adjudication": False,
            "metadata": {},
        },
        "hazards": hazards,
        "hazard_review": {
            "schema_version": "2.0",
            "artifact_type": "hazard_review",
            "primary_result_sha256": _json_sha256(hazards),
            "primary_provenance": provenance,
            "reviewer_result": hazards,
            "disagreements": [],
            "agreement_summary": {},
            "primary_preserved": True,
            "requires_adjudication": False,
        },
        "structure_diff": structure_diff,
        "structure_audit": {
            "schema_version": "2.0",
            "artifact_type": "structure_audit",
            "structure_diff_sha256": _json_sha256(structure_diff),
            "assessor_provenance": provenance,
            "verdict": "no_material_issue",
            "clinical_impact": 1,
            "confidence": 0.9,
            "summary": "No material structure issue found.",
            "issues": [],
            "primary_preserved": True,
            "requires_review": False,
            "metadata": {},
        },
    }


def _json_sha256(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_manifest(path: Path, count: int, *, with_report_text: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "case_id": f"case{i}",
            "reader": "r",
            "modality": "cxr",
            "body_part": "chest",
            "report_text": str(path.parent / "ocr" / f"case{i}.txt") if with_report_text else "",
            "warnings": [],
        }
        for i in range(count)
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
