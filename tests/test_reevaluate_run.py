from __future__ import annotations

import json
from pathlib import Path

import pytest

from medharness2.cli import main
from medharness2.config import AppConfig, ExtractorConfig, GeneratorConfig, LLMConfig
from medharness2.workflows.reevaluate_run import _generated_reports, reevaluate_run


def test_generated_reports_migrates_legacy_medharness_cli_as_debug_fallback():
    reports = _generated_reports(
        {
            "generated_reports": [
                {
                    "model": "legacy_model",
                    "source": "medharness_cli",
                    "report": "FINDINGS: Nodule.",
                    "modality": "cxr",
                }
            ]
        }
    )

    assert reports[0].evidence_tier == "debug_fallback"
    assert "legacy_reference_assisted_generation_assumed" in reports[0].warnings


def test_generated_reports_rejects_v2_report_without_evidence_tier():
    with pytest.raises(ValueError, match="evidence_tier"):
        _generated_reports(
            {
                "schema_version": "2.0",
                "generated_reports": [
                    {
                        "schema_version": "2.0",
                        "artifact_type": "generated_report",
                        "model": "model",
                        "source": "medharness_cli",
                        "report": "FINDINGS: Nodule.",
                        "modality": "cxr",
                    }
                ],
            }
        )


def test_reevaluate_run_reuses_generated_reports_without_generation(tmp_path: Path):
    source = tmp_path / "source_run"
    source_cases = source / "workflow2_cases"
    source_cases.mkdir(parents=True)
    report = tmp_path / "human.txt"
    image = tmp_path / "image.png"
    report.write_text("检查所见：右上肺见8mm结节影。未见气胸。诊断印象：右上肺结节。", encoding="utf-8")
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    _write_json(
        source / "workflow2.json",
        {
            "manifest_path": "manifest.jsonl",
            "case_count": 1,
            "failed_case_count": 0,
            "cases": [
                {
                    "case_id": "case1",
                    "reader": "reader_a",
                    "modality": "cxr",
                    "body_part": "chest",
                    "workflow1_output": str(source_cases / "case1.json"),
                    "human_metrics": {"finding_coverage": 0.1111},
                }
            ],
            "failed_cases": [],
            "per_reader": {"reader_a": {"case_count": 1, "overall_score": 0.1}},
            "statistics": {},
        },
    )
    _write_json(
        source_cases / "case1.json",
        {
            "input": {
                "report_path": str(report),
                "image_path": str(image),
                "modality": "cxr",
                "body_part": "chest",
                "prepared_assets": {"primary_image": str(image)},
            },
            "human_evaluation": {
                "finding_graph": {
                    "backend": "cxr_rule",
                    "findings": [{"id": "f1", "observation": "reported_finding"}],
                }
            },
            "generated_reports": [
                {
                    "model": "existing_model",
                    "source": "artifact_reuse",
                    "report": "FINDINGS: Right upper lung nodule measuring 8 mm. No pneumothorax.",
                    "modality": "cxr",
                    "warnings": [],
                    "metadata": {"quality_gate": {"passed": True}},
                }
            ],
            "generated_evaluations": [],
            "rankings": [],
            "pairwise_comparisons": [],
        },
    )
    output = tmp_path / "reeval_run"
    cfg = AppConfig(
        llm=LLMConfig(provider="mock"),
        extractor=ExtractorConfig(backend="cxr_rule"),
        generator=GeneratorConfig(default_models=[], local_models=[], include_legacy_ready_models=False),
    )

    result = reevaluate_run(source, output, config=cfg)

    case_payload = json.loads((output / "workflow2_cases" / "case1.json").read_text(encoding="utf-8"))
    assert result["summary"]["case_count"] == 1
    assert result["summary"]["reused_generated_report_count"] == 1
    assert result["summary"]["new_generation_count"] == 0
    assert case_payload["generated_reports"][0]["model"] == "existing_model"
    human_findings = {
        item["observation_code"]: item
        for item in case_payload["human_evaluation"]["finding_graph"]["findings"]
    }
    assert human_findings["nodule"]["anatomy_code"] == "right upper lobe"
    assert human_findings["nodule"]["measurements"][0]["normalized_mm"] == 8.0
    assert human_findings["pneumothorax"]["certainty"] == "absent"
    assert case_payload["rankings"][0]["model"] == "existing_model"
    assert case_payload["pairwise_comparisons"]
    assert (output / "workflow2.json").exists()
    assert (output / "workflow3.json").exists()
    assert (output / "run_summary.json").exists()


def test_reevaluate_run_preserves_source_real_ocr_validation_policy(tmp_path: Path):
    source = tmp_path / "source_run"
    source_cases = source / "workflow2_cases"
    source_cases.mkdir(parents=True)
    ocr_dir = source / "ocr"
    ocr_text = ocr_dir / "case1.txt"
    _write_text(ocr_text, "检查所见：右上肺见8mm结节影。未见气胸。")
    _write_json(ocr_text.with_suffix(".ocr.json"), {"case_id": "case1", "method": "vlm_ocr", "provider": "local_hf_vlm"})
    report = tmp_path / "human.txt"
    image = tmp_path / "image.png"
    report.write_text("检查所见：右上肺见8mm结节影。未见气胸。诊断印象：右上肺结节。", encoding="utf-8")
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    _write_manifest(source / "manifest.jsonl", [{"case_id": "case1", "report_text": str(ocr_text)}])
    _write_json(source / "summary.json", {"case_count": 1, "warning_counts": {}, "cases_with_report_text": 1, "cases_with_primary_image": 1})
    _write_json(
        source / "run_summary.json",
        {
            "validation": {
                "passed": True,
                "expected_cases": 1,
                "require_real_ocr": True,
                "real_ocr_count": 1,
                "mock_ocr_count": 0,
                "unknown_ocr_count": 0,
            }
        },
    )
    _write_json(
        source / "workflow2.json",
        {
            "manifest_path": "manifest.jsonl",
            "case_count": 1,
            "failed_case_count": 0,
            "cases": [
                {
                    "case_id": "case1",
                    "reader": "reader_a",
                    "modality": "cxr",
                    "body_part": "chest",
                    "workflow1_output": str(source_cases / "case1.json"),
                    "human_metrics": {"finding_coverage": 0.1111},
                }
            ],
            "failed_cases": [],
            "per_reader": {"reader_a": {"case_count": 1, "overall_score": 0.1}},
            "statistics": {},
        },
    )
    _write_json(
        source_cases / "case1.json",
        {
            "input": {
                "report_path": str(report),
                "image_path": str(image),
                "modality": "cxr",
                "body_part": "chest",
                "prepared_assets": {"primary_image": str(image)},
            },
            "human_evaluation": {"finding_graph": {"backend": "cxr_rule", "findings": []}},
            "generated_reports": [
                {
                    "model": "existing_model",
                    "source": "artifact_reuse",
                    "report": "FINDINGS: Right upper lung nodule measuring 8 mm. No pneumothorax.",
                    "modality": "cxr",
                    "warnings": [],
                    "metadata": {"quality_gate": {"passed": True}},
                }
            ],
            "generated_evaluations": [],
            "rankings": [],
            "pairwise_comparisons": [],
        },
    )
    cfg = AppConfig(
        llm=LLMConfig(provider="mock"),
        extractor=ExtractorConfig(backend="cxr_rule"),
        generator=GeneratorConfig(default_models=[], local_models=[], include_legacy_ready_models=False),
    )

    reevaluate_run(source, tmp_path / "reeval_run", config=cfg)

    validation = json.loads((tmp_path / "reeval_run" / "run_summary.json").read_text(encoding="utf-8"))["validation"]
    assert validation["passed"] is True
    assert validation["require_real_ocr"] is True
    assert validation["expected_cases"] == 1
    assert validation["real_ocr_count"] == 1
    assert validation["mock_ocr_count"] == 0
    assert validation["unknown_ocr_count"] == 0


def test_reevaluate_run_marks_reconstructed_report_as_fallback(tmp_path: Path):
    source = tmp_path / "source_run"
    source_cases = source / "workflow2_cases"
    source_cases.mkdir(parents=True)
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    _write_json(
        source / "workflow2.json",
        {
            "manifest_path": "manifest.jsonl",
            "case_count": 1,
            "failed_case_count": 0,
            "cases": [
                {
                    "case_id": "case1",
                    "reader": "reader_a",
                    "modality": "cxr",
                    "body_part": "chest",
                    "workflow1_output": str(source_cases / "case1.json"),
                }
            ],
            "failed_cases": [],
            "per_reader": {},
            "statistics": {},
        },
    )
    _write_json(
        source_cases / "case1.json",
        {
            "input": {
                "report_path": str(tmp_path / "missing-report.txt"),
                "image_path": str(image),
                "modality": "cxr",
                "body_part": "chest",
                "prepared_assets": {"primary_image": str(image)},
            },
            "human_evaluation": {
                "finding_graph": {
                    "backend": "cxr_rule",
                    "findings": [
                        {"id": "f1", "source_text": "右上肺见8mm结节影。"},
                        {"id": "f2", "source_text": "未见气胸。"},
                    ],
                }
            },
            "generated_reports": [],
            "generated_evaluations": [],
            "rankings": [],
            "pairwise_comparisons": [],
        },
    )
    cfg = AppConfig(
        llm=LLMConfig(provider="mock"),
        extractor=ExtractorConfig(backend="cxr_rule"),
        generator=GeneratorConfig(default_models=[], local_models=[], include_legacy_ready_models=False),
    )

    result = reevaluate_run(source, tmp_path / "reeval_run", config=cfg)

    case = result["workflow2"]["cases"][0]
    assert case["reevaluation"]["report_text_source"] == "reconstructed_from_finding_graph"
    assert case["human_metrics"]["metadata"]["report_text_source"] == "reconstructed_from_finding_graph"
    assert case["human_metrics"]["metadata"]["fallback_used"] is True


def test_cli_reevaluate_run_writes_run_registry(tmp_path: Path):
    source = _write_cli_source_run(tmp_path)
    output = tmp_path / "reeval_run"

    code = main(["workflow", "reevaluate-run", "--source-run-dir", str(source), "--output-dir", str(output)])

    assert code == 0
    payload = json.loads((output / "run_summary.json").read_text(encoding="utf-8"))
    registry = json.loads((output / "run_registry.json").read_text(encoding="utf-8"))
    entry = registry["entries"][-1]
    assert payload["summary"]["case_count"] == 1
    assert entry["stage"] == "workflow.reevaluate-run"
    assert entry["inputs"]["source_run_dir"] == str(source)
    assert entry["outputs"]["workflow2"] == str(output / "workflow2.json")
    assert entry["metrics"]["case_count"] == 1
    assert entry["metrics"]["reused_generated_report_count"] == 1
    assert entry["metrics"]["new_generation_count"] == 0


def test_cli_reevaluate_run_rejects_empty_source_run(tmp_path: Path):
    source = tmp_path / "empty_source"
    source.mkdir()
    _write_json(source / "workflow2.json", {"cases": [], "failed_cases": [], "case_count": 0, "failed_case_count": 0})
    output = tmp_path / "reeval_empty"

    code = main(["workflow", "reevaluate-run", "--source-run-dir", str(source), "--output-dir", str(output)])

    assert code == 1
    payload = json.loads((output / "run_summary.json").read_text(encoding="utf-8"))
    assert payload["summary"]["case_count"] == 0
    assert payload["summary"]["errors"] == ["no_cases_discovered"]
    registry = json.loads((output / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


def _write_cli_source_run(root: Path) -> Path:
    source = root / "cli_source_run"
    source_cases = source / "workflow2_cases"
    source_cases.mkdir(parents=True)
    report = root / "cli_human.txt"
    image = root / "cli_image.png"
    report.write_text("检查所见：右上肺见8mm结节影。未见气胸。诊断印象：右上肺结节。", encoding="utf-8")
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    _write_json(
        source / "workflow2.json",
        {
            "manifest_path": "manifest.jsonl",
            "case_count": 1,
            "failed_case_count": 0,
            "cases": [
                {
                    "case_id": "case1",
                    "reader": "reader_a",
                    "modality": "cxr",
                    "body_part": "chest",
                    "workflow1_output": str(source_cases / "case1.json"),
                    "human_metrics": {"finding_coverage": 0.1111},
                }
            ],
            "failed_cases": [],
            "per_reader": {"reader_a": {"case_count": 1, "overall_score": 0.1}},
            "statistics": {},
        },
    )
    _write_json(
        source_cases / "case1.json",
        {
            "input": {
                "report_path": str(report),
                "image_path": str(image),
                "modality": "cxr",
                "body_part": "chest",
                "prepared_assets": {"primary_image": str(image)},
            },
            "human_evaluation": {
                "finding_graph": {
                    "backend": "cxr_rule",
                    "findings": [{"id": "f1", "observation": "reported_finding"}],
                }
            },
            "generated_reports": [
                {
                    "model": "existing_model",
                    "source": "artifact_reuse",
                    "report": "FINDINGS: Right upper lung nodule measuring 8 mm. No pneumothorax.",
                    "modality": "cxr",
                    "warnings": [],
                    "metadata": {"quality_gate": {"passed": True}},
                }
            ],
            "generated_evaluations": [],
            "rankings": [],
            "pairwise_comparisons": [],
        },
    )
    return source


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_manifest(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = []
    for row in rows:
        normalized.append(
            {
                "case_id": row["case_id"],
                "reader": row.get("reader", "reader_a"),
                "modality": row.get("modality", "cxr"),
                "body_part": row.get("body_part", "chest"),
                "report_text": row.get("report_text", ""),
                "warnings": row.get("warnings", []),
            }
        )
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in normalized) + "\n", encoding="utf-8")
