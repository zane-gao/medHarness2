from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from medharness2.cli import main
from medharness2.contracts import (
    ArtifactReference,
    Finding,
    FindingGraph,
    Measurement,
    ModelProvenance,
    TextSpan,
)
from medharness2.tools.tool2_extract import extract_findings


def test_finding_contract_round_trip_and_normalized_measurement():
    finding = Finding(
        finding_id="f1",
        observation_text="pulmonary nodule",
        location_text="right upper lobe",
        laterality="right",
        certainty="present",
        measurements=[Measurement(value=8, unit="mm")],
        source_span=TextSpan(start=10, end=28),
        extractor=ModelProvenance(implementation_type="medical_model", provider="local", model="extractor-v1"),
    )

    payload = finding.model_dump(mode="json")

    assert payload["measurements"][0]["normalized_mm"] == 8.0
    assert Finding.model_validate(payload) == finding


def test_contracts_reject_invalid_enums_and_text_spans():
    with pytest.raises(ValidationError):
        Finding(
            finding_id="f1",
            observation_text="nodule",
            laterality="upper",
            certainty="present",
            extractor=ModelProvenance(implementation_type="code"),
        )
    with pytest.raises(ValidationError):
        TextSpan(start=20, end=10)


def test_finding_graph_requires_unique_finding_ids():
    finding = Finding(
        finding_id="f1",
        observation_text="nodule",
        laterality="unknown",
        certainty="present",
        extractor=ModelProvenance(implementation_type="code"),
    )
    with pytest.raises(ValidationError):
        FindingGraph(modality="cxr", backend="rule", findings=[finding, finding])


def test_tool2_runtime_output_is_the_exported_finding_graph_contract():
    payload = extract_findings(
        "检查所见：右上肺见8mm结节影。未见气胸。",
        modality="cxr",
        backend="cxr_rule",
    )

    graph = FindingGraph.model_validate(payload)
    by_code = {finding.observation_code: finding for finding in graph.findings}

    assert graph.schema_version == "2.0"
    assert by_code["nodule"].finding_id == "f1"
    assert by_code["nodule"].anatomy_code == "right upper lobe"
    assert by_code["nodule"].measurements[0].normalized_mm == 8.0
    assert by_code["pneumothorax"].certainty == "absent"
    assert "id" not in payload["findings"][0]


def test_artifact_reference_rejects_non_sha256_hash():
    with pytest.raises(ValidationError):
        ArtifactReference(path="workflow2.json", sha256="short", schema_version="2.0")


def test_cli_exports_versioned_json_schemas(tmp_path: Path):
    code = main(["schemas", "export", "--output-dir", str(tmp_path)])

    assert code == 0
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert index["schema_version"] == "2.0"
    assert "finding_graph" in index["schemas"]
    schema = json.loads((tmp_path / index["schemas"]["finding_graph"]).read_text(encoding="utf-8"))
    assert schema["title"] == "FindingGraph"

@pytest.mark.parametrize("bad", [True, 1.5, "2", -1])
def test_aggregate_contract_rejects_implicit_integer_counts(bad):
    from medharness2.contracts.aggregate import DenominatorAggregate, Workflow2Aggregate, Workflow3Aggregate

    with pytest.raises(ValidationError):
        Workflow2Aggregate.model_validate({"case_count": bad})
    with pytest.raises(ValidationError):
        DenominatorAggregate.model_validate({"source_case_count": bad})
    with pytest.raises(ValidationError):
        Workflow3Aggregate.model_validate({"reader_count": bad})

@pytest.mark.parametrize("bad", [True, 1.5, "2"])
def test_evaluation_contract_rejects_implicit_integer_fields(bad):
    from medharness2.contracts import HazardJudgement, TextSpan

    with pytest.raises(ValidationError):
        TextSpan.model_validate({"start": bad, "end": 2})
    with pytest.raises(ValidationError):
        HazardJudgement.model_validate(
            {
                "error_type": "other",
                "hazard_level": bad,
                "explanation": "x",
                "recommended_action": "x",
            }
        )
