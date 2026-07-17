from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from medharness2.contracts import (
    AlignmentAuditArtifact,
    CaseEvaluationArtifact,
    FindingGraph,
    GeneratedReportArtifact,
    HazardResult,
    HazardReviewArtifact,
    StructureAuditArtifact,
    Workflow2Aggregate,
    Workflow3Aggregate,
)
from medharness2.ocr import REAL_OCR_PROVIDERS


def validate_sample_run(
    output_dir: str | Path,
    *,
    expected_cases: int | None = None,
    require_real_ocr: bool = False,
    require_workflows: bool = True,
) -> dict[str, Any]:
    root = Path(output_dir)
    errors: list[str] = []
    warnings: list[str] = []
    summary_path = root / "summary.json"
    summary = _read_json(summary_path, errors, "summary") if summary_path.exists() else {}
    if not summary_path.exists():
        warnings.append("missing_summary_json")
    manifest_rows = _read_manifest(root / "manifest.jsonl", errors)
    if not summary and manifest_rows:
        summary = _summary_from_manifest(manifest_rows)
    workflow2_path = root / "workflow2.json"
    workflow3_path = root / "workflow3.json"
    workflow2 = _read_json(workflow2_path, errors, "workflow2") if require_workflows else {}
    workflow3 = _read_json(workflow3_path, errors, "workflow3") if require_workflows else {}
    if require_workflows and workflow2_path.exists():
        _validate_aggregate_contract(Workflow2Aggregate, workflow2, "workflow2_aggregate", errors)
    if require_workflows and workflow3_path.exists():
        _validate_aggregate_contract(Workflow3Aggregate, workflow3, "workflow3_aggregate", errors)

    case_count = _count_or_error(
        _first_present(summary.get("case_count"), len(manifest_rows), 0),
        "case_count",
        errors,
    )
    if expected_cases is not None and case_count != expected_cases:
        errors.append(f"case_count_mismatch:{case_count}!={expected_cases}")
    if manifest_rows and case_count != len(manifest_rows):
        errors.append(f"manifest_count_mismatch:{len(manifest_rows)}!={case_count}")

    raw_summary_warning_counts = summary.get("warning_counts")
    if raw_summary_warning_counts is None:
        summary_warning_counts: dict[str, Any] = {}
    elif isinstance(raw_summary_warning_counts, dict):
        summary_warning_counts = dict(raw_summary_warning_counts)
    else:
        summary_warning_counts = {}
        errors.append("invalid_warning_counts:object_required")
    manifest_warning_counts = _manifest_warning_counts(manifest_rows)
    warning_count_errors: list[str] = []
    warning_counts = _merge_counts(
        summary_warning_counts,
        manifest_warning_counts,
        errors=warning_count_errors,
    )
    errors.extend(warning_count_errors)
    mock_ocr_count = _count_or_error(warning_counts.get("mock_ocr_used", 0), "mock_ocr_used", errors)
    real_ocr_count = 0
    unknown_ocr_count = 0
    if require_real_ocr and mock_ocr_count:
        errors.append("mock_ocr_used")
    if require_real_ocr and _count_or_error(
        warning_counts.get("real_ocr_required_but_provider_is_mock", 0),
        "real_ocr_required_but_provider_is_mock",
        errors,
    ):
        errors.append("real_ocr_required_but_provider_is_mock")
    if require_real_ocr:
        real_ocr_count, unknown_ocr_count, provider_mock_count, missing_ocr_text_count = _count_real_ocr_provenance(root, manifest_rows)
        if provider_mock_count:
            mock_ocr_count = max(mock_ocr_count, provider_mock_count)
            errors.append("mock_ocr_used")
        if unknown_ocr_count:
            errors.append("ocr_provenance_unknown")
        if missing_ocr_text_count:
            errors.append("ocr_text_missing")

    failed_case_count = _count_or_error(
        _first_present(workflow2.get("failed_case_count") if workflow2 else None, 0),
        "failed_case_count",
        errors,
    )
    if failed_case_count:
        errors.append(f"workflow2_failed_cases:{failed_case_count}")
    workflow2_case_count = _count_or_error(
        _first_present(workflow2.get("case_count") if workflow2 else None, 0),
        "workflow2.case_count",
        errors,
    )
    if require_workflows and workflow2 and workflow2_case_count == 0 and failed_case_count == 0:
        errors.append("no_cases_discovered")
    if workflow2 and workflow2_case_count + failed_case_count != case_count:
        errors.append("workflow2_case_count_mismatch")
    workflow3_case_count = _count_or_error(
        _first_present(workflow3.get("case_count") if workflow3 else None, 0),
        "workflow3.case_count",
        errors,
    )
    if workflow3 and workflow3_case_count != workflow2_case_count:
        errors.append("workflow3_case_count_mismatch")

    artifact_contracts = _validate_case_artifact_contracts(root, errors)
    if artifact_contracts["checked"] and workflow2:
        workflow_case_count = workflow2_case_count
        if artifact_contracts["case_file_count"] != workflow_case_count:
            errors.append(
                f"case_artifact_count_mismatch:{artifact_contracts['case_file_count']}!={workflow_case_count}"
            )

    if mock_ocr_count and not require_real_ocr:
        warnings.append("mock_ocr_used")

    return {
        "passed": not errors,
        "output_dir": str(root),
        "case_count": case_count,
        "manifest_count": len(manifest_rows),
        "expected_cases": expected_cases,
        "mock_ocr_count": mock_ocr_count,
        "real_ocr_count": real_ocr_count,
        "unknown_ocr_count": unknown_ocr_count,
        "missing_ocr_text_count": missing_ocr_text_count if require_real_ocr else 0,
        "failed_case_count": failed_case_count,
        "require_real_ocr": require_real_ocr,
        "require_workflows": require_workflows,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "summary": summary,
        "warning_counts": dict(sorted(warning_counts.items())),
        "artifact_contracts": artifact_contracts,
    }


def _validate_case_artifact_contracts(root: Path, errors: list[str]) -> dict[str, Any]:
    paths = _case_artifact_paths(root)
    audit_contracts = {
        "alignment_audit": AlignmentAuditArtifact,
        "hazard_review": HazardReviewArtifact,
        "structure_audit": StructureAuditArtifact,
    }
    audit_counts = {field: 0 for field in audit_contracts}
    if not paths:
        return {
            "checked": False,
            "case_file_count": 0,
            "valid_count": 0,
            "invalid_count": 0,
            "finding_graph_count": 0,
            "generated_report_count": 0,
            "hazard_result_count": 0,
            **{f"{field}_count": count for field, count in audit_counts.items()},
        }

    valid_count = 0
    invalid_count = 0
    finding_graph_count = 0
    generated_report_count = 0
    hazard_result_count = 0
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            invalid_count += 1
            errors.append(f"invalid_case_artifact_json:{path.name}:{type(exc).__name__}")
            continue
        if not isinstance(payload, dict):
            invalid_count += 1
            errors.append(f"invalid_case_artifact_json:{path.name}:not_object")
            continue

        file_errors: list[str] = []
        _validate_contract(CaseEvaluationArtifact, payload, "case", file_errors)

        graph_payloads: list[dict[str, Any]] = []
        human_graph = _object_or_empty(payload.get("human_evaluation")).get(
            "finding_graph"
        )
        if isinstance(human_graph, dict):
            graph_payloads.append(human_graph)
        for row_index, row in enumerate(payload.get("generated_evaluations") or []):
            if not isinstance(row, dict):
                continue
            nested_evaluation = row.get("evaluation")
            if nested_evaluation is not None and not isinstance(
                nested_evaluation, dict
            ):
                file_errors.append(
                    f"generated_evaluations[{row_index}].evaluation:not_object"
                )
            graph = row.get("finding_graph") or _object_or_empty(
                nested_evaluation
            ).get("finding_graph")
            if isinstance(graph, dict):
                graph_payloads.append(graph)
        hazard_payloads: list[dict[str, Any]] = []
        for row in payload.get("pairwise_comparisons") or []:
            if not isinstance(row, dict):
                continue
            comparison = row.get("comparison") or {}
            if not isinstance(comparison, dict):
                continue
            for key in ("graph_a", "graph_b"):
                graph = comparison.get(key)
                if isinstance(graph, dict):
                    graph_payloads.append(graph)
            hazard = comparison.get("hazards")
            if isinstance(hazard, dict):
                hazard_payloads.append(hazard)
            for field, model in audit_contracts.items():
                if field not in comparison or comparison[field] is None:
                    continue
                audit_counts[field] += 1
                audit = comparison[field]
                if not isinstance(audit, dict):
                    file_errors.append(f"{field}:not_object")
                    continue
                _validate_contract(model, audit, field, file_errors)
                _validate_audit_hash_binding(field, audit, comparison, file_errors)

        for graph in graph_payloads:
            finding_graph_count += 1
            _validate_contract(FindingGraph, graph, "finding_graph", file_errors)
        for report in payload.get("generated_reports") or []:
            if isinstance(report, dict):
                generated_report_count += 1
                _validate_contract(GeneratedReportArtifact, report, "generated_report", file_errors)
        for hazard in hazard_payloads:
            hazard_result_count += 1
            _validate_contract(HazardResult, hazard, "hazard_result", file_errors)

        if file_errors:
            invalid_count += 1
            errors.extend(
                f"invalid_case_artifact_contract:{path.name}:{label}"
                for label in dict.fromkeys(file_errors)
            )
        else:
            valid_count += 1
    return {
        "checked": True,
        "case_file_count": len(paths),
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "finding_graph_count": finding_graph_count,
        "generated_report_count": generated_report_count,
        "hazard_result_count": hazard_result_count,
        **{f"{field}_count": count for field, count in audit_counts.items()},
    }


def _case_artifact_paths(root: Path) -> list[Path]:
    for directory_name in ("workflow2_cases", "cases"):
        case_dir = root / directory_name
        if not case_dir.exists():
            continue
        paths = sorted(case_dir.glob("*.json"))
        if paths:
            return paths
    return []


def _object_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _validate_contract(model: Any, payload: dict[str, Any], label: str, errors: list[str]) -> None:
    try:
        model.model_validate(payload)
    except Exception as exc:
        errors.append(f"{label}:{type(exc).__name__}")


def _first_present(*values: Any) -> Any:
    """Return first non-None value, retaining explicit zeroes."""
    for value in values:
        if value is not None:
            return value
    return 0


def _count_or_error(value: Any, label: str, errors: list[str]) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        errors.append(f"invalid_{label}:nonnegative_integer_required")
        return 0
    return value


def _validate_aggregate_contract(model: Any, payload: dict[str, Any], label: str, errors: list[str]) -> None:
    """Reject an empty existing aggregate instead of treating it as defaults."""
    if not payload:
        errors.append(f"{label}:ValidationError")
        return
    _validate_contract(model, payload, label, errors)


def _validate_audit_hash_binding(
    audit_field: str,
    audit: dict[str, Any],
    comparison: dict[str, Any],
    errors: list[str],
) -> None:
    bindings = {
        "alignment_audit": ("alignment", "alignment_sha256"),
        "hazard_review": ("hazards", "primary_result_sha256"),
        "structure_audit": ("structure_diff", "structure_diff_sha256"),
    }
    primary_field, hash_field = bindings[audit_field]
    primary = comparison.get(primary_field)
    if not isinstance(primary, dict):
        errors.append(f"{audit_field}:missing_primary")
        return
    canonical_primary = primary
    if audit_field == "hazard_review":
        try:
            canonical_primary = HazardResult.model_validate(primary).model_dump(mode="json")
        except Exception:
            pass
    if str(audit.get(hash_field) or "") != _json_sha256(canonical_primary):
        errors.append(f"{audit_field}:hash_mismatch")


def _json_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path, errors: list[str], label: str) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"missing_{label}_json")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"invalid_{label}_json:{type(exc).__name__}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"invalid_{label}_json:not_object")
        return {}
    return data


def _read_manifest(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    if not path.exists():
        errors.append("missing_manifest_jsonl")
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    errors.append(f"invalid_manifest_jsonl:row_{line_no}:invalid_json")
                    continue
                if not isinstance(row, dict):
                    errors.append(f"invalid_manifest_jsonl:row_{line_no}:not_object")
                    continue
                _validate_manifest_row_types(row, line_no, errors)
                rows.append(row)
    except Exception as exc:
        errors.append(f"invalid_manifest_jsonl:{type(exc).__name__}")
    return rows


def _validate_manifest_row_types(
    row: dict[str, Any], line_no: int, errors: list[str]
) -> None:
    """Reject malformed external manifest fields before aggregation."""
    for field in ("case_id", "reader", "modality", "body_part", "report_text", "report_pdf"):
        if field in row and row[field] is not None and not isinstance(row[field], str):
            errors.append(f"invalid_manifest_jsonl:row_{line_no}:{field}_must_be_string")
    if "warnings" in row:
        warnings = row["warnings"]
        if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
            errors.append(f"invalid_manifest_jsonl:row_{line_no}:warnings_must_be_string_list")
    if "image_paths" in row:
        image_paths = row["image_paths"]
        if not isinstance(image_paths, list) or any(not isinstance(item, str) for item in image_paths):
            errors.append(f"invalid_manifest_jsonl:row_{line_no}:image_paths_must_be_string_list")
    for field in ("derived_assets", "metadata"):
        if field in row and row[field] is not None and not isinstance(row[field], dict):
            errors.append(f"invalid_manifest_jsonl:row_{line_no}:{field}_must_be_object")


def _manifest_warning_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        raw_warnings = row.get("warnings")
        if not isinstance(raw_warnings, list):
            continue
        for warning in raw_warnings:
            if isinstance(warning, str):
                counts[warning] += 1
    return dict(counts)


def _summary_from_manifest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    modality_counts: Counter[str] = Counter()
    body_part_counts: Counter[str] = Counter()
    cases_with_report_text = 0
    cases_with_primary_image = 0
    cases_with_volume = 0
    for row in rows:
        modality = row.get("modality") if isinstance(row.get("modality"), str) else ""
        body_part = row.get("body_part") if isinstance(row.get("body_part"), str) else ""
        if modality:
            modality_counts[modality] += 1
        if body_part:
            body_part_counts[body_part] += 1
        if row.get("report_text"):
            cases_with_report_text += 1
        if row.get("primary_image") or row.get("image_paths"):
            cases_with_primary_image += 1
        if row.get("volume_path") or (row.get("derived_assets") or {}).get("volume_path"):
            cases_with_volume += 1
    return {
        "case_count": len(rows),
        "modality_counts": dict(sorted(modality_counts.items())),
        "body_part_counts": dict(sorted(body_part_counts.items())),
        "warning_counts": _manifest_warning_counts(rows),
        "cases_with_report_text": cases_with_report_text,
        "cases_with_primary_image": cases_with_primary_image,
        "cases_with_volume": cases_with_volume,
    }


def _merge_counts(*counts: dict[str, Any], errors: list[str] | None = None) -> dict[str, int]:
    merged: dict[str, int] = {}
    for count_map in counts:
        for key, value in count_map.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                if errors is not None:
                    errors.append(f"invalid_warning_count:{key}:nonnegative_integer_required")
                continue
            count = value
            merged[str(key)] = max(merged.get(str(key), 0), count)
    return merged


def _count_real_ocr_provenance(root: Path, rows: list[dict[str, Any]]) -> tuple[int, int, int, int]:
    real_count = 0
    unknown_count = 0
    mock_count = 0
    missing_text_count = 0
    for row in rows:
        case_id = row.get("case_id") if isinstance(row.get("case_id"), str) else ""
        report_text = row.get("report_text") if isinstance(row.get("report_text"), str) else ""
        report_pdf = row.get("report_pdf") if isinstance(row.get("report_pdf"), str) else ""
        report_pdf = report_pdf.strip()
        if not report_text:
            if report_pdf:
                missing_text_count += 1
            continue
        raw_warnings = row.get("warnings")
        row_warnings = set(raw_warnings) if isinstance(raw_warnings, list) and all(
            isinstance(warning, str) for warning in raw_warnings
        ) else set()
        if "mock_ocr_used" in row_warnings or "real_ocr_required_but_provider_is_mock" in row_warnings:
            mock_count += 1
            continue
        meta = _read_ocr_meta(root, report_text)
        text_path = _resolve_path(root, report_text)
        if not meta:
            unknown_count += 1
            continue
        # A manifest with a source PDF is a strict, reproducible OCR artifact:
        # require non-empty text and bind the sidecar to this case and exact
        # source bytes.  Text-only legacy manifests keep their historical
        # sidecar compatibility because no source hash can be recomputed.
        if report_pdf:
            if not text_path.is_file() or not text_path.read_text(encoding="utf-8").strip():
                unknown_count += 1
                continue
            pdf_path = _resolve_path(root, report_pdf)
            if not pdf_path.is_file() or str(meta.get("case_id") or "") != case_id:
                unknown_count += 1
                continue
            try:
                source_hash = _sha256_file(pdf_path)
            except OSError:
                unknown_count += 1
                continue
            if str(meta.get("source_pdf_sha256") or "") != source_hash:
                unknown_count += 1
                continue
            if str(meta.get("method") or "").lower() == "vlm_ocr" and _ocr_pages_have_quality_blockers(meta):
                unknown_count += 1
                continue
        method = str(meta.get("method") or "").lower()
        provider = str(meta.get("provider") or "").lower()
        warnings = {str(warning) for warning in meta.get("warnings") or []}
        if "empty_vlm_ocr_result" in warnings or "ocr_empty_page_response" in " ".join(warnings):
            unknown_count += 1
            continue
        if method == "pdf_text_layer" or provider == "local_pdf_text":
            real_count += 1
        elif method == "vlm_ocr" and provider in REAL_OCR_PROVIDERS:
            real_count += 1
        elif provider == "mock":
            mock_count += 1
        else:
            unknown_count += 1
    return real_count, unknown_count, mock_count, missing_text_count


def _ocr_pages_have_quality_blockers(meta: dict[str, Any]) -> bool:
    warnings = {str(warning) for warning in meta.get("warnings") or []}
    if any(
        warning == "ocr_possible_truncation"
        or warning.startswith("ocr_possible_truncation:")
        or warning == "empty_vlm_ocr_result"
        or warning.startswith("ocr_empty_page_response:")
        for warning in warnings
    ):
        return True
    pages = meta.get("pages")
    if not isinstance(pages, list):
        return True
    for page in pages:
        if not isinstance(page, dict):
            return True
        if not page.get("skipped"):
            char_count = page.get("char_count")
            if (
                not isinstance(char_count, int)
                or isinstance(char_count, bool)
                or char_count <= 0
            ):
                return True
    source_count = meta.get("source_page_count")
    retained_count = meta.get("retained_page_count", meta.get("page_count"))
    if source_count is not None and retained_count is not None:
        try:
            if (
                not isinstance(source_count, int)
                or isinstance(source_count, bool)
                or not isinstance(retained_count, int)
                or isinstance(retained_count, bool)
                or source_count < 0
                or retained_count < 0
                or retained_count > source_count
                or retained_count != sum(1 for page in pages if not page.get("skipped"))
            ):
                return True
        except (TypeError, ValueError):
            return True
    return False


def _read_ocr_meta(root: Path, report_text: str) -> dict[str, Any]:
    text_path = _resolve_path(root, report_text)
    meta_path = text_path.with_suffix(".ocr.json")
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _resolve_path(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    if path.exists():
        return path
    return root / path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
