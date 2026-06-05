from __future__ import annotations

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
) -> ReportTextResult:
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    pdf = Path(report_pdf)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = out_dir / f"{case_id}.txt"
    meta_path = out_dir / f"{case_id}.ocr.json"
    if cache_path.exists() and cache_path.read_text(encoding="utf-8").strip():
        return ReportTextResult(case_id=case_id, text=cache_path.read_text(encoding="utf-8"), method="cache", cache_path=str(cache_path))

    warnings: list[str] = []
    direct_text = _extract_pdf_text(pdf)
    if len(direct_text.strip()) >= min_direct_chars:
        text = direct_text
        method = "pdf_text_layer"
    else:
        prompt = (
            "Extract the radiology report text from this scanned PDF. "
            "Return only the report body. Preserve Findings and Impression sections when present."
        )
        text = str(client.call(prompt, image_path=str(pdf), response_format="text")).strip()
        method = "vlm_ocr"
        if not text:
            warnings.append("empty_vlm_ocr_result")
    cache_path.write_text(text + ("\n" if text and not text.endswith("\n") else ""), encoding="utf-8")
    meta_path.write_text(
        __import__("json").dumps(
            {"case_id": case_id, "method": method, "source_pdf": str(pdf), "warnings": warnings},
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
