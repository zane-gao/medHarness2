from __future__ import annotations

import re
from typing import Any


SECTION_WEIGHTS = {"findings": 0.55, "impression": 0.35, "clinical_history": 0.10}
SECTION_ALIASES = {
    "findings": ("findings", "finding", "检查所见", "影像所见", "所见"),
    "impression": ("impression", "诊断意见", "印象", "结论"),
    "clinical_history": ("clinical history", "history", "临床资料", "病史"),
}
_ALIAS_TO_SECTION = {
    alias.casefold(): section
    for section, aliases in SECTION_ALIASES.items()
    for alias in aliases
}
_SECTION_HEADER_RE = re.compile(
    rf"(?im)^\s*({'|'.join(re.escape(alias) for alias in sorted(_ALIAS_TO_SECTION, key=len, reverse=True))})\s*[:：]\s*"
)


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
    matches = list(_SECTION_HEADER_RE.finditer(text))
    if not matches:
        sections["findings"] = text
        return sections
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        name = _ALIAS_TO_SECTION[match.group(1).casefold()]
        content = text[start:end].strip()
        if content:
            sections[name] = "\n".join(part for part in (sections[name], content) if part)
    prefix = text[: matches[0].start()].strip()
    if prefix:
        sections["other"] = prefix
    return sections


def section_order(report_text: str) -> list[str]:
    order: list[str] = []
    for match in _SECTION_HEADER_RE.finditer(report_text):
        section = _ALIAS_TO_SECTION[match.group(1).casefold()]
        if section not in order:
            order.append(section)
    if order:
        return order
    return [section for section, text in split_sections(report_text).items() if text.strip()]


__all__ = ["check_structure", "section_order", "split_sections"]
