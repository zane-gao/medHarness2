from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from threading import Semaphore
import time
from typing import Any

from medharness2.generators.assets import ImageAsset, select_2d_image_asset, select_input_asset
from medharness2.generators.registry import ReportGeneratorRegistry
from medharness2.generators.routing import RoutePlan, RoutePlanEntry
from medharness2.llm_client import LLMClient, LLMClientError
from medharness2.schema import CandidateFailure, GeneratedReport


@dataclass
class CandidateGenerationResult:
    route_plan: RoutePlan
    reports: list[GeneratedReport]
    failures: list[CandidateFailure]


def generate_candidates(
    registry: ReportGeneratorRegistry,
    *,
    image_path: str,
    modality: str,
    body_part: str | None,
    case_id: str | None,
    reference_report: str | None = None,
    generation_mode: str = "production",
    model_keys: list[str] | None = None,
    model_sources: set[str] | None = None,
    prepared_assets: dict[str, Any] | None = None,
    precomputed_reports: dict[str, GeneratedReport] | None = None,
    llm_client: LLMClient | None = None,
    max_workers: int | None = None,
) -> CandidateGenerationResult:
    plan = registry.plan_routes(
        modality,
        body_part=body_part,
        requested=model_keys,
        sources=model_sources,
        image_path=image_path,
        prepared_assets=prepared_assets,
        case_id=case_id,
        generation_mode=generation_mode,
    )
    candidates = plan.candidates
    if not candidates:
        return CandidateGenerationResult(route_plan=plan, reports=[], failures=[])

    worker_count = max_workers or registry.config.generator.candidate_max_workers
    worker_count = min(worker_count, len(candidates))
    local_semaphores = _local_device_semaphores(candidates, max_workers=registry.config.generator.local_max_workers)
    precomputed_by_key = dict(precomputed_reports or {})
    results: dict[str, tuple[RoutePlanEntry, GeneratedReport, float]] = {}
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="report-candidate") as executor:
        futures: dict[Future[tuple[GeneratedReport, float]], RoutePlanEntry] = {
            executor.submit(
                _generate_candidate,
                registry,
                decision,
                image_path=image_path,
                modality=modality,
                body_part=body_part,
                case_id=case_id,
                reference_report=reference_report,
                generation_mode=generation_mode,
                prepared_assets=prepared_assets,
                precomputed_report=precomputed_by_key.get(decision.model_key),
                llm_client=llm_client,
                local_semaphore=local_semaphores.get(_local_device_key(decision)),
            ): decision
            for decision in candidates
        }
        for future in as_completed(futures):
            decision = futures[future]
            try:
                report, elapsed_sec = future.result()
            except Exception as exc:
                report = GeneratedReport(
                    model=decision.model_key,
                    source=decision.source,
                    report="",
                    modality=plan.modality,
                    warnings=["candidate_execution_exception", f"{type(exc).__name__}: {exc}"],
                )
                elapsed_sec = 0.0
            results[decision.model_key] = (decision, report, elapsed_sec)

    reports: list[GeneratedReport] = []
    failures: list[CandidateFailure] = []
    for decision in candidates:
        _, report, elapsed_sec = results[decision.model_key]
        candidate_id = _candidate_id(case_id, decision.model_key)
        report.metadata = {
            **report.metadata,
            "candidate_id": candidate_id,
            "route_tier": decision.route_tier,
            "route_reason": decision.route_reason,
            "runtime_state": decision.runtime_state,
            "validation_state": decision.validation_state,
            "generation_mode": generation_mode,
            "elapsed_sec": round(elapsed_sec, 4),
        }
        if report.report.strip():
            reports.append(report)
            continue
        failures.append(
            CandidateFailure(
                candidate_id=candidate_id,
                model=decision.model_key,
                source=decision.source,
                route_tier=decision.route_tier,
                warnings=list(report.warnings),
                runtime_state=decision.runtime_state,
                validation_state=decision.validation_state,
                metadata=dict(report.metadata),
            )
        )
    return CandidateGenerationResult(route_plan=plan, reports=reports, failures=failures)


def _generate_candidate(
    registry: ReportGeneratorRegistry,
    decision: RoutePlanEntry,
    *,
    image_path: str,
    modality: str,
    body_part: str | None,
    case_id: str | None,
    reference_report: str | None,
    generation_mode: str,
    prepared_assets: dict[str, Any] | None,
    precomputed_report: GeneratedReport | None,
    llm_client: LLMClient | None,
    local_semaphore: Semaphore | None,
) -> tuple[GeneratedReport, float]:
    started = time.monotonic()
    if precomputed_report is not None:
        preserve_failed_execution = (
            generation_mode in {"benchmark", "replay"}
            and not precomputed_report.report.strip()
            and precomputed_report.metadata.get("execution_attempted") is True
        )
        violations = _precomputed_report_violations(
            precomputed_report,
            decision=decision,
            case_id=case_id,
            require_fresh=not preserve_failed_execution,
        )
        if violations:
            return GeneratedReport(
                model=decision.model_key,
                source=decision.source,
                report="",
                modality=modality,
                evidence_tier=precomputed_report.evidence_tier,
                warnings=violations,
                metadata={
                    "generator_key": decision.model_key,
                    "case_id": case_id,
                    "reference_report_used": False,
                    "precomputed_report_rejected": True,
                    "precomputed_model": precomputed_report.model,
                    "precomputed_source": precomputed_report.source,
                },
            ), time.monotonic() - started
        return precomputed_report, time.monotonic() - started
    if local_semaphore is not None:
        with local_semaphore:
            report = _run_candidate(
                registry,
                decision,
                image_path=image_path,
                modality=modality,
                body_part=body_part,
                case_id=case_id,
                reference_report=reference_report,
                generation_mode=generation_mode,
                prepared_assets=prepared_assets,
                llm_client=llm_client,
            )
    else:
        report = _run_candidate(
            registry,
            decision,
            image_path=image_path,
            modality=modality,
            body_part=body_part,
            case_id=case_id,
            reference_report=reference_report,
            generation_mode=generation_mode,
            prepared_assets=prepared_assets,
            llm_client=llm_client,
        )
    return report, time.monotonic() - started


def _run_candidate(
    registry: ReportGeneratorRegistry,
    decision: RoutePlanEntry,
    *,
    image_path: str,
    modality: str,
    body_part: str | None,
    case_id: str | None,
    reference_report: str | None,
    generation_mode: str,
    prepared_assets: dict[str, Any] | None,
    llm_client: LLMClient | None,
) -> GeneratedReport:
    if decision.source == "external_vlm":
        return _generate_external_vlm(
            registry,
            decision,
            image_path=image_path,
            modality=modality,
            body_part=body_part,
            case_id=case_id,
            prepared_assets=prepared_assets,
            llm_client=llm_client,
        )
    if decision.source == "artifact_reuse":
        return registry.generate(
            decision.entry,
            image_path,
            modality,
            reference_report=reference_report,
            body_part=body_part,
            case_id=case_id,
            generation_mode=generation_mode,
        )
    selected_asset = select_input_asset(
        image_path,
        prepared_assets,
        decision.input_capabilities,
    )
    if decision.input_capabilities and selected_asset is None:
        return GeneratedReport(
            model=decision.model_key,
            source=decision.source,
            report="",
            modality=modality,
            warnings=["input_asset_unavailable"],
        )
    report = registry.generate(
        decision.entry,
        selected_asset.path if selected_asset is not None else image_path,
        modality,
        reference_report=reference_report,
        body_part=body_part,
        case_id=case_id,
        generation_mode=generation_mode,
    )
    if selected_asset is not None:
        report.metadata = {
            **report.metadata,
            "input_asset": selected_asset.path,
            "input_asset_kind": selected_asset.kind,
            "input_asset_capability": selected_asset.capability,
            "input_asset_sha256": selected_asset.sha256,
            "input_asset_size_bytes": selected_asset.size_bytes,
        }
    return report


def _local_device_semaphores(
    candidates: tuple[RoutePlanEntry, ...],
    *,
    max_workers: int,
) -> dict[str, Semaphore]:
    return {
        device: Semaphore(max_workers)
        for device in {_local_device_key(candidate) for candidate in candidates}
        if device is not None
    }


def _local_device_key(decision: RoutePlanEntry) -> str | None:
    if decision.source in {"artifact_reuse", "external_vlm"}:
        return None
    return str(getattr(decision.entry, "device", "local") or "local")


def _generate_external_vlm(
    registry: ReportGeneratorRegistry,
    decision: RoutePlanEntry,
    *,
    image_path: str,
    modality: str,
    body_part: str | None,
    case_id: str | None,
    prepared_assets: dict[str, Any] | None,
    llm_client: LLMClient | None,
) -> GeneratedReport:
    role_name = str(decision.entry.generation_parameters.get("model_role") or "report_generation")
    role = registry.config.model_roles.get(role_name)
    if role is None:
        return GeneratedReport(
            model=decision.model_key,
            source=decision.source,
            report="",
            modality=modality,
            warnings=["external_vlm_role_not_configured", role_name],
        )
    selected_asset = _external_image_asset_info(image_path, prepared_assets)
    if selected_asset is None:
        return GeneratedReport(
            model=decision.model_key,
            source=decision.source,
            report="",
            modality=modality,
            warnings=["input_asset_unavailable"],
        )
    options = role.as_call_options()
    prompt = (
        "Generate a radiology report from the provided imaging study. Preserve clinically relevant findings, "
        "uncertainty, negation, and measurements. Do not use a fixed report template unless the image supports it.\n"
        f"modality={modality}\nbody_part={body_part or 'unknown'}\ncase_id={case_id or 'unknown'}"
    )
    client = llm_client or LLMClient(registry.config)
    try:
        text = client.call(
            prompt,
            image_path=selected_asset.path,
            payload_classification="raw_medical_image",
            **options,
        )
    except (LLMClientError, TimeoutError, ConnectionError, OSError) as exc:
        return GeneratedReport(
            model=str(options.get("model") or decision.model_key),
            source=decision.source,
            report="",
            modality=modality,
            warnings=["external_vlm_generation_failed", f"{type(exc).__name__}: {exc}"],
            metadata={
                "model_role": role_name,
                "input_asset": selected_asset.path,
                "input_asset_kind": selected_asset.kind,
                "input_asset_capability": selected_asset.capability,
                "input_asset_sha256": selected_asset.sha256,
                "input_asset_size_bytes": selected_asset.size_bytes,
            },
        )
    return GeneratedReport(
        model=str(options.get("model") or decision.model_key),
        source=decision.source,
        report=str(text or ""),
        modality=modality,
        warnings=[] if str(text or "").strip() else ["external_vlm_empty_output"],
        metadata={
            "model_role": role_name,
            "input_asset": selected_asset.path,
            "input_asset_kind": selected_asset.kind,
            "input_asset_capability": selected_asset.capability,
            "input_asset_sha256": selected_asset.sha256,
            "input_asset_size_bytes": selected_asset.size_bytes,
            "fresh_inference": True,
            "reference_report_used": False,
            "provider": options.get("provider") or registry.config.llm.provider,
        },
    )


def _external_image_asset_info(
    image_path: str,
    prepared_assets: dict[str, Any] | None,
) -> ImageAsset | None:
    return select_2d_image_asset(image_path, prepared_assets)


def _external_image_asset(image_path: str, prepared_assets: dict[str, Any] | None) -> str | None:
    selected = _external_image_asset_info(image_path, prepared_assets)
    return selected.path if selected is not None else None


def _candidate_id(case_id: str | None, model_key: str) -> str:
    return f"{case_id or 'unknown-case'}:{model_key}"


def _precomputed_report_violations(
    report: GeneratedReport,
    *,
    decision: RoutePlanEntry,
    case_id: str | None,
    require_fresh: bool = True,
) -> list[str]:
    metadata = report.metadata or {}
    if metadata.get("reference_report_used") is not False:
        return ["precomputed_reference_not_allowed"]
    violations: list[str] = []
    if require_fresh and metadata.get("fresh_inference") is not True:
        violations.append("precomputed_fresh_inference_unverified")
    if str(metadata.get("case_id") or "") != str(case_id or ""):
        violations.append("precomputed_case_id_mismatch")
    if str(metadata.get("generator_key") or "") != decision.model_key:
        violations.append("precomputed_generator_key_mismatch")
    if report.source != decision.source:
        violations.append("precomputed_source_mismatch")
    return violations


__all__ = ["CandidateGenerationResult", "generate_candidates"]
