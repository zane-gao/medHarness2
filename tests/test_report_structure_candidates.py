from __future__ import annotations

from medharness2.tools.report_structure import compare_candidate_structures, structure_report


def test_structure_report_extracts_grounded_spans_and_merges_duplicate_entities():
    report = (
        "FINDINGS: No pneumothorax. Mild right lower lobe opacity. "
        "Mild right lower lobe opacity persists.\n"
        "IMPRESSION: Mild right lower lobe opacity."
    )

    structured = structure_report(report, modality="cxr", body_part="chest")

    assert structured["structure_status"] == "succeeded"
    assert structured["structure_version"] == "candidate-structure-v2"
    pneumothorax = next(item for item in structured["spans"] if item["entity"] == "pneumothorax")
    assert pneumothorax["observation_status"] == "absent"
    assert report[pneumothorax["start"] : pneumothorax["end"]] == pneumothorax["evidence_snippet"]
    opacity = next(item for item in structured["entities"] if item["entity"] == "opacity")
    assert opacity["observation_status"] == "present"
    assert opacity["subject"] == "right lower lobe"
    assert len(opacity["evidence_span_ids"]) == 2


def test_structure_report_extracts_multiple_atomic_findings_with_attributes_and_measurement():
    report = "FINDINGS: No pleural effusion or pneumothorax. An 8 mm right upper lobe nodule is present."

    structured = structure_report(report, modality="cxr", body_part="chest")

    by_entity = {item["entity"]: item for item in structured["spans"]}
    assert {"effusion", "pneumothorax", "nodule"}.issubset(by_entity)
    assert by_entity["effusion"]["observation_status"] == "absent"
    assert by_entity["pneumothorax"]["observation_status"] == "absent"
    assert by_entity["nodule"]["subject"] == "right upper lobe"
    assert by_entity["nodule"]["laterality"] == "right"
    assert by_entity["nodule"]["measurements"][0]["normalized_mm"] == 8.0
    for span in structured["spans"]:
        assert report[span["start"] : span["end"]] == span["evidence_snippet"]


def test_structure_report_keeps_chinese_evidence_and_generic_template_fallback():
    report = "影像所见：双肺未见明显实变。右下肺可见小片状磨玻璃影。诊断意见：右下肺轻度炎性改变。"

    structured = structure_report(report, modality="ct", body_part="unknown")

    assert structured["template"]["status"] == "generic_fallback"
    assert any(item["observation_status"] == "absent" for item in structured["spans"])
    assert any("右下肺" in item["evidence_snippet"] for item in structured["spans"])


def test_structure_report_uses_real_versioned_template_registry():
    matched = structure_report("FINDINGS: No pneumothorax.", modality="cxr", body_part="chest")
    fallback = structure_report("FINDINGS: No pneumothorax.", modality="ct", body_part="made_up_body")

    assert matched["template"]["status"] == "matched"
    assert matched["template"]["template_id"] == "cxr_chest"
    assert matched["template"]["matched_on"] == "exact_modality_body_part"
    assert len(matched["template"]["template_sha256"]) == 64
    assert matched["template"]["anatomy_sections"]
    assert fallback["template"]["status"] == "generic_fallback"
    assert fallback["template"]["reason"] == "no_registered_template"
    assert len(fallback["template"]["registry_sha256"]) == 64


def test_compare_candidate_structures_reports_agreement_and_status_conflicts():
    candidates = {
        "candidate-a": structure_report("FINDINGS: No pneumothorax. Mild left pleural effusion.", modality="cxr", body_part="chest"),
        "candidate-b": structure_report("FINDINGS: Small pneumothorax. Mild left pleural effusion.", modality="cxr", body_part="chest"),
    }

    comparison = compare_candidate_structures(candidates)

    assert comparison["agreement_count"] == 1
    assert comparison["conflict_count"] == 1
    assert comparison["conflicts"][0]["entity"] == "pneumothorax"


def test_compare_candidate_structures_normalizes_synonyms_and_reports_attribute_conflicts():
    candidates = {
        "candidate-a": structure_report(
            "FINDINGS: A right upper lobe nodule measures 8 mm. Small pleural effusion.",
            modality="cxr",
            body_part="chest",
        ),
        "candidate-b": structure_report(
            "FINDINGS: A left upper lobe nodule measures 12 mm. Small pleural fluid.",
            modality="cxr",
            body_part="chest",
        ),
    }

    comparison = compare_candidate_structures(candidates)

    assert any(item["entity"] == "effusion" for item in comparison["agreements"])
    nodule_conflicts = [item for item in comparison["conflicts"] if item["entity"] == "nodule"]
    assert {item["comparison_type"] for item in nodule_conflicts} >= {"laterality", "measurement"}


def test_compare_candidate_structures_reports_missing_and_internal_conflicts():
    candidates = {
        "candidate-a": structure_report(
            "FINDINGS: No pneumothorax. A small pneumothorax is present.",
            modality="cxr",
            body_part="chest",
        ),
        "candidate-b": structure_report("FINDINGS: No pneumothorax.", modality="cxr", body_part="chest"),
        "candidate-c": structure_report("FINDINGS: No pleural effusion.", modality="cxr", body_part="chest"),
    }

    comparison = compare_candidate_structures(candidates)

    assert comparison["internal_conflict_count"] == 1
    assert comparison["internal_conflicts"][0]["entity"] == "pneumothorax"
    assert any(item["entity"] == "pneumothorax" for item in comparison["omissions"])
