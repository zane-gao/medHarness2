from __future__ import annotations

import json
import hashlib
import tempfile
from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.llm_client import LLMClient
from medharness2.schema import ReportTextResult


REAL_OCR_PROVIDERS = frozenset(
    {
        "openai",
        "openai_responses",
        "chat_completions",
        "openai_chat",
        "codex_proxy",
        "codex",
        "local_vlm_cli",
        "medharness_cli_vlm",
        "local_hf_vlm",
        "hf_vlm_local",
    }
)


def extract_report_text(
    report_pdf: str | Path,
    case_id: str,
    *,
    output_dir: str | Path,
    config: AppConfig | None = None,
    llm_client: Any | None = None,
    verifier_client: Any | None = None,
    verifier_options: dict[str, Any] | None = None,
    min_direct_chars: int = 20,
    require_real: bool = False,
    force: bool = False,
) -> ReportTextResult:
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    pdf = Path(report_pdf)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = out_dir / f"{case_id}.txt"
    meta_path = out_dir / f"{case_id}.ocr.json"
    if cache_path.exists() and cache_path.read_text(encoding="utf-8").strip() and not force:
        cached_meta = _read_meta(meta_path)
        if not require_real or _is_real_ocr_meta(cached_meta):
            return ReportTextResult(
                case_id=case_id,
                text=cache_path.read_text(encoding="utf-8"),
                method="cache",
                cache_path=str(cache_path),
                warnings=list(cached_meta.get("warnings") or []),
                metadata={"cached_ocr": cached_meta},
            )

    warnings: list[str] = []
    quality_audit: dict[str, Any] | None = None
    direct_text = _extract_pdf_text(pdf)
    if len(direct_text.strip()) >= min_direct_chars:
        text = direct_text
        method = "pdf_text_layer"
        provider = "local_pdf_text"
    else:
        if require_real and cfg.llm.provider.lower() not in REAL_OCR_PROVIDERS:
            raise RuntimeError(
                "require_real OCR needs a supported non-mock provider for scanned PDFs; "
                f"got {cfg.llm.provider!r}"
            )
        prompt = (
            "Transcribe this single radiology-report page exactly. Return only visible report text; "
            "preserve line order, punctuation, measurements, negation, Findings and Impression headings. "
            "Do not summarize, translate, infer, or add Markdown."
        )
        page_results: list[str] = []
        page_meta: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory(prefix=f"{case_id}-ocr-") as tmp_dir:
            rendered_pages = _render_pdf_pages(pdf, Path(tmp_dir))
            for page_index, image_path in enumerate(rendered_pages, start=1):
                page_text = str(
                    client.call(
                        prompt,
                        image_path=image_path,
                        response_format="text",
                        payload_classification="raw_medical_document",
                    )
                ).strip()
                page_results.append(page_text)
                page_meta.append(
                    {
                        "page_index": page_index,
                        "image_sha256": _sha256(Path(image_path)),
                        "text_sha256": _text_sha256(page_text),
                        "char_count": len(page_text),
                    }
                )
                if _looks_truncated(page_text):
                    warnings.append(f"ocr_possible_truncation:page_{page_index}")
            text = "\n\n".join(item for item in page_results if item).strip()
            if any(item.startswith("ocr_possible_truncation:") for item in warnings):
                warnings.append("ocr_possible_truncation")
            if verifier_client is not None and page_results:
                audit_prompt = (
                    "Audit this OCR transcription against the supplied report page. "
                    "Return JSON only with status (agree/disagreement), evidence spans, and short reason. "
                    "Do not rewrite or provide a replacement transcription.\n\nOCR:\n" + text
                )
                raw_audit = verifier_client.call(
                    audit_prompt,
                    image_path=rendered_pages[0],
                    response_format="json",
                    payload_classification="raw_medical_document",
                    **dict(verifier_options or {}),
                )
                try:
                    quality_audit = json.loads(str(raw_audit))
                except json.JSONDecodeError:
                    quality_audit = {"status": "invalid_verifier_response", "raw": str(raw_audit)[:500]}
        method = "vlm_ocr"
        provider = cfg.llm.provider
        if not text:
            warnings.append("empty_vlm_ocr_result")
        page_count = len(page_results)
    if method == "pdf_text_layer":
        page_meta = []
        page_count = 0
    cache_path.write_text(text + ("\n" if text and not text.endswith("\n") else ""), encoding="utf-8")
    meta_path.write_text(
        json.dumps(
            {
                "case_id": case_id,
                "method": method,
                "provider": provider,
                "model": cfg.llm.model if method == "vlm_ocr" else "",
                "source_pdf": str(pdf),
                "warnings": warnings,
                "page_count": page_count,
                "pages": page_meta,
                "source_pdf_sha256": _sha256(pdf),
                "prompt_version": "ocr-page-v2",
                "quality_audit": quality_audit,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return ReportTextResult(case_id=case_id, text=text, method=method, cache_path=str(cache_path), warnings=warnings)


def _extract_pdf_text(pdf: Path) -> str:
    try:
        import fitz
    except Exception:
        return ""
    try:
        doc = fitz.open(pdf)
    except Exception:
        return ""
    return "\n".join(page.get_text().strip() for page in doc).strip()


def _render_pdf_pages(pdf: Path, output_dir: Path) -> list[str]:
    try:
        import fitz
    except Exception as exc:
        raise RuntimeError("PyMuPDF is required for scanned PDF OCR") from exc
    doc = fitz.open(pdf)
    dpi = 300
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    paths: list[str] = []
    for index, page in enumerate(doc):
        path = output_dir / f"page_{index + 1:04d}.png"
        page.get_pixmap(matrix=matrix, alpha=False).save(path)
        paths.append(str(path))
    return paths


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _looks_truncated(text: str) -> bool:
    if not text:
        return True
    upper = text.upper()
    if "FINDINGS" not in upper and "IMPRESSION" not in upper:
        return True
    terminal = text.rstrip()[-1]
    return terminal.isalnum() and not text.rstrip().endswith(("stable", "normal", "negative"))


def _read_meta(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _is_real_ocr_meta(meta: dict[str, Any]) -> bool:
    method = str(meta.get("method") or "").lower()
    provider = str(meta.get("provider") or "").lower()
    if method == "pdf_text_layer" or provider == "local_pdf_text":
        return True
    return method == "vlm_ocr" and provider in REAL_OCR_PROVIDERS
