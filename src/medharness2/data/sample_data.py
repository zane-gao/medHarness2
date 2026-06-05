from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.llm_client import LLMClient
from medharness2.ocr import extract_report_text
from medharness2.preprocessing.dicom import prepare_case_assets
from medharness2.schema import CaseManifest, PreparedCase


def build_sample_manifest(sample_root: str | Path, output_path: str | Path) -> list[CaseManifest]:
    root = Path(sample_root)
    rows: list[CaseManifest] = []
    reader_map = _read_reader_map(root / "readers.xlsx")
    for modality_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        if modality_dir.name.startswith("."):
            continue
        for case_dir in sorted(path for path in modality_dir.iterdir() if path.is_dir()):
            image_paths = sorted(str(path) for path in case_dir.rglob("Y*") if path.is_file())
            report_pdf = case_dir / "report.pdf"
            warnings: list[str] = []
            if not image_paths:
                warnings.append("missing_image_files")
            if not report_pdf.exists():
                warnings.append("missing_report_pdf")
            header = _first_dicom_header(image_paths)
            modality_key = _normalize_modality(header.get("modality") or modality_dir.name)
            body_part = _normalize_body_part(header.get("body_part"), modality_key=modality_key)
            rows.append(
                CaseManifest(
                    case_id=case_dir.name,
                    reader=reader_map.get(case_dir.name, "unknown"),
                    modality=modality_key,
                    body_part=body_part,
                    report_pdf=str(report_pdf) if report_pdf.exists() else "",
                    report_text="",
                    image_paths=image_paths,
                    volume_path=None,
                    derived_assets={},
                    warnings=warnings,
                    metadata={
                        "source_modality_dir": modality_dir.name,
                        "dicom_header": header,
                    },
                )
            )
    _write_manifest(output_path, rows)
    return rows


def prepare_sample_dataset(
    sample_root: str | Path,
    output_dir: str | Path,
    *,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
    limit: int | None = None,
    run_ocr: bool = True,
    require_real_ocr: bool = False,
    force_ocr: bool = False,
) -> list[CaseManifest]:
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = build_sample_manifest(sample_root, out_dir / "manifest.raw.jsonl")
    if limit is not None:
        rows = rows[:limit]
    prepared_rows: list[CaseManifest] = []
    for row in rows:
        try:
            prepared = prepare_case_assets(row, out_dir / "derived")
        except Exception as exc:
            warning = f"asset_prepare_failed:{type(exc).__name__}"
            prepared = PreparedCase(
                case_id=row.case_id,
                modality=row.modality,
                body_part=row.body_part,
                image_paths=row.image_paths,
                volume_path=row.volume_path,
                derived_assets=row.derived_assets,
                warnings=[warning],
            )
        report_text_path = row.report_text
        warnings = [*row.warnings, *prepared.warnings]
        if run_ocr and row.report_pdf:
            if cfg.llm.provider.lower() == "mock":
                if require_real_ocr:
                    warnings.append("real_ocr_required_but_provider_is_mock")
                else:
                    warnings.append("mock_ocr_used")
                    try:
                        ocr = extract_report_text(
                            row.report_pdf,
                            row.case_id,
                            output_dir=out_dir / "ocr",
                            config=cfg,
                            llm_client=client,
                            force=force_ocr,
                        )
                        report_text_path = ocr.cache_path
                        warnings.extend(ocr.warnings)
                    except Exception as exc:
                        warnings.append(f"ocr_failed:{type(exc).__name__}")
            else:
                try:
                    ocr = extract_report_text(
                        row.report_pdf,
                        row.case_id,
                        output_dir=out_dir / "ocr",
                        config=cfg,
                        llm_client=client,
                        require_real=require_real_ocr,
                        force=force_ocr,
                    )
                    report_text_path = ocr.cache_path
                    warnings.extend(ocr.warnings)
                except Exception as exc:
                    warnings.append(f"ocr_failed:{type(exc).__name__}")
        prepared_rows.append(
            CaseManifest(
                case_id=row.case_id,
                reader=row.reader,
                modality=row.modality,
                body_part=row.body_part,
                report_pdf=row.report_pdf,
                report_text=report_text_path,
                image_paths=prepared.image_paths,
                volume_path=prepared.volume_path,
                derived_assets=prepared.derived_assets,
                warnings=list(dict.fromkeys(warnings)),
                metadata=row.metadata,
            )
        )
    _write_manifest(out_dir / "manifest.jsonl", prepared_rows)
    _write_summary(out_dir / "summary.json", prepared_rows)
    return prepared_rows


def load_manifest(path: str | Path) -> list[CaseManifest]:
    rows: list[CaseManifest] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(CaseManifest.from_json(json.loads(line)))
    return rows


def _write_manifest(output_path: str | Path, rows: list[CaseManifest]) -> None:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row.to_json(), ensure_ascii=False) + "\n")


def _write_summary(output_path: str | Path, rows: list[CaseManifest]) -> None:
    warning_counts = Counter(warning for row in rows for warning in row.warnings)
    modality_counts = Counter(row.modality for row in rows)
    body_part_counts = Counter(row.body_part for row in rows)
    payload = {
        "case_count": len(rows),
        "modality_counts": dict(sorted(modality_counts.items())),
        "body_part_counts": dict(sorted(body_part_counts.items())),
        "warning_counts": dict(sorted(warning_counts.items())),
        "cases_with_report_text": sum(1 for row in rows if row.report_text),
        "cases_with_primary_image": sum(1 for row in rows if row.derived_assets.get("primary_image")),
        "cases_with_volume": sum(1 for row in rows if row.volume_path),
    }
    Path(output_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_reader_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        import pandas as pd
    except Exception:
        return {}
    frame = pd.read_excel(path)
    if "ID" not in frame.columns or "Reader" not in frame.columns:
        return {}
    return {str(row["ID"]): str(row["Reader"]) for _, row in frame.iterrows()}


def _first_dicom_header(image_paths: list[str]) -> dict[str, Any]:
    try:
        import pydicom
    except Exception:
        return {}
    for image_path in image_paths[:50]:
        try:
            ds = pydicom.dcmread(
                image_path,
                stop_before_pixels=True,
                force=True,
                specific_tags=["Modality", "BodyPartExamined", "StudyDescription", "SeriesDescription"],
            )
        except Exception:
            continue
        return {
            "modality": str(getattr(ds, "Modality", "") or ""),
            "body_part": str(getattr(ds, "BodyPartExamined", "") or ""),
            "study_description": str(getattr(ds, "StudyDescription", "") or ""),
            "series_description": str(getattr(ds, "SeriesDescription", "") or ""),
        }
    return {}


def _normalize_modality(value: str) -> str:
    key = str(value or "").upper()
    if key in {"CR", "DX", "XR", "X-RAY", "XRAY"}:
        return "cxr"
    if key == "CT":
        return "ct"
    if key in {"MR", "MRI"}:
        return "mri"
    return key.lower() or "unknown"


def _normalize_body_part(value: str | None, *, modality_key: str) -> str:
    key = str(value or "").strip().upper()
    mapping = {
        "CHEST": "chest",
        "LUNG": "chest",
        "ABDOMEN": "abdomen",
        "HEAD": "head",
        "BRAIN": "brain",
        "PELVIS": "pelvis",
    }
    if key in mapping:
        return mapping[key]
    if modality_key == "mri":
        return "brain"
    return key.lower() if key else "unknown"
