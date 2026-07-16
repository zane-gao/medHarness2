from __future__ import annotations

import json
from pathlib import Path

from medharness2.contracts import (
    CaseEvaluationArtifact,
    FindingGraph,
    HazardResult,
    migrate_case_evaluation_v1,
    migrate_run_case_artifacts,
)
from medharness2.validation.sample_run import validate_sample_run


def _legacy_case() -> dict:
    return {
        "input": {"modality": "cxr", "body_part": "chest", "report_path": "report.txt"},
        "human_evaluation": {"finding_graph": {"backend": "cxr_rule", "findings": []}},
        "generated_reports": [
            {
                "model": "maira_2",
                "source": "medharness_cli",
                "report": "FINDINGS: No focal opacity.",
                "modality": "cxr",
                "warnings": [],
                "metadata": {"adapter_status": "passed"},
            },
            {
                "model": "artifact_model",
                "source": "artifact_reuse",
                "report": "FINDINGS: Clear lungs.",
                "modality": "cxr",
                "warnings": [],
                "metadata": {},
            },
        ],
        "generated_evaluations": [{"model": "maira_2"}],
        "rankings": [{"model": "maira_2", "rank": 1}],
        "pairwise_comparisons": [{"model": "maira_2"}],
        "future_extension": {"must_be_preserved": True},
    }


def test_migrate_v1_case_preserves_fields_and_adds_versioned_reports():
    legacy = _legacy_case()

    migrated = migrate_case_evaluation_v1(legacy, case_id="case-1")
    artifact = CaseEvaluationArtifact.model_validate(migrated)

    assert artifact.schema_version == "2.0"
    assert artifact.case_id == "case-1"
    assert artifact.generated_reports[0].evidence_tier == "debug_fallback"
    assert artifact.generated_reports[1].evidence_tier == "artifact"
    assert artifact.legacy_extensions["future_extension"] == {"must_be_preserved": True}
    assert "preserved_unknown_top_level_fields" in artifact.migration_warnings


def test_migrate_v1_case_does_not_mutate_input():
    legacy = _legacy_case()
    before = repr(legacy)

    migrate_case_evaluation_v1(legacy, case_id="case-1")

    assert repr(legacy) == before


def test_migrate_v1_case_recursively_upgrades_finding_graphs_and_hazards():
    legacy = _legacy_case()
    human_graph = _legacy_finding_graph("hf1", "opacity", "left upper lobe", "12 mm")
    candidate_graph = _legacy_finding_graph("cf1", "nodule", "right lower lobe", "0.8 cm")
    legacy["human_evaluation"] = {"finding_graph": human_graph}
    legacy["generated_evaluations"] = [{"finding_graph": candidate_graph}]
    legacy["pairwise_comparisons"] = [
        {
            "comparison": {
                "graph_a": candidate_graph,
                "graph_b": human_graph,
                "hazards": {
                    "errors": [
                        {
                            "error_type": "incorrect_location",
                            "hazard_level": 3,
                            "explanation": "Legacy location disagreement.",
                            "finding": {"id": "cf1"},
                        }
                    ]
                },
            },
            "selected_evaluation": {"finding_graph": candidate_graph},
        }
    ]

    migrated = migrate_case_evaluation_v1(legacy, case_id="case-1")

    human = FindingGraph.model_validate(migrated["human_evaluation"]["finding_graph"])
    generated = FindingGraph.model_validate(migrated["generated_evaluations"][0]["finding_graph"])
    comparison = migrated["pairwise_comparisons"][0]["comparison"]
    graph_a = FindingGraph.model_validate(comparison["graph_a"])
    graph_b = FindingGraph.model_validate(comparison["graph_b"])
    selected = FindingGraph.model_validate(
        migrated["pairwise_comparisons"][0]["selected_evaluation"]["finding_graph"]
    )
    hazards = HazardResult.model_validate(comparison["hazards"])

    assert human.findings[0].finding_id == "hf1"
    assert human.findings[0].observation_text == "opacity"
    assert human.findings[0].laterality == "left"
    assert human.findings[0].measurements[0].normalized_mm == 12.0
    assert human.findings[0].extractor.implementation_type == "legacy_migration"
    assert generated.findings[0].measurements[0].normalized_mm == 8.0
    assert graph_a.findings[0].finding_id == "cf1"
    assert graph_b.findings[0].finding_id == "hf1"
    assert selected.findings[0].finding_id == "cf1"
    assert hazards.errors[0].recommended_action
    assert hazards.errors[0].evidence_ids == ["cf1"]
    assert hazards.provenance.implementation_type == "legacy_migration"
    assert "legacy_nested_contracts_migrated" in migrated["migration_warnings"]


def test_migrate_v1_case_preserves_scalar_evidence_id_and_measurement_object():
    legacy = _legacy_case()
    graph = _legacy_finding_graph("f1", "nodule", "right upper lobe", "not parsed")
    graph["findings"][0].pop("measurement")
    graph["findings"][0]["measurements"] = {"value": 1.2, "unit": "cm"}
    legacy["human_evaluation"] = {"finding_graph": graph}
    legacy["pairwise_comparisons"] = [
        {
            "comparison": {
                "hazards": {
                    "errors": [
                        {
                            "error_type": "false_finding",
                            "hazard_level": 2,
                            "explanation": "Legacy error.",
                            "evidence_ids": "f1",
                        }
                    ]
                }
            }
        }
    ]

    migrated = migrate_case_evaluation_v1(legacy, case_id="case-1")
    finding_graph = FindingGraph.model_validate(
        migrated["human_evaluation"]["finding_graph"]
    )
    hazards = HazardResult.model_validate(
        migrated["pairwise_comparisons"][0]["comparison"]["hazards"]
    )

    assert finding_graph.findings[0].measurements[0].normalized_mm == 12.0
    assert hazards.errors[0].evidence_ids == ["f1"]


def test_migrate_v1_missing_observation_is_explicitly_unparsed_not_reported_finding():
    legacy = _legacy_case()
    legacy["human_evaluation"] = {
        "finding_graph": {
            "modality": "cxr",
            "backend": "legacy",
            "findings": [{"id": "f1", "text": ""}],
        }
    }

    migrated = migrate_case_evaluation_v1(legacy, case_id="case-1")
    finding = migrated["human_evaluation"]["finding_graph"]["findings"][0]

    assert finding["observation_text"] == "unparsed_legacy_finding"
    assert finding["observation_code"] is None
    assert finding["attributes"]["migration_metadata"]["observation_unparsed"] is True
    assert "legacy_finding_missing_observation" in finding["attributes"]["migration_warnings"]


def test_migrate_v1_hazard_preserves_unknown_top_level_fields():
    legacy = _legacy_case()
    legacy["pairwise_comparisons"] = [
        {
            "comparison": {
                "hazards": {
                    "errors": [],
                    "warnings": ["legacy-warning"],
                    "legacy_top": {"must_be_preserved": True},
                }
            }
        }
    ]

    migrated = migrate_case_evaluation_v1(legacy, case_id="case-1")
    hazards = HazardResult.model_validate(
        migrated["pairwise_comparisons"][0]["comparison"]["hazards"]
    )

    assert hazards.metadata["legacy_fields"] == {
        "warnings": ["legacy-warning"],
        "legacy_top": {"must_be_preserved": True},
    }


def test_migrate_run_case_artifacts_writes_report_and_valid_v2_cases(tmp_path: Path):
    source = tmp_path / "source" / "workflow2_cases"
    source.mkdir(parents=True)
    (source / "case-1.json").write_text(json.dumps(_legacy_case()), encoding="utf-8")
    output = tmp_path / "migrated"

    report = migrate_run_case_artifacts(source.parent, output)

    assert report["case_count"] == 1
    assert report["error_count"] == 0
    migrated = CaseEvaluationArtifact.model_validate_json((output / "cases" / "case-1.json").read_text())
    assert migrated.schema_version == "2.0"
    assert json.loads((output / "migration_report.json").read_text())["case_count"] == 1


def test_migrate_run_case_artifacts_rejects_missing_or_empty_source(tmp_path: Path):
    missing = migrate_run_case_artifacts(tmp_path / "missing", tmp_path / "out_missing")
    assert missing["error_count"] == 1
    assert missing["errors"][0]["error"] == "source_run_dir_not_found"
    empty = tmp_path / "empty"
    (empty / "workflow2_cases").mkdir(parents=True)
    report = migrate_run_case_artifacts(empty, tmp_path / "out_empty")
    assert report["error_count"] == 1
    assert report["errors"][0]["error"] == "no_cases_discovered"


def test_migrate_run_case_artifacts_writes_a_directly_validatable_run(tmp_path: Path):
    source = tmp_path / "source"
    case_dir = source / "workflow2_cases"
    case_dir.mkdir(parents=True)
    (case_dir / "case-1.json").write_text(json.dumps(_legacy_case()), encoding="utf-8")
    (source / "summary.json").write_text(
        json.dumps({"case_count": 1, "warning_counts": {}}),
        encoding="utf-8",
    )
    (source / "manifest.jsonl").write_text(
        json.dumps({"case_id": "case-1", "reader": "r", "warnings": []}) + "\n",
        encoding="utf-8",
    )
    (source / "workflow2.json").write_text(
        json.dumps({"case_count": 1, "failed_case_count": 0}),
        encoding="utf-8",
    )
    (source / "workflow3.json").write_text(
        json.dumps({"case_count": 1, "reader_count": 1}),
        encoding="utf-8",
    )
    output = tmp_path / "migrated"

    report = migrate_run_case_artifacts(source, output)
    validation = validate_sample_run(output, expected_cases=1)

    assert (output / "workflow2_cases" / "case-1.json").exists()
    assert (output / "cases" / "case-1.json").exists()
    assert report["copied_support_files"] == [
        "manifest.jsonl",
        "summary.json",
        "workflow2.json",
        "workflow3.json",
    ]
    assert validation["passed"] is True
    assert validation["artifact_contracts"]["valid_count"] == 1


def _legacy_finding_graph(
    finding_id: str,
    observation: str,
    location: str,
    measurement: str,
) -> dict:
    return {
        "modality": "cxr",
        "backend": "cxr_rule",
        "findings": [
            {
                "id": finding_id,
                "observation": observation,
                "location": location,
                "severity": "mild",
                "measurement": measurement,
                "certainty": "present",
                "text": f"{observation} in the {location}, measuring {measurement}.",
                "legacy_flag": "preserve-me",
            }
        ],
        "missing": [],
        "coverage": 1.0,
        "nodes": [],
        "template_coverage": {"coverage_rate": 1.0},
        "warnings": [],
    }
