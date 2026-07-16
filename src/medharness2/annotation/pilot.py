from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from medharness2.annotation.models import AnnotationCase, CandidateReportForAnnotation, ReaderAnnotation
from medharness2.privacy import ExternalPayloadPolicy
from medharness2.utils.io import read_json


def build_pilot_annotation_package(
    run_dir: str | Path,
    output_dir: str | Path,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be positive")
    root = Path(run_dir)
    output = Path(output_dir)
    cases_dir = output / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    policy = ExternalPayloadPolicy()
    selected = _stratified_cases(_load_case_payloads(root), limit=limit)
    manifest_rows = []
    for index, (source_case_id, payload) in enumerate(selected, start=1):
        pilot_case_id = f"pilot-{index:03d}"
        input_payload = dict(payload.get("input") or {})
        reference_text = _reference_report(input_payload, payload, policy)
        candidates = [
            CandidateReportForAnnotation(
                candidate_id=f"candidate-{candidate_index:02d}",
                blinded_model_id=f"model-{candidate_index:02d}",
                report_text=policy.deidentify_clinical_text(str(item.get("report") or "")),
            )
            for candidate_index, item in enumerate(payload.get("generated_reports") or [], start=1)
        ]
        annotation_case = AnnotationCase(
            pilot_case_id=pilot_case_id,
            source_case_sha256=hashlib.sha256(source_case_id.encode("utf-8")).hexdigest(),
            modality=str(input_payload.get("modality") or "unknown"),
            body_part=str(input_payload.get("body_part") or "unknown"),
            reference_report=reference_text,
            candidate_reports=candidates,
            annotations={
                slot: ReaderAnnotation(reader_slot=slot)
                for slot in ("reader_a", "reader_b", "adjudication")
            },
        )
        filename = f"{pilot_case_id}.json"
        raw = annotation_case.model_dump_json(indent=2)
        scan = policy.scan(raw)
        if not scan.allowed:
            categories = ",".join(sorted({finding.category for finding in scan.findings}))
            raise ValueError(f"Annotation case failed privacy scan: {pilot_case_id}: {categories}")
        (cases_dir / filename).write_text(raw + "\n", encoding="utf-8")
        manifest_rows.append(
            {
                "pilot_case_id": pilot_case_id,
                "modality": annotation_case.modality,
                "body_part": annotation_case.body_part,
                "candidate_count": len(candidates),
                "annotation_path": f"cases/{filename}",
                "status": "not_started",
            }
        )
    (output / "manifest.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in manifest_rows),
        encoding="utf-8",
    )
    (output / "annotation.schema.json").write_text(
        json.dumps(AnnotationCase.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(_package_readme(len(manifest_rows)), encoding="utf-8")
    return {
        "schema_version": "2.0",
        "case_count": len(manifest_rows),
        "manifest": str(output / "manifest.jsonl"),
        "output_dir": str(output),
    }


def validate_pilot_annotation_package(package_dir: str | Path) -> dict[str, Any]:
    """Validate package/file/reader state without upgrading incomplete labels."""
    root = Path(package_dir)
    manifest_path = root / "manifest.jsonl"
    errors: list[str] = []
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    if not manifest_path.exists():
        return {"status": "blocked", "case_count": 0, "complete_case_count": 0, "errors": ["missing_manifest"]}
    for index, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"manifest:row_{index}:invalid_json")
            continue
        if not isinstance(row, dict):
            errors.append(f"manifest:row_{index}:not_an_object")
            continue
        rows.append(row)

    complete = 0
    in_progress = 0
    for row in rows:
        pilot_case_id = str(row.get("pilot_case_id") or "")
        relative = str(row.get("annotation_path") or "")
        if not pilot_case_id or not relative:
            errors.append(f"manifest:{pilot_case_id or 'unknown'}:missing_identity")
            continue
        case_path = root / relative
        if not case_path.exists():
            errors.append(f"case:{pilot_case_id}:missing_file")
            continue
        try:
            case = AnnotationCase.model_validate_json(case_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"case:{pilot_case_id}:invalid_contract:{type(exc).__name__}")
            continue
        if case.pilot_case_id != pilot_case_id:
            errors.append(f"case:{pilot_case_id}:id_mismatch")
        if case.modality != str(row.get("modality") or "unknown"):
            errors.append(f"case:{pilot_case_id}:modality_mismatch")
        if case.body_part != str(row.get("body_part") or "unknown"):
            errors.append(f"case:{pilot_case_id}:body_part_mismatch")
        statuses = {slot: case.annotations[slot].status for slot in ("reader_a", "reader_b", "adjudication")}
        if statuses["adjudication"] == "complete" and not (
            statuses["reader_a"] == "complete" and statuses["reader_b"] == "complete"
        ):
            errors.append(f"case:{pilot_case_id}:adjudication_before_readers")
        derived = _annotation_status(statuses)
        declared = str(row.get("status") or "not_started")
        if declared != derived:
            errors.append(f"case:{pilot_case_id}:status_mismatch:{declared}!={derived}")
        if derived == "complete":
            complete += 1
        elif derived == "in_progress":
            in_progress += 1

    if not rows:
        errors.append("manifest:empty")
    status = "blocked" if errors else ("complete" if complete == len(rows) and rows else "in_progress" if in_progress else "not_started")
    if status == "not_started" and rows:
        warnings.append("no_reader_annotations_started")
    return {
        "status": status,
        "case_count": len(rows),
        "complete_case_count": complete,
        "in_progress_case_count": in_progress,
        "not_started_case_count": len(rows) - complete - in_progress,
        "errors": list(dict.fromkeys(errors)),
        "warnings": warnings,
    }


def _annotation_status(statuses: dict[str, str]) -> str:
    if all(statuses[slot] == "complete" for slot in ("reader_a", "reader_b", "adjudication")):
        return "complete"
    if any(status != "not_started" for status in statuses.values()):
        return "in_progress"
    return "not_started"


def _load_case_payloads(root: Path) -> list[tuple[str, dict[str, Any]]]:
    workflow2 = read_json(root / "workflow2.json") if (root / "workflow2.json").exists() else {}
    rows: list[tuple[str, dict[str, Any]]] = []
    for case in workflow2.get("cases") or []:
        source_case_id = str(case.get("case_id") or "")
        path = Path(str(case.get("workflow1_output") or ""))
        candidates = [path] if path.is_absolute() else [root / path, path]
        for candidate in candidates:
            if candidate.exists():
                rows.append((source_case_id or candidate.stem, read_json(candidate)))
                break
    if rows:
        return rows
    case_dir = root / "workflow2_cases"
    return [(path.stem, read_json(path)) for path in sorted(case_dir.glob("*.json"))]


def _stratified_cases(rows: list[tuple[str, dict[str, Any]]], *, limit: int) -> list[tuple[str, dict[str, Any]]]:
    groups: dict[tuple[str, str], deque[tuple[str, dict[str, Any]]]] = defaultdict(deque)
    for row in sorted(rows, key=lambda item: item[0]):
        input_payload = row[1].get("input") or {}
        key = (str(input_payload.get("modality") or "unknown"), str(input_payload.get("body_part") or "unknown"))
        groups[key].append(row)
    selected = []
    keys = sorted(groups)
    while keys and len(selected) < min(limit, len(rows)):
        next_keys = []
        for key in keys:
            if groups[key] and len(selected) < limit:
                selected.append(groups[key].popleft())
            if groups[key]:
                next_keys.append(key)
        keys = next_keys
    return selected


def _reference_report(input_payload: dict[str, Any], case_payload: dict[str, Any], policy: ExternalPayloadPolicy) -> str:
    report_path = Path(str(input_payload.get("report_path") or ""))
    if report_path.exists():
        return policy.deidentify_clinical_text(report_path.read_text(encoding="utf-8", errors="ignore"))
    findings = ((case_payload.get("human_evaluation") or {}).get("finding_graph") or {}).get("findings") or []
    fallback = "\n".join(
        str(
            finding.get("source_text")
            or finding.get("text")
            or finding.get("observation_text")
            or finding.get("observation")
            or ""
        )
        for finding in findings
    )
    return policy.deidentify_clinical_text(fallback)


def _package_readme(case_count: int) -> str:
    return (
        "# medHarness2 Finding/Hazard Pilot Annotation Package\n\n"
        f"- Cases: {case_count}\n"
        "- Blinding: model identities and source case identifiers are not included.\n"
        "- Readers: reader_a and reader_b annotate independently; adjudication is completed only after both readers finish.\n"
        "- Finding guidance: `annotation/guidelines/finding_annotation.md`.\n"
        "- Hazard guidance: `annotation/guidelines/hazard_annotation.md`.\n"
        "- This pilot is for guideline calibration and must not be used as a formal test set.\n"
    )
