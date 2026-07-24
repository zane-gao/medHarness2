from __future__ import annotations

import json
import hashlib
import subprocess
from pathlib import Path

import fitz
import numpy as np
import pandas as pd
import pydicom
from PIL import Image
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

import medharness2.llm_client as llm_client_module
from medharness2.config import AppConfig, LLMConfig, ModelRoleConfig
from medharness2.data.sample_data import build_sample_manifest
from medharness2.data.sample_data import prepare_sample_dataset
from medharness2.ocr import extract_report_text
from medharness2.preprocessing.dicom import prepare_case_assets


class StaticOCRClient:
    def __init__(self):
        self.calls = 0

    def call(self, prompt: str, image_path: str | None = None, **kwargs):
        self.calls += 1
        assert image_path and Path(image_path).suffix.lower() in {".pdf", ".png"}
        return "FINDINGS: OCR text.\nIMPRESSION: OCR impression."


def test_extract_report_text_uses_vlm_for_scanned_pdf(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(10, 10, 11, 11), color=(0, 0, 0), fill=(0, 0, 0))
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


def test_extract_report_text_refreshes_unknown_cache_when_real_ocr_required(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    _write_blank_pdf(pdf)
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    (ocr_dir / "case1.txt").write_text("old cached text\n", encoding="utf-8")
    client = StaticOCRClient()
    result = extract_report_text(
        pdf,
        case_id="case1",
        output_dir=ocr_dir,
        config=AppConfig(llm=LLMConfig(provider="openai", model="gpt-5.6-sol")),
        llm_client=client,
        require_real=True,
    )
    assert client.calls == 1
    assert result.text.startswith("FINDINGS: OCR text")
    meta = json.loads((ocr_dir / "case1.ocr.json").read_text(encoding="utf-8"))
    assert meta["provider"] == "openai"


def test_extract_report_text_reuses_real_ocr_cache_when_real_ocr_required(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    _write_blank_pdf(pdf)
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    (ocr_dir / "case1.txt").write_text("real cached text\n", encoding="utf-8")
    (ocr_dir / "case1.ocr.json").write_text(
        json.dumps(
            {
                "case_id": "case1",
                "method": "vlm_ocr",
                "provider": "openai",
                "model": "gpt-5.6-sol",
                "role": "default",
                "prompt_version": "ocr-page-v2",
                "source_pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                "verifier": {"configured": False, "provider": "", "model": "", "role": ""},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class FailingClient:
        def call(self, *args, **kwargs):
            raise AssertionError("real OCR cache should be reused")

    result = extract_report_text(
        pdf,
        case_id="case1",
        output_dir=ocr_dir,
        config=AppConfig(llm=LLMConfig(provider="openai", model="gpt-5.6-sol")),
        llm_client=FailingClient(),
        require_real=True,
    )
    assert result.text == "real cached text\n"
    assert result.method == "cache"


def test_extract_report_text_does_not_reuse_real_cache_after_model_change(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    _write_blank_pdf(pdf)
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    (ocr_dir / "case1.txt").write_text("real cached text\n", encoding="utf-8")
    (ocr_dir / "case1.ocr.json").write_text(
        json.dumps(
            {
                "case_id": "case1",
                "method": "vlm_ocr",
                "provider": "openai",
                "model": "old-model",
                "role": "default",
                "prompt_version": "ocr-page-v2",
                "source_pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                "verifier": {"configured": False, "provider": "", "model": "", "role": ""},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    client = StaticOCRClient()
    result = extract_report_text(
        pdf,
        case_id="case1",
        output_dir=ocr_dir,
        config=AppConfig(llm=LLMConfig(provider="openai", model="new-model")),
        llm_client=client,
        require_real=True,
    )

    assert client.calls == 1
    assert result.method == "vlm_ocr"


def test_extract_report_text_rejects_cache_sidecar_for_different_case(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    _write_blank_pdf(pdf)
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    (ocr_dir / "target.txt").write_text("text from another case\n", encoding="utf-8")
    (ocr_dir / "target.ocr.json").write_text(
        json.dumps(
            {
                "case_id": "other-case",
                "method": "vlm_ocr",
                "provider": "openai",
                "model": "gpt-5.6-sol",
                "role": "default",
                "prompt_version": "ocr-page-v2",
                "source_pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                "verifier": {"configured": False, "provider": "", "model": "", "role": ""},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    client = StaticOCRClient()
    result = extract_report_text(
        pdf,
        case_id="target",
        output_dir=ocr_dir,
        config=AppConfig(llm=LLMConfig(provider="openai")),
        llm_client=client,
        require_real=True,
    )

    assert client.calls == 1
    assert result.method == "vlm_ocr"
    assert result.text.startswith("FINDINGS: OCR text")


def test_extract_report_text_does_not_reuse_cache_sidecar_without_case_id(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    _write_blank_pdf(pdf)
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    (ocr_dir / "case1.txt").write_text("unbound cached text\n", encoding="utf-8")
    (ocr_dir / "case1.ocr.json").write_text(
        json.dumps(
            {
                "method": "vlm_ocr",
                "provider": "openai",
                "model": "gpt-5.6-sol",
                "role": "default",
                "prompt_version": "ocr-page-v2",
                "source_pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    client = StaticOCRClient()
    result = extract_report_text(
        pdf,
        case_id="case1",
        output_dir=ocr_dir,
        config=AppConfig(llm=LLMConfig(provider="openai", model="gpt-5.6-sol")),
        llm_client=client,
        require_real=True,
    )

    assert client.calls == 1
    assert result.method == "vlm_ocr"
    assert result.text.startswith("FINDINGS: OCR text")


def test_extract_report_text_does_not_trust_unknown_provider_cache(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    _write_blank_pdf(pdf)
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    (ocr_dir / "case1.txt").write_text("untrusted cached text\n", encoding="utf-8")
    (ocr_dir / "case1.ocr.json").write_text(
        json.dumps({"case_id": "case1", "method": "vlm_ocr", "provider": "future_magic_provider"}) + "\n",
        encoding="utf-8",
    )
    client = StaticOCRClient()

    result = extract_report_text(
        pdf,
        case_id="case1",
        output_dir=ocr_dir,
        config=AppConfig(llm=LLMConfig(provider="chat_completions")),
        llm_client=client,
        require_real=True,
    )

    assert client.calls == 1
    assert result.text.startswith("FINDINGS: OCR text")
    meta = json.loads((ocr_dir / "case1.ocr.json").read_text(encoding="utf-8"))
    assert meta["provider"] == "chat_completions"


def test_extract_report_text_require_real_rejects_unsupported_provider(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    _write_blank_pdf(pdf)

    try:
        extract_report_text(
            pdf,
            case_id="case1",
            output_dir=tmp_path / "ocr",
            config=AppConfig(llm=LLMConfig(provider="future_magic_provider")),
            llm_client=StaticOCRClient(),
            require_real=True,
        )
    except RuntimeError as exc:
        assert "supported non-mock provider" in str(exc)
    else:
        raise AssertionError("unsupported provider must not satisfy require_real OCR")


def test_extract_report_text_force_refreshes_cache(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    _write_blank_pdf(pdf)
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    (ocr_dir / "case1.txt").write_text("real cached text\n", encoding="utf-8")
    (ocr_dir / "case1.ocr.json").write_text(
        json.dumps({"case_id": "case1", "method": "vlm_ocr", "provider": "openai"}) + "\n",
        encoding="utf-8",
    )
    client = StaticOCRClient()
    result = extract_report_text(
        pdf,
        case_id="case1",
        output_dir=ocr_dir,
        config=AppConfig(llm=LLMConfig(provider="openai")),
        llm_client=client,
        force=True,
    )
    assert client.calls == 1
    assert result.text.startswith("FINDINGS: OCR text")


def test_extract_report_text_can_use_local_vlm_cli_for_scanned_pdf(monkeypatch, tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    _write_blank_pdf(pdf)
    script = tmp_path / "run_report_generation.py"
    script.write_text("# fake runner\n", encoding="utf-8")
    config = tmp_path / "reportgen_models.yaml"
    config.write_text("models: {}\n", encoding="utf-8")
    seen_image_paths: list[str] = []

    def fake_run(cmd, check, capture_output, text, timeout):
        input_path = Path(cmd[cmd.index("--input-jsonl") + 1])
        output_path = Path(cmd[cmd.index("--output-jsonl") + 1])
        row = json.loads(input_path.read_text(encoding="utf-8"))
        seen_image_paths.extend(row["image_paths"])
        output_path.write_text(
            json.dumps({"case_id": row["case_id"], "generated_text": "FINDINGS: Local PDF OCR."}) + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(llm_client_module, "run_isolated_process", fake_run)
    cfg = AppConfig(
        llm=LLMConfig(
            provider="local_vlm_cli",
            model="qwen25vl_7b_instruct",
            local_cli_script=str(script),
            local_cli_config_path=str(config),
            local_cli_timeout_sec=30,
        )
    )
    result = extract_report_text(pdf, case_id="case1", output_dir=tmp_path / "ocr", config=cfg)
    assert result.text == "FINDINGS: Local PDF OCR."
    assert seen_image_paths and seen_image_paths[0].endswith(".png")
    meta = json.loads((tmp_path / "ocr" / "case1.ocr.json").read_text(encoding="utf-8"))
    assert meta["provider"] == "local_vlm_cli"
    assert meta["model"] == "qwen25vl_7b_instruct"


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


def test_prepare_case_assets_creates_contact_sheet_from_existing_numpy_volume(tmp_path: Path):
    volume = tmp_path / "brain.npy"
    array = np.zeros((12, 16, 20), dtype=np.float32)
    for index in range(array.shape[0]):
        array[index, 3:13, 4:16] = index + 1
    np.save(volume, array)

    prepared = prepare_case_assets(
        {
            "case_id": "MR-VOLUME-001",
            "modality": "mri",
            "body_part": "brain",
            "image_paths": [],
            "volume_path": str(volume),
            "report_pdf": "",
            "warnings": [],
        },
        tmp_path / "derived",
    )

    contact_sheet = Path(prepared.derived_assets["contact_sheet"])
    assert prepared.volume_path == str(volume)
    assert prepared.derived_assets["volume_path"] == str(volume)
    assert prepared.derived_assets["primary_image"] == str(contact_sheet)
    assert prepared.derived_assets["contact_sheet_source"] == "volume"
    assert contact_sheet.exists()
    with Image.open(contact_sheet) as image:
        assert image.format == "PNG"
        assert image.width > 0
        assert image.height > 0


def test_prepare_case_assets_prefers_flair_series_for_brain_mri(monkeypatch, tmp_path: Path):
    fgr_uid = generate_uid()
    flair_uid = generate_uid()
    paths: list[str] = []
    for index in range(3):
        path = tmp_path / f"fgr_{index}.dcm"
        _write_dicom(
            path,
            modality="MR",
            body_part="BRAIN",
            series_uid=fgr_uid,
            instance_number=index + 1,
            series_description="FGR",
        )
        paths.append(str(path))
    for index in range(2):
        path = tmp_path / f"flair_{index}.dcm"
        _write_dicom(
            path,
            modality="MR",
            body_part="BRAIN",
            series_uid=flair_uid,
            instance_number=index + 1,
            series_description="T2_FLAIR_8mm",
        )
        paths.append(str(path))

    selected_descriptions: list[str] = []

    def fake_write_series_volume(image_paths, output_path, warnings):
        ds = pydicom.dcmread(image_paths[0], stop_before_pixels=True, force=True)
        selected_descriptions.append(str(ds.SeriesDescription))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("volume", encoding="utf-8")
        return str(output_path)

    def fake_write_contact_sheet(image_paths, output_path, warnings, *, num_slices=9):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("sheet", encoding="utf-8")
        return str(output_path)

    monkeypatch.setattr("medharness2.preprocessing.dicom._write_series_volume", fake_write_series_volume)
    monkeypatch.setattr("medharness2.preprocessing.dicom._write_contact_sheet", fake_write_contact_sheet)
    prepared = prepare_case_assets(
        {
            "case_id": "MR001",
            "modality": "mri",
            "body_part": "brain",
            "image_paths": paths,
            "report_pdf": "",
            "warnings": [],
        },
        tmp_path / "derived",
    )
    assert selected_descriptions == ["T2_FLAIR_8mm"]
    assert prepared.derived_assets["selected_series_description"] == "T2_FLAIR_8mm"
    assert prepared.derived_assets["series_selection_reason"] == "brain_mri_flair_preferred"
    assert prepared.derived_assets["selected_series_type"] == "flair"


def test_prepare_case_assets_prefers_t2_series_when_flair_absent(monkeypatch, tmp_path: Path):
    fgr_uid = generate_uid()
    t2_uid = generate_uid()
    paths: list[str] = []
    for index in range(3):
        path = tmp_path / f"fgr_{index}.dcm"
        _write_dicom(
            path,
            modality="MR",
            body_part="BRAIN",
            series_uid=fgr_uid,
            instance_number=index + 1,
            series_description="FGR",
        )
        paths.append(str(path))
    for index in range(2):
        path = tmp_path / f"t2_{index}.dcm"
        _write_dicom(
            path,
            modality="MR",
            body_part="BRAIN",
            series_uid=t2_uid,
            instance_number=index + 1,
            series_description="T2_FSE_8mm",
        )
        paths.append(str(path))

    selected_descriptions: list[str] = []

    def fake_write_series_volume(image_paths, output_path, warnings):
        ds = pydicom.dcmread(image_paths[0], stop_before_pixels=True, force=True)
        selected_descriptions.append(str(ds.SeriesDescription))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("volume", encoding="utf-8")
        return str(output_path)

    def fake_write_contact_sheet(image_paths, output_path, warnings, *, num_slices=9):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("sheet", encoding="utf-8")
        return str(output_path)

    monkeypatch.setattr("medharness2.preprocessing.dicom._write_series_volume", fake_write_series_volume)
    monkeypatch.setattr("medharness2.preprocessing.dicom._write_contact_sheet", fake_write_contact_sheet)
    prepared = prepare_case_assets(
        {
            "case_id": "MR001",
            "modality": "mri",
            "body_part": "brain",
            "image_paths": paths,
            "report_pdf": "",
            "warnings": [],
        },
        tmp_path / "derived",
    )
    assert selected_descriptions == ["T2_FSE_8mm"]
    assert prepared.derived_assets["selected_series_description"] == "T2_FSE_8mm"
    assert prepared.derived_assets["series_selection_reason"] == "brain_mri_t2_preferred"
    assert prepared.derived_assets["selected_series_type"] == "t2"


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


def test_prepare_sample_dataset_blocks_truncated_ocr_text(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    _write_dicom(case_dir / "Y1", modality="CR", body_part="CHEST")
    _write_blank_pdf(sample_root / "CR" / "CR001" / "report.pdf")
    pd.DataFrame({"ID": ["CR001"], "Reader": ["reader_a"]}).to_excel(sample_root / "readers.xlsx", index=False)

    class TruncatedClient:
        def call(self, *args, **kwargs):
            return "FINDINGS: unfinished sentence"

    rows = prepare_sample_dataset(
        sample_root,
        tmp_path / "out",
        config=AppConfig(llm=LLMConfig(provider="openai")),
        llm_client=TruncatedClient(),
    )
    assert rows[0].report_text == ""
    assert "ocr_quality_blocked" in rows[0].warnings


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


def test_prepare_sample_dataset_refreshes_mock_cache_when_real_ocr_required(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    _write_dicom(case_dir / "Y1", modality="CR", body_part="CHEST")
    _write_blank_pdf(sample_root / "CR" / "CR001" / "report.pdf")
    pd.DataFrame({"ID": ["CR001"], "Reader": ["reader_a"]}).to_excel(sample_root / "readers.xlsx", index=False)
    out_dir = tmp_path / "out"

    prepare_sample_dataset(sample_root, out_dir, config=AppConfig(llm=LLMConfig(provider="mock")))
    client = StaticOCRClient()
    rows = prepare_sample_dataset(
        sample_root,
        out_dir,
        config=AppConfig(llm=LLMConfig(provider="openai")),
        llm_client=client,
        require_real_ocr=True,
    )
    assert client.calls == 1
    assert "mock_ocr_used" not in rows[0].warnings
    meta = json.loads((out_dir / "ocr" / "CR001.ocr.json").read_text(encoding="utf-8"))
    assert meta["provider"] == "openai"


def test_prepare_sample_dataset_uses_configured_ocr_roles_even_when_top_level_is_mock(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    _write_dicom(case_dir / "Y1", modality="CR", body_part="CHEST")
    _write_blank_pdf(sample_root / "CR" / "CR001" / "report.pdf")
    pd.DataFrame({"ID": ["CR001"], "Reader": ["reader_a"]}).to_excel(sample_root / "readers.xlsx", index=False)

    class RoutedClient(StaticOCRClient):
        def call(self, prompt, image_path=None, **kwargs):
            if kwargs.get("model") == "verifier-model":
                return '{"status":"agree","reason":"ok"}'
            assert kwargs.get("model") == "primary-model"
            return super().call(prompt, image_path=image_path, **kwargs)

    cfg = AppConfig(
        llm=LLMConfig(provider="mock"),
        model_roles={
            "ocr_primary": ModelRoleConfig(provider="chat_completions", model="primary-model"),
            "ocr_verifier": ModelRoleConfig(provider="chat_completions", model="verifier-model"),
        },
    )
    rows = prepare_sample_dataset(
        sample_root,
        tmp_path / "out",
        config=cfg,
        llm_client=RoutedClient(),
        require_real_ocr=True,
    )

    assert rows[0].report_text
    assert "real_ocr_required_but_provider_is_mock" not in rows[0].warnings
    meta = json.loads((tmp_path / "out" / "ocr" / "CR001.ocr.json").read_text(encoding="utf-8"))
    assert meta["model"] == "primary-model"
    assert meta["quality_audit"]["status"] == "agree"


def test_prepare_sample_dataset_blocks_verifier_review_text(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    _write_dicom(case_dir / "Y1", modality="CR", body_part="CHEST")
    _write_blank_pdf(sample_root / "CR" / "CR001" / "report.pdf")
    pd.DataFrame({"ID": ["CR001"], "Reader": ["reader_a"]}).to_excel(sample_root / "readers.xlsx", index=False)

    class DisagreeClient(StaticOCRClient):
        def call(self, prompt, image_path=None, **kwargs):
            if kwargs.get("model") == "verifier-model":
                return '{"status":"disagreement","reason":"check"}'
            return super().call(prompt, image_path=image_path, **kwargs)

    cfg = AppConfig(
        llm=LLMConfig(provider="mock"),
        model_roles={
            "ocr_primary": ModelRoleConfig(provider="chat_completions", model="primary-model"),
            "ocr_verifier": ModelRoleConfig(provider="chat_completions", model="verifier-model"),
        },
    )
    rows = prepare_sample_dataset(
        sample_root,
        tmp_path / "out",
        config=cfg,
        llm_client=DisagreeClient(),
        require_real_ocr=True,
    )

    assert rows[0].report_text == ""
    assert "ocr_quality_review_required" in rows[0].warnings


def _write_blank_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    # A scanned-page fixture: no extractable text layer, but a tiny raster-like
    # mark so the production blank-page gate does not skip the page.
    page.draw_rect(fitz.Rect(10, 10, 11, 11), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(path)


def _write_dicom(
    path: Path,
    *,
    modality: str,
    body_part: str,
    rows: int = 4,
    columns: int = 4,
    series_uid: str | None = None,
    instance_number: int = 1,
    series_description: str | None = None,
) -> None:
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
    ds.SeriesInstanceUID = series_uid or generate_uid()
    ds.InstanceNumber = instance_number
    if series_description:
        ds.SeriesDescription = series_description
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
