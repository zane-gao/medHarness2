from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from medharness2.contracts import FindingGraph


NEGATION_RE = re.compile(
    r"(?:\b(?:no|without|negative for|no evidence of|absent|cannot identify)\b|未见|未发现|未提示|无|否认|不伴)",
    re.I,
)

CONTRAST_BOUNDARY_RE = re.compile(
    r"(?:\b(?:but|however|yet|nevertheless|though)\b|但是|但|然而|不过|而|却)",
    re.I,
)

SENTENCE_BOUNDARY_RE = re.compile(r"[。；;\n]|(?<!\d)\.(?!\d)")

SEVERITY_ALIASES: dict[str, list[str]] = {
    "severe": ["severe", "marked", "重度", "大量", "显著", "明显"],
    "moderate": ["moderate", "中度", "中等量"],
    "mild": ["mild", "small", "minimal", "轻度", "少量", "少许", "轻微", "稍"],
}


@dataclass(frozen=True)
class RuleFindingExtractor:
    backend: str
    modalities: tuple[str, ...]
    observation_aliases: dict[str, list[str]]
    location_aliases: dict[str, list[str]]
    fallback_reported_finding: bool = False
    attribute_resolver: Callable[[str, int], dict[str, Any]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def extract(self, report_text: str, *, modality: str) -> dict[str, Any]:
        observations = _find_alias_matches(report_text, self.observation_aliases)
        locations = _find_alias_matches(report_text, self.location_aliases)
        measurements = _find_measurements(report_text)
        findings = []
        for index, match in enumerate(observations, start=1):
            start = int(match["start"])
            end = int(match["end"])
            location = _nearest_location(report_text, start, locations)
            measurement = _nearest_measurement(report_text, start, measurements)
            attributes = self.attribute_resolver(report_text, start) if self.attribute_resolver else {}
            source_text = _sentence_snippet(report_text, start)
            findings.append(
                {
                    "finding_id": f"f{index}",
                    "observation_code": str(match["canonical"]),
                    "observation_text": str(match["canonical"]),
                    "anatomy_code": None if location == "unspecified" else location,
                    "location_text": None if location == "unspecified" else location,
                    "laterality": _laterality(location),
                    "severity": _severity(report_text, start),
                    "measurements": _measurement_rows(measurement),
                    "certainty": "absent" if _is_negated(report_text, start) else "present",
                    "source_span": {"start": start, "end": end},
                    "source_text": source_text,
                    "extractor": {
                        "implementation_type": "rule",
                        "provider": "local",
                        "model": self.backend,
                        "version": "2.0",
                        "fallback_used": False,
                    },
                    "attributes": attributes,
                }
            )
        findings = _deduplicate_findings(findings)
        warnings = []
        if not findings and report_text.strip() and self.fallback_reported_finding:
            findings = [_reported_finding(report_text, self.backend)]
            warnings.append("reported_finding_fallback")
        elif not findings and report_text.strip():
            warnings.append("no_supported_finding_detected")
        coverage = len(findings) / max(len(self.observation_aliases), 1)
        payload = {
            "schema_version": "2.0",
            "artifact_type": "finding_graph",
            "modality": modality,
            "backend": self.backend,
            "findings": findings,
            "relations": [],
            "missing": [] if findings else ["findings"],
            "coverage": round(min(1.0, coverage), 4),
            "warnings": warnings,
            "nodes": [
                {
                    "node_id": finding["finding_id"],
                    "type": "ObservationAbsent" if finding["certainty"] == "absent" else "ObservationPresent",
                    "canonical_name": finding["observation_code"],
                    "properties": {
                        "location": finding["anatomy_code"] or "unspecified",
                        "severity": finding["severity"],
                        "measurements": finding["measurements"],
                    },
                }
                for finding in findings
            ],
            "template_coverage": {
                "total_template_items": len(self.observation_aliases),
                "satisfied": len(findings),
                "coverage_rate": round(min(1.0, coverage), 4),
            },
            "metadata": dict(self.metadata),
        }
        return FindingGraph.model_validate(payload).model_dump(mode="json")


def _reported_finding(text: str, backend: str) -> dict[str, Any]:
    measurement = (_find_measurements(text) or [{}])[0].get("value")
    return {
        "finding_id": "f1",
        "observation_code": "reported_finding",
        "observation_text": "reported_finding",
        "anatomy_code": None,
        "location_text": None,
        "laterality": "unknown",
        "severity": _severity(text, None),
        "measurements": _measurement_rows(measurement),
        "certainty": "present",
        "source_span": None,
        "source_text": text[:500],
        "extractor": {
            "implementation_type": "rule",
            "provider": "local",
            "model": backend,
            "version": "2.0",
            "fallback_used": True,
        },
        "attributes": {},
    }


def _deduplicate_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for finding in findings:
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(selected)
                if _same_finding_context(existing, finding)
                and _measurements_can_merge(existing.get("measurements") or [], finding.get("measurements") or [])
            ),
            None,
        )
        if duplicate_index is None:
            selected.append(finding)
            continue
        existing = selected[duplicate_index]
        if not existing.get("measurements") and finding.get("measurements"):
            selected[duplicate_index] = finding
    for index, finding in enumerate(selected, start=1):
        finding["finding_id"] = f"f{index}"
    return selected


def _same_finding_context(a: dict[str, Any], b: dict[str, Any]) -> bool:
    fields = ("observation_code", "anatomy_code", "laterality", "certainty", "source_text")
    return all(a.get(field) == b.get(field) for field in fields)


def _measurements_can_merge(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> bool:
    if not a or not b:
        return True
    return _measurement_signature(a) == _measurement_signature(b)


def _measurement_signature(
    measurements: list[dict[str, Any]],
) -> tuple[tuple[float | None, str], ...]:
    return tuple(
        (
            _optional_float(item.get("normalized_mm")),
            str(item.get("unit") or ""),
        )
        for item in measurements
    )


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _find_alias_matches(text: str, aliases_by_canonical: dict[str, list[str]]) -> list[dict[str, Any]]:
    lower = text.lower()
    candidates: list[dict[str, Any]] = []
    for canonical, aliases in aliases_by_canonical.items():
        for alias in sorted(aliases, key=len, reverse=True):
            pattern = re.escape(alias.lower())
            if alias.isascii() and re.fullmatch(r"[a-z0-9 _-]+", alias.lower()):
                pattern = rf"\b{pattern}\b"
            for match in re.finditer(pattern, lower, flags=re.I):
                candidates.append(
                    {
                        "canonical": canonical,
                        "start": match.start(),
                        "end": match.end(),
                        "length": len(match.group()),
                    }
                )

    selected: list[dict[str, Any]] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (-int(item["length"]), int(item["start"]), str(item["canonical"])),
    ):
        if any(_spans_overlap(candidate, existing) for existing in selected):
            continue
        selected.append(candidate)
    return sorted(selected, key=lambda item: (int(item["start"]), -int(item["length"]), str(item["canonical"])))


def _spans_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return int(a["start"]) < int(b["end"]) and int(b["start"]) < int(a["end"])


def _find_measurements(text: str) -> list[dict[str, Any]]:
    rows = []
    pattern = re.compile(r"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)\s*(cm|mm|厘米|毫米)(?![A-Za-z0-9])", re.I)
    for match in pattern.finditer(text):
        unit = {"厘米": "cm", "毫米": "mm"}.get(match.group(2).lower(), match.group(2).lower())
        rows.append({"value": f"{match.group(1)} {unit}", "start": match.start(), "end": match.end()})
    return rows


def _measurement_rows(measurement: str | None) -> list[dict[str, Any]]:
    if not measurement:
        return []
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(cm|mm)", measurement)
    if not match:
        return []
    value = float(match.group(1))
    unit = match.group(2)
    return [{"value": value, "unit": unit, "normalized_mm": value * 10.0 if unit == "cm" else value}]


def _nearest_location(text: str, start: int, locations: list[dict[str, Any]]) -> str:
    if not locations:
        return "unspecified"
    same_sentence = [item for item in locations if not _has_sentence_boundary(text, int(item["start"]), start)]
    candidates = same_sentence or locations
    best = min(candidates, key=lambda item: abs(int(item["start"]) - start) - int(item["length"]) * 2)
    return str(best["canonical"])


def _nearest_measurement(text: str, start: int, measurements: list[dict[str, Any]]) -> str | None:
    if not measurements:
        return None
    same_sentence = [item for item in measurements if not _has_sentence_boundary(text, int(item["end"]), start)]
    candidates = same_sentence or measurements
    nearest = min(candidates, key=lambda item: abs(int(item["start"]) - start))
    return str(nearest["value"]) if abs(int(nearest["start"]) - start) <= 64 else None


def _severity(text: str, start: int | None) -> str:
    window = text if start is None else _sentence_snippet(text, start)
    lower = window.lower()
    for severity, aliases in SEVERITY_ALIASES.items():
        if any(alias.lower() in lower for alias in aliases):
            return severity
    return "unspecified"


def _is_negated(text: str, start: int) -> bool:
    sentence = _sentence_snippet(text, start, before_only=True)
    boundaries = list(CONTRAST_BOUNDARY_RE.finditer(sentence))
    if boundaries:
        sentence = sentence[boundaries[-1].end() :]
    return bool(NEGATION_RE.search(sentence))


def _sentence_snippet(text: str, start: int, *, before_only: bool = False) -> str:
    left = max(text.rfind(mark, 0, start) for mark in ("。", ".", "；", ";", "\n")) + 1
    if before_only:
        return text[left:start]
    right_candidates = [position for mark in ("。", ".", "；", ";", "\n") if (position := text.find(mark, start)) >= 0]
    right = min(right_candidates) + 1 if right_candidates else min(len(text), start + 180)
    return text[left:right].strip()


def _has_sentence_boundary(text: str, left: int, right: int) -> bool:
    lo, hi = sorted((left, right))
    return bool(SENTENCE_BOUNDARY_RE.search(text[lo:hi]))


def _laterality(location: str) -> str:
    lower = location.lower()
    if "bilateral" in lower:
        return "bilateral"
    if "right" in lower:
        return "right"
    if "left" in lower:
        return "left"
    if "midline" in lower:
        return "midline"
    return "unknown"


def sequence_attributes(text: str, start: int) -> dict[str, Any]:
    sentence = _sentence_snippet(text, start).upper()
    for sequence in ("DWI", "ADC", "T2-FLAIR", "FLAIR", "T2WI", "T1WI", "SWI"):
        if sequence in sentence:
            return {"sequence": sequence}
    return {}
