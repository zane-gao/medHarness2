from __future__ import annotations

import json
from pathlib import Path

import fitz

from medharness2.config import AppConfig, LLMConfig
from medharness2.ocr import extract_report_text


class PageOCRClient:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def call(self, prompt: str, image_path: str | None = None, **kwargs):
        assert image_path
        self.paths.append(image_path)
        return f"FINDINGS: page {len(self.paths)}\nIMPRESSION: stable"


def test_scanned_pdf_ocr_is_page_ordered_and_records_provenance(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    for text in ("page one", "page two"):
        page = doc.new_page(width=300, height=200)
        page.insert_text((30, 60), text)
    doc.save(pdf)

    client = PageOCRClient()
    result = extract_report_text(
        pdf,
        case_id="case-pages",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai")),
        llm_client=client,
        force=True,
    )

    assert len(client.paths) == 2
    assert all(path.endswith(".png") for path in client.paths)
    assert result.text.index("page 1") < result.text.index("page 2")
    meta = json.loads((tmp_path / "ocr" / "case-pages.ocr.json").read_text(encoding="utf-8"))
    assert meta["page_count"] == 2
    assert meta["pages"][0]["page_index"] == 1
    assert meta["pages"][1]["page_index"] == 2
    assert meta["provider"] == "openai"


def test_truncated_page_response_is_marked_in_metadata(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.save(pdf)

    class TruncatedClient:
        def call(self, *args, **kwargs):
            return "FINDINGS: unfinished sentence"

    result = extract_report_text(
        pdf,
        case_id="case-truncated",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai")),
        llm_client=TruncatedClient(),
        force=True,
    )
    assert "ocr_possible_truncation" in result.warnings
    meta = json.loads((tmp_path / "ocr" / "case-truncated.ocr.json").read_text(encoding="utf-8"))
    assert "ocr_possible_truncation" in meta["warnings"]


def test_ocr_verifier_is_audit_only_and_cannot_change_primary_text(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.save(pdf)
    primary = PageOCRClient()

    class Verifier:
        def __init__(self):
            self.calls = 0

        def call(self, prompt, image_path=None, **kwargs):
            self.calls += 1
            return '{"status":"disagreement","spans":["audit only"]}'

    verifier = Verifier()
    result = extract_report_text(
        pdf,
        case_id="case-verifier",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai")),
        llm_client=primary,
        verifier_client=verifier,
        force=True,
    )
    assert result.text.startswith("FINDINGS: page 1")
    assert verifier.calls == 1
    meta = json.loads((tmp_path / "ocr" / "case-verifier.ocr.json").read_text(encoding="utf-8"))
    assert meta["quality_audit"]["status"] == "disagreement"
    assert meta["quality_audit"]["spans"] == ["audit only"]
