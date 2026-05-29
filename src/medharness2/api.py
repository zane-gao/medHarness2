from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from medharness2.config import load_config
from medharness2.workflows.single_case import run_single_case


app = FastAPI(title="medHarness2 API", version="0.1.0")


class SingleCaseRequest(BaseModel):
    report_text: str | None = None
    report_path: str | None = None
    image_path: str
    output_path: str
    modality: str | None = None
    top_n: int | None = None
    model_keys: list[str] | None = None
    config_path: str | None = None


@app.post("/workflow/single-case")
def single_case(request: SingleCaseRequest) -> dict[str, Any]:
    if bool(request.report_text) == bool(request.report_path):
        raise HTTPException(status_code=400, detail="Provide exactly one of report_text or report_path.")
    cfg = load_config(request.config_path) if request.config_path else load_config()
    with tempfile.TemporaryDirectory(prefix="medharness2_api_") as tmpdir:
        report_path = Path(request.report_path) if request.report_path else Path(tmpdir) / "report.txt"
        if request.report_text is not None:
            report_path.write_text(request.report_text, encoding="utf-8")
        result = run_single_case(
            report_path=report_path,
            image_path=Path(request.image_path),
            output_path=Path(request.output_path),
            modality=request.modality,
            top_n=request.top_n,
            model_keys=request.model_keys,
            config=cfg,
        )
    return {
        "output_path": request.output_path,
        "summary": {
            "modality": result.get("input", {}).get("modality"),
            "generated_reports": len(result.get("generated_reports") or []),
            "pairwise_comparisons": len(result.get("pairwise_comparisons") or []),
            "rankings": len(result.get("rankings") or []),
        },
        "result": result,
    }
