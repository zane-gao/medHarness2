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
    ocr_role: str = "ocr_primary",
    min_direct_chars: int = 20,
    require_real: bool = False,
    force: bool = False,
) -> ReportTextResult:
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    primary_options = _ocr_role_options(cfg, ocr_role)
    primary_provider = str(primary_options.get("provider") or cfg.llm.provider).lower()
    primary_model = str(primary_options.get("model") or cfg.llm.model)
    verifier_route = cfg.model_roles.get("ocr_verifier")
    effective_verifier_options = dict(verifier_options or {})
    if verifier_route is not None and not effective_verifier_options:
        effective_verifier_options = verifier_route.as_call_options()
    verifier_provider = str(effective_verifier_options.get("provider") or "").lower()
    verifier_model = str(effective_verifier_options.get("model") or "")
    verifier_role = "ocr_verifier" if verifier_route is not None or verifier_options else ""
    pdf = Path(report_pdf)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = out_dir / f"{case_id}.txt"
    meta_path = out_dir / f"{case_id}.ocr.json"
    source_pdf_sha256 = _sha256(pdf)
    source_page_count = _pdf_page_count(pdf)
    if cache_path.exists() and cache_path.read_text(encoding="utf-8").strip() and not force:
        cached_meta = _read_meta(meta_path)
        if _cache_metadata_valid(cached_meta) and _cache_is_compatible(
            cached_meta,
            case_id=case_id,
            source_pdf_sha256=source_pdf_sha256,
            provider=primary_provider,
            model=primary_model,
            role=ocr_role if primary_options else "default",
            verifier_options=effective_verifier_options,
            require_real=require_real,
        ):
            return ReportTextResult(
                case_id=case_id,
                text=cache_path.read_text(encoding="utf-8"),
                method="cache",
                cache_path=str(cache_path),
                warnings=list(cached_meta.get("warnings") or []),
                metadata={
                    "cached_ocr": cached_meta,
                    "quality_audit": cached_meta.get("quality_audit"),
                    "quality_status": cached_meta.get("quality_status") or _ocr_quality_status(
                        list(cached_meta.get("warnings") or []), cached_meta.get("quality_audit"), cache_path.read_text(encoding="utf-8")
                    ),
                },
            )

    warnings: list[str] = []
    quality_audit: dict[str, Any] | None = None
    direct_text = _extract_pdf_text(pdf)
    if len(direct_text.strip()) >= min_direct_chars:
        text = direct_text
        method = "pdf_text_layer"
        provider = "local_pdf_text"
    else:
        if require_real and primary_provider not in REAL_OCR_PROVIDERS:
            raise RuntimeError(
                "require_real OCR needs a supported non-mock provider for scanned PDFs; "
                f"got {primary_provider!r}"
            )
        prompt = (
            "Transcribe this single radiology-report page exactly. Return only visible report text; "
            "preserve line order, punctuation, measurements, negation, Findings and Impression headings. "
            "Do not summarize, translate, infer, or add Markdown."
        )
        page_results: list[str] = []
        page_meta: list[dict[str, Any]] = []
        retained_rendered_pages: list[str] = []
        retained_page_indices: list[int] = []
        with tempfile.TemporaryDirectory(prefix=f"{case_id}-ocr-") as tmp_dir:
            rendered_pages = _render_pdf_pages(pdf, Path(tmp_dir))
            for page_index, image_path in enumerate(rendered_pages, start=1):
                ink_ratio = _image_ink_ratio(Path(image_path))
                if _is_deterministic_blank_page(Path(image_path), ink_ratio):
                    page_meta.append(
                        {
                            "page_index": page_index,
                            "image_sha256": _sha256(Path(image_path)),
                            "text_sha256": _text_sha256(""),
                            "char_count": 0,
                            "ink_ratio": ink_ratio,
                            "skipped": True,
                            "skip_reason": "blank_page",
                        }
                    )
                    continue
                retained_rendered_pages.append(image_path)
                retained_page_indices.append(page_index)
                raw_page_text = client.call(
                    prompt,
                    image_path=image_path,
                    response_format="text",
                    payload_classification="raw_medical_document",
                    **primary_options,
                )
                page_text = raw_page_text.strip() if isinstance(raw_page_text, str) else ""
                if not page_text:
                    warnings.append(f"ocr_empty_page_response:page_{page_index}")
                page_results.append(page_text)
                page_meta.append(
                    {
                        "page_index": page_index,
                        "image_sha256": _sha256(Path(image_path)),
                        "text_sha256": _text_sha256(page_text),
                        "char_count": len(page_text),
                        "ink_ratio": ink_ratio,
                        "skipped": False,
                    }
                )
                if _looks_truncated(page_text):
                    warnings.append(f"ocr_possible_truncation:page_{page_index}")
            text = "\n\n".join(item for item in page_results if item).strip()
            if any(item.startswith("ocr_possible_truncation:") for item in warnings):
                warnings.append("ocr_possible_truncation")
            if verifier_client is not None and page_results and retained_rendered_pages:
                page_audits: list[dict[str, Any]] = []
                for page_index, page_text, image_path in zip(
                    retained_page_indices, page_results, retained_rendered_pages
                ):
                    audit_prompt = (
                        "Audit this OCR transcription against the supplied report page. "
                        "Return JSON only with status (agree/disagreement), evidence spans, and short reason. "
                        "Do not rewrite or provide a replacement transcription.\n\nOCR:\n" + page_text
                    )
                    try:
                        raw_audit = verifier_client.call(
                            audit_prompt,
                            image_path=image_path,
                            response_format="json",
                            payload_classification="raw_medical_document",
                            **effective_verifier_options,
                        )
                        try:
                            if isinstance(raw_audit, dict):
                                audit = raw_audit
                            elif isinstance(raw_audit, str):
                                audit = json.loads(raw_audit)
                            else:
                                raise TypeError("verifier response must be a JSON object")
                            if not isinstance(audit, dict):
                                raise TypeError("verifier response must be a JSON object")
                            status = str(audit.get("status") or "").strip().lower()
                            if status not in {"agree", "disagreement"}:
                                raise ValueError("verifier status must be agree or disagreement")
                            audit["status"] = status
                        except (TypeError, ValueError, json.JSONDecodeError):
                            audit = {"status": "invalid_verifier_response", "raw": str(raw_audit)[:500]}
                            warnings.append(f"ocr_verifier_invalid_response:page_{page_index}")
                            warnings.append("ocr_verifier_invalid_response")
                    except Exception as exc:
                        audit = {
                            "status": "verifier_failed",
                            "error_type": type(exc).__name__,
                            "error": str(exc)[:500],
                        }
                        warnings.append(f"ocr_verifier_failed:page_{page_index}")
                        warnings.append("ocr_verifier_failed")
                    page_audits.append({"page_index": page_index, **audit})
                quality_audit = page_audits[0] if len(page_audits) == 1 else {
                    "status": "completed",
                    "pages": page_audits,
                }
        method = "vlm_ocr"
        provider = primary_provider
        if not text:
            warnings.append("empty_vlm_ocr_result")
        retained_page_count = len(page_results)
    if method == "pdf_text_layer":
        page_meta = []
        retained_page_count = 0
    quality_status = _ocr_quality_status(warnings, quality_audit, text)
    if quality_status == "blocked":
        warnings.append("ocr_quality_blocked")
    elif quality_status == "review_required":
        warnings.append("ocr_quality_review_required")
    cache_path.write_text(text + ("\n" if text and not text.endswith("\n") else ""), encoding="utf-8")
    meta_path.write_text(
        json.dumps(
            {
                "case_id": case_id,
                "method": method,
                "provider": provider,
                "model": primary_model if method == "vlm_ocr" else "",
                "role": ocr_role if method == "vlm_ocr" and primary_options else "default",
                "verifier": {
                    "provider": verifier_provider,
                    "model": verifier_model,
                    "role": verifier_role,
                    "configured": verifier_client is not None,
                },
                "source_pdf": str(pdf),
                "warnings": warnings,
                # ``page_count`` is retained for compatibility and means the
                # number of pages sent through page-level OCR.  The explicit
                # fields remove the old ambiguity for downstream audits.
                "page_count": retained_page_count,
                "source_page_count": source_page_count,
                "retained_page_count": retained_page_count,
                "pages": page_meta,
                "source_pdf_sha256": source_pdf_sha256,
                "prompt_version": "ocr-page-v2",
                "quality_audit": quality_audit,
                "quality_status": quality_status,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return ReportTextResult(
        case_id=case_id,
        text=text,
        method=method,
        cache_path=str(cache_path),
        warnings=warnings,
        metadata={
            "provider": provider,
            "model": primary_model if method == "vlm_ocr" else "",
            "role": ocr_role if method == "vlm_ocr" and primary_options else "default",
            "source_pdf_sha256": source_pdf_sha256,
            "source_page_count": source_page_count,
            "retained_page_count": retained_page_count,
            "pages": page_meta,
            "verifier": {
                "provider": verifier_provider,
                "model": verifier_model,
                "role": verifier_role,
                "configured": verifier_client is not None,
            },
            "quality_audit": quality_audit,
            "quality_status": quality_status,
        },
    )


def _extract_pdf_text(pdf: Path) -> str:
    try:
        import fitz
    except Exception:
        return ""
    try:
        with fitz.open(pdf) as doc:
            return "\n".join(page.get_text().strip() for page in doc).strip()
    except Exception:
        return ""


def _ocr_role_options(config: AppConfig, role: str) -> dict[str, Any]:
    route = config.model_roles.get(role) if role else None
    return route.as_call_options() if route is not None else {}


def _cache_is_compatible(
    meta: dict[str, Any],
    *,
    case_id: str,
    source_pdf_sha256: str,
    provider: str,
    model: str,
    role: str,
    verifier_options: dict[str, Any],
    require_real: bool,
) -> bool:
    """Only reuse OCR text when its source and route provenance still match."""
    if not meta or meta.get("source_pdf_sha256") != source_pdf_sha256:
        return False
    # The cache filename is caller-controlled; bind the sidecar to the case as
    # well so a copied/renamed OCR artifact cannot cross case boundaries.
    cached_case_id = str(meta.get("case_id") or "")
    if not cached_case_id or cached_case_id != str(case_id):
        return False
    method = str(meta.get("method") or "").lower()
    if method == "pdf_text_layer":
        return meta.get("provider") == "local_pdf_text"
    if method != "vlm_ocr":
        return False
    if require_real and not _is_real_ocr_meta(meta):
        return False
    if str(meta.get("provider") or "").lower() != provider:
        return False
    cached_model = str(meta.get("model") or "")
    cached_role = str(meta.get("role") or "")
    if cached_role != role:
        return False
    # OCR sidecars are route-bound: a model change must force recomputation.
    # Same-model legacy caches remain compatible for backwards compatibility.
    if cached_model != model:
        return False
    if str(meta.get("prompt_version") or "") != "ocr-page-v2":
        return False
    expected_verifier = {
        "provider": str(verifier_options.get("provider") or "").lower(),
        "model": str(verifier_options.get("model") or ""),
    }
    cached_verifier = meta.get("verifier") or {}
    expected_verifier_configured = bool(expected_verifier["provider"] or expected_verifier["model"])
    cached_verifier_configured = cached_verifier.get("configured", False)
    if not isinstance(cached_verifier_configured, bool):
        return False
    if cached_verifier_configured != expected_verifier_configured:
        return False
    if expected_verifier_configured and (
        str(cached_verifier.get("provider") or "").lower() != expected_verifier["provider"]
        or str(cached_verifier.get("model") or "") != expected_verifier["model"]
    ):
        return False
    return True


def _cache_metadata_valid(meta: dict[str, Any]) -> bool:
    if not isinstance(meta, dict):
        return False
    for field in (
        "case_id",
        "source_pdf_sha256",
        "method",
        "provider",
        "model",
        "role",
        "prompt_version",
    ):
        if field in meta and meta[field] is not None and not isinstance(meta[field], str):
            return False
    warnings = meta.get("warnings", [])
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        return False
    verifier = meta.get("verifier", {})
    if not isinstance(verifier, dict):
        return False
    if "configured" in verifier and not isinstance(verifier["configured"], bool):
        return False
    for field in ("provider", "model", "role"):
        if field in verifier and verifier[field] is not None and not isinstance(verifier[field], str):
            return False
    audit = meta.get("quality_audit")
    if audit is not None and not isinstance(audit, dict):
        return False
    if isinstance(audit, dict) and "pages" in audit:
        pages = audit["pages"]
        if not isinstance(pages, list) or any(not isinstance(page, dict) for page in pages):
            return False
    status = meta.get("quality_status")
    if status is not None and status not in {"passed", "review_required", "blocked"}:
        return False
    return True


def _render_pdf_pages(pdf: Path, output_dir: Path) -> list[str]:
    try:
        import fitz
    except Exception as exc:
        raise RuntimeError("PyMuPDF is required for scanned PDF OCR") from exc
    dpi = 300
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    paths: list[str] = []
    with fitz.open(pdf) as doc:
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


def _pdf_page_count(pdf: Path) -> int:
    try:
        import fitz
    except Exception:
        return 0
    try:
        with fitz.open(pdf) as document:
            return len(document)
    except Exception:
        return 0


def _image_ink_ratio(path: Path) -> float:
    """Return the fraction of visibly dark pixels in a rendered page."""
    try:
        import fitz
    except Exception:
        return 1.0
    try:
        pixmap = fitz.Pixmap(str(path))
        channels = pixmap.n
        samples = pixmap.samples
        total = max(1, pixmap.width * pixmap.height)
        if channels == 1:
            dark = sum(1 for value in samples if value < 245)
        else:
            dark = sum(
                1
                for index in range(0, len(samples), channels)
                if max(samples[index : index + 3]) < 245
            )
        return round(dark / total, 6)
    except Exception:
        return 1.0


def _is_deterministic_blank_page(path: Path, ink_ratio: float) -> bool:
    """Skip only pages that are safely blank, preserving sparse small pages."""
    # A fixed 0.01 ratio incorrectly drops sparse but clinically valid pages
    # (for example a short one-line impression). Only an exactly white render
    # is deterministic evidence of a blank page; low-ink pages remain eligible
    # for OCR and can be flagged by the normal truncation/quality checks.
    return ink_ratio == 0.0


def _looks_truncated(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped[-1] in "。！？.!?)]】}」』”\"'":
        return False
    if len(stripped) < 8:
        return True
    return stripped[-1].isascii() and stripped[-1].isalnum() and not stripped.lower().endswith(
        ("stable", "normal", "negative", "正常")
    )


def _ocr_quality_status(
    warnings: list[str], quality_audit: dict[str, Any] | None, text: str,
) -> str:
    """Classify OCR evidence without silently upgrading weak text to usable input."""
    warning_set = {str(item) for item in warnings}
    if not text.strip() or "empty_vlm_ocr_result" in warning_set or any(
        item.startswith("ocr_possible_truncation") for item in warning_set
    ):
        return "blocked"
    audit_statuses: list[str] = []
    if isinstance(quality_audit, dict):
        pages = quality_audit.get("pages")
        if isinstance(pages, list):
            audit_statuses = [str(item.get("status") or "").lower() for item in pages if isinstance(item, dict)]
        else:
            audit_statuses = [str(quality_audit.get("status") or "").lower()]
    if any(status in {"disagreement", "verifier_failed", "invalid_verifier_response"} for status in audit_statuses):
        return "review_required"
    return "passed"


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
