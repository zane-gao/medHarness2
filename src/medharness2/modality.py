"""Canonical imaging-modality vocabulary used by routing boundaries.

The project routes on three image families (``cxr``, ``ct`` and ``mri``).
Inputs arrive from DICOM headers, directory names, legacy manifests and VLM
text, so aliases must be normalized in one place before compatibility checks.
Unknown values are preserved as a lowercase token rather than being silently
assigned to one of the three families.
"""

from __future__ import annotations

import re
from typing import Any


CANONICAL_MODALITIES = frozenset({"cxr", "ct", "mri"})

_CXR_RE = re.compile(
    r"(?:\bcxr\b|\bx[-\s]?ray\b|\bxray\b|\bxr\b|\bcr\b|\bdx\b|"
    r"\bradiograph(?:y)?\b|\bchest\s+film\b|胸片|胸部平片|x线|x光)",
    re.IGNORECASE,
)
_CT_RE = re.compile(
    r"(?:\bct\b|\bcta\b|\bcomputed\s+tomography\b|计算机断层|电子计算机断层)",
    re.IGNORECASE,
)
_MRI_RE = re.compile(
    r"(?:\bmri\b|\bmr\b|\bmra\b|\bmagnetic\s+resonance\b|磁共振|核磁)",
    re.IGNORECASE,
)


def normalize_modality(value: Any) -> str:
    """Return the canonical route key for a modality or free-text label.

    Matching is deliberately family-level.  For example ``CTA`` remains a
    CT route and ``chest x-ray`` becomes CXR.  A value that does not identify
    one of the three supported families is returned as a normalized token so
    callers can fail closed instead of guessing.
    """

    if value is None:
        return "unknown"
    if not isinstance(value, str):
        value = str(value)
    raw = value.strip().lower()
    if not raw:
        return "unknown"

    # Check MRI before generic MR and CT before short aliases.  Word-boundary
    # matching avoids false positives such as ``primary`` containing ``mr``.
    if _MRI_RE.search(raw):
        return "mri"
    if _CT_RE.search(raw):
        return "ct"
    if _CXR_RE.search(raw):
        return "cxr"

    # Exact compact aliases are useful for values such as ``X_RAY`` where a
    # phrase regex may not match due to punctuation.
    compact = re.sub(r"[^a-z0-9]+", "", raw)
    if compact in {"mri", "mr", "mra", "magneticresonance"}:
        return "mri"
    if compact in {"ct", "cta", "computedtomography"}:
        return "ct"
    if compact in {"cxr", "xray", "xr", "cr", "dx", "radiograph", "radiography"}:
        return "cxr"

    # Preserve a stable, human-readable unknown key.  Spaces/punctuation are
    # collapsed so equivalent unknown labels do not create duplicate routes.
    return compact or "unknown"

