from __future__ import annotations

import json
from pathlib import Path

import fitz
import pandas as pd
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from medharness2.config import AppConfig, LLMConfig
from medharness2.data.sample_data import build_sample_manifest
from medharness2.data.sample_data import prepare_sample_dataset
from medharness2.ocr import extract_report_text
from medharness2.preprocessing.dicom import prepare_case_assets


class StaticOCRClient:
    def call(self, prompt: str, image_path: str | None = None, **kwargs):
        assert image_path and image_path.endswith(".pdf")
        return "FINDINGS: OCR text.\nIMPRESSION: OCR impression."


def test_extract_report_text_uses_vlm_for_scanned_pdf(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.save(pdf)
    result = extract_report_text(
        pdf,
        case_id="case1",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="mock")),
        llm_client=StaticOCRClient(),
    )
    assert result.text.startswith("FINDINGS:")
    assert result.method == "vlm_ocr"
    assert Path(result.cache_path).exists()
    meta = json.loads((tmp_path / "ocr" / "case1.ocr.json").read_text(encoding="utf-8"))
    assert meta["provider"] == "mock"
    assert meta["method"] == "vlm_ocr"


def test_build_sample_manifest_reads_reader_map_and_dicom_headers(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    _write_dicom(case_dir / "Y1", modality="CR", body_part="CHEST")
    _write_blank_pdf(sample_root / "CR" / "CR001" / "report.pdf")
    pd.DataFrame({"ID": ["CR001"], "Reader": ["reader_a"]}).to_excel(sample_root / "readers.xlsx", index=False)
    out = tmp_path / "manifest.jsonl"
    rows = build_sample_manifest(sample_root, out)
    assert out.exists()
    assert rows[0].case_id == "CR001"
    assert rows[0].reader == "reader_a"
    assert rows[0].modality == "cxr"
    assert rows[0].body_part == "chest"
    assert json.loads(out.read_text(encoding="utf-8").splitlines()[0])["report_pdf"].endswith("report.pdf")


def test_prepare_case_assets_converts_cr_dicom_to_png(tmp_path: Path):
    dicom_path = tmp_path / "Y1"
    _write_dicom(dicom_path, modality="CR", body_part="CHEST", rows=8, columns=8)
    case = {
        "case_id": "CR001",
        "modality": "cxr",
        "body_part": "chest",
        "image_paths": [str(dicom_path)],
        "report_pdf": "",
        "warnings": [],
    }
    prepared = prepare_case_assets(case, tmp_path / "derived")
    assert prepared.derived_assets["primary_image"].endswith(".png")
    assert Path(prepared.derived_assets["primary_image"]).exists()
    assert prepared.image_paths[0].endswith(".png")


def test_prepare_sample_dataset_continues_when_ocr_fails(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    _write_dicom(case_dir / "Y1", modality="CR", body_part="CHEST")
    _write_blank_pdf(sample_root / "CR" / "CR001" / "report.pdf")
    pd.DataFrame({"ID": ["CR001"], "Reader": ["reader_a"]}).to_excel(sample_root / "readers.xlsx", index=False)

    class FailingClient:
        def call(self, *args, **kwargs):
            raise RuntimeError("ocr unavailable")

    rows = prepare_sample_dataset(sample_root, tmp_path / "out", llm_client=FailingClient())
    assert len(rows) == 1
    assert any("ocr_failed:RuntimeError" in warning for warning in rows[0].warnings)
    assert Path(tmp_path / "out" / "summary.json").exists()
    summary = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert summary["case_count"] == 1
    assert summary["warning_counts"]["ocr_failed:RuntimeError"] == 1


def test_prepare_sample_dataset_marks_mock_ocr(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    _write_dicom(case_dir / "Y1", modality="CR", body_part="CHEST")
    _write_blank_pdf(sample_root / "CR" / "CR001" / "report.pdf")
    pd.DataFrame({"ID": ["CR001"], "Reader": ["reader_a"]}).to_excel(sample_root / "readers.xlsx", index=False)
    rows = prepare_sample_dataset(sample_root, tmp_path / "out", config=AppConfig(llm=LLMConfig(provider="mock")))
    assert "mock_ocr_used" in rows[0].warnings
    summary = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert summary["warning_counts"]["mock_ocr_used"] == 1


def test_prepare_sample_dataset_require_real_ocr_rejects_mock_provider(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    _write_dicom(case_dir / "Y1", modality="CR", body_part="CHEST")
    _write_blank_pdf(sample_root / "CR" / "CR001" / "report.pdf")
    pd.DataFrame({"ID": ["CR001"], "Reader": ["reader_a"]}).to_excel(sample_root / "readers.xlsx", index=False)
    rows = prepare_sample_dataset(
        sample_root,
        tmp_path / "out",
        config=AppConfig(llm=LLMConfig(provider="mock")),
        require_real_ocr=True,
    )
    assert "real_ocr_required_but_provider_is_mock" in rows[0].warnings
    assert rows[0].report_text == ""


def _write_blank_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.save(path)


def _write_dicom(path: Path, *, modality: str, body_part: str, rows: int = 4, columns: int = 4) -> None:
    import numpy as np

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.PatientName = "Test"
    ds.PatientID = "1"
    ds.Modality = modality
    ds.BodyPartExamined = body_part
    ds.SeriesInstanceUID = generate_uid()
    ds.InstanceNumber = 1
    ds.Rows = rows
    ds.Columns = columns
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    arr = (np.arange(rows * columns, dtype=np.uint16).reshape(rows, columns) * 16)
    ds.PixelData = arr.tobytes()
    ds.save_as(path, write_like_original=False)
