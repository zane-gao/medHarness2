from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from medharness2.config import PrivacyConfig


class PrivacyViolation(RuntimeError):
    """Raised before an external request when its payload violates policy."""


@dataclass(frozen=True)
class PrivacyFinding:
    category: str
    pattern_name: str


@dataclass(frozen=True)
class PrivacyScanResult:
    allowed: bool
    scan_id: str
    findings: tuple[PrivacyFinding, ...]


_PATTERNS = (
    (
        "labeled_identifier",
        "chinese_clinical_identifier",
        re.compile(r"(?:姓名|住院号|门诊号|身份证(?:号)?|影像号|检查号|床号|电话|手机号|联系电话|报告医生|审核医生)\s*[:：]\s*[^\s,，;；]+", re.I),
    ),
    ("phone", "phone_number", re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")),
    ("email", "email_address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("national_id", "cn_national_id", re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")),
    (
        "date",
        "calendar_date",
        re.compile(r"(?<!\d)(?:19|20)\d{2}(?:[-/.年])\d{1,2}(?:[-/.月])\d{1,2}日?(?!\d)"),
    ),
    ("dicom_uid", "dicom_uid", re.compile(r"(?<!\d)\d+(?:\.\d+){4,}(?!\d)")),
    ("absolute_path", "server_absolute_path", re.compile(r"(?<![A-Za-z0-9])/(?:data|nfsdata[^/]*|home|tmp|var|opt|private)(?:/[^\s,，;；]+)+")),
    ("privacy_canary", "privacy_canary", re.compile(r"PATIENT_CANARY_[A-Z0-9_-]+", re.I)),
)

_HAZARD_FIELDS = (
    "error_type",
    "observation",
    "location",
    "severity",
    "measurement",
    "certainty",
    "alignment_error_index",
    "alignment_audit_judgement",
    "original_error_type",
)


class ExternalPayloadPolicy:
    def __init__(self, config: PrivacyConfig | None = None):
        self.config = config or PrivacyConfig()

    def scan(self, payload: str) -> PrivacyScanResult:
        findings: list[PrivacyFinding] = []
        for category, pattern_name, pattern in _PATTERNS:
            if pattern.search(payload):
                findings.append(PrivacyFinding(category=category, pattern_name=pattern_name))
        scan_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return PrivacyScanResult(allowed=not findings, scan_id=scan_id, findings=tuple(findings))

    def validate_external(self, prompt: str, *, image_path: str | None, classification: str) -> PrivacyScanResult:
        if classification not in set(self.config.allowed_external_classifications):
            raise PrivacyViolation(f"External payload classification is not allowed: {classification or 'missing'}")
        if image_path and self.config.block_external_images:
            raise PrivacyViolation("External image/document transfer is blocked by privacy policy")
        result = self.scan(prompt)
        if not result.allowed:
            categories = ",".join(sorted({finding.category for finding in result.findings}))
            raise PrivacyViolation(f"External payload blocked by privacy scan: {categories}; scan_id={result.scan_id}")
        return result

    def sanitize_hazard_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sanitized = []
        for candidate in candidates:
            row = {key: candidate[key] for key in _HAZARD_FIELDS if candidate.get(key) not in (None, "")}
            sanitized.append(row)
        encoded = json.dumps(sanitized, ensure_ascii=False, sort_keys=True)
        result = self.scan(encoded)
        if not result.allowed:
            categories = ",".join(sorted({finding.category for finding in result.findings}))
            raise PrivacyViolation(f"Structured hazard payload blocked: {categories}; scan_id={result.scan_id}")
        return sanitized

    def deidentify_clinical_text(self, text: str) -> str:
        clinical = _clinical_sections_only(text)
        replacements = {
            "labeled_identifier": "[REDACTED_IDENTIFIER]",
            "phone": "[REDACTED_PHONE]",
            "email": "[REDACTED_EMAIL]",
            "national_id": "[REDACTED_IDENTIFIER]",
            "date": "[REDACTED_DATE]",
            "dicom_uid": "[REDACTED_UID]",
            "absolute_path": "[REDACTED_PATH]",
            "privacy_canary": "[REDACTED_CANARY]",
        }
        sanitized = clinical
        for category, _, pattern in _PATTERNS:
            sanitized = pattern.sub(replacements[category], sanitized)
        return "\n".join(line.rstrip() for line in sanitized.splitlines() if line.strip()).strip()


def _clinical_sections_only(text: str) -> str:
    start = re.search(r"(?:^|\n)\s*[*#_\-]*\s*(?:检查所见|影像所见|所见|findings?)\s*[:：]", text, re.I)
    clinical = text[start.start() :] if start else text
    end = re.search(
        r"(?:^|\n)\s*[*#_\-]*\s*(?:报告医生|审核医生|审核时间|打印时间|注\s*[:：]|PATIENT_CANARY_[A-Z0-9_-]+)",
        clinical,
        re.I,
    )
    return clinical[: end.start()] if end else clinical
