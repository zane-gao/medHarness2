from __future__ import annotations

from medharness2.tools.tool2_extract import extract_findings


def test_ct_rule_extracts_multiorgan_findings_negation_and_measurement():
    result = extract_findings(
        "检查所见：肝右叶见2.1cm低密度灶，考虑囊肿。肠管扩张伴气液平，提示肠梗阻。未见腹水。",
        modality="ct",
        backend="auto",
    )
    by_observation = {finding["observation_code"]: finding for finding in result["findings"]}

    assert result["backend"] == "ct_rule"
    assert result["schema_version"] == "2.0"
    assert by_observation["low_density_lesion"]["anatomy_code"] == "liver"
    assert by_observation["low_density_lesion"]["measurements"][0]["normalized_mm"] == 21.0
    assert by_observation["cyst"]["anatomy_code"] == "liver"
    assert by_observation["bowel_obstruction"]["anatomy_code"] == "bowel"
    assert by_observation["ascites"]["certainty"] == "absent"


def test_ct_rule_returns_no_fake_reported_finding_when_nothing_supported():
    result = extract_findings("检查所见：图像质量欠佳，建议复查。", modality="ct", backend="auto")

    assert result["findings"] == []
    assert "no_supported_finding_detected" in result["warnings"]
