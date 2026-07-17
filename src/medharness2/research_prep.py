from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from medharness2.modality import normalize_modality
from medharness2.annotation.models import AnnotationCase
from medharness2.utils.io import read_json


OCR_CANDIDATES = (
    {"candidate_id": "ocr_primary_doubao", "provider": "chat_completions", "model": "doubao-seed-2-1-pro-260628", "role": "ocr_primary"},
    {"candidate_id": "ocr_verifier_qwen", "provider": "chat_completions", "model": "qwen-vl-ocr-latest", "role": "ocr_verifier"},
    {"candidate_id": "ocr_baseline_paddle", "provider": "paddleocr", "model": "PaddleOCR-VL", "role": "ocr_baseline"},
)

# The Beichuan reference reports are the current engineering benchmark gold.
# Clinical reader labels remain a separate calibration layer.
CURRENT_GOLD_SOURCE = "beichuan_reference_report"
CURRENT_GOLD_STATUS = "available_for_current_benchmark"


def prepare_research_manifests(pilot_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    pilot = Path(pilot_dir)
    output = Path(output_dir)
    manifest_path = pilot / "manifest.jsonl"
    if not manifest_path.is_file():
        raise ValueError("pilot_manifest_not_found")
    try:
        rows = [
            json.loads(line)
            for line in manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"pilot_manifest_invalid_json:{type(exc).__name__}") from exc
    if not rows:
        raise ValueError("pilot_manifest_empty")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("pilot_manifest_malformed_row")
    _validate_pilot_rows(rows, pilot)
    modalities = {normalize_modality(row.get("modality")) for row in rows}
    required = {"cxr", "ct", "mri"}
    coverage_ok = required.issubset(modalities)
    ocr_rows = []
    for row in rows:
        for candidate in OCR_CANDIDATES:
            for repeat in (1, 2):
                ocr_rows.append({
                    "pilot_case_id": row.get("pilot_case_id"),
                    "modality": normalize_modality(row.get("modality")),
                    "annotation_path": row.get("annotation_path"),
                    "candidate": candidate,
                    "repeat": repeat,
                    "status": "blocked",
                    "gold_source": CURRENT_GOLD_SOURCE,
                    "gold_status": CURRENT_GOLD_STATUS,
                    "blocked_reasons": ["real_provider_run_not_available"],
                })
    output.mkdir(parents=True, exist_ok=True)
    ocr_manifest = {
        "schema_version": "1.0",
        "artifact_type": "ocr_research_manifest",
        "status": "blocked",
        "case_count": len(rows),
        "modality_coverage": sorted(modalities),
        "coverage_ok": coverage_ok,
        "gold_source": CURRENT_GOLD_SOURCE,
        "gold_status": CURRENT_GOLD_STATUS,
        "winner_status": "blocked",
        "candidates": list(OCR_CANDIDATES),
        "runs": ocr_rows,
        "winner_rule": ["clinical_cer", "truncation_count", "numeric_token_accuracy", "negation_accuracy", "repeat_consistency"],
    }
    paper_manifest = {
        "schema_version": "1.0",
        "artifact_type": "paper_experiment_manifest",
        "status": "pending",
        "data": {
            "pilot_annotation_dir": str(pilot),
            "case_count": len(rows),
            "modalities": sorted(modalities),
            "gold_source": CURRENT_GOLD_SOURCE,
            "gold_status": CURRENT_GOLD_STATUS,
            "clinical_reader_status": "not_started",
        },
        "experiments": [
            {"id": "ocr_comparison", "status": "blocked", "required_evidence": [CURRENT_GOLD_SOURCE, "real_provider_runs"]},
            {"id": "finding_extraction", "status": "pending", "metric": "finding_graph_precision_recall_f1"},
            {"id": "report_generation", "status": "pending", "metric": "likert_structure_alignment_hazard"},
            {"id": "reader_and_model_evaluation", "status": "not_started", "metric": "reader_agreement_and_modelwise_statistics"},
        ],
        "statistics": ["bootstrap_ci", "welch_anova", "holm_correction", "reader_agreement", "sensitivity_analysis"],
        "formal_claim_allowed": False,
    }
    (output / "ocr_manifest.json").write_text(json.dumps(ocr_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "paper_experiment_manifest.json").write_text(json.dumps(paper_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "blocked", "case_count": len(rows), "modality_coverage": sorted(modalities), "output_dir": str(output)}


def _validate_pilot_rows(rows: list[dict[str, Any]], pilot_dir: Path) -> None:
    """Reject malformed package identity fields before creating research runs."""
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, row in enumerate(rows, start=1):
        case_id = row.get("pilot_case_id")
        modality = row.get("modality")
        annotation_path = row.get("annotation_path")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(f"pilot_manifest_row_{index}:pilot_case_id_must_be_string")
        if not isinstance(modality, str) or not modality.strip():
            raise ValueError(f"pilot_manifest_row_{index}:modality_must_be_string")
        if not isinstance(annotation_path, str) or not annotation_path.strip():
            raise ValueError(f"pilot_manifest_row_{index}:annotation_path_must_be_string")
        normalized_id = case_id.strip()
        normalized_path = annotation_path.strip()
        if normalized_id in seen_ids:
            raise ValueError(f"pilot_manifest_duplicate_case_id:{normalized_id}")
        if normalized_path in seen_paths:
            raise ValueError(f"pilot_manifest_duplicate_annotation_path:{normalized_path}")
        raw_path = Path(normalized_path)
        if raw_path.is_absolute():
            raise ValueError(f"pilot_manifest_row_{index}:annotation_path_must_be_relative")
        case_root = (pilot_dir / "cases").resolve()
        case_path = (pilot_dir / raw_path).resolve()
        if case_root not in case_path.parents or case_path == case_root:
            raise ValueError(f"pilot_manifest_row_{index}:annotation_path_outside_cases")
        if not case_path.is_file():
            raise ValueError(f"pilot_manifest_row_{index}:annotation_case_missing:{normalized_path}")
        try:
            case = AnnotationCase.model_validate_json(case_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError(f"pilot_manifest_row_{index}:annotation_case_invalid:{normalized_path}") from exc
        if case.pilot_case_id != normalized_id:
            raise ValueError(f"pilot_manifest_row_{index}:annotation_case_identity_mismatch")
        if normalize_modality(case.modality) != normalize_modality(modality):
            raise ValueError(f"pilot_manifest_row_{index}:annotation_case_modality_mismatch")
        seen_ids.add(normalized_id)
        seen_paths.add(normalized_path)
