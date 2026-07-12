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
