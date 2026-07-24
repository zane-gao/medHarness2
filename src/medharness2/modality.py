"""Canonical imaging-modality vocabulary used by routing boundaries.

Inputs arrive from DICOM headers, directory names, legacy manifests and VLM
text, so aliases must be normalized in one place before compatibility checks.
Unknown values are preserved as a lowercase token rather than being silently
assigned to a supported family.
"""

from __future__ import annotations

import re
from typing import Any


CANONICAL_MODALITIES = frozenset(
    {
        "cxr",
        "ct",
        "dermatology",
        "ecg",
        "endoscopy",
        "generic_image",
        "mammography",
        "mri",
        "multimodal",
        "ophthalmology",
        "otoscopy",
        "pathology",
        "pet",
        "pet_ct",
        "ultrasound",
    }
)
GENERIC_MODALITIES = frozenset({"generic_image", "multimodal"})

_CXR_RE = re.compile(
    r"(?:\bcxr\b|\bx[-\s]?ray\b|\bxray\b|\bxr\b|\bcr\b|\bdr\b|\bdx\b|"
    r"\bradiograph(?:y)?\b|\bchest\s+film\b|胸片|胸部平片|x线|x光)",
    re.IGNORECASE,
)
_CT_RE = re.compile(
    r"(?:\bct\b|\bcta\b|\bctpa\b|\bcomputed\s+tomography\b|计算机断层|电子计算机断层)",
    re.IGNORECASE,
)
_MRI_RE = re.compile(
    r"(?:\bmri\b|\bmr\b|\bmra\b|\bmagnetic\s+resonance\b|磁共振|核磁)",
    re.IGNORECASE,
)

_MODALITY_PATTERNS = (
    (
        "pet_ct",
        re.compile(
            r"(?:\bpet\s*[/+_-]?\s*ct\b|\bpetct\b|正电子发射.*(?:ct|断层))",
            re.IGNORECASE,
        ),
    ),
    ("mri", _MRI_RE),
    ("ct", _CT_RE),
    ("cxr", _CXR_RE),
    (
        "ultrasound",
        re.compile(
            r"(?:\bultrasound\b|\bultrasonography\b|\bsonograph(?:y|ic)?\b|\bus\b|超声|彩超)",
            re.IGNORECASE,
        ),
    ),
    (
        "pathology",
        re.compile(
            r"(?:\bpatholog(?:y|ical)\b|\bhistopatholog(?:y|ical)\b|\bhistology\b|"
            r"\bwhole[-\s]?slide\b|\bwsi\b|\bmicroscopy\b|\bmultiphoton\b|病理|组织学|显微镜)",
            re.IGNORECASE,
        ),
    ),
    (
        "pet",
        re.compile(r"(?:\bpet\b|\bpositron\s+emission\s+tomography\b|正电子发射)", re.IGNORECASE),
    ),
    (
        "mammography",
        re.compile(r"(?:\bmammogra(?:m|phy|phic)\b|乳腺钼靶|乳房摄影)", re.IGNORECASE),
    ),
    (
        "ophthalmology",
        re.compile(
            r"(?:\bfundus\b|\bretin(?:a|al|ography)\b|\bophthalm(?:ic|ology)\b|\boct\b|"
            r"眼底|眼科|光学相干断层)",
            re.IGNORECASE,
        ),
    ),
    (
        "endoscopy",
        re.compile(r"(?:\bendoscop(?:y|ic)\b|\bcapsule\s+endoscopy\b|内镜|内窥镜|胶囊内镜)", re.IGNORECASE),
    ),
    ("dermatology", re.compile(r"(?:\bdermatolog(?:y|ical)\b|皮肤镜|皮肤科)", re.IGNORECASE)),
    ("otoscopy", re.compile(r"(?:\botoscop(?:y|ic)\b|耳镜)", re.IGNORECASE)),
    ("ecg", re.compile(r"(?:\becg\b|\bekg\b|\belectrocardiogra(?:m|phy)\b|心电图)", re.IGNORECASE)),
    (
        "multimodal",
        re.compile(r"(?:\bmulti[-\s]?modal\b|\bmultimodal\b|多模态)", re.IGNORECASE),
    ),
    (
        "generic_image",
        re.compile(
            r"(?:\bmedical\s+image\b|\bgeneric\s+image\b|\bclinical\s+image\b|\bradiology\b|通用医学影像)",
            re.IGNORECASE,
        ),
    ),
)

_COMPACT_ALIASES = {
    "capsuleendoscopy": "endoscopy",
    "clinicalimage": "generic_image",
    "cr": "cxr",
    "ct": "ct",
    "cta": "ct",
    "ctpa": "ct",
    "computedtomography": "ct",
    "cxr": "cxr",
    "dermatology": "dermatology",
    "dr": "cxr",
    "dx": "cxr",
    "ecg": "ecg",
    "echocardiography": "ultrasound",
    "ekg": "ecg",
    "endoscopy": "endoscopy",
    "fundus": "ophthalmology",
    "fundusphotography": "ophthalmology",
    "genericimage": "generic_image",
    "histology": "pathology",
    "histopathology": "pathology",
    "magneticresonance": "mri",
    "mammogram": "mammography",
    "mammography": "mammography",
    "medicalimage": "generic_image",
    "microscopy": "pathology",
    "mr": "mri",
    "mra": "mri",
    "mri": "mri",
    "multimodal": "multimodal",
    "multiphotonmicroscopy": "pathology",
    "oct": "ophthalmology",
    "ophthalmicimaging": "ophthalmology",
    "ophthalmology": "ophthalmology",
    "otoscopy": "otoscopy",
    "pathology": "pathology",
    "pathologywsi": "pathology",
    "pet": "pet",
    "petct": "pet_ct",
    "petscan": "pet",
    "pt": "pet",
    "radiograph": "cxr",
    "radiography": "cxr",
    "radiology": "generic_image",
    "retinalfundus": "ophthalmology",
    "retinography": "ophthalmology",
    "sonography": "ultrasound",
    "ultrasound": "ultrasound",
    "ultrasoundstudy": "ultrasound",
    "us": "ultrasound",
    "wsi": "pathology",
    "xray": "cxr",
    "xr": "cxr",
}


def normalize_modality(value: Any) -> str:
    """Return a canonical route key for a modality or free-text label."""

    if value is None:
        return "unknown"
    if not isinstance(value, str):
        value = str(value)
    raw = value.strip().lower()
    if not raw:
        return "unknown"

    for modality, pattern in _MODALITY_PATTERNS:
        if pattern.search(raw):
            return modality

    compact = re.sub(r"[^a-z0-9]+", "", raw)
    if compact in _COMPACT_ALIASES:
        return _COMPACT_ALIASES[compact]
    return compact or "unknown"


def canonical_modality(value: Any) -> str:
    """Return a supported route key, or ``unknown`` for unrecognized input."""

    key = normalize_modality(value)
    return key if key in CANONICAL_MODALITIES else "unknown"


__all__ = [
    "CANONICAL_MODALITIES",
    "GENERIC_MODALITIES",
    "canonical_modality",
    "normalize_modality",
]
