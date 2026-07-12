from __future__ import annotations

import json
from pathlib import Path

from medharness2.annotation import AnnotationCase, build_pilot_annotation_package
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


def test_annotation_schema_is_exported_with_package(tmp_path: Path):
    run_dir = _write_run(tmp_path / "run")
    output_dir = tmp_path / "pilot10"

    build_pilot_annotation_package(run_dir, output_dir, limit=10)

    schema = json.loads((output_dir / "annotation.schema.json").read_text(encoding="utf-8"))
    assert schema["title"] == "AnnotationCase"
    assert (output_dir / "README.md").exists()
