from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.llm_client import LLMClient
from medharness2.schema import ReportTextResult


def extract_report_text(
    report_pdf: str | Path,
    case_id: str,
    *,
    output_dir: str | Path,
    config: AppConfig | None = None,
    llm_client: Any | None = None,
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
    direct_text = _extract_pdf_text(pdf)
    if len(direct_text.strip()) >= min_direct_chars:
        text = direct_text
        method = "pdf_text_layer"
        provider = "local_pdf_text"
    else:
        prompt = (
            "Extract the radiology report text from this scanned PDF. "
            "Return only the report body. Preserve Findings and Impression sections when present."
        )
        text = str(client.call(prompt, image_path=str(pdf), response_format="text")).strip()
        method = "vlm_ocr"
        provider = cfg.llm.provider
        if not text:
            warnings.append("empty_vlm_ocr_result")
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
    return method == "vlm_ocr" and bool(provider) and provider != "mock"
