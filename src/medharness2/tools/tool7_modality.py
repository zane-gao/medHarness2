from __future__ import annotations

from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.llm_client import LLMClient


def recognize_modality(image_path: str, config: AppConfig | None = None, llm_client: LLMClient | None = None) -> str:
    cfg = config or load_config()
    path = Path(image_path)
    detected = _detect_dicom_modality(path)
    if detected:
        return cfg.modality_map.get(detected, detected.lower())
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg"}:
        return "xray"
    if llm_client is not None:
        text = llm_client.call(
            "Identify imaging modality. Return one word such as CT, MR, DX, pathology.",
            image_path=image_path,
            payload_classification="raw_medical_image",
        )
        token = text.strip().split()[0].upper() if text.strip() else ""
        return cfg.modality_map.get(token, token.lower() or "unknown")
    return "unknown"


def _detect_dicom_modality(path: Path) -> str | None:
    try:
        import pydicom  # type: ignore
    except Exception:
        return None
    try:
        dataset = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
    except Exception:
        return None
    modality = getattr(dataset, "Modality", None)
    return str(modality).upper() if modality else None
