from __future__ import annotations

from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, load_config
from medharness2.llm_client import LLMClient
from medharness2.modality import normalize_modality


def recognize_modality(image_path: str, config: AppConfig | None = None, llm_client: LLMClient | None = None) -> str:
    cfg = config or load_config()
    path = Path(image_path)
    detected = _detect_dicom_modality(path)
    if detected:
        return normalize_modality(cfg.modality_map.get(detected, detected))
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg"}:
        return "cxr"
    if llm_client is not None:
        text = llm_client.call(
            "Identify imaging modality. Return one word such as CT, MR, DX, pathology.",
            image_path=image_path,
            payload_classification="raw_medical_image",
        )
        token = _normalize_modality_token(text)
        return normalize_modality(cfg.modality_map.get(token, token))
    return "unknown"


def _normalize_modality_token(text: str) -> str:
    raw = str(text or "").strip().upper()
    if not raw:
        return ""
    canonical = normalize_modality(raw)
    if canonical in {"cxr", "ct", "mri"}:
        return {"cxr": "DX", "ct": "CT", "mri": "MR"}[canonical]
    compact = raw.replace("-", "").replace("_", "")
    for token in ("MRI", "MRA", "MR", "CT", "XRAY", "X RAY", "X-RAY", "DX", "CR", "XR"):
        if token.replace("-", "").replace(" ", "") in compact:
            return "MR" if token in {"MRI", "MRA", "MR"} else ("DX" if token in {"XRAY", "X RAY", "X-RAY", "DX", "CR", "XR"} else "CT")
    return raw.split()[0]


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
