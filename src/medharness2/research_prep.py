from __future__ import annotations

import json
import copy
import hashlib
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from medharness2.modality import normalize_modality
from medharness2.annotation import validate_pilot_annotation_package
from medharness2.annotation.models import AnnotationCase
from medharness2.utils.io import read_json
from medharness2.config import AppConfig, PROJECT_ROOT, load_config
from medharness2.llm_client import LLMClient
from medharness2 import ocr as ocr_module
from medharness2.ocr import extract_report_text
from medharness2.ocr_benchmark import evaluate_ocr_candidates

# Keep the renderer patchable for provider integration tests while resolving
# it from the OCR module at runtime in production.
_render_pdf_pages = ocr_module._render_pdf_pages


OCR_CANDIDATES = (
    {"candidate_id": "ocr_primary_doubao", "provider": "chat_completions", "model": "doubao-seed-2-1-pro-260628", "role": "ocr_primary"},
    {"candidate_id": "ocr_verifier_qwen", "provider": "chat_completions", "model": "qwen-vl-ocr-latest", "role": "ocr_verifier"},
    {"candidate_id": "ocr_baseline_paddle", "provider": "paddleocr", "model": "PaddleOCR-VL-1.6", "role": "ocr_baseline"},
)
# Only OCR-producing routes are scored.  The Qwen route is an external
# audit-only quality check and must not create a missing-candidate blocker in
# the text benchmark.
OCR_BENCHMARK_CANDIDATES = tuple(
    candidate for candidate in OCR_CANDIDATES if candidate["role"] != "ocr_verifier"
)

# The Beichuan reference reports are the current engineering benchmark gold.
# Clinical reader labels remain a separate calibration layer.
CURRENT_GOLD_SOURCE = "beichuan_reference_report"
CURRENT_GOLD_STATUS = "available_for_current_benchmark"


def run_ocr_research(
    pilot_dir: str | Path,
    research_dir: str | Path,
    *,
    config_path: str | Path | None = None,
    source_root: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Execute the frozen OCR candidate manifest without fabricating evidence.

    Every declared case/repeat/candidate receives a JSON sidecar.  Provider,
    source-asset, or quality failures are represented as ``blocked`` or
    ``review_required`` sidecars and never converted into candidate text.
    """
    pilot = Path(pilot_dir)
    research = Path(research_dir)
    manifest_result = prepare_research_manifests(pilot, research)
    cfg = load_config(config_path) if config_path else load_config()
    root = Path(source_root) if source_root else PROJECT_ROOT.parent / "medHarness"
    source_index = _build_source_pdf_index(root)
    route_status = _ocr_candidate_readiness(cfg)
    blocked_reasons: list[str] = []
    if not route_status["ocr_primary_doubao"]["ready"]:
        blocked_reasons.append("real_ocr_provider_unavailable")
    if not route_status["ocr_verifier_qwen"]["ready"]:
        blocked_reasons.append("real_ocr_verifier_unavailable")
    client = LLMClient(cfg) if any(item["ready"] for item in route_status.values()) else None
    blocked_count = 0
    review_count = 0
    success_count = 0
    audit_success_count = 0
    audit_review_count = 0
    audit_blocked_count = 0
    pilot_rows = _read_pilot_rows(pilot)
    run_payloads: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in pilot_rows:
        case_id = str(row["pilot_case_id"])
        if not _safe_case_component(case_id):
            raise ValueError(f"pilot_case_id_unsafe_path:{case_id}")
        case = AnnotationCase.model_validate_json((pilot / row["annotation_path"]).read_text(encoding="utf-8"))
        source_pdf = source_index.get(case.source_case_sha256)
        source_pdf_hash: str | None = None
        source_pdf_hash_error = False
        if source_pdf is not None:
            try:
                source_pdf_hash = _hash_file(source_pdf)
            except (OSError, UnicodeError):
                source_pdf_hash_error = True
        for repeat in (1, 2):
            primary_payload: dict[str, Any] | None = None
            for candidate in OCR_CANDIDATES:
                candidate_id = candidate["candidate_id"]
                sidecar_path = research / "ocr_runs" / f"repeat_{repeat}" / case_id / f"{candidate_id}.json"
                sidecar_path.parent.mkdir(parents=True, exist_ok=True)
                payload = _blocked_ocr_sidecar(case, candidate, repeat, reason=None)
                payload["model"] = _candidate_model_name(cfg, candidate)
                payload["model_key"] = candidate_id
                payload["execution_mode"] = (
                    "audit_only" if candidate["role"] == "ocr_verifier" else "primary_ocr"
                )
                if source_pdf is not None:
                    payload["source_pdf"] = str(source_pdf)
                    if source_pdf_hash is not None:
                        payload["source_pdf_sha256"] = source_pdf_hash
                readiness = route_status[candidate_id]
                if candidate["role"] == "ocr_verifier":
                    # Qwen is an audit-only external multimodal check.  It is
                    # never scored as an independent OCR transcription and
                    # must not be routed through the primary OCR role.
                    reasons: list[str] = []
                    if source_pdf is None:
                        reasons.append("source_pdf_missing")
                    elif source_pdf_hash_error:
                        reasons.append("source_pdf_unreadable")
                    elif not readiness["ready"]:
                        reasons.append(readiness["reason"])
                    if primary_payload is not None:
                        audit = (primary_payload.get("metadata") or {}).get("quality_audit")
                        if audit is not None:
                            payload["quality_audit"] = audit
                        payload["audit_target_sidecar"] = str(
                            research / "ocr_runs" / f"repeat_{repeat}" / case_id / "ocr_primary_doubao.json"
                        )
                        if not reasons and audit is not None:
                            audit_status = _audit_quality_status(audit)
                            payload["status"] = "succeeded" if audit_status == "passed" else "review_required"
                            payload["quality_status"] = audit_status
                            payload["blocked_reasons"] = (
                                [] if audit_status == "passed" else ["verifier_audit_review_required"]
                            )
                            if audit_status == "passed":
                                audit_success_count += 1
                            else:
                                audit_review_count += 1
                        else:
                            payload["blocked_reasons"] = reasons or ["primary_ocr_audit_missing"]
                            payload["status"] = "blocked"
                            payload["quality_status"] = "blocked"
                            audit_blocked_count += 1
                    else:
                        payload["blocked_reasons"] = reasons or ["primary_ocr_audit_missing"]
                        payload["status"] = "blocked"
                        payload["quality_status"] = "blocked"
                        audit_blocked_count += 1
                elif source_pdf is None or source_pdf_hash_error:
                    payload["status"] = "blocked"
                    payload["blocked_reasons"] = [
                        "source_pdf_unreadable" if source_pdf_hash_error else "source_pdf_missing"
                    ]
                    blocked_count += 1
                elif candidate["provider"] == "paddleocr":
                    try:
                        result = _run_paddleocr_candidate(
                            source_pdf,
                            case_id=case_id,
                            output_dir=research / "ocr_cache" / candidate_id / f"repeat_{repeat}",
                            verifier_ready=route_status["ocr_verifier_qwen"]["ready"],
                            verifier_client=client if route_status["ocr_verifier_qwen"]["ready"] else None,
                            verifier_options=_verifier_candidate_options(cfg),
                        )
                        result = _validate_paddleocr_result(result)
                        metadata = result["metadata"]
                        quality = metadata["quality_status"]
                        audit = metadata.get("quality_audit")
                        # A ready route is only configuration evidence.  A
                        # Paddle transcription cannot pass without actual
                        # page-level Qwen audit evidence in this result.
                        if quality == "passed" and not _paddle_audit_passed(audit):
                            quality = "review_required"
                            metadata["quality_status"] = quality
                            metadata["quality_gate"] = "verifier_audit_missing"
                            result["warnings"].append("ocr_verifier_audit_missing")
                        if quality == "passed" and not route_status["ocr_verifier_qwen"]["ready"]:
                            quality = "review_required"
                            metadata["quality_status"] = quality
                            metadata["quality_gate"] = "verifier_not_ready"
                            result["warnings"].append("ocr_verifier_not_ready")
                        payload.update({
                            "status": "succeeded" if quality == "passed" else quality,
                            "text": result["text"] if quality in {"passed", "review_required"} else "",
                            "warnings": result["warnings"],
                            "quality_status": quality,
                            "metadata": metadata,
                        })
                        if quality == "passed":
                            success_count += 1
                        elif quality == "review_required":
                            review_count += 1
                        else:
                            blocked_count += 1
                    except Exception as exc:
                        payload["status"] = "blocked"
                        reason = str(exc) if str(exc) in {
                            "paddleocr_provider_unavailable",
                            "paddle_runtime_unavailable",
                            "paddleocr_no_rendered_pages",
                            "paddleocr_empty_result",
                            "paddleocr_invalid_result",
                            "paddleocr_invalid_text",
                            "paddleocr_invalid_warnings",
                            "paddleocr_invalid_metadata",
                            "paddleocr_invalid_quality_status",
                            "paddleocr_invalid_quality_audit",
                        } else f"provider_error:{type(exc).__name__}"
                        payload["blocked_reasons"] = [reason]
                        payload["error"] = str(exc)[:500]
                        blocked_count += 1
                elif not readiness["ready"]:
                    payload["status"] = "blocked"
                    payload["blocked_reasons"] = [readiness["reason"]]
                    blocked_count += 1
                else:
                    try:
                        verifier_ready = route_status["ocr_verifier_qwen"]["ready"]
                        call_cfg = _primary_candidate_config(
                            cfg,
                            candidate["role"],
                            include_verifier=True,
                        )
                        result = extract_report_text(
                            source_pdf,
                            case_id,
                            output_dir=research / "ocr_cache" / candidate_id / f"repeat_{repeat}",
                            config=call_cfg,
                            llm_client=client,
                            verifier_client=client if verifier_ready else None,
                            ocr_role="ocr_primary",
                            require_real=True,
                            force=force,
                        )
                        quality = (result.metadata or {}).get("quality_status") or "blocked"
                        payload.update({
                            "status": "succeeded" if quality == "passed" else quality,
                            "text": result.text if quality in {"passed", "review_required"} else "",
                            "warnings": list(result.warnings),
                            "quality_status": quality,
                            "metadata": dict(result.metadata or {}),
                        })
                        payload["model"] = _candidate_model_name(cfg, candidate)
                        payload["model_key"] = candidate_id
                        if quality == "passed":
                            success_count += 1
                        elif quality == "review_required":
                            review_count += 1
                        else:
                            blocked_count += 1
                    except Exception as exc:
                        payload["status"] = "blocked"
                        payload["blocked_reasons"] = [f"provider_error:{type(exc).__name__}"]
                        payload["error"] = str(exc)[:500]
                        blocked_count += 1
                if candidate["role"] == "ocr_primary":
                    primary_payload = payload
                run_payloads[(case_id, candidate_id, repeat)] = payload
                sidecar_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    benchmark_results: dict[str, dict[str, Any]] = {}
    _synchronize_benchmark_routes(research, cfg)
    for repeat, name in ((1, "ocr_benchmark_repeat_1.json"), (2, "ocr_benchmark_repeat_2.json")):
        manifest_path = research / name
        result_path = research / f"{manifest_path.stem}_result.json"
        benchmark_results[str(repeat)] = evaluate_ocr_candidates(manifest_path, result_path)
    status = "succeeded" if success_count and not blocked_count and not review_count else "blocked"
    benchmark_summary = {
        key: {"status": value.get("status"), "selection": value.get("selection", {})}
        for key, value in benchmark_results.items()
    }
    run_summary = {
        "status": status,
        "case_count": len(pilot_rows),
        "candidate_count": len(OCR_CANDIDATES),
        "repeat_count": 2,
        "success_count": success_count,
        "review_required_count": review_count,
        "blocked_count": blocked_count,
        "audit_success_count": audit_success_count,
        "audit_review_required_count": audit_review_count,
        "audit_blocked_count": audit_blocked_count,
        "blocked_reasons": sorted(set(blocked_reasons + _collect_blocked_reasons(research))),
        "benchmark_results": benchmark_summary,
    }
    _persist_ocr_run_state(research, run_payloads, cfg, run_summary, benchmark_results)
    return {
        "status": status,
        "case_count": len(pilot_rows),
        "candidate_count": len(OCR_CANDIDATES),
        "repeat_count": 2,
        "success_count": success_count,
        "review_required_count": review_count,
        "blocked_count": blocked_count,
        "blocked_reasons": run_summary["blocked_reasons"],
        "benchmark_results": benchmark_summary,
        "research_dir": str(research),
    }


def _read_pilot_rows(pilot: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (pilot / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def _canonical_payload_sha256(payload: dict[str, Any]) -> str:
    """Return the same source hash used by the blinded pilot builder."""
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_source_pdf_index(source_root: Path) -> dict[str, Path]:
    """Map an exact pilot source hash to a report PDF, failing closed on ambiguity.

    ``source_root`` may be the medHarness project root, its ``data`` folder,
    or one concrete ``sample_data_*`` folder.  The hash remains the only case
    identity join; a PDF is never selected by a blinded case number alone.
    """
    root = Path(source_root)
    if not root.exists():
        return {}
    if (root / "report.pdf").is_file():
        pdfs = [root / "report.pdf"]
    elif root.name.startswith("sample_data_"):
        pdfs = sorted(root.glob("**/report.pdf"))
    else:
        pdfs = sorted(root.glob("data/sample_data*/**/report.pdf"))
        if not pdfs:
            pdfs = sorted(root.glob("sample_data*/**/report.pdf"))
    if not pdfs:
        return {}

    workflow_roots: list[Path] = []
    for candidate in (
        PROJECT_ROOT,
        root,
        root.parent,
        root.parent.parent,
    ):
        candidate = candidate.resolve()
        if candidate not in workflow_roots:
            workflow_roots.append(candidate)
    case_payloads: dict[str, list[dict[str, Any]]] = {}
    for workflow_root in workflow_roots:
        outputs = workflow_root / "outputs"
        if not outputs.is_dir():
            continue
        for case_json in outputs.glob("**/workflow2_cases/*.json"):
            case_id = case_json.stem
            try:
                payload = json.loads(case_json.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                continue
            if isinstance(payload, dict):
                case_payloads.setdefault(case_id, []).append(payload)

    by_hash: dict[str, Path] = {}
    ambiguous: set[str] = set()
    for pdf in pdfs:
        case_id = pdf.parent.name
        for payload in case_payloads.get(case_id, []):
            digest = _canonical_payload_sha256(payload)
            previous = by_hash.get(digest)
            if previous is not None and previous != pdf:
                ambiguous.add(digest)
            else:
                by_hash[digest] = pdf
    for digest in ambiguous:
        by_hash.pop(digest, None)
    return by_hash


def _ocr_candidate_readiness(config: AppConfig) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for candidate in OCR_CANDIDATES:
        if candidate["provider"] == "paddleocr":
            try:
                from paddleocr import PaddleOCRVL  # type: ignore[import-not-found,unused-ignore]
                del PaddleOCRVL
            except Exception:
                result[candidate["candidate_id"]] = {
                    "ready": False,
                    "reason": "paddleocr_provider_unavailable",
                }
                continue
            try:
                import paddle  # type: ignore[import-not-found,unused-ignore]
                del paddle
            except Exception:
                result[candidate["candidate_id"]] = {
                    "ready": False,
                    "reason": "paddle_runtime_unavailable",
                }
            else:
                result[candidate["candidate_id"]] = {"ready": True, "reason": ""}
            continue
        route = config.model_roles.get(candidate["role"])
        provider = str(route.provider if route and route.provider else "").lower()
        api_env = str(route.api_key_env if route else "")
        ready = provider == candidate["provider"] and bool(api_env and str(os.environ.get(api_env) or "").strip())
        result[candidate["candidate_id"]] = {"ready": ready, "reason": "missing_api_key" if not ready else ""}
    return result


def _primary_candidate_config(
    config: AppConfig,
    role: str,
    *,
    include_verifier: bool = False,
) -> AppConfig:
    cloned = copy.deepcopy(config)
    route = cloned.model_roles.get(role)
    cloned.model_roles = {"ocr_primary": route} if route is not None else {}
    if include_verifier and "ocr_verifier" in config.model_roles:
        cloned.model_roles["ocr_verifier"] = copy.deepcopy(config.model_roles["ocr_verifier"])
    return cloned


def _candidate_model_name(config: AppConfig, candidate: dict[str, Any]) -> str:
    role = str(candidate.get("role") or "")
    route = config.model_roles.get(role)
    if route is not None and str(route.model or "").strip():
        return str(route.model)
    return str(candidate.get("model") or "")


def _verifier_candidate_options(config: AppConfig) -> dict[str, Any]:
    route = config.model_roles.get("ocr_verifier")
    return route.as_call_options() if route is not None else {}


def _blocked_ocr_sidecar(case: AnnotationCase, candidate: dict[str, Any], repeat: int, reason: str | None) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "artifact_type": "ocr_candidate_sidecar",
        "status": "blocked",
        "case_id": case.pilot_case_id,
        "modality": normalize_modality(case.modality),
        "repeat": repeat,
        "model": candidate["candidate_id"],
        "provider": candidate["provider"],
        "role": candidate["role"],
        "source_case_sha256": case.source_case_sha256,
        "quality_status": "blocked",
        "text": "",
        "blocked_reasons": [reason] if reason else [],
    }


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_blocked_reasons(research: Path) -> list[str]:
    reasons: list[str] = []
    for path in research.glob("ocr_runs/repeat_*/**/*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        reasons.extend(str(item) for item in payload.get("blocked_reasons") or [])
    return reasons


def _audit_quality_status(audit: Any) -> str:
    """Translate verifier audit evidence without treating it as OCR text."""
    if not isinstance(audit, dict):
        return "blocked"
    statuses: list[str] = []
    pages = audit.get("pages")
    if isinstance(pages, list):
        if not pages or any(not isinstance(item, dict) for item in pages):
            return "blocked"
        statuses = [str(item.get("status") or "").strip().lower() for item in pages]
    else:
        statuses = [str(audit.get("status") or "").strip().lower()]
    if statuses and all(status == "agree" for status in statuses):
        return "passed"
    if any(status in {"disagreement", "verifier_failed", "invalid_verifier_response"} for status in statuses):
        return "review_required"
    return "blocked"


def _run_paddleocr_candidate(
    report_pdf: Path,
    *,
    case_id: str,
    output_dir: Path,
    verifier_ready: bool,
    verifier_client: Any | None = None,
    verifier_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the optional official PaddleOCR pipeline on rendered PDF pages.

    PaddleOCR is intentionally an optional dependency.  Missing packages or
    unsupported API responses become explicit blocked results at the caller.
    """
    try:
        from paddleocr import PaddleOCRVL  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError("paddleocr_provider_unavailable") from exc
    try:
        import paddle  # type: ignore[import-not-found]
        del paddle
    except Exception as exc:
        raise RuntimeError("paddle_runtime_unavailable") from exc
    if not report_pdf.is_file():
        raise RuntimeError("paddleocr_source_pdf_missing")
    output_dir.mkdir(parents=True, exist_ok=True)
    page_dir = output_dir / f"{case_id}_pages"
    page_dir.mkdir(parents=True, exist_ok=True)
    pages = _render_pdf_pages(report_pdf, page_dir)
    if not pages:
        raise RuntimeError("paddleocr_no_rendered_pages")
    engine = PaddleOCRVL(pipeline_version="v1.6")
    texts: list[str] = []
    page_audits: list[dict[str, Any]] = []
    empty_page_seen = False
    try:
        markdown_root = output_dir / f"{case_id}_markdown"
        markdown_root.mkdir(parents=True, exist_ok=True)
        for page_index, page in enumerate(pages, start=1):
            result = engine.predict(page)
            # The official API returns an iterable of Result objects, not
            # necessarily a list.  Consume it once so generators are not
            # mistaken for an empty unsupported response.
            if isinstance(result, (str, dict, list, tuple)):
                result_items: Any = result
            elif isinstance(result, Iterable):
                result_items = list(result)
            else:
                result_items = result
            page_markdown_dir = markdown_root / f"page_{page_index:04d}"
            page_markdown_dir.mkdir(parents=True, exist_ok=True)
            page_text = _paddleocr_text(
                result_items,
                markdown_dir=page_markdown_dir,
                page_index=page_index,
            )
            if page_text:
                texts.append(page_text)
                if verifier_client is not None and verifier_ready:
                    audit_prompt = (
                        "Audit this OCR transcription against the supplied report page. "
                        "Return JSON only with status (agree/disagreement), evidence spans, and short reason. "
                        "Do not rewrite or provide a replacement transcription.\n\nOCR:\n" + page_text
                    )
                    try:
                        raw_audit = verifier_client.call(
                            audit_prompt,
                            image_path=page,
                            response_format="json",
                            payload_classification="raw_medical_document",
                            **(verifier_options or {}),
                        )
                        if isinstance(raw_audit, dict):
                            audit = dict(raw_audit)
                        elif isinstance(raw_audit, str):
                            parsed = json.loads(raw_audit)
                            if not isinstance(parsed, dict):
                                raise TypeError("verifier response must be a JSON object")
                            audit = parsed
                        else:
                            raise TypeError("verifier response must be a JSON object")
                        status = str(audit.get("status") or "").strip().lower()
                        if status not in {"agree", "disagreement"}:
                            raise ValueError("verifier status must be agree or disagreement")
                        audit["status"] = status
                    except json.JSONDecodeError:
                        audit = {"status": "invalid_verifier_response"}
                    except Exception as exc:
                        audit = {
                            "status": "verifier_failed",
                            "error_type": type(exc).__name__,
                            "error": str(exc)[:500],
                        }
                    page_audits.append({"page_index": page_index, **audit})
            else:
                # An omitted page is not covered by agreement on the other
                # pages.  Keep the final gate review_required even if Qwen
                # agrees with every non-empty page.
                empty_page_seen = True
    finally:
        close = getattr(engine, "close", None)
        if callable(close):
            close()
    text = "\n\n".join(texts).strip()
    if not text:
        raise RuntimeError("paddleocr_empty_result")
    package_version = ""
    try:
        import paddleocr
        package_version = str(getattr(paddleocr, "__version__", ""))
    except Exception:
        pass
    return {
        "text": text,
        "warnings": [],
        "metadata": {
            "provider": "paddleocr",
            "model": "PaddleOCR-VL-1.6",
            "role": "ocr_baseline",
            "quality_status": (
                "passed"
                if not empty_page_seen and _paddle_audit_passed({"pages": page_audits})
                else "review_required"
            ),
            "quality_gate": "verifier_audit" if page_audits else "verifier_not_run",
            "quality_audit": ({"pages": page_audits} if page_audits else None),
            "empty_page_count": int(empty_page_seen),
            "page_count": len(pages),
            "pipeline_version": "v1.6",
            "paddleocr_version": package_version,
        },
    }


def _paddleocr_text(
    result: Any,
    *,
    markdown_dir: Path | None = None,
    page_index: int = 1,
) -> str:
    """Extract Markdown/text from current PaddleOCR-VL result shapes."""
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, (list, tuple)):
        return "\n".join(
            part
            for part in (
                _paddleocr_text(
                    item,
                    markdown_dir=markdown_dir,
                    page_index=page_index,
                )
                for item in result
            )
            if part
        )
    if isinstance(result, Iterable) and not isinstance(result, (dict, bytes, bytearray)):
        return _paddleocr_text(
            list(result),
            markdown_dir=markdown_dir,
            page_index=page_index,
        )
    if isinstance(result, dict):
        for key in ("markdown_text", "markdown_texts", "text", "ocr_text", "markdown", "rec_texts", "texts"):
            if key in result:
                text = _paddleocr_text(
                    result[key],
                    markdown_dir=markdown_dir,
                    page_index=page_index,
                )
                if text:
                    return text
        blocks = result.get("parsing_res_list")
        if isinstance(blocks, list):
            block_texts: list[str] = []
            for block in blocks:
                if isinstance(block, dict):
                    value = block.get("block_content", block.get("content"))
                else:
                    value = getattr(block, "block_content", getattr(block, "content", None))
                if isinstance(value, str) and value.strip():
                    block_texts.append(value.strip())
            text = "\n".join(block_texts)
            if text:
                return text
        markdown_attr = getattr(result, "markdown", None)
        if markdown_attr is not None and markdown_attr is not result:
            text = _paddleocr_text(
                markdown_attr,
                markdown_dir=markdown_dir,
                page_index=page_index,
            )
            if text:
                return text
        return ""
    for attr in ("markdown_text", "text", "ocr_text", "markdown", "json"):
        if not hasattr(result, attr):
            continue
        try:
            value = getattr(result, attr)
            value = value() if callable(value) else value
            text = _paddleocr_text(
                value,
                markdown_dir=markdown_dir,
                page_index=page_index,
            )
        except Exception:
            continue
        if text:
            return text
    save_to_markdown = getattr(result, "save_to_markdown", None)
    if markdown_dir is not None and callable(save_to_markdown):
        markdown_dir.mkdir(parents=True, exist_ok=True)
        # The official exporter may overwrite a prior `page.md`.  Remove
        # generated leftovers first so a failed/empty export cannot return
        # stale text from the previous invocation.
        for stale in markdown_dir.rglob("*.md"):
            try:
                stale.unlink()
            except OSError:
                continue
        try:
            returned = save_to_markdown(save_path=markdown_dir)
        except Exception:
            returned = None
        candidates: list[Path] = []
        if isinstance(returned, (str, Path)):
            candidates.append(Path(returned))
        candidates.extend(sorted(markdown_dir.rglob("*.md")))
        root = markdown_dir.resolve()
        for candidate in candidates:
            if not candidate.is_absolute():
                candidate = markdown_dir / candidate
            try:
                candidate = candidate.resolve()
                candidate.relative_to(root)
            except (OSError, ValueError):
                continue
            if not candidate.is_file():
                continue
            try:
                text = candidate.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError):
                continue
            if text:
                return text
    return ""


def _paddle_audit_passed(audit: Any) -> bool:
    """Require explicit page-level Qwen agreement before Paddle can pass."""
    if not isinstance(audit, dict):
        return False
    pages = audit.get("pages")
    if isinstance(pages, list):
        if not pages or any(not isinstance(item, dict) for item in pages):
            return False
        statuses = [
            str(item.get("status") or "").strip().lower()
            for item in pages
        ]
        return bool(statuses) and all(status == "agree" for status in statuses)
    return str(audit.get("status") or "").strip().lower() == "agree"


def _validate_paddleocr_result(result: Any) -> dict[str, Any]:
    """Validate the adapter contract before writing a candidate sidecar."""
    if not isinstance(result, dict):
        raise RuntimeError("paddleocr_invalid_result")
    text = result.get("text")
    if not isinstance(text, str):
        raise RuntimeError("paddleocr_invalid_text")
    if not text.strip():
        raise RuntimeError("paddleocr_empty_result")
    warnings = result.get("warnings", [])
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise RuntimeError("paddleocr_invalid_warnings")
    metadata = result.get("metadata")
    if not isinstance(metadata, dict):
        raise RuntimeError("paddleocr_invalid_metadata")
    quality_status = metadata.get("quality_status")
    if quality_status not in {"passed", "review_required", "blocked"}:
        raise RuntimeError("paddleocr_invalid_quality_status")
    audit = metadata.get("quality_audit")
    if audit is not None and not isinstance(audit, dict):
        raise RuntimeError("paddleocr_invalid_quality_audit")
    for key in ("provider", "model", "role", "quality_gate"):
        if key in metadata and not isinstance(metadata[key], str):
            raise RuntimeError("paddleocr_invalid_metadata")
    return {"text": text, "warnings": list(warnings), "metadata": dict(metadata)}


def _safe_case_component(value: str) -> bool:
    """Keep generated sidecar paths inside the research output directory."""
    return bool(value) and re.fullmatch(r"[A-Za-z0-9._-]+", value) is not None and value not in {".", ".."}


def _persist_ocr_run_state(
    research: Path,
    run_payloads: dict[tuple[str, str, int], dict[str, Any]],
    config: AppConfig,
    run_summary: dict[str, Any],
    benchmark_results: dict[str, dict[str, Any]],
) -> None:
    """Write observed sidecar state back to the frozen manifest atomically enough for audit use."""
    manifest_path = research / "ocr_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("ocr_manifest_invalid_after_run") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("runs"), list):
        raise ValueError("ocr_manifest_invalid_after_run")
    for run in manifest["runs"]:
        if not isinstance(run, dict):
            raise ValueError("ocr_manifest_malformed_run")
        candidate = run.get("candidate")
        if not isinstance(candidate, dict):
            raise ValueError("ocr_manifest_malformed_candidate")
        key = (
            str(run.get("pilot_case_id") or ""),
            str(candidate.get("candidate_id") or ""),
            int(run.get("repeat") or 0),
        )
        payload = run_payloads.get(key)
        if payload is None:
            raise ValueError(f"ocr_manifest_missing_run_result:{key[0]}:{key[1]}:{key[2]}")
        run["status"] = payload.get("status")
        run["blocked_reasons"] = list(payload.get("blocked_reasons") or [])
        run["quality_status"] = payload.get("quality_status")
        run["execution_mode"] = payload.get("execution_mode")
        run["sidecar_path"] = str(
            Path("ocr_runs")
            / f"repeat_{key[2]}"
            / key[0]
            / f"{key[1]}.json"
        )
        run["candidate"] = {
            "candidate_id": key[1],
            "provider": payload.get("provider"),
            "model": payload.get("model"),
            "role": payload.get("role"),
        }
    manifest["status"] = run_summary["status"]
    manifest["winner_status"] = "blocked"
    manifest["run_summary"] = dict(run_summary)
    manifest["benchmark_results"] = dict(
        {
            repeat: {
                "status": result.get("status"),
                "selection": result.get("selection", {}),
            }
            for repeat, result in benchmark_results.items()
        }
    )
    manifest["route_readiness"] = _route_snapshot(config)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _route_snapshot(config: AppConfig) -> dict[str, dict[str, str]]:
    return {
        candidate["candidate_id"]: {
            "provider": candidate["provider"],
            "model": _candidate_model_name(config, candidate),
            "role": candidate["role"],
        }
        for candidate in OCR_CANDIDATES
    }


def _synchronize_benchmark_routes(research: Path, config: AppConfig) -> None:
    """Refresh benchmark route provenance before scoring candidate sidecars."""
    manifest_path = research / "ocr_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("ocr_manifest_invalid_before_benchmark") from exc
    routes = _route_snapshot(config)
    benchmark_ids = {item["candidate_id"] for item in OCR_BENCHMARK_CANDIDATES}
    for benchmark_name in manifest.get("benchmark_manifests") or []:
        benchmark_path = research / str(benchmark_name)
        try:
            benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError(f"ocr_benchmark_manifest_invalid:{benchmark_name}") from exc
        if not isinstance(benchmark, dict) or not isinstance(benchmark.get("cases"), list):
            raise ValueError(f"ocr_benchmark_manifest_invalid:{benchmark_name}")
        for case in benchmark["cases"]:
            if not isinstance(case, dict):
                raise ValueError(f"ocr_benchmark_manifest_invalid_case:{benchmark_name}")
            case["candidate_routes"] = {
                candidate_id: dict(routes[candidate_id]) for candidate_id in benchmark_ids
            }
        benchmark_path.write_text(json.dumps(benchmark, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare_research_manifests(pilot_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    pilot = Path(pilot_dir)
    output = Path(output_dir)
    manifest_path = pilot / "manifest.jsonl"
    if not manifest_path.is_file():
        raise ValueError("pilot_manifest_not_found")
    try:
        rows = [
            json.loads(line)
            for line in manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"pilot_manifest_invalid_json:{type(exc).__name__}") from exc
    if not rows:
        raise ValueError("pilot_manifest_empty")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("pilot_manifest_malformed_row")
    _validate_pilot_rows(rows, pilot)
    package_validation = validate_pilot_annotation_package(pilot)
    if package_validation["status"] == "blocked":
        first_error = (package_validation.get("errors") or ["invalid_package"])[0]
        raise ValueError(f"pilot_manifest_invalid_package:{first_error}")
    modalities = {normalize_modality(row.get("modality")) for row in rows}
    required = {"cxr", "ct", "mri"}
    coverage_ok = required.issubset(modalities)
    ocr_rows = []
    benchmark_cases_by_repeat: dict[int, list[dict[str, Any]]] = {1: [], 2: []}
    for row in rows:
        annotation_case = AnnotationCase.model_validate_json(
            (pilot / str(row["annotation_path"])).read_text(encoding="utf-8")
        )
        candidate_routes = {
            item["candidate_id"]: {
                "provider": item["provider"],
                "model": item["model"],
                "role": item["role"],
            }
            for item in OCR_BENCHMARK_CANDIDATES
        }
        for candidate in OCR_CANDIDATES:
            for repeat in (1, 2):
                ocr_rows.append({
                    "pilot_case_id": row.get("pilot_case_id"),
                    "modality": normalize_modality(row.get("modality")),
                    "annotation_path": row.get("annotation_path"),
                    "candidate": candidate,
                    "repeat": repeat,
                    "status": "blocked",
                    "gold_source": CURRENT_GOLD_SOURCE,
                    "gold_status": CURRENT_GOLD_STATUS,
                    "blocked_reasons": ["real_provider_run_not_available"],
                })
        for repeat in (1, 2):
            benchmark_cases_by_repeat[repeat].append(
                {
                    "case_id": annotation_case.pilot_case_id,
                    "modality": annotation_case.modality,
                    "gold_text": annotation_case.reference_report,
                    "candidates": {
                        candidate["candidate_id"]: {
                            "path": (
                                f"ocr_runs/repeat_{repeat}/{annotation_case.pilot_case_id}/"
                                f"{candidate['candidate_id']}.json"
                            )
                        }
                        for candidate in OCR_BENCHMARK_CANDIDATES
                        },
                    "candidate_routes": {
                        candidate_id: candidate_routes[candidate_id]
                        for candidate_id in {
                            candidate["candidate_id"] for candidate in OCR_BENCHMARK_CANDIDATES
                        }
                    },
                    "audit_candidates": {
                        candidate["candidate_id"]: {
                            "provider": candidate["provider"],
                            "model": candidate["model"],
                            "role": candidate["role"],
                            "sidecar_path": (
                                f"ocr_runs/repeat_{repeat}/{annotation_case.pilot_case_id}/"
                                f"{candidate['candidate_id']}.json"
                            ),
                        }
                        for candidate in OCR_CANDIDATES
                        if candidate["role"] == "ocr_verifier"
                    },
                }
            )
    benchmark_manifest_names = ["ocr_benchmark_repeat_1.json", "ocr_benchmark_repeat_2.json"]
    output.mkdir(parents=True, exist_ok=True)
    ocr_manifest = {
        "schema_version": "1.0",
        "artifact_type": "ocr_research_manifest",
        "status": "blocked",
        "case_count": len(rows),
        "modality_coverage": sorted(modalities),
        "coverage_ok": coverage_ok,
        "gold_source": CURRENT_GOLD_SOURCE,
        "gold_status": CURRENT_GOLD_STATUS,
        "winner_status": "blocked",
        "candidates": list(OCR_CANDIDATES),
        "benchmark_candidates": list(OCR_BENCHMARK_CANDIDATES),
        "runs": ocr_rows,
        "benchmark_manifests": benchmark_manifest_names,
        "winner_rule": ["clinical_cer", "truncation_count", "numeric_token_accuracy", "negation_accuracy", "repeat_consistency"],
    }
    paper_manifest = {
        "schema_version": "1.0",
        "artifact_type": "paper_experiment_manifest",
        "status": "pending",
        "data": {
            "pilot_annotation_dir": str(pilot),
            "case_count": len(rows),
            "modalities": sorted(modalities),
            "gold_source": CURRENT_GOLD_SOURCE,
            "gold_status": CURRENT_GOLD_STATUS,
            "clinical_reader_status": package_validation["status"],
        },
        "experiments": [
            {"id": "ocr_comparison", "status": "blocked", "required_evidence": [CURRENT_GOLD_SOURCE, "real_provider_runs"]},
            {"id": "finding_extraction", "status": "pending", "metric": "finding_graph_precision_recall_f1"},
            {"id": "report_generation", "status": "pending", "metric": "likert_structure_alignment_hazard"},
            {"id": "reader_and_model_evaluation", "status": "not_started", "metric": "reader_agreement_and_modelwise_statistics"},
        ],
        "statistics": ["bootstrap_ci", "welch_anova", "holm_correction", "reader_agreement", "sensitivity_analysis"],
        "formal_claim_allowed": False,
    }
    (output / "ocr_manifest.json").write_text(json.dumps(ocr_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for repeat, name in ((1, benchmark_manifest_names[0]), (2, benchmark_manifest_names[1])):
        benchmark_manifest = {
            "schema_version": "1.0",
            "artifact_type": "ocr_candidate_benchmark_manifest",
            "status": "blocked",
            "gold_source": CURRENT_GOLD_SOURCE,
            "gold_status": CURRENT_GOLD_STATUS,
            "repeat": repeat,
            "cases": benchmark_cases_by_repeat[repeat],
        }
        (output / name).write_text(
            json.dumps(benchmark_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    (output / "paper_experiment_manifest.json").write_text(json.dumps(paper_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "blocked", "case_count": len(rows), "modality_coverage": sorted(modalities), "output_dir": str(output)}


def _validate_pilot_rows(rows: list[dict[str, Any]], pilot_dir: Path) -> None:
    """Reject malformed package identity fields before creating research runs."""
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, row in enumerate(rows, start=1):
        case_id = row.get("pilot_case_id")
        modality = row.get("modality")
        annotation_path = row.get("annotation_path")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(f"pilot_manifest_row_{index}:pilot_case_id_must_be_string")
        if not isinstance(modality, str) or not modality.strip():
            raise ValueError(f"pilot_manifest_row_{index}:modality_must_be_string")
        if not isinstance(annotation_path, str) or not annotation_path.strip():
            raise ValueError(f"pilot_manifest_row_{index}:annotation_path_must_be_string")
        normalized_id = case_id.strip()
        normalized_path = annotation_path.strip()
        if normalized_id in seen_ids:
            raise ValueError(f"pilot_manifest_duplicate_case_id:{normalized_id}")
        if normalized_path in seen_paths:
            raise ValueError(f"pilot_manifest_duplicate_annotation_path:{normalized_path}")
        raw_path = Path(normalized_path)
        if raw_path.is_absolute():
            raise ValueError(f"pilot_manifest_row_{index}:annotation_path_must_be_relative")
        case_root = (pilot_dir / "cases").resolve()
        case_path = (pilot_dir / raw_path).resolve()
        if case_root not in case_path.parents or case_path == case_root:
            raise ValueError(f"pilot_manifest_row_{index}:annotation_path_outside_cases")
        if not case_path.is_file():
            raise ValueError(f"pilot_manifest_row_{index}:annotation_case_missing:{normalized_path}")
        try:
            case = AnnotationCase.model_validate_json(case_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError(f"pilot_manifest_row_{index}:annotation_case_invalid:{normalized_path}") from exc
        if case.pilot_case_id != normalized_id:
            raise ValueError(f"pilot_manifest_row_{index}:annotation_case_identity_mismatch")
        if normalize_modality(case.modality) != normalize_modality(modality):
            raise ValueError(f"pilot_manifest_row_{index}:annotation_case_modality_mismatch")
        seen_ids.add(normalized_id)
        seen_paths.add(normalized_path)
