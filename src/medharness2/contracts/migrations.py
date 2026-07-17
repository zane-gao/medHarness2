from __future__ import annotations

from copy import deepcopy
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

from medharness2.contracts.case import CaseEvaluationArtifact
from medharness2.contracts.evaluation import FindingGraph, GeneratedReportArtifact, HazardResult


_CASE_FIELDS = {
    "schema_version",
    "artifact_type",
    "case_id",
    "input",
    "human_evaluation",
    "generated_reports",
    "generated_evaluations",
    "rankings",
    "pairwise_comparisons",
    "migration_warnings",
    "legacy_extensions",
}

_FINDING_FIELDS = {
    "finding_id",
    "id",
    "observation_code",
    "observation_text",
    "observation",
    "anatomy_code",
    "location_text",
    "location",
    "laterality",
    "certainty",
    "severity",
    "measurements",
    "measurement",
    "source_span",
    "source_text",
    "text",
    "extractor",
    "attributes",
}

_GRAPH_FIELDS = {
    "schema_version",
    "artifact_type",
    "modality",
    "backend",
    "findings",
    "relations",
    "missing",
    "coverage",
    "nodes",
    "template_coverage",
    "warnings",
    "metadata",
}

_HAZARD_ERROR_FIELDS = {
    "error_type",
    "hazard_level",
    "explanation",
    "recommended_action",
    "confidence",
    "evidence_ids",
    "abstain",
    "finding",
    "candidate",
    "reference",
    "a",
    "b",
    "observation",
    "location",
    "severity",
    "measurement",
    "certainty",
    "text",
}

_HAZARD_RESULT_FIELDS = {
    "schema_version",
    "artifact_type",
    "errors",
    "provenance",
    "metadata",
}

_MEASUREMENT_PATTERN = re.compile(r"(?<!\w)(\d+(?:\.\d+)?)\s*(mm|cm)\b", re.IGNORECASE)


def infer_evidence_tier(source: str, metadata: dict[str, Any] | None = None) -> str:
    key = source.strip().lower()
    explicit = str((metadata or {}).get("evidence_tier") or "").strip()
    if explicit:
        return explicit
    if key in {"artifact_reuse", "artifact", "cached_artifact"}:
        return "artifact"
    if key in {"mock", "mock_fallback"}:
        return "mock"
    if "fallback" in key:
        return "debug_fallback"
    return "exploratory_fresh"


def migrate_generated_report_v1(
    payload: dict[str, Any],
    *,
    legacy_reference_assisted: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("generated_report payload must be an object")

    def _string_field(key: str, default: str) -> str:
        value = payload.get(key)
        if value is None:
            return default
        if not isinstance(value, str):
            raise TypeError(f"generated_report.{key} must be a string")
        return value

    source = _string_field("source", "unknown")
    metadata_value = payload.get("metadata")
    if metadata_value is None:
        metadata: dict[str, Any] = {}
    elif not isinstance(metadata_value, dict):
        raise TypeError("generated_report.metadata must be an object")
    else:
        metadata = deepcopy(metadata_value)
    warnings = _string_list(payload.get("warnings"), "generated_report.warnings")
    assumed_reference_assisted = legacy_reference_assisted and source == "medharness_cli"
    if assumed_reference_assisted:
        metadata["legacy_reference_assisted_generation_assumed"] = True
        if "legacy_reference_assisted_generation_assumed" not in warnings:
            warnings.append("legacy_reference_assisted_generation_assumed")
    return GeneratedReportArtifact(
        model=_string_field("model", "unknown"),
        source=source,
        report=_string_field("report", ""),
        modality=_string_field("modality", "unknown"),
        evidence_tier=(
            "debug_fallback"
            if assumed_reference_assisted
            else infer_evidence_tier(source, metadata)
        ),
        warnings=warnings,
        metadata=metadata,
    ).model_dump(mode="json")


def migrate_case_evaluation_v1(payload: dict[str, Any], *, case_id: str) -> dict[str, Any]:
    source = deepcopy(payload)
    generated_reports = _dict_list(source.get("generated_reports"), "generated_reports")
    rankings = _dict_list(source.get("rankings"), "rankings")
    unknown = {key: value for key, value in source.items() if key not in _CASE_FIELDS}
    warnings = _string_list(source.get("migration_warnings"), "migration_warnings")
    if unknown:
        warnings.append("preserved_unknown_top_level_fields")
    if any(str(item.get("source") or "") == "medharness_cli" for item in generated_reports):
        warnings.append("legacy_reference_assisted_generation_assumed")
    human_evaluation, human_migrated = _migrate_evaluation(source.get("human_evaluation") or {})
    generated_evaluations, generated_migrated = _migrate_generated_evaluations(
        _dict_list(source.get("generated_evaluations"), "generated_evaluations")
    )
    pairwise_comparisons, pairwise_migrated = _migrate_pairwise_comparisons(
        _dict_list(source.get("pairwise_comparisons"), "pairwise_comparisons")
    )
    if human_migrated or generated_migrated or pairwise_migrated:
        warnings.append("legacy_nested_contracts_migrated")
    legacy_extensions = deepcopy(dict(source.get("legacy_extensions") or {}))
    legacy_extensions.update(unknown)
    artifact = CaseEvaluationArtifact(
        case_id=case_id,
        input=dict(source.get("input") or {}),
        human_evaluation=human_evaluation,
        generated_reports=[
            migrate_generated_report_v1(item, legacy_reference_assisted=True)
            for item in generated_reports
        ],
        generated_evaluations=generated_evaluations,
        rankings=rankings,
        pairwise_comparisons=pairwise_comparisons,
        migration_warnings=list(dict.fromkeys(warnings)),
        legacy_extensions=legacy_extensions,
    )
    return artifact.model_dump(mode="json")


def _migrate_generated_evaluations(rows: list[Any]) -> tuple[list[dict[str, Any]], bool]:
    migrated_rows: list[dict[str, Any]] = []
    migrated_any = False
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise TypeError(f"generated_evaluations[{index}] must be an object")
        migrated, changed = _migrate_evaluation(row)
        nested = migrated.get("evaluation")
        if isinstance(nested, dict):
            migrated["evaluation"], nested_changed = _migrate_evaluation(nested)
            changed = changed or nested_changed
        migrated_rows.append(migrated)
        migrated_any = migrated_any or changed
    return migrated_rows, migrated_any


def _dict_list(value: Any, label: str) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise TypeError(f"{label} must be a list of objects")
    return [deepcopy(item) for item in value]


def _migrate_pairwise_comparisons(rows: list[Any]) -> tuple[list[dict[str, Any]], bool]:
    migrated_rows: list[dict[str, Any]] = []
    migrated_any = False
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise TypeError(f"pairwise_comparisons[{index}] must be an object")
        migrated = deepcopy(row)
        comparison = migrated.get("comparison")
        if isinstance(comparison, dict):
            comparison = deepcopy(comparison)
            for field in ("graph_a", "graph_b"):
                graph = comparison.get(field)
                if isinstance(graph, dict):
                    comparison[field] = _migrate_finding_graph(graph)
                    migrated_any = True
            hazards = comparison.get("hazards")
            if isinstance(hazards, dict):
                comparison["hazards"] = _migrate_hazard_result(hazards)
                migrated_any = True
            migrated["comparison"] = comparison
        selected = migrated.get("selected_evaluation")
        if isinstance(selected, dict):
            migrated["selected_evaluation"], selected_changed = _migrate_evaluation(selected)
            migrated_any = migrated_any or selected_changed
        migrated_rows.append(migrated)
    return migrated_rows, migrated_any


def _migrate_evaluation(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    migrated = deepcopy(dict(payload))
    graph = migrated.get("finding_graph")
    if not isinstance(graph, dict):
        return migrated, False
    migrated["finding_graph"] = _migrate_finding_graph(graph)
    return migrated, True


def _migrate_finding_graph(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("finding_graph payload must be an object")
    for field in ("modality", "backend"):
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            raise TypeError(f"finding_graph.{field} must be a string")
    for field in ("metadata", "template_coverage"):
        value = payload.get(field)
        if value is not None and not isinstance(value, dict):
            raise TypeError(f"finding_graph.{field} must be an object")
    for field in ("missing", "warnings"):
        value = payload.get(field)
        if value not in (None, ""):
            _string_list(value, f"finding_graph.{field}")
    validation_error = ""
    try:
        return FindingGraph.model_validate(payload).model_dump(mode="json")
    except Exception as exc:
        validation_error = f"{type(exc).__name__}: {exc}"

    findings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(payload.get("findings") or [], start=1):
        if not isinstance(raw, dict):
            raise TypeError(f"finding_graph.findings[{index - 1}] must be an object")
        for field in ("finding_id", "id", "observation_text", "observation", "observation_code", "source_text", "text"):
            value = raw.get(field)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"finding_graph.findings[{index - 1}].{field} must be a string")
        finding_id = _unique_finding_id(
            (raw.get("finding_id") or raw.get("id") or f"f{index}"),
            seen_ids,
        )
        observation_value = (
            raw.get("observation_text")
            or raw.get("observation")
            or raw.get("observation_code")
            or raw.get("source_text")
            or raw.get("text")
        )
        observation_text = (observation_value or "unparsed_legacy_finding").strip()
        location_text = _optional_text(raw.get("location_text") or raw.get("location"))
        measurements, unparsed_measurement = _migrate_measurements(raw)
        attributes = deepcopy(dict(raw.get("attributes") or {}))
        legacy_fields = {
            key: deepcopy(value)
            for key, value in raw.items()
            if key not in _FINDING_FIELDS
        }
        if raw.get("extractor") is not None:
            legacy_fields["extractor"] = deepcopy(raw.get("extractor"))
        if unparsed_measurement is not None:
            legacy_fields["measurement"] = deepcopy(unparsed_measurement)
        if legacy_fields:
            attributes["legacy_fields"] = legacy_fields
        if validation_error:
            attributes["migration_metadata"] = {
                "v2_validation_failed": True,
                "v2_validation_error": validation_error[:500],
            }
        if not observation_value:
            attributes.setdefault("migration_metadata", {})["observation_unparsed"] = True
            attributes.setdefault("migration_warnings", []).append(
                "legacy_finding_missing_observation"
            )
        findings.append(
            {
                "finding_id": finding_id,
                "observation_code": _optional_text(
                    raw.get("observation_code") or raw.get("observation")
                ),
                "observation_text": observation_text,
                "anatomy_code": _optional_text(raw.get("anatomy_code")),
                "location_text": location_text,
                "laterality": _normalize_laterality(raw.get("laterality"), location_text),
                "certainty": _normalize_certainty(raw.get("certainty")),
                "severity": _optional_text(raw.get("severity")),
                "measurements": measurements,
                "source_span": _valid_source_span(raw.get("source_span")),
                "source_text": raw.get("source_text") or raw.get("text") or "",
                "extractor": _legacy_provenance(
                    role="finding_extractor",
                    model=str(payload.get("backend") or "legacy_finding_extractor"),
                ),
                "attributes": attributes,
            }
        )

    metadata = deepcopy(payload.get("metadata") or {})
    graph_legacy_fields = {
        key: deepcopy(value)
        for key, value in payload.items()
        if key not in _GRAPH_FIELDS
    }
    metadata.update(
        {
            "migrated_from_schema_version": str(payload.get("schema_version") or "1"),
            "migration_method": "legacy_contract_adapter",
        }
    )
    if graph_legacy_fields:
        metadata["legacy_fields"] = graph_legacy_fields
    graph = {
        "schema_version": "2.0",
        "artifact_type": "finding_graph",
        "modality": payload.get("modality") or "unknown",
        "backend": payload.get("backend") or "legacy_unknown",
        "findings": findings,
        "relations": [deepcopy(item) for item in payload.get("relations") or [] if isinstance(item, dict)],
        "missing": _string_list(payload.get("missing"), "finding_graph.missing"),
        "coverage": _bounded_float(payload.get("coverage"), default=0.0),
        "nodes": [deepcopy(item) for item in payload.get("nodes") or [] if isinstance(item, dict)],
        "template_coverage": deepcopy(payload.get("template_coverage") or {}),
        "warnings": _string_list(payload.get("warnings"), "finding_graph.warnings"),
        "metadata": metadata,
    }
    return FindingGraph.model_validate(graph).model_dump(mode="json")


def _migrate_hazard_result(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return HazardResult.model_validate(payload).model_dump(mode="json")
    except Exception:
        pass

    errors: list[dict[str, Any]] = []
    legacy_error_fields: list[dict[str, Any]] = []
    for index, raw in enumerate(payload.get("errors") or []):
        if not isinstance(raw, dict):
            raise TypeError(f"hazard_result.errors[{index}] must be an object")
        for field in ("error_type", "explanation", "recommended_action"):
            value = raw.get(field)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"hazard_result.errors[{index}].{field} must be a string")
        raw_abstain = raw.get("abstain")
        if raw_abstain is not None and not isinstance(raw_abstain, bool):
            raise TypeError(f"hazard_result.errors[{index}].abstain must be a boolean")
        raw_evidence_ids = raw.get("evidence_ids")
        if raw_evidence_ids not in (None, ""):
            if isinstance(raw_evidence_ids, str):
                pass
            elif not isinstance(raw_evidence_ids, (list, tuple, set)) or any(
                not isinstance(item, str) for item in raw_evidence_ids
            ):
                raise TypeError(f"hazard_result.errors[{index}].evidence_ids must be strings")
        evidence_ids = _string_values(raw_evidence_ids)
        if not evidence_ids:
            evidence_ids = _legacy_evidence_ids(raw)
        error = {
            "error_type": raw.get("error_type") or "legacy_error",
            "hazard_level": _bounded_int(raw.get("hazard_level"), default=3, lower=1, upper=5),
            "explanation": raw.get("explanation") or "Legacy hazard judgement without explanation.",
            "recommended_action": (
                raw.get("recommended_action")
                or "Review this discrepancy against the source study and adjudicate before use."
            ),
            "confidence": _optional_confidence(raw.get("confidence")),
            "evidence_ids": list(dict.fromkeys(evidence_ids)),
            "abstain": raw.get("abstain", False),
        }
        for field in (
            "finding",
            "candidate",
            "reference",
            "a",
            "b",
            "observation",
            "location",
            "severity",
            "measurement",
            "certainty",
            "text",
        ):
            value = raw.get(field)
            if value is not None:
                error[field] = deepcopy(value)
        errors.append(error)
        extras = {
            key: deepcopy(value)
            for key, value in raw.items()
            if key not in _HAZARD_ERROR_FIELDS
        }
        if extras:
            legacy_error_fields.append({"error_index": index, "fields": extras})

    metadata = deepcopy(dict(payload.get("metadata") or {}))
    metadata.update(
        {
            "migrated_from_schema_version": str(payload.get("schema_version") or "1"),
            "migration_method": "legacy_contract_adapter",
        }
    )
    if payload.get("provenance") is not None:
        metadata["legacy_provenance"] = deepcopy(payload.get("provenance"))
    if legacy_error_fields:
        metadata["legacy_error_fields"] = legacy_error_fields
    legacy_fields = {
        key: deepcopy(value)
        for key, value in payload.items()
        if key not in _HAZARD_RESULT_FIELDS
    }
    if legacy_fields:
        existing_legacy_fields = metadata.get("legacy_fields")
        if isinstance(existing_legacy_fields, dict):
            legacy_fields = {**deepcopy(existing_legacy_fields), **legacy_fields}
        metadata["legacy_fields"] = legacy_fields
    result = {
        "schema_version": "2.0",
        "artifact_type": "hazard_result",
        "errors": errors,
        "provenance": _legacy_provenance(role="hazard_primary", model="legacy_tool4"),
        "metadata": metadata,
    }
    return HazardResult.model_validate(result).model_dump(mode="json")


def _migrate_measurements(raw: dict[str, Any]) -> tuple[list[dict[str, Any]], Any]:
    source = raw.get("measurements")
    if isinstance(source, list):
        migrated: list[dict[str, Any]] = []
        unparsed: list[Any] = []
        for item in source:
            parsed = _parse_measurement(item)
            if parsed is None:
                unparsed.append(deepcopy(item))
            else:
                migrated.append(parsed)
        return migrated, unparsed or None
    if source not in (None, ""):
        parsed = _parse_measurement(source)
        return ([parsed], None) if parsed is not None else ([], source)
    value = raw.get("measurement")
    if value in (None, ""):
        return [], None
    parsed = _parse_measurement(value)
    return ([parsed], None) if parsed is not None else ([], value)


def _parse_measurement(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        number = value.get("value")
        unit = str(value.get("unit") or "").lower()
        if isinstance(number, (int, float)) and not isinstance(number, bool) and unit in {"mm", "cm"}:
            normalized = float(number) * (10.0 if unit == "cm" else 1.0)
            return {"value": float(number), "unit": unit, "normalized_mm": normalized}
        return None
    match = _MEASUREMENT_PATTERN.search(str(value))
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2).lower()
    return {
        "value": number,
        "unit": unit,
        "normalized_mm": number * (10.0 if unit == "cm" else 1.0),
    }


def _legacy_evidence_ids(raw: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for field in ("finding", "candidate", "reference", "a", "b"):
        value = raw.get(field)
        if isinstance(value, dict):
            finding_id = str(value.get("finding_id") or value.get("id") or "")
            if finding_id:
                ids.append(finding_id)
    return list(dict.fromkeys(ids))


def _string_values(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return [str(item) for item in values if str(item)]


def _string_list(value: Any, label: str) -> list[str]:
    """Normalize legacy warning lists without splitting scalar strings."""
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, (list, tuple, set)) or any(not isinstance(item, str) for item in value):
        raise TypeError(f"{label} must be a string or a list of strings")
    return list(value)


def _legacy_provenance(*, role: str, model: str) -> dict[str, Any]:
    return {
        "implementation_type": "legacy_migration",
        "provider": "local",
        "model": model,
        "version": "1",
        "role": role,
        "prompt_version": "legacy_unknown",
        "fallback_used": True,
        "metadata": {"migration_only": True},
    }


def _unique_finding_id(value: str, seen: set[str]) -> str:
    base = value.strip() or "finding"
    candidate = base
    suffix = 2
    while candidate in seen:
        candidate = f"{base}-{suffix}"
        suffix += 1
    seen.add(candidate)
    return candidate


def _normalize_laterality(value: Any, location: str | None) -> str:
    explicit = str(value or "").strip().lower()
    if explicit in {"left", "right", "bilateral", "midline", "unknown"}:
        return explicit
    text = f"{explicit} {location or ''}".lower()
    if "bilateral" in text or "both" in text or "双" in text:
        return "bilateral"
    if "left" in text or "左" in text:
        return "left"
    if "right" in text or "右" in text:
        return "right"
    if "midline" in text or "中线" in text:
        return "midline"
    return "unknown"


def _normalize_certainty(value: Any) -> str:
    text = str(value or "present").strip().lower()
    if text in {"absent", "negative", "negated", "no", "none"}:
        return "absent"
    if text in {"uncertain", "possible", "probable", "equivocal", "indeterminate"}:
        return "uncertain"
    return "present"


def _valid_source_span(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    start = value.get("start")
    end = value.get("end")
    if not isinstance(start, int) or isinstance(start, bool):
        return None
    if not isinstance(end, int) or isinstance(end, bool) or start < 0 or end < start:
        return None
    return {"start": start, "end": end}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_confidence(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return max(0.0, min(1.0, float(value)))


def _bounded_float(value: Any, *, default: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return default
    return max(0.0, min(1.0, float(value)))


def _bounded_int(value: Any, *, default: int, lower: int, upper: int) -> int:
    parsed = value if isinstance(value, int) and not isinstance(value, bool) else default
    return max(lower, min(upper, parsed))


def migrate_run_case_artifacts(source_run_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    source_root = Path(source_run_dir)
    source = source_root / "workflow2_cases"
    output = Path(output_dir)
    if source_root.resolve() == output.resolve():
        raise ValueError("Migration output_dir must differ from source_run_dir")
    cases_dir = output / "workflow2_cases"
    compatibility_dir = output / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    compatibility_dir.mkdir(parents=True, exist_ok=True)
    errors = []
    warnings: Counter[str] = Counter()
    tiers: Counter[str] = Counter()
    migrated_count = 0
    source_case_paths = sorted(source.glob("*.json")) if source.is_dir() else []
    if not source_root.is_dir():
        errors.append({"case_id": "", "error": "source_run_dir_not_found"})
    elif not source.is_dir() or not source_case_paths:
        errors.append({"case_id": "", "error": "no_cases_discovered"})
    for path in source_case_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            migrated = migrate_case_evaluation_v1(payload, case_id=path.stem)
            artifact = CaseEvaluationArtifact.model_validate(migrated)
            for warning in artifact.migration_warnings:
                warnings[warning] += 1
            for report in artifact.generated_reports:
                tiers[report.evidence_tier] += 1
            migrated_path = cases_dir / path.name
            migrated_path.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
            compatibility_path = compatibility_dir / path.name
            if compatibility_path.exists():
                compatibility_path.unlink()
            try:
                os.link(migrated_path, compatibility_path)
            except OSError:
                shutil.copy2(migrated_path, compatibility_path)
            migrated_count += 1
        except Exception as exc:
            errors.append({"case_id": path.stem, "error": f"{type(exc).__name__}: {exc}"})
    copied_support_files: list[str] = []
    for filename in ("manifest.jsonl", "summary.json", "workflow2.json", "workflow3.json"):
        source_path = source_root / filename
        if not source_path.exists():
            continue
        shutil.copy2(source_path, output / filename)
        copied_support_files.append(filename)
    report = {
        "schema_version": "2.0",
        "artifact_type": "case_artifact_migration_report",
        "source_run_dir": str(source_root),
        "source_case_count": len(source_case_paths),
        "case_count": migrated_count,
        "error_count": len(errors),
        "errors": errors,
        "migration_warning_counts": dict(sorted(warnings.items())),
        "evidence_tier_counts": dict(sorted(tiers.items())),
        "case_artifact_dir": "workflow2_cases",
        "compatibility_case_artifact_dir": "cases",
        "copied_support_files": copied_support_files,
    }
    (output / "migration_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
