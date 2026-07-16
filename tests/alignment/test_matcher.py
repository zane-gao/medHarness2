from __future__ import annotations

from medharness2.tools.tool5_align import align_graphs


def test_presence_reversal_is_a_contradiction_not_a_match():
    candidate = {"findings": [_finding("pneumothorax", "right pleural", certainty="present")]}
    reference = {"findings": [_finding("pneumothorax", "right pleural", certainty="absent")]}

    result = align_graphs(candidate, reference)

    assert result["matched"] == []
    assert len(result["mismatched"]) == 1
    assert [item["error_type"] for item in result["error_candidates"]] == ["contradiction"]
    assert result["metrics"]["f1"] == 0.0


def test_duplicate_observations_use_global_best_location_matching():
    candidate = {
        "findings": [
            _finding("nodule", "right upper lobe", laterality="right"),
            _finding("nodule", "left lower lobe", laterality="left"),
        ]
    }
    reference = {
        "findings": [
            _finding("nodule", "left lower lobe", laterality="left"),
            _finding("nodule", "right upper lobe", laterality="right"),
        ]
    }

    result = align_graphs(candidate, reference)

    assert len(result["matched"]) == 2
    assert result["mismatched"] == []
    assert result["error_candidates"] == []
    assert result["metrics"]["f1"] == 1.0


def test_unparsed_legacy_finding_is_not_aligned_as_a_real_observation():
    candidate = {"findings": [_finding("unparsed_legacy_finding", "right lung")]}
    reference = {"findings": [_finding("nodule", "right lung")]}

    result = align_graphs(candidate, reference)

    assert result["matched"] == []
    assert result["candidate_only"][0]["observation"] == "unparsed_legacy_finding"
    assert result["reference_only"][0]["observation"] == "nodule"
    assert [item["error_type"] for item in result["error_candidates"]] == [
        "false_finding",
        "omission_finding",
    ]
    assert result["metrics"]["f1"] == 0.0


def test_perfect_alignment_has_symmetric_agreement_one():
    graph = {"findings": [_finding("nodule", "right upper lobe", measurement="10 mm")]}

    result = align_graphs(graph, graph)

    assert result["metrics"]["symmetric_agreement"] == 1.0


def test_missing_measurement_is_reported_as_attribute_mismatch():
    candidate = {"findings": [_finding("nodule", "right upper lobe")]}
    reference = {"findings": [_finding("nodule", "right upper lobe", measurement="10 mm")]}

    result = align_graphs(candidate, reference)

    assert len(result["mismatched"]) == 1
    assert result["mismatched"][0]["differences"] == ["measurement_missing"]
    assert [item["error_type"] for item in result["error_candidates"]] == ["mismatched_finding"]


def test_generic_unmapped_findings_never_match_only_because_their_code_is_equal():
    candidate = {
        "findings": [
            _finding("other_finding", "upper chest"),
        ]
    }
    reference = {
        "findings": [
            _finding("other_finding", "upper chest"),
        ]
    }

    result = align_graphs(candidate, reference)

    assert result["matched"] == []
    assert len(result["candidate_only"]) == 1
    assert len(result["reference_only"]) == 1


def test_abnormality_oriented_normal_findings_match_deterministically():
    candidate = {
        "findings": [
            _finding("opacity", "lung", certainty="absent"),
            _finding("cardiomegaly", "heart", certainty="absent"),
        ]
    }
    reference = {
        "findings": [
            _finding("opacity", "lung", certainty="absent"),
            _finding("cardiomegaly", "heart", certainty="absent"),
        ]
    }

    result = align_graphs(candidate, reference)

    assert len(result["matched"]) == 2
    assert result["metrics"]["f1"] == 1.0


def _finding(
    observation: str,
    location: str,
    *,
    laterality: str = "unknown",
    certainty: str = "present",
    severity: str = "unspecified",
    measurement: str | None = None,
) -> dict[str, str | None]:
    return {
        "observation": observation,
        "location": location,
        "laterality": laterality,
        "certainty": certainty,
        "severity": severity,
        "measurement": measurement,
    }
