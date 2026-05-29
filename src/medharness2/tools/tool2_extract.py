from __future__ import annotations

import re
from typing import Any


OBSERVATION_TERMS = [
    "opacity",
    "nodule",
    "mass",
    "effusion",
    "pneumothorax",
    "edema",
    "consolidation",
    "atelectasis",
    "normal",
]

LOCATION_TERMS = [
    "right upper lobe",
    "right lower lobe",
    "left upper lobe",
    "left lower lobe",
    "right lung",
    "left lung",
    "bilateral",
    "pleural",
    "heart",
    "brain",
]


def extract_findings(report_text: str, modality: str = "unknown", backend: str = "placeholder") -> dict[str, Any]:
    if backend != "placeholder":
        raise ValueError(f"Unsupported extractor backend for MVP: {backend}")
    findings = _extract_placeholder_findings(report_text)
    missing = [] if findings else ["findings"]
    return {
        "modality": modality,
        "backend": backend,
        "findings": findings,
        "missing": missing,
        "coverage": 1.0 if findings else 0.0,
        "warnings": ["placeholder_extractor"],
    }


def _extract_placeholder_findings(report_text: str) -> list[dict[str, Any]]:
    lower = report_text.lower()
    observations = [term for term in OBSERVATION_TERMS if term in lower]
    locations = [term for term in LOCATION_TERMS if term in lower]
    measurements = re.findall(r"\b\d+(?:\.\d+)?\s*(?:cm|mm)\b", lower)
    if not observations and report_text.strip():
        observations = ["reported_finding"]
    findings: list[dict[str, Any]] = []
    for idx, observation in enumerate(observations, start=1):
        finding = {
            "id": f"f{idx}",
            "observation": observation,
            "location": locations[0] if locations else "unspecified",
            "severity": _severity(lower),
            "measurement": measurements[0] if measurements else None,
            "text": report_text[:500],
        }
        findings.append(finding)
    return findings


def _severity(text: str) -> str:
    for term in ["severe", "moderate", "mild"]:
        if term in text:
            return term
    return "unspecified"
