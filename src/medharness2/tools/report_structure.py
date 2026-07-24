from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from medharness2.contracts import CandidateReportStructure, CandidateStructureComparison
from medharness2.generators.routing import normalize_body_part
from medharness2.modality import canonical_modality
from medharness2.tools.tool2_extract import extract_findings
from medharness2.tools.tool3_structure import split_sections


_HEADER_RE = re.compile(
    r"(?im)^\s*(findings?|impression|clinical history|history|检查所见|影像所见|所见|诊断意见|印象|结论)\s*[:：]\s*"
)
_DEFAULT_TEMPLATE_REGISTRY = (
    Path(__file__).resolve().parents[1] / "templates" / "report_structure_templates.json"
)
_STRUCTURE_VERSION = "candidate-structure-v2"


def structure_report(
    report_text: str,
    *,
    modality: str,
    body_part: str | None,
    template_registry_path: str | Path | None = None,
) -> dict[str, Any]:
    text = str(report_text or "")
    modality_key = canonical_modality(modality)
    body_part_key = normalize_body_part(body_part)
    template = _template_attachment(
        modality_key,
        body_part_key,
        template_registry_path=template_registry_path,
    )
    if not text.strip():
        return _validated_structure(
            {
                "schema_version": "2.0",
                "artifact_type": "candidate_report_structure",
                "structure_status": "empty_report",
                "structure_version": _STRUCTURE_VERSION,
                "modality": modality_key,
                "body_part": body_part_key,
                "sections": split_sections(text),
                "spans": [],
                "entities": [],
                "finding_graph": _empty_finding_graph(modality_key),
                "template": template,
                "warnings": ["empty_report"],
            }
        )

    try:
        graph = extract_findings(text, modality=modality_key, backend="auto")
        spans, grounding_warnings = _atomic_spans(text, graph.get("findings") or [])
        payload = {
            "schema_version": "2.0",
            "artifact_type": "candidate_report_structure",
            "structure_status": "succeeded",
            "structure_version": _STRUCTURE_VERSION,
            "modality": modality_key,
            "body_part": body_part_key,
            "sections": split_sections(text),
            "spans": spans,
            "entities": _merge_entities(spans),
            "finding_graph": graph,
            "template": template,
            "warnings": [*list(graph.get("warnings") or []), *grounding_warnings],
        }
        return _validated_structure(payload)
    except Exception as exc:
        return _validated_structure(
            {
                "schema_version": "2.0",
                "artifact_type": "candidate_report_structure",
                "structure_status": "failed",
                "structure_version": _STRUCTURE_VERSION,
                "modality": modality_key,
                "body_part": body_part_key,
                "sections": split_sections(text),
                "spans": [],
                "entities": [],
                "finding_graph": _empty_finding_graph(modality_key),
                "template": template,
                "warnings": ["structure_extraction_failed"],
                "error": f"{type(exc).__name__}: {exc}",
            }
        )


def failed_structure_report(
    report_text: str,
    *,
    modality: str,
    body_part: str | None,
    error: BaseException | str,
    template_registry_path: str | Path | None = None,
) -> dict[str, Any]:
    modality_key = canonical_modality(modality)
    body_part_key = normalize_body_part(body_part)
    detail = str(error) if isinstance(error, str) else f"{type(error).__name__}: {error}"
    return _validated_structure(
        {
            "schema_version": "2.0",
            "artifact_type": "candidate_report_structure",
            "structure_status": "failed",
            "structure_version": _STRUCTURE_VERSION,
            "modality": modality_key,
            "body_part": body_part_key,
            "sections": split_sections(str(report_text or "")),
            "spans": [],
            "entities": [],
            "finding_graph": _empty_finding_graph(modality_key),
            "template": _template_attachment(
                modality_key,
                body_part_key,
                template_registry_path=template_registry_path,
            ),
            "warnings": ["structure_extraction_failed"],
            "error": detail,
        }
    )


def compare_candidate_structures(candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    candidate_ids = sorted(candidates)
    by_entity: dict[str, dict[str, list[dict[str, Any]]]] = {}
    internal_conflicts: list[dict[str, Any]] = []
    for candidate_id in candidate_ids:
        structure = candidates[candidate_id]
        for entity in structure.get("entities") or []:
            entity_key = str(entity.get("entity") or "").strip()
            if entity_key:
                by_entity.setdefault(entity_key, {}).setdefault(candidate_id, []).append(entity)

    agreements: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    omissions: list[dict[str, Any]] = []
    for entity, values_by_candidate in sorted(by_entity.items()):
        present_candidate_ids = sorted(values_by_candidate)
        missing_candidate_ids = sorted(set(candidate_ids) - set(present_candidate_ids))
        status_values = {
            candidate_id: sorted(
                {str(item.get("observation_status") or "uncertain") for item in rows}
            )
            for candidate_id, rows in values_by_candidate.items()
        }
        internally_conflicted = {
            candidate_id: values
            for candidate_id, values in status_values.items()
            if len(values) > 1
        }
        if internally_conflicted:
            internal_conflicts.append(
                _comparison_item(
                    entity,
                    "internal_status",
                    candidate_ids=sorted(internally_conflicted),
                    candidate_values=internally_conflicted,
                )
            )
        if missing_candidate_ids:
            omissions.append(
                _comparison_item(
                    entity,
                    "candidate_missing",
                    candidate_ids=present_candidate_ids,
                    candidate_values=status_values,
                    missing_candidate_ids=missing_candidate_ids,
                )
            )
        if len({tuple(values) for values in status_values.values()}) > 1:
            conflicts.append(
                _comparison_item(
                    entity,
                    "observation_status",
                    candidate_ids=present_candidate_ids,
                    candidate_values=status_values,
                )
            )

        attribute_conflicts = _attribute_conflicts(entity, values_by_candidate)
        conflicts.extend(attribute_conflicts)
        if len(present_candidate_ids) >= 2 and not missing_candidate_ids and not internally_conflicted:
            no_status_conflict = len({tuple(values) for values in status_values.values()}) == 1
            if no_status_conflict and not attribute_conflicts:
                agreements.append(
                    _comparison_item(
                        entity,
                        "agreement",
                        candidate_ids=present_candidate_ids,
                        candidate_values=status_values,
                    )
                )

    payload = {
        "schema_version": "2.0",
        "artifact_type": "candidate_structure_comparison",
        "structure_version": _STRUCTURE_VERSION,
        "candidate_ids": candidate_ids,
        "agreement_count": len(agreements),
        "conflict_count": len(conflicts),
        "omission_count": len(omissions),
        "internal_conflict_count": len(internal_conflicts),
        "agreements": agreements,
        "conflicts": conflicts,
        "omissions": omissions,
        "internal_conflicts": internal_conflicts,
    }
    return CandidateStructureComparison.model_validate(payload).model_dump(mode="json")


def _atomic_spans(text: str, findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    spans: list[dict[str, Any]] = []
    warnings: list[str] = []
    headers = list(_HEADER_RE.finditer(text))
    for finding in findings:
        bounds = _grounded_evidence_bounds(text, finding)
        if bounds is None:
            warnings.append(f"ungrounded_finding_skipped:{finding.get('finding_id') or 'unknown'}")
            continue
        start, end = bounds
        evidence = text[start:end]
        certainty = _observation_status(finding.get("certainty"))
        anatomy_code = _optional_text(finding.get("anatomy_code"))
        location_text = _optional_text(finding.get("location_text"))
        subject = location_text or anatomy_code or "unspecified"
        entity = _canonical_entity(finding)
        measurements = list(finding.get("measurements") or [])
        span = {
            "span_id": len(spans),
            "subject": subject,
            "entity": entity,
            "attribute": "observation",
            "value_raw": _optional_text(finding.get("observation_text")) or entity,
            "observation_status": certainty,
            "certainty": certainty,
            "laterality": str(finding.get("laterality") or "unknown"),
            "severity": _optional_text(finding.get("severity")),
            "measurements": measurements,
            "evidence_snippet": evidence,
            "start": start,
            "end": end,
            "section": _section_for_offset(start, headers),
            "attributes": dict(finding.get("attributes") or {}),
            "anatomy_code": anatomy_code,
            "location_text": location_text,
            "finding_id": str(finding.get("finding_id") or ""),
        }
        spans.append(span)
    return spans, warnings


def _grounded_evidence_bounds(text: str, finding: dict[str, Any]) -> tuple[int, int] | None:
    evidence = str(finding.get("source_text") or "").strip()
    if not evidence:
        return None
    positions = [match.start() for match in re.finditer(re.escape(evidence), text)]
    if not positions:
        return None
    source_span = finding.get("source_span") or {}
    hint = source_span.get("start") if isinstance(source_span, dict) else None
    if isinstance(hint, int):
        containing = [position for position in positions if position <= hint < position + len(evidence)]
        start = containing[0] if containing else min(positions, key=lambda position: abs(position - hint))
    else:
        start = positions[0]
    return start, start + len(evidence)


def _merge_entities(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for span in spans:
        key = (
            span["entity"],
            span["subject"],
            span["laterality"],
            span["observation_status"],
            span["severity"],
            _measurement_signature(span.get("measurements") or []),
            _stable_attributes(span.get("attributes") or {}),
        )
        item = merged.setdefault(
            key,
            {
                "entity": span["entity"],
                "subject": span["subject"],
                "anatomy_code": span.get("anatomy_code"),
                "location_text": span.get("location_text"),
                "laterality": span["laterality"],
                "observation_status": span["observation_status"],
                "certainty": span["certainty"],
                "severity": span["severity"],
                "measurements": span["measurements"],
                "attributes": span["attributes"],
                "evidence_span_ids": [],
                "evidence_snippets": [],
                "sections": [],
            },
        )
        item["evidence_span_ids"].append(span["span_id"])
        item["evidence_snippets"].append(span["evidence_snippet"])
        if span["section"] not in item["sections"]:
            item["sections"].append(span["section"])
    return list(merged.values())


def _attribute_conflicts(
    entity: str,
    values_by_candidate: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for field_name, comparison_type in (
        ("laterality", "laterality"),
        ("anatomy_code", "anatomy"),
        ("measurements", "measurement"),
        ("severity", "severity"),
    ):
        values: dict[str, list[str]] = {}
        for candidate_id, rows in values_by_candidate.items():
            normalized = sorted(
                {
                    value
                    for row in rows
                    if (value := _comparison_value(row, field_name)) not in {"", "unknown", "unspecified"}
                }
            )
            if normalized:
                values[candidate_id] = normalized
        if len(values) >= 2 and len({tuple(value) for value in values.values()}) > 1:
            result.append(
                _comparison_item(
                    entity,
                    comparison_type,
                    candidate_ids=sorted(values),
                    candidate_values=values,
                )
            )
    return result


def _comparison_item(
    entity: str,
    comparison_type: str,
    *,
    candidate_ids: list[str],
    candidate_values: dict[str, list[str]],
    missing_candidate_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "entity": entity,
        "comparison_type": comparison_type,
        "candidate_ids": candidate_ids,
        "candidate_values": {key: list(value) for key, value in sorted(candidate_values.items())},
        "missing_candidate_ids": list(missing_candidate_ids or []),
    }


def _comparison_value(entity: dict[str, Any], field_name: str) -> str:
    if field_name == "measurements":
        return ",".join(_measurement_signature(entity.get("measurements") or []))
    return str(entity.get(field_name) or "").strip().casefold()


def _measurement_signature(measurements: list[dict[str, Any]]) -> tuple[str, ...]:
    values = []
    for measurement in measurements:
        normalized = measurement.get("normalized_mm")
        if normalized is None:
            value = measurement.get("value")
            unit = str(measurement.get("unit") or "")
            normalized = float(value) * 10.0 if unit == "cm" and value is not None else value
        if normalized is not None:
            values.append(f"{float(normalized):g}mm")
    return tuple(sorted(values))


def _stable_attributes(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _section_for_offset(offset: int, headers: list[re.Match[str]]) -> str:
    if not headers:
        return "findings"
    current = "other"
    for header in headers:
        if header.start() > offset:
            break
        label = header.group(1).casefold()
        if label in {"impression", "诊断意见", "印象", "结论"}:
            current = "impression"
        elif label in {"clinical history", "history"}:
            current = "clinical_history"
        else:
            current = "findings"
    return current


def _template_attachment(
    modality: str,
    body_part: str,
    *,
    template_registry_path: str | Path | None,
) -> dict[str, Any]:
    path = Path(template_registry_path) if template_registry_path else _DEFAULT_TEMPLATE_REGISTRY
    try:
        raw = path.read_bytes()
        registry = json.loads(raw.decode("utf-8"))
        if not isinstance(registry, dict) or not isinstance(registry.get("templates"), list):
            raise ValueError("invalid_template_registry")
        registry_version = str(registry.get("registry_version") or "report-structure-templates-v1")
        registry_sha256 = hashlib.sha256(raw).hexdigest()
        for template in registry["templates"]:
            if not isinstance(template, dict):
                continue
            modalities = {canonical_modality(item) for item in template.get("modalities") or []}
            body_parts = {normalize_body_part(item) for item in template.get("body_parts") or []}
            if modality in modalities and body_part in body_parts:
                return _template_payload(
                    template,
                    registry_version=registry_version,
                    registry_sha256=registry_sha256,
                    status="matched",
                    matched_on="exact_modality_body_part",
                    reason="",
                )
        generic = registry.get("generic_template")
        if not isinstance(generic, dict):
            raise ValueError("generic_template_missing")
        return _template_payload(
            generic,
            registry_version=registry_version,
            registry_sha256=registry_sha256,
            status="generic_fallback",
            matched_on="generic_fallback",
            reason="no_registered_template",
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        fallback = {
            "template_id": "generic",
            "template_version": "report-structure-generic-v1",
            "anatomy_sections": ["findings", "impression"],
        }
        raw = json.dumps(fallback, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return _template_payload(
            fallback,
            registry_version="report-structure-templates-unavailable",
            registry_sha256=hashlib.sha256(raw).hexdigest(),
            status="generic_fallback",
            matched_on="generic_fallback",
            reason="template_registry_unavailable",
        )


def _template_payload(
    template: dict[str, Any],
    *,
    registry_version: str,
    registry_sha256: str,
    status: str,
    matched_on: str,
    reason: str,
) -> dict[str, Any]:
    encoded = json.dumps(template, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "status": status,
        "template_id": str(template.get("template_id") or "generic"),
        "template_version": str(template.get("template_version") or registry_version),
        "template_sha256": hashlib.sha256(encoded).hexdigest(),
        "registry_version": registry_version,
        "registry_sha256": registry_sha256,
        "matched_on": matched_on,
        "reason": reason,
        "anatomy_sections": [str(item) for item in template.get("anatomy_sections") or []],
    }


def _empty_finding_graph(modality: str) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "artifact_type": "finding_graph",
        "modality": modality or "unknown",
        "backend": "candidate_structure",
        "findings": [],
        "relations": [],
        "missing": ["findings"],
        "coverage": 0.0,
        "nodes": [],
        "template_coverage": {},
        "warnings": [],
        "metadata": {},
    }


def _validated_structure(payload: dict[str, Any]) -> dict[str, Any]:
    return CandidateReportStructure.model_validate(payload).model_dump(mode="json")


def _canonical_entity(finding: dict[str, Any]) -> str:
    return (
        _optional_text(finding.get("observation_code"))
        or _optional_text(finding.get("observation_text"))
        or "reported_finding"
    ).casefold()


def _observation_status(value: Any) -> str:
    status = str(value or "uncertain").strip().lower()
    return status if status in {"present", "absent", "uncertain"} else "uncertain"


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


__all__ = ["compare_candidate_structures", "failed_structure_report", "structure_report"]
