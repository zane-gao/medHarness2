from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


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
    summary = _read_json(root / "summary.json", errors, "summary")
    manifest_rows = _read_manifest(root / "manifest.jsonl", errors)
    workflow2 = _read_json(root / "workflow2.json", errors, "workflow2") if require_workflows else {}
    workflow3 = _read_json(root / "workflow3.json", errors, "workflow3") if require_workflows else {}

    case_count = int(summary.get("case_count") or len(manifest_rows) or 0)
    if expected_cases is not None and case_count != expected_cases:
        errors.append(f"case_count_mismatch:{case_count}!={expected_cases}")
    if manifest_rows and case_count != len(manifest_rows):
        errors.append(f"manifest_count_mismatch:{len(manifest_rows)}!={case_count}")

    summary_warning_counts = dict(summary.get("warning_counts") or {})
    manifest_warning_counts = _manifest_warning_counts(manifest_rows)
    warning_counts = _merge_counts(summary_warning_counts, manifest_warning_counts)
    mock_ocr_count = int(warning_counts.get("mock_ocr_used", 0))
    real_ocr_count = 0
    unknown_ocr_count = 0
    if require_real_ocr and mock_ocr_count:
        errors.append("mock_ocr_used")
    if require_real_ocr and int(warning_counts.get("real_ocr_required_but_provider_is_mock", 0)):
        errors.append("real_ocr_required_but_provider_is_mock")
    if require_real_ocr:
        real_ocr_count, unknown_ocr_count, provider_mock_count = _count_real_ocr_provenance(root, manifest_rows)
        if provider_mock_count:
            mock_ocr_count = max(mock_ocr_count, provider_mock_count)
            errors.append("mock_ocr_used")
        if unknown_ocr_count:
            errors.append("ocr_provenance_unknown")

    failed_case_count = int(workflow2.get("failed_case_count", 0) or 0) if workflow2 else 0
    if failed_case_count:
        errors.append(f"workflow2_failed_cases:{failed_case_count}")
    if workflow2 and int(workflow2.get("case_count", 0) or 0) + failed_case_count != case_count:
        errors.append("workflow2_case_count_mismatch")
    if workflow3 and int(workflow3.get("case_count", 0) or 0) != int(workflow2.get("case_count", workflow3.get("case_count", 0)) or 0):
        errors.append("workflow3_case_count_mismatch")

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
        "failed_case_count": failed_case_count,
        "require_real_ocr": require_real_ocr,
        "require_workflows": require_workflows,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "summary": summary,
        "warning_counts": dict(sorted(warning_counts.items())),
    }


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
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
    except Exception as exc:
        errors.append(f"invalid_manifest_jsonl:{type(exc).__name__}")
    return rows


def _manifest_warning_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        for warning in row.get("warnings") or []:
            counts[str(warning)] += 1
    return dict(counts)


def _merge_counts(*counts: dict[str, Any]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for count_map in counts:
        for key, value in count_map.items():
            try:
                count = int(value)
            except (TypeError, ValueError):
                continue
            merged[str(key)] = max(merged.get(str(key), 0), count)
    return merged


def _count_real_ocr_provenance(root: Path, rows: list[dict[str, Any]]) -> tuple[int, int, int]:
    real_count = 0
    unknown_count = 0
    mock_count = 0
    for row in rows:
        report_text = str(row.get("report_text") or "")
        if not report_text:
            continue
        row_warnings = {str(warning) for warning in row.get("warnings") or []}
        if "mock_ocr_used" in row_warnings or "real_ocr_required_but_provider_is_mock" in row_warnings:
            mock_count += 1
            continue
        meta = _read_ocr_meta(root, report_text)
        if not meta:
            unknown_count += 1
            continue
        method = str(meta.get("method") or "").lower()
        provider = str(meta.get("provider") or "").lower()
        if method == "pdf_text_layer" or provider == "local_pdf_text":
            real_count += 1
        elif method == "vlm_ocr" and provider and provider != "mock":
            real_count += 1
        elif provider == "mock":
            mock_count += 1
        else:
            unknown_count += 1
    return real_count, unknown_count, mock_count


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
