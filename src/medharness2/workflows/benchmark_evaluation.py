from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from medharness2.checkpoints import StageCheckpointStore
from medharness2.config import AppConfig, load_config, resolve_existing_path
from medharness2.data.sample_data import load_manifest
from medharness2.llm_client import LLMClient
from medharness2.schema import GeneratedReport
from medharness2.tools.tool12_statistics import compare_metric_groups, correct_pvalues_holm
from medharness2.utils.io import read_json, write_json
from medharness2.workflows.single_case import run_single_case


_REQUIRED_LLM_ROLES = {
    "general_judge",
    "finding_extractor",
    "alignment_auditor",
    "hazard_primary",
    "hazard_reviewer",
    "hazard_adjudicator",
    "structure_auditor",
}

_EVALUATION_SOURCE_PATHS = (
    "alignment/audit.py",
    "alignment/matcher.py",
    "alignment/scoring.py",
    "checkpoints.py",
    "config.py",
    "contracts/common.py",
    "contracts/evaluation.py",
    "extractors/cxr.py",
    "extractors/registry.py",
    "extractors/rules.py",
    "llm_client.py",
    "modules/pairwise_report.py",
    "modules/single_report.py",
    "ontology/cxr.py",
    "privacy.py",
    "schema.py",
    "tools/quality_gate.py",
    "tools/tool1_likert.py",
    "tools/tool2_extract.py",
    "tools/tool3_structure.py",
    "tools/tool4_hazard.py",
    "tools/tool5_align.py",
    "tools/tool6_structure_diff.py",
    "tools/tool9_rank.py",
    "utils/io.py",
    "workflows/benchmark_evaluation.py",
    "workflows/single_case.py",
)


def evaluate_generation_benchmark(
    benchmark_dir: str | Path,
    case_manifest_path: str | Path,
    output_dir: str | Path,
    *,
    config: AppConfig | None = None,
    llm_client: Any | None = None,
    resume: bool = True,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    benchmark_root = Path(benchmark_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    route_snapshot = _validate_role_routes(
        cfg,
        require_credentials=llm_client is None,
    )
    evaluation_spec_snapshot = _evaluation_spec_snapshot()
    evaluation_spec_sha256 = _stable_sha256(evaluation_spec_snapshot)
    evaluation_config_snapshot = _evaluation_config_snapshot(cfg)
    evaluation_config_sha256 = _stable_sha256(evaluation_config_snapshot)
    client = llm_client or LLMClient(cfg)
    source = _load_verified_benchmark_source(
        benchmark_root,
        Path(case_manifest_path),
        cfg,
    )
    for generation_result in source["results"]:
        if generation_result.get("status") == "succeeded":
            _validate_source_isolation(generation_result)
    cases = {case.case_id: case for case in load_manifest(case_manifest_path)}
    result_rows: list[dict[str, Any]] = []
    resumed_count = 0

    for generation_result in source["results"]:
        case_id = str(generation_result.get("case_id") or "")
        model = str(generation_result.get("model") or "")
        row_sha256 = _stable_sha256(generation_result)
        base_result = {
            "case_id": case_id,
            "model": model,
            "benchmark_result_sha256": row_sha256,
        }
        checkpoint_store: StageCheckpointStore | None = None
        checkpointing = _checkpointing_disabled("not_started")
        _emit_progress(
            progress_callback,
            event="case_started",
            case_id=case_id,
            model=model,
        )
        try:
            if generation_result.get("status") != "succeeded":
                raise ValueError("source_generation_failed")
            _validate_source_isolation(generation_result)
            case = cases.get(case_id)
            if case is None:
                raise ValueError(f"case_not_found_in_manifest:{case_id}")
            reference_path = _resolve_case_path(case.report_text, cfg)
            if not reference_path.is_file():
                raise ValueError(f"reference_report_not_found:{reference_path}")
            reference_text = reference_path.read_text(encoding="utf-8").strip()
            if not reference_text:
                raise ValueError(f"reference_report_empty:{reference_path}")
            reference_sha256 = _file_sha256(reference_path)
            input_asset = _resolve_case_input_asset(case, cfg)
            if not input_asset.is_file():
                raise ValueError(f"evaluation_input_asset_not_found:{input_asset}")
            input_asset_sha256 = _file_sha256(input_asset)
            expected_asset_sha256 = str(generation_result.get("input_asset_sha256") or "")
            if expected_asset_sha256 and input_asset_sha256 != expected_asset_sha256:
                raise ValueError(f"evaluation_input_asset_hash_mismatch:{case_id}")

            model_dir = output / "cases" / _safe_component(model)
            raw_path = model_dir / "case_evaluations" / f"{_safe_component(case_id)}.json"
            artifact_path = model_dir / "evaluation_artifacts" / f"{_safe_component(case_id)}.json"
            was_resumed = False
            if resume and artifact_path.is_file():
                artifact = read_json(artifact_path)
                _validate_resumable_artifact(
                    artifact,
                    raw_path=raw_path,
                    benchmark_result_sha256=row_sha256,
                    reference_report_sha256=reference_sha256,
                    input_asset_sha256=input_asset_sha256,
                    route_snapshot=route_snapshot,
                    evaluation_spec_snapshot=evaluation_spec_snapshot,
                    evaluation_spec_sha256=evaluation_spec_sha256,
                    evaluation_config_snapshot=evaluation_config_snapshot,
                    evaluation_config_sha256=evaluation_config_sha256,
                    required_general_judge_consistency_runs=cfg.model_roles["general_judge"].consistency_runs,
                )
                resumed_count += 1
                was_resumed = True
                checkpointing = _checkpointing_disabled("whole_case_artifact_reused")
            else:
                generated_payload = dict(generation_result.get("generated_report") or {})
                generated = GeneratedReport(
                    model=str(generated_payload.get("model") or model),
                    source=str(generated_payload.get("source") or "unknown"),
                    report=str(generated_payload.get("report") or ""),
                    modality=str(generated_payload.get("modality") or case.modality),
                    evidence_tier=str(generated_payload.get("evidence_tier") or "artifact"),
                    warnings=list(generated_payload.get("warnings") or []),
                    metadata=dict(generated_payload.get("metadata") or {}),
                )
                if resume:
                    checkpoint_store = StageCheckpointStore(
                        model_dir
                        / "checkpoints"
                        / evaluation_spec_sha256
                        / _safe_component(case_id),
                        event_callback=lambda event, case_id=case_id, model=model: _emit_progress(
                            progress_callback,
                            event=f"checkpoint_{event['status']}",
                            case_id=case_id,
                            model=model,
                            stage=event["stage"],
                            checkpoint_path=event["path"],
                        ),
                    )
                else:
                    checkpointing = _checkpointing_disabled("resume_disabled")
                case_evaluation = run_single_case(
                    report_text=reference_text,
                    image_path=input_asset,
                    output_path=raw_path,
                    case_id=case_id,
                    prepared_assets={
                        "primary_image": str(input_asset)
                        if generation_result.get("input_asset_kind") == "image"
                        else "",
                        "volume_path": str(input_asset)
                        if generation_result.get("input_asset_kind") == "volume"
                        else "",
                    },
                    modality=case.modality,
                    body_part=case.body_part,
                    top_n=1,
                    precomputed_generated_reports=[generated],
                    config=cfg,
                    llm_client=client,
                    checkpoint_store=checkpoint_store,
                )
                if checkpoint_store is not None:
                    checkpointing = checkpoint_store.summary()
                llm_verification = verify_real_llm_case_evaluation(
                    case_evaluation,
                    required_general_judge_consistency_runs=cfg.model_roles["general_judge"].consistency_runs,
                )
                artifact = {
                    "schema_version": "2.0",
                    "artifact_type": "generation_benchmark_case_evaluation",
                    "status": "succeeded",
                    "case_id": case_id,
                    "model": model,
                    "benchmark_result_sha256": row_sha256,
                    "reference_report_sha256": reference_sha256,
                    "input_asset_sha256": input_asset_sha256,
                    "source_isolation": {
                        "generation_reference_report_used": False,
                        "generated_report_reference_report_used": False,
                        "reference_usage_phase": "posthoc_evaluation_only",
                    },
                    "case_evaluation": str(raw_path),
                    "case_evaluation_sha256": _file_sha256(raw_path),
                    "llm_verification": llm_verification,
                    "route_snapshot": route_snapshot,
                    "evaluation_spec_snapshot": evaluation_spec_snapshot,
                    "evaluation_spec_sha256": evaluation_spec_sha256,
                    "evaluation_config_snapshot": evaluation_config_snapshot,
                    "evaluation_config_sha256": evaluation_config_sha256,
                    "checkpointing": checkpointing,
                }
                write_json(artifact_path, artifact)

            result_rows.append(
                {
                    **base_result,
                    "status": "succeeded",
                    "reference_report_sha256": reference_sha256,
                    "evaluation_artifact": str(artifact_path),
                    "evaluation_artifact_sha256": _file_sha256(artifact_path),
                    "case_evaluation": str(raw_path),
                    "case_evaluation_sha256": _file_sha256(raw_path),
                    "llm_verification": artifact["llm_verification"],
                    "metrics": _case_evaluation_metrics(read_json(raw_path)),
                    "checkpointing": checkpointing,
                }
            )
            _emit_progress(
                progress_callback,
                event="case_succeeded",
                case_id=case_id,
                model=model,
                resumed=was_resumed,
            )
        except Exception as exc:
            if checkpoint_store is not None:
                checkpointing = checkpoint_store.summary()
            failure_path = (
                output
                / "failures"
                / _safe_component(model or "unknown_model")
                / f"{_safe_component(case_id or 'unknown_case')}.json"
            )
            failure = {
                "schema_version": "2.0",
                "artifact_type": "generation_benchmark_evaluation_failure",
                "status": "failed",
                **base_result,
                "error_type": type(exc).__name__,
                "error": _safe_error(exc),
                "checkpointing": checkpointing,
            }
            write_json(failure_path, failure)
            result_rows.append(
                {
                    **base_result,
                    "status": "failed",
                    "failure_artifact": str(failure_path),
                    "failure_artifact_sha256": _file_sha256(failure_path),
                    "error_type": type(exc).__name__,
                    "error": _safe_error(exc),
                    "checkpointing": checkpointing,
                }
            )
            _emit_progress(
                progress_callback,
                event="case_failed",
                case_id=case_id,
                model=model,
                error_type=type(exc).__name__,
            )

    results_path = output / "benchmark_evaluation_results.jsonl"
    results_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in result_rows
        ),
        encoding="utf-8",
    )
    historical_failures = _historical_failure_artifacts(output)
    summary = _build_evaluation_summary(
        result_rows,
        source_mode=str(source["benchmark_manifest"].get("mode") or "unknown"),
        resumed_count=resumed_count,
        results_path=results_path,
        historical_failure_count=len(historical_failures),
    )
    summary_path = output / "benchmark_evaluation_summary.json"
    write_json(summary_path, summary)
    evaluation_manifest = {
        "schema_version": "2.0",
        "artifact_type": "generation_benchmark_evaluation_manifest",
        "status": summary["status"],
        "source": {
            "benchmark_dir": str(benchmark_root),
            "benchmark_manifest_sha256": _file_sha256(
                benchmark_root / "benchmark_manifest.json"
            ),
            "benchmark_results_sha256": source["results_sha256"],
            "benchmark_summary_sha256": source["summary_sha256"],
            "case_manifest_sha256": source["case_manifest_sha256"],
        },
        "route_snapshot": route_snapshot,
        "route_snapshot_sha256": _stable_sha256(route_snapshot),
        "evaluation_spec_snapshot": evaluation_spec_snapshot,
        "evaluation_spec_sha256": evaluation_spec_sha256,
        "evaluation_config_snapshot": evaluation_config_snapshot,
        "evaluation_config_sha256": evaluation_config_sha256,
        "historical_failures": {
            "count": len(historical_failures),
            "artifacts": historical_failures,
            "current_result_failure_count": summary["failure_count"],
        },
        "artifacts": {
            "results": str(results_path),
            "summary": str(summary_path),
        },
        "artifact_sha256": {
            "results": _file_sha256(results_path),
            "summary": _file_sha256(summary_path),
        },
    }
    write_json(output / "benchmark_evaluation_manifest.json", evaluation_manifest)
    return summary


def verify_real_llm_case_evaluation(
    payload: dict[str, Any],
    *,
    required_general_judge_consistency_runs: int = 1,
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    human = dict(payload.get("human_evaluation") or {})
    generated = list(payload.get("generated_evaluations") or [])
    pairwise = list(payload.get("pairwise_comparisons") or [])
    if not human or len(generated) != 1 or len(pairwise) != 1:
        raise ValueError(
            "Real LLM verification requires one reference evaluation, one candidate evaluation, and one pairwise comparison"
        )

    required_consistency_runs = max(1, int(required_general_judge_consistency_runs))
    _verify_likert_consistency(
        (human.get("likert") or {}).get("_metadata"),
        label="T1.reference",
        required_runs=required_consistency_runs,
    )
    _verify_likert_consistency(
        ((generated[0].get("likert") or {}).get("_metadata")),
        label="T1.candidate",
        required_runs=required_consistency_runs,
    )
    evidence.append(
        _verify_metadata(
            (human.get("likert") or {}).get("_metadata"),
            label="T1.reference",
            role="general_judge",
            implementation_types={"llm_judge"},
        )
    )
    evidence.append(
        _verify_metadata(
            ((generated[0].get("likert") or {}).get("_metadata")),
            label="T1.candidate",
            role="general_judge",
            implementation_types={"llm_judge"},
        )
    )
    evidence.append(
        _verify_metadata(
            ((human.get("finding_graph") or {}).get("metadata") or {}).get(
                "llm_correction"
            ),
            label="T2.reference",
            role="finding_extractor",
            implementation_types={"llm_extractor"},
        )
    )
    evidence.append(
        _verify_metadata(
            (
                ((generated[0].get("finding_graph") or {}).get("metadata") or {}).get(
                    "llm_correction"
                )
            ),
            label="T2.candidate",
            role="finding_extractor",
            implementation_types={"llm_extractor"},
        )
    )

    comparison = dict((pairwise[0] or {}).get("comparison") or {})
    alignment = dict(comparison.get("alignment") or {})
    alignment_audit = dict(comparison.get("alignment_audit") or {})
    if alignment_audit.get("alignment_sha256") != _stable_sha256(alignment):
        raise ValueError("T5 alignment audit hash mismatch")
    adjudication_summary = dict(
        alignment_audit.get("adjudication_summary") or {}
    )
    deterministic_error_count = len(alignment.get("error_candidates") or [])
    adjudicated_candidates = list(
        alignment_audit.get("adjudicated_error_candidates") or []
    )
    if adjudication_summary.get("complete") is not True:
        raise ValueError("T5 adjudication is incomplete")
    if int(adjudication_summary.get("deterministic_error_count", -1)) != deterministic_error_count:
        raise ValueError("T5 deterministic error count mismatch")
    if int(adjudication_summary.get("retained_error_count", -1)) != len(
        adjudicated_candidates
    ):
        raise ValueError("T5 retained error count mismatch")
    if len(alignment_audit.get("error_judgements") or []) != deterministic_error_count:
        raise ValueError("T5 error judgement coverage mismatch")
    evidence.append(
        _verify_provenance(
            alignment_audit.get("auditor_provenance"),
            label="T5.alignment_audit",
            role="alignment_auditor",
            implementation_types={"llm_audit"},
        )
    )

    hazards = dict(comparison.get("hazards") or {})
    hazard_review = dict(comparison.get("hazard_review") or {})
    if len(hazards.get("errors") or []) != len(adjudicated_candidates):
        raise ValueError("T4 hazard count does not match T5 adjudicated candidates")
    if hazard_review.get("primary_result_sha256") != _stable_sha256(hazards):
        raise ValueError("T4 hazard review hash mismatch")
    primary = _verify_provenance(
        hazards.get("provenance"),
        label="T4.primary",
        role="hazard_primary",
        implementation_types={"llm_judge"},
    )
    reviewer = _verify_provenance(
        ((hazard_review.get("reviewer_result") or {}).get("provenance")),
        label="T4.reviewer",
        role="hazard_reviewer",
        implementation_types={"llm_judge"},
    )
    if (primary["provider"], primary["model"], primary["endpoint_host"]) == (
        reviewer["provider"],
        reviewer["model"],
        reviewer["endpoint_host"],
    ):
        raise ValueError("T4 reviewer is not independent from the primary judge")
    evidence.extend([primary, reviewer])

    disagreements = list(hazard_review.get("disagreements") or [])
    if disagreements:
        hazard_adjudication = comparison.get("hazard_adjudication")
        if not isinstance(hazard_adjudication, dict):
            raise ValueError("T4 hazard adjudication is missing for reviewer disagreements")
        if hazard_adjudication.get("primary_result_sha256") != _stable_sha256(
            hazards
        ):
            raise ValueError("T4 hazard adjudication primary hash mismatch")
        if hazard_adjudication.get("hazard_review_sha256") != _stable_sha256(
            hazard_review
        ):
            raise ValueError("T4 hazard adjudication review hash mismatch")
        decisions = list(hazard_adjudication.get("decisions") or [])
        expected_indices = {
            int(item["error_index"])
            for item in disagreements
            if isinstance(item, dict) and _valid_int(item.get("error_index"))
        }
        decision_indices = {
            int(item["error_index"])
            for item in decisions
            if isinstance(item, dict) and _valid_int(item.get("error_index"))
        }
        if len(decisions) != len(disagreements) or decision_indices != expected_indices:
            raise ValueError("T4 hazard adjudication decision coverage mismatch")
        adjudicator = _verify_provenance(
            hazard_adjudication.get("adjudicator_provenance"),
            label="T4.adjudicator",
            role="hazard_adjudicator",
            implementation_types={"llm_adjudication"},
        )
        if (
            adjudicator["provider"],
            adjudicator["model"],
            adjudicator["endpoint_host"],
        ) in {
            (primary["provider"], primary["model"], primary["endpoint_host"]),
            (reviewer["provider"], reviewer["model"], reviewer["endpoint_host"]),
        }:
            raise ValueError("T4 adjudicator is not independent from prior judges")
        evidence.append(adjudicator)

    structure_diff = dict(comparison.get("structure_diff") or {})
    structure_audit = dict(comparison.get("structure_audit") or {})
    if structure_audit.get("structure_diff_sha256") != _stable_sha256(
        structure_diff
    ):
        raise ValueError("T6 structure audit hash mismatch")
    evidence.append(
        _verify_provenance(
            structure_audit.get("assessor_provenance"),
            label="T6.structure_audit",
            role="structure_auditor",
            implementation_types={"llm_assessment"},
        )
    )

    role_counts = Counter(item["role"] for item in evidence)
    validated_attempt_counts: Counter[str] = Counter()
    for item in evidence:
        validated_attempt_counts[item["role"]] += int(item["attempt_count"])
    provider_model_counts = Counter(
        f"{item['provider']}::{item['model']}::{item['endpoint_host']}"
        for item in evidence
    )
    fallback_count = sum(1 for item in evidence if bool(item.get("fallback_used")))
    return {
        "passed": True,
        "evidence_count": len(evidence),
        "fallback_count": fallback_count,
        "role_counts": dict(sorted(role_counts.items())),
        "validated_attempt_counts": dict(
            sorted(validated_attempt_counts.items())
        ),
        "provider_model_counts": dict(sorted(provider_model_counts.items())),
        "evidence": evidence,
    }


def _load_verified_benchmark_source(
    benchmark_dir: Path,
    case_manifest_path: Path,
    config: AppConfig,
) -> dict[str, Any]:
    manifest_path = benchmark_dir / "benchmark_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Benchmark manifest not found: {manifest_path}")
    benchmark_manifest = read_json(manifest_path)
    results_path = _resolve_artifact_path(
        (benchmark_manifest.get("artifacts") or {}).get("results"),
        benchmark_dir,
        config,
    )
    summary_path = _resolve_artifact_path(
        (benchmark_manifest.get("artifacts") or {}).get("summary"),
        benchmark_dir,
        config,
    )
    expected_hashes = dict(benchmark_manifest.get("artifact_sha256") or {})
    results_sha256 = _file_sha256(results_path)
    summary_sha256 = _file_sha256(summary_path)
    if results_sha256 != expected_hashes.get("results"):
        raise ValueError("Benchmark results SHA-256 mismatch")
    if summary_sha256 != expected_hashes.get("summary"):
        raise ValueError("Benchmark summary SHA-256 mismatch")
    resolved_case_manifest = _resolve_case_path(str(case_manifest_path), config)
    case_manifest_sha256 = _file_sha256(resolved_case_manifest)
    if case_manifest_sha256 != benchmark_manifest.get("input_manifest_sha256"):
        raise ValueError("Benchmark case manifest SHA-256 mismatch")
    results = _read_jsonl(results_path)
    source_summary = read_json(summary_path)
    if int(source_summary.get("result_count", len(results))) != len(results):
        raise ValueError("Benchmark result count does not match its summary")
    return {
        "benchmark_manifest": benchmark_manifest,
        "results": results,
        "results_sha256": results_sha256,
        "summary_sha256": summary_sha256,
        "case_manifest_sha256": case_manifest_sha256,
    }


def _validate_source_isolation(generation_result: dict[str, Any]) -> None:
    if generation_result.get("reference_report_used") is not False:
        raise ValueError("Generation result reference_report_used must be false")
    metadata = dict((generation_result.get("generated_report") or {}).get("metadata") or {})
    if metadata.get("reference_report_used") is not False:
        raise ValueError("Generated report metadata reference_report_used must be false")


def _validate_role_routes(
    config: AppConfig,
    *,
    require_credentials: bool,
) -> dict[str, dict[str, Any]]:
    missing = sorted(_REQUIRED_LLM_ROLES - set(config.model_roles))
    if missing:
        raise ValueError(f"Missing required LLM role routes: {missing}")
    snapshot: dict[str, dict[str, Any]] = {}
    for role in sorted(_REQUIRED_LLM_ROLES):
        route = config.model_roles[role]
        route_options = route.as_call_options()
        if route.provider.lower() == "mock" or not route.provider or not route.model:
            raise ValueError(f"Role {role} must use a real configured LLM")
        if require_credentials and (
            not route.api_key_env
            or not str(os.environ.get(route.api_key_env) or "").strip()
        ):
            raise ValueError(
                f"Missing API credential environment variable for role {role}: {route.api_key_env}"
            )
        snapshot[role] = {
            "provider": route.provider,
            "model": route.model,
            "endpoint_host": (
                urlparse(route.base_url).hostname or ""
            ).lower(),
            "endpoint_base_url": _sanitized_endpoint_base_url(route.base_url),
            "api_key_env": route.api_key_env,
            "max_tokens": route_options.get(
                "max_tokens",
                config.llm.chat_max_tokens,
            ),
            "schema_max_attempts": route.schema_attempts(
                default=config.llm.max_retries
            ),
            "transport_max_retries": route_options.get(
                "max_retries",
                config.llm.max_retries,
            ),
            "timeout_sec": route_options.get(
                "timeout_sec",
                config.llm.timeout_sec,
            ),
            "temperature": None
            if route.omit_temperature
            else route_options.get("temperature", config.llm.temperature),
            "seed": route_options.get("seed", config.llm.seed),
            "omit_temperature": route.omit_temperature,
            "consistency_runs": max(1, int(route.consistency_runs)),
        }
    return snapshot


def _sanitized_endpoint_base_url(value: str) -> str:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.hostname:
        return ""
    host = parsed.hostname.lower()
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme.lower()}://{host}{path}"


def _verify_metadata(
    metadata: Any,
    *,
    label: str,
    role: str,
    implementation_types: set[str],
) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise ValueError(f"{label} is missing real LLM metadata")
    return _normalize_verified_evidence(
        metadata,
        label=label,
        role=role,
        implementation_type=str(metadata.get("backend") or ""),
        implementation_types=implementation_types,
        endpoint_host=str(metadata.get("endpoint_host") or ""),
        attempt_count=metadata.get("attempt_count"),
    )


def _verify_provenance(
    provenance: Any,
    *,
    label: str,
    role: str,
    implementation_types: set[str],
) -> dict[str, Any]:
    if not isinstance(provenance, dict):
        raise ValueError(f"{label} is missing real LLM provenance")
    metadata = dict(provenance.get("metadata") or {})
    return _normalize_verified_evidence(
        provenance,
        label=label,
        role=role,
        implementation_type=str(provenance.get("implementation_type") or ""),
        implementation_types=implementation_types,
        endpoint_host=str(metadata.get("endpoint_host") or ""),
        attempt_count=metadata.get("attempt_count"),
    )


def _normalize_verified_evidence(
    source: dict[str, Any],
    *,
    label: str,
    role: str,
    implementation_type: str,
    implementation_types: set[str],
    endpoint_host: str,
    attempt_count: Any,
) -> dict[str, Any]:
    provider = str(source.get("provider") or "")
    model = str(source.get("model") or "")
    actual_role = str(source.get("role") or "")
    if implementation_type not in implementation_types:
        raise ValueError(
            f"{label} did not use the required real LLM implementation: {implementation_type}"
        )
    if provider.lower() == "mock" or not provider or not model:
        raise ValueError(f"{label} did not record a real provider/model")
    if actual_role != role:
        raise ValueError(f"{label} role mismatch: {actual_role!r} != {role!r}")
    if bool(source.get("fallback_used")):
        raise ValueError(f"{label} used a fallback")
    try:
        attempts = int(attempt_count)
    except (TypeError, ValueError):
        attempts = 0
    if attempts < 1:
        raise ValueError(f"{label} did not record a completed LLM attempt")
    return {
        "label": label,
        "role": role,
        "implementation_type": implementation_type,
        "provider": provider,
        "model": model,
        "endpoint_host": endpoint_host.lower(),
        "fallback_used": False,
        "attempt_count": attempts,
    }


def _verify_likert_consistency(
    metadata: dict[str, Any] | None,
    *,
    label: str,
    required_runs: int,
) -> None:
    """Enforce configured T1 retest coverage before formal promotion."""
    if required_runs <= 1:
        return
    if not isinstance(metadata, dict):
        raise ValueError(f"{label} is missing Likert consistency metadata")
    try:
        actual_runs = int(metadata.get("consistency_runs"))
        compared_count = int(metadata.get("consistency_compared_count"))
    except (TypeError, ValueError):
        raise ValueError(f"{label} has invalid Likert consistency metadata") from None
    if actual_runs != required_runs:
        raise ValueError(f"{label} consistency_runs mismatch: {actual_runs} != {required_runs}")
    if compared_count != required_runs - 1:
        raise ValueError(f"{label} consistency comparison is incomplete")
    if metadata.get("consistency_errors"):
        raise ValueError(f"{label} consistency retest contains errors")
    if metadata.get("consistency_exact") is not True:
        raise ValueError(f"{label} consistency retest did not reach exact agreement")


def _validate_resumable_artifact(
    artifact: dict[str, Any],
    *,
    raw_path: Path,
    benchmark_result_sha256: str,
    reference_report_sha256: str,
    input_asset_sha256: str,
    route_snapshot: dict[str, Any],
    evaluation_spec_snapshot: dict[str, Any],
    evaluation_spec_sha256: str,
    evaluation_config_snapshot: dict[str, Any],
    evaluation_config_sha256: str,
    required_general_judge_consistency_runs: int = 1,
) -> None:
    if artifact.get("status") != "succeeded":
        raise ValueError("Existing evaluation artifact is not successful")
    if artifact.get("benchmark_result_sha256") != benchmark_result_sha256:
        raise ValueError("Existing evaluation artifact source hash mismatch")
    if artifact.get("reference_report_sha256") != reference_report_sha256:
        raise ValueError("Existing evaluation artifact reference hash mismatch")
    if artifact.get("input_asset_sha256") != input_asset_sha256:
        raise ValueError("Existing evaluation artifact input asset hash mismatch")
    if artifact.get("route_snapshot") != route_snapshot:
        raise ValueError("Existing evaluation artifact route snapshot mismatch")
    artifact_spec_snapshot = artifact.get("evaluation_spec_snapshot")
    artifact_spec_sha256 = str(artifact.get("evaluation_spec_sha256") or "")
    if (
        not isinstance(artifact_spec_snapshot, dict)
        or artifact_spec_sha256 != _stable_sha256(artifact_spec_snapshot)
    ):
        raise ValueError("Existing evaluation artifact implementation snapshot integrity mismatch")
    if (
        artifact_spec_snapshot != evaluation_spec_snapshot
        or artifact_spec_sha256 != evaluation_spec_sha256
    ):
        raise ValueError("Existing evaluation artifact implementation snapshot mismatch")
    artifact_config_snapshot = artifact.get("evaluation_config_snapshot")
    artifact_config_sha256 = str(artifact.get("evaluation_config_sha256") or "")
    if (
        not isinstance(artifact_config_snapshot, dict)
        or artifact_config_sha256 != _stable_sha256(artifact_config_snapshot)
    ):
        raise ValueError("Existing evaluation artifact evaluation config snapshot integrity mismatch")
    if (
        artifact_config_snapshot != evaluation_config_snapshot
        or artifact_config_sha256 != evaluation_config_sha256
    ):
        raise ValueError("Existing evaluation artifact evaluation config snapshot mismatch")
    if not raw_path.is_file() or artifact.get("case_evaluation_sha256") != _file_sha256(
        raw_path
    ):
        raise ValueError("Existing case evaluation hash mismatch")
    verification = verify_real_llm_case_evaluation(
        read_json(raw_path),
        required_general_judge_consistency_runs=required_general_judge_consistency_runs,
    )
    if verification != artifact.get("llm_verification"):
        raise ValueError("Existing evaluation LLM verification mismatch")


def _build_evaluation_summary(
    result_rows: list[dict[str, Any]],
    *,
    source_mode: str,
    resumed_count: int,
    results_path: Path,
    historical_failure_count: int,
) -> dict[str, Any]:
    succeeded = [row for row in result_rows if row.get("status") == "succeeded"]
    failed = [row for row in result_rows if row.get("status") == "failed"]
    checkpoint_stats = {
        key: sum(
            int(
                ((row.get("checkpointing") or {}).get("stats") or {}).get(key)
                or 0
            )
            for row in result_rows
        )
        for key in ("hits", "misses", "writes")
    }
    artifact_checkpoint_stats = {
        key: sum(
            int(
                (
                    (
                        read_json(Path(row["evaluation_artifact"])).get(
                            "checkpointing"
                        )
                        or {}
                    ).get("stats")
                    or {}
                ).get(key)
                or 0
            )
            for row in succeeded
            if row.get("evaluation_artifact")
        )
        for key in ("hits", "misses", "writes")
    }
    role_counts: Counter[str] = Counter()
    provider_model_counts: Counter[str] = Counter()
    validated_attempt_counts: Counter[str] = Counter()
    for row in succeeded:
        verification = dict(row.get("llm_verification") or {})
        role_counts.update(verification.get("role_counts") or {})
        provider_model_counts.update(verification.get("provider_model_counts") or {})
        validated_attempt_counts.update(
            verification.get("validated_attempt_counts") or {}
        )
    case_metrics = [dict(row.get("metrics") or {}) for row in succeeded]
    candidate_likert = [
        float(metrics["candidate_likert_mean"])
        for metrics in case_metrics
        if isinstance(metrics.get("candidate_likert_mean"), (int, float))
        and not isinstance(metrics.get("candidate_likert_mean"), bool)
        and math.isfinite(float(metrics["candidate_likert_mean"]))
    ]
    alignment_f1 = [
        float(metrics["alignment_f1"])
        for metrics in case_metrics
        if isinstance(metrics.get("alignment_f1"), (int, float))
        and not isinstance(metrics.get("alignment_f1"), bool)
        and math.isfinite(float(metrics["alignment_f1"]))
    ]
    alignment_verdicts = Counter(
        str(metrics["alignment_audit_verdict"])
        for metrics in case_metrics
        if metrics.get("alignment_audit_verdict")
    )
    structure_verdicts = Counter(
        str(metrics["structure_audit_verdict"])
        for metrics in case_metrics
        if metrics.get("structure_audit_verdict")
    )
    max_hazard_levels = Counter(
        str(metrics["max_hazard_level"])
        for metrics in case_metrics
        if _valid_int(metrics.get("max_hazard_level"))
    )
    adjudicated_hazard_levels = Counter(
        str(level)
        for metrics in case_metrics
        for level in metrics.get("adjudicated_hazard_levels") or []
        if _valid_hazard_level(level)
    )
    consensus_hazard_levels = Counter(
        str(level)
        for metrics in case_metrics
        for level in metrics.get("consensus_hazard_levels") or []
        if _valid_hazard_level(level)
    )
    consensus_max_hazard_levels = Counter(
        str(metrics["consensus_max_hazard_level"])
        for metrics in case_metrics
        if _valid_int(metrics.get("consensus_max_hazard_level"))
        and int(metrics["consensus_max_hazard_level"]) > 0
    )
    hazard_compared_count = sum(int(metrics.get("hazard_compared_count") or 0) for metrics in case_metrics)
    hazard_exact_agreement_count = sum(int(metrics.get("hazard_exact_agreement_count") or 0) for metrics in case_metrics)
    hazard_within_one_count = sum(int(metrics.get("hazard_within_one_count") or 0) for metrics in case_metrics)
    hazard_action_agreement_count = sum(int(metrics.get("hazard_action_agreement_count") or 0) for metrics in case_metrics)
    return {
        "schema_version": "2.0",
        "artifact_type": "generation_benchmark_evaluation_summary",
        "status": "succeeded" if succeeded and not failed else "completed_with_failures" if result_rows else "failed",
        "source_benchmark_mode": source_mode,
        "source_result_count": len(result_rows),
        "evaluation_count": len(succeeded),
        "failure_count": len(failed),
        "historical_failure_count": historical_failure_count,
        "resumed_count": resumed_count,
        "checkpoint_stats": checkpoint_stats,
        "artifact_checkpoint_stats": artifact_checkpoint_stats,
        "fallback_count": sum(
            int((row.get("llm_verification") or {}).get("fallback_count") or 0)
            for row in succeeded
        ),
        "role_call_counts": dict(sorted(role_counts.items())),
        "validated_attempt_counts": dict(
            sorted(validated_attempt_counts.items())
        ),
        "provider_model_counts": dict(sorted(provider_model_counts.items())),
        "formal_statistics": _formal_statistical_comparisons(result_rows),
        "metrics": {
            "candidate_likert_mean": _numeric_summary(candidate_likert),
            "alignment_f1": _numeric_summary(alignment_f1),
            "hazard_error_count": sum(
                int(metrics.get("hazard_error_count") or 0)
                for metrics in case_metrics
            ),
            "deterministic_alignment_error_count": sum(
                int(metrics.get("deterministic_alignment_error_count") or 0)
                for metrics in case_metrics
            ),
            "t5_retained_error_count": sum(
                int(metrics.get("t5_retained_error_count") or 0)
                for metrics in case_metrics
            ),
            "t5_rejected_error_count": sum(
                int(metrics.get("t5_rejected_error_count") or 0)
                for metrics in case_metrics
            ),
            "t5_modified_error_count": sum(
                int(metrics.get("t5_modified_error_count") or 0)
                for metrics in case_metrics
            ),
            "t5_abstained_error_count": sum(
                int(metrics.get("t5_abstained_error_count") or 0)
                for metrics in case_metrics
            ),
            "max_hazard_level_counts": dict(sorted(max_hazard_levels.items())),
            "hazard_disagreement_count": sum(
                int(metrics.get("hazard_disagreement_count") or 0)
                for metrics in case_metrics
            ),
            "hazard_agreement": {
                "compared_count": hazard_compared_count,
                "exact_agreement_count": hazard_exact_agreement_count,
                "within_one_count": hazard_within_one_count,
                "action_agreement_count": hazard_action_agreement_count,
                "exact_agreement_rate": round(hazard_exact_agreement_count / hazard_compared_count, 4) if hazard_compared_count else None,
                "within_one_rate": round(hazard_within_one_count / hazard_compared_count, 4) if hazard_compared_count else None,
                "action_agreement_rate": round(hazard_action_agreement_count / hazard_compared_count, 4) if hazard_compared_count else None,
                "source": "hazard_review.agreement_summary",
            },
            "hazard_adjudication_decision_count": sum(
                int(metrics.get("hazard_adjudication_decision_count") or 0)
                for metrics in case_metrics
            ),
            "hazard_adjudication_abstained_count": sum(
                int(metrics.get("hazard_adjudication_abstained_count") or 0)
                for metrics in case_metrics
            ),
            "adjudicated_hazard_level_counts": dict(
                sorted(adjudicated_hazard_levels.items())
            ),
            "consensus_hazard_level_counts": dict(
                sorted(consensus_hazard_levels.items())
            ),
            "consensus_max_hazard_level_counts": dict(
                sorted(consensus_max_hazard_levels.items())
            ),
            "consensus_nontrivial_error_count": sum(
                int(metrics.get("consensus_nontrivial_error_count") or 0)
                for metrics in case_metrics
            ),
            "consensus_material_error_count": sum(
                int(metrics.get("consensus_material_error_count") or 0)
                for metrics in case_metrics
            ),
            "consensus_unresolved_error_count": sum(
                int(metrics.get("consensus_unresolved_error_count") or 0)
                for metrics in case_metrics
            ),
            "third_hazard_adjudication_required_count": sum(
                bool(metrics.get("third_hazard_adjudication_required"))
                for metrics in case_metrics
            ),
            "clinical_validation_required_count": sum(
                bool(metrics.get("clinical_validation_required"))
                for metrics in case_metrics
            ),
            "alignment_audit_verdict_counts": dict(
                sorted(alignment_verdicts.items())
            ),
            "structure_audit_verdict_counts": dict(
                sorted(structure_verdicts.items())
            ),
        },
        "results_path": str(results_path),
    }


def _checkpointing_disabled(reason: str) -> dict[str, Any]:
    return {
        "enabled": False,
        "reason": reason,
        "root": "",
        "stats": {"hits": 0, "misses": 0, "writes": 0},
        "events": [],
    }


def _historical_failure_artifacts(output: Path) -> list[dict[str, str]]:
    failure_root = output / "failures"
    if not failure_root.is_dir():
        return []
    return [
        {"path": str(path), "sha256": _file_sha256(path)}
        for path in sorted(failure_root.rglob("*.json"))
        if path.is_file()
    ]


def _formal_statistical_comparisons(result_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build auditable model-pair comparisons; never infer significance from a single case."""
    eligible = [row for row in result_rows if row.get("status") == "succeeded"]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in eligible:
        model = str(row.get("model") or "unknown")
        grouped.setdefault(model, []).append(row)
    models = sorted(grouped)
    metrics = ("candidate_likert_mean", "alignment_f1")
    comparisons: list[dict[str, Any]] = []
    raw_p_values: dict[str, float] = {}
    blocked_reasons: list[str] = []
    for left_index, left_model in enumerate(models):
        for right_model in models[left_index + 1 :]:
            for metric in metrics:
                left = [
                    float((row.get("metrics") or {})[metric])
                    for row in grouped[left_model]
                    if _finite_stat_value((row.get("metrics") or {}).get(metric))
                ]
                right = [
                    float((row.get("metrics") or {})[metric])
                    for row in grouped[right_model]
                    if _finite_stat_value((row.get("metrics") or {}).get(metric))
                ]
                comparison_id = f"{left_model}__vs__{right_model}__{metric}"
                result = compare_metric_groups(left, right)
                item = {"id": comparison_id, "model_a": left_model, "model_b": right_model, "metric": metric, **result}
                if result["method"] == "insufficient_data":
                    blocked_reasons.append(comparison_id)
                else:
                    raw_p_values[comparison_id] = float(result["p_value"])
                comparisons.append(item)
    if not comparisons:
        return {"status": "blocked", "method": "insufficient_data", "comparisons": [], "blocked_reasons": ["need_at_least_two_models"]}
    corrected = correct_pvalues_holm(raw_p_values)
    for item in comparisons:
        if item["id"] in corrected:
            item["p_value_holm"] = corrected[item["id"]]
    status = (
        "succeeded"
        if raw_p_values and not blocked_reasons
        else "completed_with_blocked_comparisons"
        if raw_p_values
        else "blocked"
    )
    return {
        "status": status,
        "method": "welch_normal_approximation+holm" if raw_p_values else "insufficient_data",
        "comparisons": comparisons,
        "blocked_reasons": blocked_reasons,
        "eligible_case_count": len(eligible),
        "model_count": len(models),
    }


def _finite_stat_value(value: Any) -> bool:
    """Accept only finite numeric observations; bool is not a measurement."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _valid_int(value: Any) -> bool:
    """Return true only for integer values, excluding bool-as-int coercion."""
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_hazard_level(value: Any) -> bool:
    return _valid_int(value) and 1 <= int(value) <= 5


def _case_evaluation_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    generated = list(payload.get("generated_evaluations") or [])
    pairwise = list(payload.get("pairwise_comparisons") or [])
    candidate = dict(generated[0]) if generated else {}
    comparison = dict((pairwise[0] or {}).get("comparison") or {}) if pairwise else {}
    hazards = dict(comparison.get("hazards") or {})
    hazard_review = dict(comparison.get("hazard_review") or {})
    agreement_summary = dict(hazard_review.get("agreement_summary") or {})
    hazard_adjudication = dict(comparison.get("hazard_adjudication") or {})
    adjudication_decisions = list(hazard_adjudication.get("decisions") or [])
    alignment_audit = dict(comparison.get("alignment_audit") or {})
    adjudication_summary = dict(
        alignment_audit.get("adjudication_summary") or {}
    )
    hazard_errors = list(hazards.get("errors") or [])
    hazard_levels = [
        int(error["hazard_level"])
        for error in hazard_errors
        if isinstance(error, dict)
        and _valid_int(error.get("hazard_level"))
    ]
    consensus_hazard_levels, consensus_unresolved_count = _consensus_hazard_levels(
        hazard_errors,
        hazard_review,
        hazard_adjudication,
    )
    return {
        "candidate_likert_mean": (candidate.get("composite_inputs") or {}).get(
            "likert_mean"
        ),
        "alignment_f1": (
            (comparison.get("alignment") or {}).get("metrics") or {}
        ).get("f1"),
        "deterministic_alignment_error_count": len(
            (comparison.get("alignment") or {}).get("error_candidates") or []
        ),
        "t5_rejected_error_count": int(adjudication_summary.get("rejected_error_count", 0)),
        "t5_retained_error_count": int(adjudication_summary.get("retained_error_count", 0)),
        "t5_modified_error_count": int(adjudication_summary.get("modified_error_count", 0)),
        "t5_abstained_error_count": int(adjudication_summary.get("abstained_error_count", 0)),
        "hazard_error_count": len(hazard_errors),
        "max_hazard_level": max(hazard_levels) if hazard_levels else 0,
        "hazard_disagreement_count": len(hazard_review.get("disagreements") or []),
        "hazard_compared_count": int(
            agreement_summary["compared_count"]
            if "compared_count" in agreement_summary
            else len(hazard_errors)
        ),
        "hazard_exact_agreement_count": int(agreement_summary.get("exact_agreement_count", 0)),
        "hazard_within_one_count": int(agreement_summary.get("within_one_count", 0)),
        "hazard_action_agreement_count": int(agreement_summary.get("action_agreement_count", 0)),
        "hazard_adjudication_decision_count": len(adjudication_decisions),
        "hazard_adjudication_abstained_count": sum(
            bool(decision.get("abstain"))
            for decision in adjudication_decisions
            if isinstance(decision, dict)
        ),
        "adjudicated_hazard_levels": [
            int(decision["hazard_level"])
            for decision in adjudication_decisions
            if isinstance(decision, dict)
            and _valid_int(decision.get("hazard_level"))
            and not decision.get("abstain")
        ],
        "consensus_hazard_levels": consensus_hazard_levels,
        "consensus_max_hazard_level": max(consensus_hazard_levels)
        if consensus_hazard_levels
        else 0,
        "consensus_nontrivial_error_count": sum(
            level >= 2 for level in consensus_hazard_levels
        ),
        "consensus_material_error_count": sum(
            level >= 3 for level in consensus_hazard_levels
        ),
        "consensus_unresolved_error_count": consensus_unresolved_count,
        "third_hazard_adjudication_required": bool(
            hazard_adjudication.get("clinical_validation_required")
        ),
        "clinical_validation_required": True,
        "alignment_audit_verdict": (
            comparison.get("alignment_audit") or {}
        ).get("verdict"),
        "structure_audit_verdict": (
            comparison.get("structure_audit") or {}
        ).get("verdict"),
        "structure_clinical_impact": (
            comparison.get("structure_audit") or {}
        ).get("clinical_impact"),
    }


def _consensus_hazard_levels(
    primary_errors: list[Any],
    hazard_review: dict[str, Any],
    hazard_adjudication: dict[str, Any],
) -> tuple[list[int], int]:
    disagreement_indices = {
        int(item["error_index"])
        for item in hazard_review.get("disagreements") or []
        if isinstance(item, dict) and _valid_int(item.get("error_index"))
    }
    decisions = {
        int(item["error_index"]): item
        for item in hazard_adjudication.get("decisions") or []
        if isinstance(item, dict) and _valid_int(item.get("error_index"))
    }
    levels: list[int] = []
    unresolved = 0
    for index, primary in enumerate(primary_errors):
        if index in disagreement_indices:
            decision = decisions.get(index)
            if (
                not isinstance(decision, dict)
                or bool(decision.get("abstain"))
                or not _valid_int(decision.get("hazard_level"))
            ):
                unresolved += 1
                continue
            levels.append(int(decision["hazard_level"]))
            continue
        if not isinstance(primary, dict) or not _valid_int(primary.get("hazard_level")):
            unresolved += 1
            continue
        levels.append(int(primary["hazard_level"]))
    return levels, unresolved


def _numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": round(sum(values) / len(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def _resolve_artifact_path(
    raw_path: Any,
    benchmark_dir: Path,
    config: AppConfig,
) -> Path:
    if not raw_path:
        raise ValueError("Benchmark manifest is missing an artifact path")
    candidate = resolve_existing_path(str(raw_path))
    if candidate.is_file():
        return candidate
    if not candidate.is_absolute():
        for root in (config.project_root, benchmark_dir):
            rooted = resolve_existing_path(root / candidate)
            if rooted.is_file():
                return rooted
    raise FileNotFoundError(f"Benchmark artifact not found: {raw_path}")


def _resolve_case_path(raw_path: str | Path, config: AppConfig) -> Path:
    candidate = resolve_existing_path(raw_path)
    if candidate.exists() or candidate.is_absolute():
        return candidate
    return resolve_existing_path(config.project_root / candidate)


def _resolve_case_input_asset(case: Any, config: AppConfig) -> Path:
    modality = str(case.modality or "").lower()
    if modality in {"ct", "mr", "mri"}:
        raw_path = (case.derived_assets or {}).get("volume_path") or case.volume_path
    else:
        raw_path = (case.derived_assets or {}).get("primary_image") or (
            case.image_paths[0] if case.image_paths else ""
        )
    if not raw_path:
        return Path("")
    return _resolve_case_path(str(raw_path), config)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"Expected JSON object at {path}:{line_number}")
        rows.append(payload)
    return rows


def _safe_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._")
    return safe or "unknown"


def _safe_error(exc: Exception) -> str:
    text = re.sub(r"(?i)(authorization|api[_ -]?key|bearer)[^,;\n]*", r"\1=<redacted>", str(exc))
    return text[-2000:]


def _emit_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    *,
    event: str,
    case_id: str,
    model: str,
    **details: Any,
) -> None:
    if callback is not None:
        callback(
            {
                "event": event,
                "case_id": case_id,
                "model": model,
                **details,
            }
        )


def _stable_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _evaluation_spec_snapshot() -> dict[str, Any]:
    package_root = Path(__file__).resolve().parents[1]
    source_sha256: dict[str, str] = {}
    for relative_path in _EVALUATION_SOURCE_PATHS:
        source_path = package_root / relative_path
        if not source_path.is_file():
            raise FileNotFoundError(
                f"Evaluation implementation source not found: {source_path}"
            )
        source_sha256[relative_path] = _file_sha256(source_path)
    return {
        "version": "evaluation-implementation-v1",
        "hash_algorithm": "sha256",
        "source_sha256": source_sha256,
    }


def _evaluation_config_snapshot(config: AppConfig) -> dict[str, Any]:
    return {
        "version": "evaluation-runtime-config-v1",
        "extractor": asdict(config.extractor),
        "ranking": asdict(config.ranking),
        "alignment": asdict(config.alignment),
        "privacy": asdict(config.privacy),
        "modality_map": dict(sorted(config.modality_map.items())),
        "llm_roles": {
            role: {
                "consistency_runs": max(1, int(route.consistency_runs)),
                "schema_attempts": route.schema_attempts(default=config.llm.max_retries),
                "transport_max_retries": route.as_call_options().get("max_retries", config.llm.max_retries),
            }
            for role, route in sorted(config.model_roles.items())
        },
    }


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "evaluate_generation_benchmark",
    "verify_real_llm_case_evaluation",
]
