from __future__ import annotations

import json
import math
from pathlib import Path

import fitz
import pytest

from medharness2.config import AppConfig, LLMConfig, ModelRoleConfig
from medharness2.ocr import extract_report_text
from medharness2.ocr import _cache_metadata_valid
from medharness2.ocr_benchmark import _aggregate, evaluate_ocr_candidates


class PageOCRClient:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def call(self, prompt: str, image_path: str | None = None, **kwargs):
        assert image_path
        self.paths.append(image_path)
        return f"FINDINGS: page {len(self.paths)}\nIMPRESSION: stable"


def test_ocr_aggregate_excludes_non_finite_metric_rows():
    result = _aggregate(
        [
            {
                "case_id": "case1",
                "model": "model-a",
                "clinical_cer": math.nan,
                "digit_token_accuracy": math.inf,
                "negation_token_accuracy": 0.5,
                "possible_truncation": False,
            },
            {
                "case_id": "case2",
                "model": "model-a",
                "clinical_cer": 0.2,
                "digit_token_accuracy": 1.0,
                "negation_token_accuracy": 1.0,
                "possible_truncation": False,
            },
        ]
    )
    assert result["model-a"] == {
        "case_count": 1,
        "clinical_cer_mean": 0.2,
        "digit_token_accuracy_mean": 1.0,
        "negation_token_accuracy_mean": 1.0,
        "truncation_count": 0,
    }


@pytest.mark.parametrize("bad", [1, 0, "false", [], {}])
def test_ocr_aggregate_rejects_malformed_truncation_flag(bad):
    with pytest.raises(ValueError, match="possible_truncation"):
        _aggregate(
            [{
                "case_id": "case1",
                "model": "model-a",
                "clinical_cer": 0.2,
                "digit_token_accuracy": 1.0,
                "negation_token_accuracy": 1.0,
                "possible_truncation": bad,
            }]
        )


@pytest.mark.parametrize("field,bad", [("warnings", "bad"), ("verifier", []), ("quality_audit", "bad"), ("quality_status", "unknown")])
def test_ocr_cache_sidecar_rejects_malformed_metadata(field, bad):
    payload = {"warnings": [], "verifier": {"configured": False}, "quality_audit": None, "quality_status": "passed"}
    payload[field] = bad
    assert _cache_metadata_valid(payload) is False


def test_ocr_cache_compatibility_rejects_malformed_verifier_configured(tmp_path: Path):
    from medharness2.ocr import _cache_is_compatible

    assert _cache_is_compatible(
        {
            "source_pdf_sha256": "hash",
            "case_id": "case",
            "method": "vlm_ocr",
            "provider": "local",
            "model": "model",
            "role": "ocr",
            "prompt_version": "ocr-page-v2",
            "verifier": {"configured": "false"},
        },
        case_id="case",
        source_pdf_sha256="hash",
        provider="local",
        model="model",
        role="ocr",
        verifier_options={},
        require_real=False,
    ) is False


@pytest.mark.parametrize("quality_status", ["review_required", "blocked"])
def test_ocr_cache_compatibility_rejects_non_passed_quality_status(quality_status: str):
    from medharness2.ocr import _cache_is_compatible

    assert _cache_is_compatible(
        {
            "source_pdf_sha256": "hash",
            "case_id": "case",
            "method": "vlm_ocr",
            "provider": "openai",
            "model": "model",
            "role": "ocr",
            "prompt_version": "ocr-page-v2",
            "quality_status": quality_status,
            "verifier": {"configured": False},
        },
        case_id="case",
        source_pdf_sha256="hash",
        provider="openai",
        model="model",
        role="ocr",
        verifier_options={},
        require_real=False,
    ) is False


def test_ocr_cache_compatibility_rejects_stale_unconfigured_verifier_identity():
    from medharness2.ocr import _cache_is_compatible

    assert _cache_is_compatible(
        {
            "source_pdf_sha256": "hash",
            "case_id": "case",
            "method": "vlm_ocr",
            "provider": "openai",
            "model": "model",
            "role": "ocr",
            "prompt_version": "ocr-page-v2",
            "quality_status": "passed",
            "verifier": {"configured": False, "provider": "old", "model": "old", "role": "ocr_verifier"},
        },
        case_id="case",
        source_pdf_sha256="hash",
        provider="openai",
        model="model",
        role="ocr",
        verifier_options={},
        require_real=False,
    ) is False


@pytest.mark.parametrize("quality_status", ["passed", "review_required"])
def test_ocr_cache_sidecar_rejects_inconsistent_verifier_quality_status(quality_status: str):
    payload = {
        "warnings": [],
        "verifier": {"configured": True, "provider": "chat_completions", "model": "v", "role": "ocr_verifier"},
        "quality_audit": {"status": "disagreement"},
        "quality_status": quality_status,
    }
    from medharness2.ocr import _cache_metadata_valid

    assert _cache_metadata_valid(payload) is (quality_status == "review_required")


@pytest.mark.parametrize(
    "field",
    ["case_id", "source_pdf_sha256", "method", "provider", "model", "role", "prompt_version", "text_sha256"],
)
@pytest.mark.parametrize("bad", [1, True, [], {}])
def test_ocr_cache_sidecar_rejects_malformed_provenance_types(field: str, bad: object):
    payload = {
        "warnings": [],
        "verifier": {"configured": False},
        "quality_audit": None,
        "quality_status": "passed",
        field: bad,
    }
    assert _cache_metadata_valid(payload) is False


@pytest.mark.parametrize(
    "payload",
    [
        {"pages": "not-a-list"},
        {"pages": [{"char_count": "12"}]},
        {"pages": [{"ink_ratio": 2.0}]},
        {"page_count": True},
        {"source_page_count": 1, "retained_page_count": 2},
        {"quality_audit": {"pages": [{"status": "maybe"}]}},
        {"quality_audit": {"pages": []}},
        {"quality_audit": {"pages": [{"page_index": 1}]}},
    ],
)
def test_ocr_cache_sidecar_rejects_malformed_page_contracts(payload: dict[str, object]):
    base = {
        "warnings": [],
        "verifier": {"configured": False},
        "quality_audit": None,
        "quality_status": "passed",
    }
    base.update(payload)
    assert _cache_metadata_valid(base) is False


def test_ocr_cache_sidecar_requires_audit_when_verifier_is_configured():
    payload = {
        "warnings": [],
        "verifier": {
            "configured": True,
            "provider": "chat_completions",
            "model": "verifier-v1",
            "role": "ocr_verifier",
        },
        "quality_audit": None,
        "quality_status": "passed",
    }
    assert _cache_metadata_valid(payload) is False


def test_ocr_cache_does_not_reuse_blocked_quality_result(tmp_path: Path):
    pdf = tmp_path / "blocked-cache.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(10, 10, 11, 11), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(pdf)

    class TruncatedClient:
        def call(self, *args, **kwargs):
            return "FINDINGS: unfinished sentence"

    first = extract_report_text(
        pdf,
        case_id="case-blocked-cache",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai", model="ocr-v1")),
        llm_client=TruncatedClient(),
        force=True,
    )
    assert first.metadata["quality_status"] == "blocked"

    second = PageOCRClient()
    result = extract_report_text(
        pdf,
        case_id="case-blocked-cache",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai", model="ocr-v1")),
        llm_client=second,
    )
    assert result.method == "vlm_ocr"
    assert len(second.paths) == 1
    assert result.metadata["quality_status"] == "passed"


def test_ocr_cache_does_not_reuse_when_text_file_changes_after_sidecar(tmp_path: Path):
    pdf = tmp_path / "text-cache-integrity.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(10, 10, 11, 11), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(pdf)

    first = PageOCRClient()
    extract_report_text(
        pdf,
        case_id="case-text-integrity",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai", model="ocr-v1")),
        llm_client=first,
        force=True,
    )
    cache_path = tmp_path / "ocr" / "case-text-integrity.txt"
    cache_path.write_text("tampered report\n", encoding="utf-8")

    second = PageOCRClient()
    result = extract_report_text(
        pdf,
        case_id="case-text-integrity",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai", model="ocr-v1")),
        llm_client=second,
    )

    assert result.method == "vlm_ocr"
    assert len(second.paths) == 1
    assert result.text.startswith("FINDINGS: page 1")


def test_ocr_cache_invalid_utf8_is_treated_as_miss(tmp_path: Path):
    pdf = tmp_path / "invalid-cache.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(10, 10, 11, 11), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(pdf)
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    (ocr_dir / "case-invalid-cache.txt").write_bytes(b"\xff\xfe\xfa")

    client = PageOCRClient()
    result = extract_report_text(
        pdf,
        case_id="case-invalid-cache",
        output_dir=ocr_dir,
        config=AppConfig(llm=LLMConfig(provider="openai", model="ocr-v1")),
        llm_client=client,
    )

    assert result.method == "vlm_ocr"
    assert len(client.paths) == 1
    assert result.text.startswith("FINDINGS: page 1")


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


def test_direct_pdf_text_extraction_closes_document_and_preserves_text(tmp_path: Path):
    pdf = tmp_path / "text-layer.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((30, 60), "FINDINGS: Clear lungs. IMPRESSION: Normal.")
    doc.save(pdf)
    result = extract_report_text(pdf, case_id="text-layer", output_dir=tmp_path / "ocr", force=True)
    assert result.method == "pdf_text_layer"
    assert "Clear lungs" in result.text


def test_text_layer_ocr_runs_configured_verifier_audit(tmp_path: Path):
    """A text layer must not bypass the configured page-level visual audit."""
    pdf = tmp_path / "text-layer-audited.pdf"
    doc = fitz.open()
    for text in (
        "FINDINGS: Clear lungs. IMPRESSION: Normal.",
        "FINDINGS: No pleural effusion. IMPRESSION: Stable.",
    ):
        page = doc.new_page(width=300, height=200)
        page.insert_text((30, 60), text)
    doc.save(pdf)

    class Verifier:
        def __init__(self) -> None:
            self.images: list[str] = []

        def call(self, prompt, image_path=None, **kwargs):
            assert image_path
            self.images.append(image_path)
            return {"status": "disagreement", "reason": "audit only"}

    verifier = Verifier()
    result = extract_report_text(
        pdf,
        case_id="text-layer-audited",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="mock")),
        verifier_client=verifier,
        verifier_options={"provider": "chat_completions", "model": "verifier-v1"},
        force=True,
    )

    assert result.method == "pdf_text_layer"
    assert "Clear lungs" in result.text
    assert len(verifier.images) == 2
    assert result.metadata["quality_status"] == "review_required"
    assert [item["page_index"] for item in result.metadata["quality_audit"]["pages"]] == [1, 2]


def test_pdf_text_cache_is_not_reused_when_verifier_is_configured_but_missing(
    tmp_path: Path,
):
    """A primary-only text-layer cache must not bypass a newly required audit."""
    pdf = tmp_path / "text-layer-verifier.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((30, 60), "FINDINGS: Clear lungs. IMPRESSION: Normal.")
    doc.save(pdf)

    output_dir = tmp_path / "ocr"
    first = extract_report_text(
        pdf,
        case_id="text-layer-verifier",
        output_dir=output_dir,
        config=AppConfig(llm=LLMConfig(provider="mock")),
        force=True,
    )
    assert first.method == "pdf_text_layer"
    assert first.metadata["quality_status"] == "passed"

    second = extract_report_text(
        pdf,
        case_id="text-layer-verifier",
        output_dir=output_dir,
        config=AppConfig(
            llm=LLMConfig(provider="mock"),
            model_roles={
                "ocr_verifier": ModelRoleConfig(
                    provider="chat_completions",
                    model="qwen-vl-ocr-latest",
                    api_key_env="OCR_VERIFIER_KEY",
                )
            },
        ),
    )

    assert second.method == "pdf_text_layer"
    assert second.metadata["quality_status"] == "review_required"
    assert "ocr_verifier_client_missing" in second.warnings
    sidecar = json.loads(
        (output_dir / "text-layer-verifier.ocr.json").read_text(encoding="utf-8")
    )
    assert sidecar["quality_status"] == "review_required"


def test_pdf_text_cache_ignores_vlm_route_changes(tmp_path: Path):
    """Changing the VLM route must not invalidate deterministic text extraction."""
    pdf = tmp_path / "text-layer-route.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((30, 60), "FINDINGS: Clear lungs. IMPRESSION: Normal.")
    doc.save(pdf)

    output_dir = tmp_path / "ocr"
    extract_report_text(
        pdf,
        case_id="text-layer-route",
        output_dir=output_dir,
        config=AppConfig(llm=LLMConfig(provider="mock", model="old-model")),
        force=True,
    )

    class FailingClient:
        def call(self, *args, **kwargs):
            raise AssertionError("text-layer cache should be reused")

    result = extract_report_text(
        pdf,
        case_id="text-layer-route",
        output_dir=output_dir,
        config=AppConfig(llm=LLMConfig(provider="openai", model="new-model")),
        llm_client=FailingClient(),
    )

    assert result.method == "cache"


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


def test_require_real_ocr_does_not_reuse_default_cache_after_model_change(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.draw_rect(fitz.Rect(10, 10, 11, 11), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(pdf)

    class RecordingClient(PageOCRClient):
        pass

    first = RecordingClient()
    extract_report_text(
        pdf,
        case_id="case-model-cache",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai", model="model-a")),
        llm_client=first,
        require_real=True,
        force=True,
    )
    second = RecordingClient()
    result = extract_report_text(
        pdf,
        case_id="case-model-cache",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai", model="model-b")),
        llm_client=second,
        require_real=True,
    )

    assert result.method == "vlm_ocr"
    assert len(first.paths) == 1
    assert len(second.paths) == 1


def test_ocr_cache_does_not_reuse_when_verifier_route_changes(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(10, 10, 11, 11), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(pdf)

    first = PageOCRClient()
    class AgreeVerifier:
        def call(self, *args, **kwargs):
            return '{"status":"agree"}'

    extract_report_text(
        pdf,
        case_id="case-verifier-cache",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai", model="model-a")),
        llm_client=first,
        verifier_client=AgreeVerifier(),
        verifier_options={"provider": "chat_completions", "model": "verifier-a"},
        force=True,
    )
    second = PageOCRClient()
    result = extract_report_text(
        pdf,
        case_id="case-verifier-cache",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai", model="model-a")),
        llm_client=second,
    )

    assert result.method == "vlm_ocr"
    assert len(second.paths) == 1


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
    assert result.metadata["quality_status"] == "blocked"
    meta = json.loads((tmp_path / "ocr" / "case-truncated.ocr.json").read_text(encoding="utf-8"))
    assert "ocr_possible_truncation" in meta["warnings"]
    assert meta["quality_status"] == "blocked"


def test_complete_chinese_page_response_is_not_marked_truncated(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(10, 10, 11, 11), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(pdf)

    class ChineseOCRClient:
        def call(self, *args, **kwargs):
            return "检查所见：双肺未见异常。\n诊断印象：未见急性病变。"

    result = extract_report_text(
        pdf,
        case_id="case-chinese-complete",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai")),
        llm_client=ChineseOCRClient(),
        force=True,
    )

    assert "ocr_possible_truncation" not in result.warnings
    assert result.metadata["quality_status"] == "passed"


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
    assert meta["quality_status"] == "review_required"


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


def test_configured_ocr_verifier_without_client_requires_review(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(10, 10, 11, 11), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(pdf)

    result = extract_report_text(
        pdf,
        case_id="case-missing-verifier-client",
        output_dir=tmp_path / "ocr",
        config=AppConfig(
            llm=LLMConfig(provider="openai", model="ocr-v1"),
            model_roles={
                "ocr_verifier": ModelRoleConfig(
                    provider="chat_completions", model="verifier-v1"
                )
            },
        ),
        llm_client=PageOCRClient(),
        # The route is configured, but no verifier client is wired by caller.
    )

    assert result.text.startswith("FINDINGS: page 1")
    assert "ocr_verifier_client_missing" in result.warnings
    assert result.metadata["quality_status"] == "review_required"
    meta = json.loads((tmp_path / "ocr" / "case-missing-verifier-client.ocr.json").read_text(encoding="utf-8"))
    assert meta["quality_status"] == "review_required"
    assert meta["verifier"]["configured"] is False


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


def test_ocr_verifier_unknown_status_is_invalid_audit_response(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(10, 10, 11, 11), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(pdf)

    class UnknownVerifier:
        def call(self, *args, **kwargs):
            return '{"status":"maybe","reason":"unclear"}'

    result = extract_report_text(
        pdf,
        case_id="case-verifier-unknown-status",
        output_dir=tmp_path / "ocr",
        config=AppConfig(llm=LLMConfig(provider="openai")),
        llm_client=PageOCRClient(),
        verifier_client=UnknownVerifier(),
        force=True,
    )

    assert "ocr_verifier_invalid_response" in result.warnings
    assert result.metadata["quality_status"] == "review_required"


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


def test_ocr_candidate_benchmark_accepts_candidate_key_separate_from_provider_model(tmp_path: Path):
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps({
            "case_id": "case1",
            "modality": "cxr",
            "model_key": "ocr_primary_doubao",
            "model": "doubao-seed-2-1-pro-260628",
            "provider": "chat_completions",
            "role": "ocr_primary",
            "quality_status": "passed",
            "text": "FINDINGS: No nodule measuring 8 mm.",
        }),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{
        "case_id": "case1",
        "modality": "cxr",
        "gold_text": "FINDINGS: No nodule measuring 8 mm.",
        "candidate_routes": {
            "ocr_primary_doubao": {
                "provider": "chat_completions",
                "model": "doubao-seed-2-1-pro-260628",
                "role": "ocr_primary",
            }
        },
        "candidates": {"ocr_primary_doubao": {"path": "candidate.json"}},
    }]), encoding="utf-8")

    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")

    assert result["evaluated_count"] == 1
    assert result["blocked_items"] == []


def test_ocr_candidate_benchmark_blocks_missing_manifest(tmp_path: Path):
    result = evaluate_ocr_candidates(tmp_path / "does-not-exist.json", tmp_path / "summary.json")
    assert result["status"] == "blocked"
    assert result["blocked_items"] == ["manifest:missing_file"]
    assert result["selection"]["status"] == "blocked"


def test_ocr_candidate_benchmark_reports_empty_manifest_reason(tmp_path: Path):
    manifest = tmp_path / "empty.jsonl"
    manifest.write_text("", encoding="utf-8")

    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")

    assert result["status"] == "blocked"
    assert result["blocked_items"] == ["manifest:empty"]
    assert result["selection"]["reason"] == "invalid_manifest"


def test_ocr_candidate_benchmark_blocks_invalid_utf8_jsonl_manifest(tmp_path: Path):
    manifest = tmp_path / "ocr_manifest.jsonl"
    manifest.write_bytes(b'{"case_id":"case1"}\n\xff\n')

    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")

    assert result["status"] == "blocked"
    assert result["selection"]["status"] == "blocked"
    assert any("manifest:" in item for item in result["blocked_items"])


def test_ocr_candidate_benchmark_rejects_candidate_sidecar_for_different_case(tmp_path: Path):
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps({"case_id": "other-case", "text": "same"}),
        encoding="utf-8",
    )
    manifest = tmp_path / "ocr_manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "case_id": "case1",
                    "gold_text": "same",
                    "candidates": {"model-a": str(candidate)},
                }
            ]
        ),
        encoding="utf-8",
    )

    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")

    assert result["status"] == "blocked"
    assert result["selection"]["reason"] == "invalid_candidate_provenance"
    assert result["blocked_items"] == ["provenance:case1:model-a:case_id"]


@pytest.mark.parametrize("field", ["case_id", "model_key", "modality"])
@pytest.mark.parametrize("bad", [7, True, [], {"value": "x"}])
def test_ocr_candidate_benchmark_blocks_non_string_sidecar_identity(
    tmp_path: Path, field: str, bad: object
):
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps({"case_id": "case1", "model_key": "model-a", "modality": "cxr", "text": "same", field: bad}),
        encoding="utf-8",
    )
    manifest = tmp_path / "ocr_manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "case_id": "case1",
                    "gold_text": "same",
                    "modality": "cxr",
                    "candidates": {"model-a": str(candidate)},
                }
            ]
        ),
        encoding="utf-8",
    )

    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")

    assert result["status"] == "blocked"
    assert result["selection"]["reason"] == "invalid_candidate_provenance"
    assert any(item.endswith(f":{field}") for item in result["blocked_items"])


@pytest.mark.parametrize(
    ("quality_status", "reason"),
    [
        ("blocked", "ocr_quality_blocked"),
        ("review_required", "ocr_quality_review_required"),
    ],
)
def test_ocr_candidate_benchmark_excludes_low_quality_sidecars(tmp_path: Path, quality_status: str, reason: str):
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps({"case_id": "case1", "model_key": "model-a", "quality_status": quality_status, "text": "same"}),
        encoding="utf-8",
    )
    manifest = tmp_path / "ocr_manifest.json"
    manifest.write_text(
        json.dumps([{"case_id": "case1", "gold_text": "same", "candidates": {"model-a": str(candidate)}}]),
        encoding="utf-8",
    )

    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")

    assert result["status"] == "blocked"
    assert result["selection"]["reason"] == "invalid_candidate_provenance"
    assert result["blocked_items"] == [f"provenance:case1:model-a:{reason}"]


@pytest.mark.parametrize("quality_status", ["blocked", "review_required"])
def test_ocr_candidate_benchmark_rejects_low_quality_gold_sidecars(tmp_path: Path, quality_status: str):
    gold = tmp_path / "gold.json"
    gold.write_text(
        json.dumps({"case_id": "case1", "quality_status": quality_status, "text": "same"}),
        encoding="utf-8",
    )
    manifest = tmp_path / "ocr_manifest.json"
    manifest.write_text(
        json.dumps([{"case_id": "case1", "gold_text": str(gold), "candidates": {"model-a": "same"}}]),
        encoding="utf-8",
    )

    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")

    assert result["status"] == "blocked"
    assert result["blocked_items"] == [f"provenance:case1:gold:ocr_quality_{quality_status}"]


def test_ocr_candidate_benchmark_rejects_candidate_sidecar_for_different_model(tmp_path: Path):
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps({"case_id": "case1", "model_key": "model-b", "text": "same"}),
        encoding="utf-8",
    )
    manifest = tmp_path / "ocr_manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "case_id": "case1",
                    "gold_text": "same",
                    "candidates": {"model-a": str(candidate)},
                }
            ]
        ),
        encoding="utf-8",
    )

    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")

    assert result["status"] == "blocked"
    assert result["selection"]["reason"] == "invalid_candidate_provenance"
    assert result["blocked_items"] == ["provenance:case1:model-a:model_key"]


def test_ocr_candidate_benchmark_blocks_empty_model_key(tmp_path: Path):
    manifest = tmp_path / "ocr_manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "case_id": "case1",
                    "gold_text": "same",
                    "candidates": {"  ": "same"},
                }
            ]
        ),
        encoding="utf-8",
    )

    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")

    assert result["status"] == "blocked"
    assert result["selection"]["reason"] == "invalid_manifest"
    assert result["blocked_items"] == ["manifest:case1:empty_model_key"]


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


def test_ocr_candidate_benchmark_normalizes_model_keys_for_coverage(tmp_path: Path):
    manifest = tmp_path / "ocr_manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {"case_id": "case1", "gold_text": "same", "candidates": {" model-a ": "same", "model-b": "same"}},
                {"case_id": "case2", "gold_text": "same", "candidates": {" model-a ": "same", "model-b": "same"}},
            ]
        ),
        encoding="utf-8",
    )

    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")

    assert result["status"] == "succeeded"
    assert set(result["by_model"]) == {"model-a", "model-b"}
    assert result["selection"]["primary_model"] in {"model-a", "model-b"}


def test_ocr_candidate_benchmark_normalizes_case_id_for_provenance_and_coverage(tmp_path: Path):
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps({"case_id": "case1", "model_key": "model-a", "text": "same"}),
        encoding="utf-8",
    )
    manifest = tmp_path / "ocr_manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "case_id": " case1 ",
                    "gold_text": "same",
                    "candidates": {"model-a": str(candidate)},
                }
            ]
        ),
        encoding="utf-8",
    )

    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")

    assert result["status"] == "succeeded"
    assert result["evaluated_count"] == 1
    assert result["metrics"][0]["case_id"] == "case1"


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


def test_ocr_benchmark_ignores_clinical_history_when_scoring_clinical_sections(tmp_path: Path):
    manifest = tmp_path / "ocr_manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "case_id": "case-history",
                    "gold_text": "FINDINGS: nodule.\nCLINICAL HISTORY: patient one\nIMPRESSION: stable.",
                    "candidates": {
                        "model-a": "FINDINGS: nodule.\nCLINICAL HISTORY: patient two\nIMPRESSION: stable."
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")

    assert result["status"] == "succeeded"
    assert result["metrics"][0]["clinical_cer"] == 0.0
    assert result["metrics"][0]["clinical_text_source"] == "sections"


def test_ocr_candidate_benchmark_accepts_long_inline_gold_text(tmp_path: Path):
    gold = "检查所见：" + ("未见明显异常。" * 80) + "\n诊断印象：未见急性改变。"
    manifest = tmp_path / "ocr_manifest.json"
    manifest.write_text(
        json.dumps(
            [{"case_id": "case-long-inline", "gold_text": gold, "candidates": {"model-a": gold}}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")

    assert result["status"] == "succeeded"
    assert result["metrics"][0]["clinical_cer"] == 0.0

@pytest.mark.parametrize("bad", [True, 1, 1.5, ["text"], {"unexpected": "value"}])
def test_ocr_candidate_benchmark_blocks_non_text_inline_values(tmp_path: Path, bad):
    manifest = tmp_path / "ocr_manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "case_id": "case1",
                    "gold_text": "gold text",
                    "candidates": {"model-a": bad},
                }
            ]
        ),
        encoding="utf-8",
    )
    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")
    assert result["status"] == "blocked"
    assert "case1:model-a" in result["blocked_items"]

@pytest.mark.parametrize("bad_case_id", [True, 1, 1.5, {"id": "case1"}])
def test_ocr_candidate_benchmark_rejects_non_string_case_ids(tmp_path: Path, bad_case_id):
    manifest = tmp_path / "ocr_manifest.json"
    manifest.write_text(
        json.dumps([{"case_id": bad_case_id, "gold_text": "gold", "candidates": {"model-a": "gold"}}]),
        encoding="utf-8",
    )
    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")
    assert result["status"] == "blocked"


def test_ocr_candidate_benchmark_rejects_non_string_model_keys(tmp_path: Path):
    manifest = tmp_path / "ocr_manifest.json"
    manifest.write_text(
        json.dumps([{"case_id": "case1", "gold_text": "gold", "candidates": {"1": "gold"}}]),
        encoding="utf-8",
    )
    # JSON object keys are strings on disk; this is a valid model key and must remain supported.
    result = evaluate_ocr_candidates(manifest, tmp_path / "summary.json")
    assert result["status"] == "succeeded"
