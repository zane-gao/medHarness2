from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from medharness2.config import AppConfig, LLMConfig, ModelRoleConfig
from medharness2.ocr import extract_report_text
from medharness2.ocr_benchmark import evaluate_ocr_candidates


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
    assert meta["source_page_count"] == 2
    assert meta["retained_page_count"] == 2
    assert meta["pages"][0]["page_index"] == 1
    assert meta["pages"][1]["page_index"] == 2
    assert meta["provider"] == "openai"


def test_scanned_pdf_ocr_skips_deterministic_blank_pages(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((30, 60), "visible page")
    doc.new_page(width=300, height=200)
    doc.save(pdf)

    client = PageOCRClient()
    result = extract_report_text(
        pdf,
        case_id="case-blank-page",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai")),
        llm_client=client,
        force=True,
    )

    assert len(client.paths) == 1
    assert result.text.startswith("FINDINGS: page 1")
    meta = json.loads((tmp_path / "ocr" / "case-blank-page.ocr.json").read_text(encoding="utf-8"))
    assert meta["page_count"] == 1
    assert meta["source_page_count"] == 2
    assert meta["retained_page_count"] == 1
    assert meta["pages"][1]["skipped"] is True
    assert meta["pages"][1]["skip_reason"] == "blank_page"


def test_scanned_pdf_ocr_uses_configured_primary_role_and_records_route(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((30, 60), "visible page")
    doc.save(pdf)

    class RecordingClient(PageOCRClient):
        def call(self, prompt, image_path=None, **kwargs):
            assert kwargs["provider"] == "chat_completions"
            assert kwargs["model"] == "doubao-seed-2-1-pro-260628"
            return super().call(prompt, image_path=image_path, **kwargs)

    result = extract_report_text(
        pdf,
        case_id="case-route",
        output_dir=tmp_path / "ocr",
        config=AppConfig(
            llm=LLMConfig(provider="mock"),
            model_roles={
                "ocr_primary": ModelRoleConfig(
                    provider="chat_completions",
                    model="doubao-seed-2-1-pro-260628",
                    api_key_env="DMX_API_KEY",
                    base_url="https://www.DMXAPI.cn/v1",
                )
            },
        ),
        llm_client=RecordingClient(),
        force=True,
    )

    assert result.text.startswith("FINDINGS:")
    meta = json.loads((tmp_path / "ocr" / "case-route.ocr.json").read_text(encoding="utf-8"))
    assert meta["provider"] == "chat_completions"
    assert meta["model"] == "doubao-seed-2-1-pro-260628"
    assert meta["role"] == "ocr_primary"


def test_truncated_page_response_is_marked_in_metadata(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(10, 10, 11, 11), color=(0, 0, 0), fill=(0, 0, 0))
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
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(10, 10, 11, 11), color=(0, 0, 0), fill=(0, 0, 0))
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


def test_ocr_verifier_failure_does_not_fail_primary_ocr(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(10, 10, 11, 11), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(pdf)

    class FailingVerifier:
        def call(self, *args, **kwargs):
            raise RuntimeError("verifier unavailable")

    result = extract_report_text(
        pdf,
        case_id="case-verifier-failure",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai")),
        llm_client=PageOCRClient(),
        verifier_client=FailingVerifier(),
        force=True,
    )

    assert result.text.startswith("FINDINGS: page 1")
    assert "ocr_verifier_failed" in result.warnings
    meta = json.loads((tmp_path / "ocr" / "case-verifier-failure.ocr.json").read_text(encoding="utf-8"))
    assert meta["quality_audit"]["status"] == "verifier_failed"


@pytest.mark.parametrize("response", [None, [], "not-json"])
def test_ocr_verifier_invalid_response_is_audit_warning(tmp_path: Path, response):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(10, 10, 11, 11), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(pdf)

    class InvalidVerifier:
        def call(self, *args, **kwargs):
            return response

    result = extract_report_text(
        pdf,
        case_id="case-verifier-invalid",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai")),
        llm_client=PageOCRClient(),
        verifier_client=InvalidVerifier(),
        force=True,
    )

    assert result.text.startswith("FINDINGS: page 1")
    assert "ocr_verifier_invalid_response" in result.warnings
    assert "ocr_verifier_failed" not in result.warnings
    meta = json.loads((tmp_path / "ocr" / "case-verifier-invalid.ocr.json").read_text(encoding="utf-8"))
    assert meta["quality_audit"]["status"] == "invalid_verifier_response"


def test_ocr_verifier_audits_each_retained_page(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    for text in ("page one", "page two"):
        page = doc.new_page(width=300, height=200)
        page.insert_text((30, 60), text)
    doc.save(pdf)

    class Verifier:
        def __init__(self):
            self.images: list[str] = []

        def call(self, prompt, image_path=None, **kwargs):
            self.images.append(image_path)
            return '{"status":"agree"}'

    verifier = Verifier()
    extract_report_text(
        pdf,
        case_id="case-multi-audit",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai")),
        llm_client=PageOCRClient(),
        verifier_client=verifier,
        force=True,
    )
    assert len(verifier.images) == 2
    meta = json.loads((tmp_path / "ocr" / "case-multi-audit.ocr.json").read_text(encoding="utf-8"))
    assert [item["page_index"] for item in meta["quality_audit"]["pages"]] == [1, 2]


def test_ocr_verifier_preserves_original_page_numbers_across_blank_pages(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    for text in ("page one", None, "page three"):
        page = doc.new_page(width=300, height=200)
        # Draw marks rather than a text layer so the scanned-PDF OCR path runs.
        if text:
            page.draw_rect(fitz.Rect(10, 10, 11, 11), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(pdf)

    class Verifier:
        def call(self, prompt, image_path=None, **kwargs):
            return '{"status":"agree"}'

    meta_path = tmp_path / "ocr" / "case-page-numbers.ocr.json"
    extract_report_text(
        pdf,
        case_id="case-page-numbers",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai")),
        llm_client=PageOCRClient(),
        verifier_client=Verifier(),
        verifier_options={"provider": "chat_completions", "model": "qwen-vl-ocr-latest"},
        force=True,
    )
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert [item["page_index"] for item in meta["quality_audit"]["pages"]] == [1, 3]
    assert meta["verifier"] == {
        "provider": "chat_completions",
        "model": "qwen-vl-ocr-latest",
        "role": "ocr_verifier",
        "configured": True,
    }


def test_ocr_candidate_benchmark_scores_and_blocks_missing_artifacts(tmp_path: Path):
    manifest = tmp_path / "ocr_manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "case_id": "case1",
                    "gold_text": "FINDINGS: No nodule measuring 8 mm.",
                    "candidates": {"model-a": "FINDINGS: No nodule measuring 8 mm."},
                },
                {"case_id": "case2", "gold_text": "gold", "candidates": {"model-a": ""}},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")
    assert result["status"] == "completed_with_blockers"
    assert result["by_model"]["model-a"]["clinical_cer_mean"] == 0.0
    assert result["blocked_items"] == ["case2:model-a"]


def test_ocr_candidate_benchmark_blocks_missing_manifest(tmp_path: Path):
    result = evaluate_ocr_candidates(tmp_path / "does-not-exist.json", tmp_path / "summary.json")
    assert result["status"] == "blocked"
    assert result["selection"]["status"] == "blocked"


def test_ocr_candidate_benchmark_blocks_unequal_model_coverage(tmp_path: Path):
    manifest = tmp_path / "ocr_manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {"case_id": "case1", "gold_text": "same", "candidates": {"a": "same", "b": "same"}},
                {"case_id": "case2", "gold_text": "same", "candidates": {"a": "same", "b": ""}},
            ]
        ),
        encoding="utf-8",
    )
    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")
    assert result["status"] == "completed_with_blockers"
    assert result["selection"] == {
        "status": "blocked",
        "reason": "missing_gold_or_candidate_artifacts",
        "blocked_items": ["case2:b", "coverage:b"],
    }


def test_ocr_candidate_benchmark_reports_coverage_blocker_without_missing_artifact(tmp_path: Path):
    manifest = tmp_path / "ocr_manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {"case_id": "case1", "gold_text": "same", "candidates": {"a": "same", "b": "same"}},
                {"case_id": "case2", "gold_text": "same", "candidates": {"a": "same"}},
            ]
        ),
        encoding="utf-8",
    )
    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")
    assert result["selection"]["status"] == "blocked"
    assert result["selection"]["reason"] == "unequal_candidate_coverage"


def test_ocr_candidate_benchmark_blocks_duplicate_case_model_rows(tmp_path: Path):
    manifest = tmp_path / "ocr_manifest.jsonl"
    manifest.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"case_id": "case1", "gold_text": "same", "candidates": {"a": "same"}},
                {"case_id": "case1", "gold_text": "same", "candidates": {"a": "same"}},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")
    assert result["selection"]["reason"] == "duplicate_case_model_rows"
    assert result["selection"]["blocked_items"] == ["duplicate:case1:a"]


@pytest.mark.parametrize(
    ("field", "missing_value"),
    [
        ("gold_text", "missing_gold.txt"),
        ("candidate", "missing_candidate.txt"),
        ("gold_text", {"path": "missing_gold.txt"}),
        ("candidate", {"path": "missing_candidate.txt"}),
    ],
)
def test_ocr_candidate_benchmark_blocks_missing_declared_text_paths(
    tmp_path: Path, field: str, missing_value: object
):
    row = {
        "case_id": "case1",
        "gold_text": "gold text",
        "candidates": {"model-a": "candidate text"},
    }
    if field == "gold_text":
        row[field] = missing_value
    else:
        row["candidates"]["model-a"] = missing_value
    manifest = tmp_path / "ocr_manifest.json"
    manifest.write_text(json.dumps([row]), encoding="utf-8")

    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")

    assert result["status"] == "blocked"
    assert result["selection"]["status"] == "blocked"
    assert any("missing" in item for item in result["blocked_items"])
