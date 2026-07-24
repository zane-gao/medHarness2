from __future__ import annotations

from medharness2.tools.tool2_extract import extract_findings
from medharness2.extractors.rules import _deduplicate_findings


def test_cxr_plugin_preserves_existing_bilingual_behavior():
    result = extract_findings(
        "检查所见：右上肺见8mm结节影。左侧胸腔少量积液。未见气胸。",
        modality="cxr",
        backend="auto",
    )
    by_observation = {finding["observation_code"]: finding for finding in result["findings"]}

    assert result["backend"] == "cxr_rule"
    assert by_observation["nodule"]["anatomy_code"] == "right upper lobe"
    assert by_observation["nodule"]["measurements"][0]["normalized_mm"] == 8.0
    assert by_observation["effusion"]["severity"] == "mild"
    assert by_observation["pneumothorax"]["certainty"] == "absent"


def test_cxr_plugin_extracts_repeated_observations_as_distinct_findings():
    result = extract_findings(
        "A 4 mm nodule is present in the right upper lobe and a 7 mm nodule is present in the left lower lobe.",
        modality="cxr",
        backend="auto",
    )

    nodules = [finding for finding in result["findings"] if finding["observation_code"] == "nodule"]

    assert len(nodules) == 2
    assert [finding["anatomy_code"] for finding in nodules] == ["right upper lobe", "left lower lobe"]
    assert [finding["measurements"][0]["normalized_mm"] for finding in nodules] == [4.0, 7.0]


def test_cxr_plugin_stops_negation_at_contrast_boundary():
    result = extract_findings(
        "No effusion, but pneumothorax is present.",
        modality="cxr",
        backend="auto",
    )
    by_observation = {finding["observation_code"]: finding for finding in result["findings"]}

    assert by_observation["effusion"]["certainty"] == "absent"
    assert by_observation["pneumothorax"]["certainty"] == "present"


def test_cxr_plugin_deduplicates_repeated_mentions_of_one_finding():
    result = extract_findings(
        "Multiple nodules are present in the right upper lobe, with the largest nodule measuring 8 mm and this nodule appearing solid.",
        modality="cxr",
        backend="auto",
    )

    nodules = [finding for finding in result["findings"] if finding["observation_code"] == "nodule"]

    assert len(nodules) == 1
    assert nodules[0]["anatomy_code"] == "right upper lobe"
    assert nodules[0]["measurements"][0]["normalized_mm"] == 8.0


def test_cxr_plugin_merges_impression_summary_and_keeps_measured_finding():
    result = extract_findings(
        "检查所见：右上肺见8mm结节影。未见气胸。诊断印象：右上肺结节。",
        modality="cxr",
        backend="auto",
    )

    nodules = [finding for finding in result["findings"] if finding["observation_code"] == "nodule"]

    assert len(nodules) == 1
    assert nodules[0]["anatomy_code"] == "right upper lobe"
    assert nodules[0]["measurements"][0]["normalized_mm"] == 8.0
    assert "8mm" in nodules[0]["source_text"]


def test_cxr_plugin_keeps_distinct_measured_findings_when_impression_summarizes_them():
    result = extract_findings(
        "FINDINGS: A 4 mm nodule and a 7 mm nodule are present in the right upper lobe. "
        "IMPRESSION: Right upper lobe nodules.",
        modality="cxr",
        backend="auto",
    )

    nodules = [finding for finding in result["findings"] if finding["observation_code"] == "nodule"]

    assert len(nodules) == 2
    assert sorted(finding["measurements"][0]["normalized_mm"] for finding in nodules) == [4.0, 7.0]


def test_rule_dedup_does_not_treat_missing_measurement_as_zero():
    base = {
        "observation_code": "nodule",
        "anatomy_code": "right upper lobe",
        "laterality": "right",
        "certainty": "present",
        "source_text": "right upper lobe nodule",
    }
    findings = [
        {
            **base,
            "finding_id": "f1",
            "measurements": [{"value": "unknown", "unit": "mm"}],
        },
        {
            **base,
            "finding_id": "f2",
            "measurements": [{"value": 0.0, "unit": "mm", "normalized_mm": 0.0}],
        },
    ]

    deduplicated = _deduplicate_findings(findings)

    assert len(deduplicated) == 2


def test_rule_dedup_preserves_distinct_raw_measurements_without_normalized_value():
    base = {
        "observation_code": "nodule",
        "anatomy_code": "right upper lobe",
        "laterality": "right",
        "certainty": "present",
        "source_text": "right upper lobe nodules",
    }
    findings = [
        {**base, "finding_id": "f1", "measurements": [{"value": 4.0, "unit": "mm"}]},
        {**base, "finding_id": "f2", "measurements": [{"value": 7.0, "unit": "mm"}]},
    ]

    deduplicated = _deduplicate_findings(findings)

    assert len(deduplicated) == 2


def test_cxr_rule_output_uses_the_same_controlled_ontology_as_hybrid_t2():
    result = extract_findings(
        "FINDINGS: The lungs are clear. No pleural effusion or pneumothorax.",
        modality="cxr",
        backend="auto",
    )
    by_observation = {finding["observation_code"]: finding for finding in result["findings"]}

    assert by_observation["opacity"]["certainty"] == "absent"
    assert by_observation["effusion"]["certainty"] == "absent"
    assert by_observation["pneumothorax"]["certainty"] == "absent"
    assert result["metadata"]["ontology"]["version"] == "cxr-controlled-v1"


def test_cxr_rule_maps_chinese_normal_template_to_specific_abnormality_concepts():
    result = extract_findings(
        "骨性胸廓双侧对称，气管及纵隔居中。双肺纹理清晰，未见异常密度影。"
        "双侧肺门未见增大、增浓。心影不大，主动脉未见异常。"
        "双侧膈肌光整，肋膈角锐利。心肺未见明显异常。",
        modality="cxr",
        backend="auto",
    )
    by_observation = {
        finding["observation_code"]: finding for finding in result["findings"]
    }

    assert {
        "aortic_abnormality",
        "cardiomegaly",
        "cardiopulmonary_abnormality",
        "costophrenic_angle_blunting",
        "diaphragm_abnormality",
        "hilar_enlargement",
        "opacity",
        "thoracic_cage_asymmetry",
    }.issubset(by_observation)
    assert all(finding["certainty"] == "absent" for finding in by_observation.values())
    assert sum(
        finding["observation_code"] == "cardiopulmonary_abnormality"
        for finding in result["findings"]
    ) == 1


def test_cxr_rule_recognizes_plural_acute_osseous_abnormalities():
    result = extract_findings(
        "No acute osseous abnormalities identified.",
        modality="cxr",
        backend="auto",
    )

    assert len(result["findings"]) == 1
    assert result["findings"][0]["observation_code"] == "osseous_abnormality"
    assert result["findings"][0]["certainty"] == "absent"


def test_cxr_rule_maps_punctuated_normal_cardiac_silhouette_template():
    result = extract_findings(
        "心影形态、大小未见异常，主动脉未见异常。",
        modality="cxr",
        backend="auto",
    )
    by_observation = {
        finding["observation_code"]: finding for finding in result["findings"]
    }

    assert by_observation["cardiomegaly"]["certainty"] == "absent"
    assert by_observation["aortic_abnormality"]["certainty"] == "absent"
