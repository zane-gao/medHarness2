from __future__ import annotations

import re
from typing import Any


SECTION_WEIGHTS = {"findings": 0.55, "impression": 0.35, "clinical_history": 0.10}


def check_structure(report_text: str) -> dict[str, Any]:
    sections = split_sections(report_text)
    section_scores: dict[str, float] = {}
    weighted = 0.0
    for section, weight in SECTION_WEIGHTS.items():
        present = bool(sections.get(section, "").strip())
        section_scores[section] = 1.0 if present else 0.0
        weighted += section_scores[section] * weight
    warnings = []
    if not sections.get("findings"):
        warnings.append("missing_findings_section")
    if not sections.get("impression"):
        warnings.append("missing_impression_section")
    return {
        "sections": sections,
        "section_scores": section_scores,
        "score": round(weighted, 4),
        "warnings": warnings,
    }


def split_sections(report_text: str) -> dict[str, str]:
    text = report_text.strip()
    sections = {"findings": "", "impression": "", "clinical_history": "", "other": ""}
    if not text:
        return sections
    pattern = re.compile(r"(?im)^\s*(findings?|impression|clinical history|history)\s*:\s*")
    matches = list(pattern.finditer(text))
    if not matches:
        sections["findings"] = text
        return sections
    for idx, match in enumerate(matches):
        raw_name = match.group(1).lower()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        name = "clinical_history" if "history" in raw_name else raw_name.rstrip("s")
        if name == "finding":
            name = "findings"
        sections[name] = text[start:end].strip()
    prefix = text[: matches[0].start()].strip()
    if prefix:
        sections["other"] = prefix
    return sections
