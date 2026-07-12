from __future__ import annotations

from medharness2.tools.tool2_extract import extract_findings


def test_mri_rule_extracts_brain_findings_and_dwi_negation():
    result = extract_findings(
        "检查所见：双侧脑室旁白质见多发点片状T2-FLAIR高信号。脑沟稍增宽，轻度脑萎缩。DWI未见急性梗死。",
        modality="mri",
        backend="auto",
    )
    by_observation = {finding["observation_code"]: finding for finding in result["findings"]}

    assert result["backend"] == "mri_rule"
    assert by_observation["white_matter_hyperintensity"]["anatomy_code"] == "periventricular_white_matter"
    assert by_observation["cerebral_atrophy"]["severity"] == "mild"
    assert by_observation["acute_infarct"]["certainty"] == "absent"
    assert by_observation["acute_infarct"]["attributes"]["sequence"] == "DWI"


def test_mri_rule_prefers_longest_overlapping_observation_alias():
    result = extract_findings(
        "Acute infarct is present in the right frontal lobe.",
        modality="mri",
        backend="auto",
    )

    observations = [finding["observation_code"] for finding in result["findings"]]

    assert observations == ["acute_infarct"]
