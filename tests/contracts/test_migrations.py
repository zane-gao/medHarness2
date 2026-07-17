from __future__ import annotations

import json
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("field", ["modality", "backend"])
@pytest.mark.parametrize("bad", [{"x": 1}, 7, True, ["cxr"]])
def test_finding_graph_migration_rejects_non_string_identity_fields(field, bad):
    from medharness2.contracts.migrations import _migrate_finding_graph

    with pytest.raises((TypeError, ValueError), match=field):
        _migrate_finding_graph({"modality": "cxr", "backend": "legacy", "findings": [], field: bad})


@pytest.mark.parametrize("field", ["metadata", "template_coverage"])
@pytest.mark.parametrize("bad", ["x", ["x"], 7, True])
def test_finding_graph_migration_rejects_non_object_fields(field, bad):
    from medharness2.contracts.migrations import _migrate_finding_graph

    with pytest.raises((TypeError, ValueError), match=field):
        _migrate_finding_graph({"modality": "cxr", "backend": "legacy", "findings": [], field: bad})


@pytest.mark.parametrize("field", ["id", "finding_id", "observation", "observation_text", "source_text", "text"])
@pytest.mark.parametrize("bad", [{"x": 1}, 7, True, ["x"]])
def test_finding_graph_migration_rejects_non_string_finding_text_fields(field, bad):
    from medharness2.contracts.migrations import _migrate_finding_graph

    with pytest.raises((TypeError, ValueError), match=field):
        _migrate_finding_graph({
            "modality": "cxr",
            "backend": "legacy",
            "findings": [{"id": "f1", "observation": "opacity", field: bad}],
        })


@pytest.mark.parametrize("field", ["missing", "warnings"])
@pytest.mark.parametrize("bad", [["ok", 7], {"x": 1}, 7, True])
def test_finding_graph_migration_rejects_malformed_string_lists(field, bad):
    from medharness2.contracts.migrations import _migrate_finding_graph

    with pytest.raises((TypeError, ValueError), match=field):
        _migrate_finding_graph({"modality": "cxr", "backend": "legacy", "findings": [], field: bad})


@pytest.mark.parametrize("bad", [["f1", 7], {"x": 1}, 7, True])
def test_hazard_migration_rejects_malformed_evidence_ids(bad):
    from medharness2.contracts.migrations import _migrate_hazard_result

    with pytest.raises((TypeError, ValueError), match="evidence_ids"):
        _migrate_hazard_result({"errors": [{"error_type": "false_finding", "evidence_ids": bad}]})


@pytest.mark.parametrize("field", ["error_type", "explanation", "recommended_action"])
@pytest.mark.parametrize("bad", [{"x": 1}, 7, True, ["x"]])
def test_hazard_migration_rejects_non_string_text_fields(field, bad):
    from medharness2.contracts.migrations import _migrate_hazard_result

    with pytest.raises((TypeError, ValueError), match=field):
        _migrate_hazard_result({"errors": [{"error_type": "false_finding", field: bad}]})


@pytest.mark.parametrize("bad", [0, 1, "false", "true", {"x": 1}, [True]])
def test_hazard_migration_rejects_non_boolean_abstain(bad):
    from medharness2.contracts.migrations import _migrate_hazard_result

    with pytest.raises((TypeError, ValueError), match="abstain"):
        _migrate_hazard_result({"errors": [{"error_type": "false_finding", "abstain": bad}]})


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


def test_migration_bounded_hazard_level_rejects_implicit_integer_coercion():
    from medharness2.contracts.migrations import _bounded_int

    for bad in (True, 3.8, "3"):
        assert _bounded_int(bad, default=3, lower=1, upper=5) == 3


def test_reevaluate_expected_cases_rejects_implicit_integer_coercion():
    from medharness2.workflows.reevaluate_run import _optional_int

    assert _optional_int(True) is None
    assert _optional_int(1.5) is None
    assert _optional_int("2") is None
    assert _optional_int(2) == 2


def test_migration_warning_strings_are_not_split_into_characters():
    from medharness2.contracts.migrations import migrate_generated_report_v1

    migrated = migrate_generated_report_v1(
        {
            "model": "legacy",
            "source": "artifact_reuse",
            "report": "text",
            "modality": "cxr",
            "warnings": "legacy_warning",
        }
    )
    assert migrated["warnings"] == ["legacy_warning"]


def test_migration_warning_lists_reject_non_string_items():
    from medharness2.contracts.migrations import migrate_generated_report_v1

    with pytest.raises(TypeError, match="generated_report.warnings"):
        migrate_generated_report_v1(
            {
                "model": "legacy",
                "source": "artifact_reuse",
                "report": "text",
                "modality": "cxr",
                "warnings": {"unexpected": True},
            }
        )


@pytest.mark.parametrize("field", ["model", "source", "report", "modality"])
@pytest.mark.parametrize("bad", [{"x": 1}, 7, True, ["x"]])
def test_generated_report_migration_rejects_non_string_identity_and_text(field, bad):
    from medharness2.contracts.migrations import migrate_generated_report_v1

    with pytest.raises((TypeError, ValueError), match=field):
        migrate_generated_report_v1({"model": "m", "source": "artifact_reuse", "report": "text", "modality": "cxr", field: bad})


@pytest.mark.parametrize("bad", ["metadata", ["x"], 7, True])
def test_generated_report_migration_rejects_non_object_metadata(bad):
    from medharness2.contracts.migrations import migrate_generated_report_v1

    with pytest.raises((TypeError, ValueError), match="metadata"):
        migrate_generated_report_v1({"model": "m", "source": "artifact_reuse", "report": "text", "modality": "cxr", "metadata": bad})

@pytest.mark.parametrize("field", ["generated_reports", "generated_evaluations", "pairwise_comparisons", "rankings"])
@pytest.mark.parametrize("bad", ["not-a-list", {"x": 1}, ["bad-item"]])
def test_case_migration_rejects_malformed_top_level_object_lists(field, bad):
    from medharness2.contracts.migrations import migrate_case_evaluation_v1

    with pytest.raises(TypeError, match=field):
        migrate_case_evaluation_v1({field: bad}, case_id="case-1")
