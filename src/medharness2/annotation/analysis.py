from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from medharness2.annotation.models import AnnotationCase
from medharness2.annotation.pilot import validate_pilot_annotation_package


def analyze_pilot_annotations(package_dir: str | Path, output_path: str | Path) -> dict[str, Any]:
    """Summarize completed double-read annotations without inventing statistics.

    The function is deliberately conservative: any incomplete case blocks formal
    claims. Agreement is computed only on complete cases and uses exact sets of
    reader finding/hazard signatures, which is transparent and reproducible for
    the pilot. The output is an analysis input/queue, not a clinical gold label.
    """
    package = Path(package_dir)
    validation = validate_pilot_annotation_package(package)
    rows = _read_manifest(package / "manifest.jsonl")
    cases: list[AnnotationCase] = []
    for row in rows:
        path = package / str(row["annotation_path"])
        cases.append(AnnotationCase.model_validate_json(path.read_text(encoding="utf-8")))

    complete_cases = [
        case for case in cases
        if all(case.annotations[slot].status == "complete" for slot in ("reader_a", "reader_b", "adjudication"))
    ]
    disagreement_queue: list[dict[str, Any]] = []
    exact_matches = 0
    finding_agreements = 0
    hazard_agreements = 0
    for case in complete_cases:
        reader_a = case.annotations["reader_a"]
        reader_b = case.annotations["reader_b"]
        findings_a = _finding_signatures(reader_a.findings)
        findings_b = _finding_signatures(reader_b.findings)
        hazards_a = _hazard_signatures(reader_a.hazards)
        hazards_b = _hazard_signatures(reader_b.hazards)
        finding_equal = findings_a == findings_b
        hazard_equal = hazards_a == hazards_b
        exact_matches += int(finding_equal and hazard_equal)
        finding_agreements += int(finding_equal)
        hazard_agreements += int(hazard_equal)
        if not finding_equal or not hazard_equal:
            disagreement_queue.append({
                "pilot_case_id": case.pilot_case_id,
                "finding_disagreement": not finding_equal,
                "hazard_disagreement": not hazard_equal,
                "reader_a_only_findings": sorted(findings_a - findings_b),
                "reader_b_only_findings": sorted(findings_b - findings_a),
                "reader_a_only_hazards": sorted(hazards_a - hazards_b),
                "reader_b_only_hazards": sorted(hazards_b - hazards_a),
                "adjudication_status": case.annotations["adjudication"].status,
            })

    count = len(complete_cases)
    agreement = {
        "compared_case_count": count,
        "case_exact_agreement": exact_matches / count if count else None,
        "finding_exact_agreement": finding_agreements / count if count else None,
        "hazard_exact_agreement": hazard_agreements / count if count else None,
        "metric_note": "pilot exact-set agreement; no kappa/ICC is emitted until a validated clinical analysis protocol is run",
    }
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_type": "pilot_annotation_analysis",
        "status": "complete" if validation["status"] == "complete" else "blocked",
        "package_dir": str(package),
        "case_count": len(cases),
        "complete_case_count": count,
        "validation": validation,
        "reader_agreement": agreement,
        "disagreement_queue": disagreement_queue,
        "formal_claim_allowed": bool(validation["status"] == "complete" and count == len(cases) and count > 0),
        "next_gate": "完成双读和 adjudication 后再运行正式统计协议；当前输出不替代医生 adjudication",
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _read_manifest(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("annotation_manifest_row_must_be_object")
            rows.append(value)
    return rows


def _finding_signatures(items: list[Any]) -> set[str]:
    return {
        "|".join((item.observation_text.strip(), item.location_text or "", item.laterality, item.certainty, item.severity or ""))
        for item in items
    }


def _hazard_signatures(items: list[Any]) -> set[str]:
    return {
        "|".join((item.candidate_id, item.error_type, str(item.hazard_level), str(item.clinically_significant)))
        for item in items
    }
