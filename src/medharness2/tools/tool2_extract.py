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

NEGATION_RE = re.compile(r"\b(no|without|negative for|no evidence of|absent)\b", re.I)

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
    if backend == "auto":
        backend = "cxr_rule" if modality.lower() in {"cxr", "xray", "xr"} else "placeholder"
    if backend == "cxr_rule":
        return _extract_cxr_rule(report_text, modality=modality)
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


def _extract_cxr_rule(report_text: str, modality: str) -> dict[str, Any]:
    lower = report_text.lower()
    findings = []
    observations = [term for term in OBSERVATION_TERMS if term in lower]
    locations = [term for term in LOCATION_TERMS if term in lower]
    measurements = re.findall(r"\b\d+(?:\.\d+)?\s*(?:cm|mm)\b", lower)
    for idx, observation in enumerate(observations, start=1):
        start = lower.find(observation)
        certainty = "absent" if _is_negated(report_text, start) else "present"
        findings.append(
            {
                "id": f"f{idx}",
                "observation": observation,
                "location": _nearest_location(lower, start, locations),
                "severity": _severity(lower),
                "measurement": measurements[0] if measurements else None,
                "certainty": certainty,
                "text": report_text[max(0, start - 80) : start + 120] if start >= 0 else report_text[:500],
            }
        )
    if not findings and report_text.strip():
        findings = _extract_placeholder_findings(report_text)
        for finding in findings:
            finding["certainty"] = "present"
    coverage = len(findings) / max(len(OBSERVATION_TERMS), 1)
    return {
        "modality": modality,
        "backend": "cxr_rule",
        "findings": findings,
        "missing": [] if findings else ["findings"],
        "coverage": round(min(1.0, coverage), 4),
        "warnings": [],
        "nodes": [
            {
                "node_id": finding["id"],
                "type": "ObservationAbsent" if finding.get("certainty") == "absent" else "ObservationPresent",
                "canonical_name": finding["observation"],
                "properties": {"location": finding["location"], "severity": finding["severity"], "measurement": finding["measurement"]},
            }
            for finding in findings
        ],
        "template_coverage": {
            "total_template_items": len(OBSERVATION_TERMS),
            "satisfied": len(findings),
            "coverage_rate": round(min(1.0, coverage), 4),
        },
    }


def _is_negated(text: str, start: int) -> bool:
    if start < 0:
        return False
    window = text[max(0, start - 48) : start]
    return bool(NEGATION_RE.search(window))


def _nearest_location(text: str, start: int, locations: list[str]) -> str:
    if not locations:
        return "unspecified"
    if start < 0:
        return locations[0]
    return min(locations, key=lambda loc: abs(text.find(loc) - start) if text.find(loc) >= 0 else 10**9)
