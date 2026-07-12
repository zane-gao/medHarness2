from __future__ import annotations

import pytest

from medharness2.ontology.cxr import (
    CXR_ONTOLOGY_VERSION,
    canonicalize_cxr_finding,
    cxr_prompt_catalog,
)


@pytest.mark.parametrize(
    ("code", "text", "evidence", "certainty", "expected_code", "expected_certainty", "expected_anatomy"),
    [
        (
            "clear lungs",
            "Lungs are clear",
            "The lungs are clear.",
            "present",
            "opacity",
            "absent",
            "lung",
        ),
        (
            "normal cardiomediastinal silhouette",
            "Cardiomediastinal silhouette is within normal limits",
            "The cardiomediastinal silhouette is within normal limits.",
            "present",
            "cardiomegaly",
            "absent",
            "heart",
        ),
        (
            "pleural effusion",
            "No pleural effusion",
            "No pleural effusion is seen.",
            "absent",
            "effusion",
            "absent",
            "pleura",
        ),
        (
            "sharp costophrenic angles",
            "Costophrenic angles are sharp",
            "Bilateral costophrenic angles are sharp.",
            "present",
            "costophrenic_angle_blunting",
            "absent",
            "costophrenic_angle",
        ),
        (
            "midline trachea",
            "Trachea is midline",
            "The trachea is midline.",
            "present",
            "tracheal_deviation",
            "absent",
            "trachea",
        ),
        (
            "pulmonary nodule",
            "A pulmonary nodule",
            "A pulmonary nodule is present.",
            "present",
            "nodule",
            "present",
            "lung",
        ),
        (
            "normal",
            "No acute cardiopulmonary abnormality",
            "No acute cardiopulmonary abnormality is identified.",
            "present",
            "cardiopulmonary_abnormality",
            "absent",
            "cardiopulmonary",
        ),
    ],
)
def test_cxr_canonicalizer_uses_abnormality_oriented_concepts(
    code: str,
    text: str,
    evidence: str,
    certainty: str,
    expected_code: str,
    expected_certainty: str,
    expected_anatomy: str,
):
    finding = canonicalize_cxr_finding(
        observation_code=code,
        observation_text=text,
        evidence=evidence,
        anatomy_code=None,
        location_text=None,
        certainty=certainty,
    )

    assert finding["observation_code"] == expected_code
    assert finding["certainty"] == expected_certainty
    assert finding["anatomy_code"] == expected_anatomy
    assert finding["attributes"]["ontology_version"] == CXR_ONTOLOGY_VERSION
    assert finding["attributes"]["original_observation_code"] == code


def test_cxr_canonicalizer_preserves_unknown_concept_without_making_it_matchable():
    finding = canonicalize_cxr_finding(
        observation_code="unusual device configuration",
        observation_text="Unusual device configuration",
        evidence="An unusual device configuration is present.",
        anatomy_code="chest",
        location_text="upper chest",
        certainty="present",
    )

    assert finding["observation_code"] == "other_finding"
    assert finding["certainty"] == "present"
    assert finding["attributes"]["original_observation_code"] == "unusual device configuration"
    assert finding["attributes"]["ontology_match"] == "unmapped"


def test_cxr_canonicalizer_prefers_the_finding_identity_in_shared_evidence():
    finding = canonicalize_cxr_finding(
        observation_code="pneumothorax",
        observation_text="Pneumothorax",
        evidence="No pleural effusion or pneumothorax.",
        anatomy_code="pleura",
        location_text=None,
        certainty="absent",
    )

    assert finding["observation_code"] == "pneumothorax"
    assert finding["certainty"] == "absent"


def test_cxr_canonicalizer_preserves_specific_anatomic_location():
    finding = canonicalize_cxr_finding(
        observation_code="nodule",
        observation_text="Pulmonary nodule",
        evidence="An 8 mm nodule is present in the right upper lobe.",
        anatomy_code="right upper lobe",
        location_text="right upper lobe",
        certainty="present",
    )

    assert finding["observation_code"] == "nodule"
    assert finding["anatomy_code"] == "right upper lobe"
    assert finding["location_text"] == "right upper lobe"


def test_cxr_canonicalizer_prefers_specific_evidence_over_broad_concept_code():
    finding = canonicalize_cxr_finding(
        observation_code="cardiopulmonary_abnormality",
        observation_text="Normal cardiomediastinal silhouette",
        evidence="The cardiomediastinal silhouette is normal.",
        anatomy_code="cardiomediastinum",
        location_text="cardiomediastinum",
        certainty="absent",
    )

    assert finding["observation_code"] == "cardiomegaly"
    assert finding["certainty"] == "absent"
    assert finding["anatomy_code"] == "heart"


def test_cxr_prompt_catalog_is_versioned_and_has_no_generic_normal_concept():
    catalog = cxr_prompt_catalog()

    assert catalog["version"] == CXR_ONTOLOGY_VERSION
    assert "normal" not in catalog["concepts"]
    assert catalog["concepts"]["opacity"]["orientation"] == "abnormality"
    assert catalog["concepts"]["other_finding"]["matchable"] is False
