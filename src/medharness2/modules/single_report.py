from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from medharness2.checkpoints import (
    StageCheckpointStore,
    file_fingerprint,
    llm_route_fingerprint,
)
from medharness2.config import AppConfig, load_config
from medharness2.contracts import FindingGraph
from medharness2.llm_client import LLMClient
from medharness2.schema import SingleReportResult
from medharness2.tools.tool1_likert import LIKERT_METRICS, evaluate_likert, likert_mean
from medharness2.tools.tool2_extract import extract_findings
from medharness2.tools.tool3_structure import check_structure


def evaluate_single_report(
    report_text: str,
    image_path: str | None = None,
    modality: str | None = None,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
    checkpoint_store: StageCheckpointStore | None = None,
    checkpoint_namespace: str = "single",
) -> dict[str, Any]:
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    modality_key = modality or "unknown"
    judge_role = cfg.model_roles.get("general_judge")
    judge_options = judge_role.as_call_options() if judge_role else {}
    judge_retries = (
        judge_role.schema_attempts(default=cfg.llm.max_retries)
        if judge_role
        else cfg.llm.max_retries
    )
    judge_consistency_runs = judge_role.consistency_runs if judge_role else 1
    def compute_likert() -> dict[str, Any]:
        return evaluate_likert(
            report_text,
            image_path=image_path,
            llm_client=client,
            max_retries=judge_retries,
            model_role="general_judge" if judge_role else "",
            judge_options=judge_options,
            require_llm=judge_role is not None,
            allow_fallback=judge_role is None,
            consistency_runs=judge_consistency_runs,
        )

    likert = (
        checkpoint_store.get_or_compute(
            f"{checkpoint_namespace}.tool1_likert",
            {
                "stage_version": "tool1-likert-v1",
                "report_text": report_text,
                "image": file_fingerprint(image_path),
                "schema_attempts": judge_retries,
                "model_role": "general_judge" if judge_role else "",
                "require_llm": judge_role is not None,
                "allow_fallback": judge_role is None,
                "consistency_runs": judge_consistency_runs,
                "route": llm_route_fingerprint(client, judge_options),
            },
            compute_likert,
            validator=lambda payload: _validate_likert_checkpoint(
                payload,
                image_path=image_path,
                strict=judge_role is not None,
                role="general_judge",
                options=judge_options,
            ),
        )
        if checkpoint_store is not None
        else compute_likert()
    )
    extractor_role = cfg.model_roles.get("finding_extractor")
    extractor_options = extractor_role.as_call_options() if extractor_role else {}
    extractor_retries = (
        extractor_role.schema_attempts(default=cfg.llm.max_retries)
        if extractor_role
        else cfg.llm.max_retries
    )
    def compute_finding_graph() -> dict[str, Any]:
        return extract_findings(
            report_text,
            modality=modality_key,
            backend=cfg.extractor.backend,
            llm_client=client if extractor_role else None,
            extractor_options=extractor_options,
            model_role="finding_extractor" if extractor_role else "",
            max_retries=extractor_retries,
            require_llm=extractor_role is not None,
            allow_fallback=extractor_role is None,
        )

    finding_graph = (
        checkpoint_store.get_or_compute(
            f"{checkpoint_namespace}.tool2_findings",
            {
                "stage_version": "tool2-hybrid-v3",
                "report_text": report_text,
                "modality": modality_key,
                "backend": cfg.extractor.backend,
                "schema_attempts": extractor_retries,
                "model_role": "finding_extractor" if extractor_role else "",
                "require_llm": extractor_role is not None,
                "allow_fallback": extractor_role is None,
                "route": llm_route_fingerprint(client, extractor_options),
            },
            compute_finding_graph,
            validator=lambda payload: _validate_finding_graph_checkpoint(
                payload,
                strict=extractor_role is not None,
                role="finding_extractor",
                options=extractor_options,
            ),
        )
        if checkpoint_store is not None
        else compute_finding_graph()
    )
    structure = check_structure(report_text)
    composite_inputs = {
        "likert_mean": likert_mean(likert),
        "structure_score": float(structure.get("score", 0.0)),
        # A reference report is evaluated against itself: ranking coverage is
        # reference recall, while extractor/template coverage remains a
        # diagnostic field on the finding graph.
        "finding_coverage": 1.0 if finding_graph.get("findings") else 0.0,
    }
    return SingleReportResult(
        likert=likert,
        finding_graph=finding_graph,
        structure=structure,
        composite_inputs=composite_inputs,
    ).to_json()


def _validate_likert_checkpoint(
    payload: dict[str, Any],
    *,
    image_path: str | None,
    strict: bool,
    role: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    for metric in LIKERT_METRICS:
        item = payload.get(metric)
        if not isinstance(item, dict):
            raise ValueError(f"Likert checkpoint is missing metric {metric!r}")
        score = item.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
            raise ValueError(f"Likert checkpoint score is invalid for {metric!r}")
        explanation = item.get("explanation")
        if not isinstance(explanation, str) or not explanation.strip():
            raise ValueError(f"Likert checkpoint explanation is invalid for {metric!r}")
    metadata = payload.get("_metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Likert checkpoint is missing _metadata")
    if not isinstance(metadata.get("fallback_used"), bool):
        raise ValueError("Likert checkpoint fallback_used must be boolean")
    if not isinstance(metadata.get("attempt_count"), int) or metadata["attempt_count"] < 1:
        raise ValueError("Likert checkpoint attempt_count must be positive")
    if strict:
        _validate_strict_llm_metadata(
            metadata,
            role=role,
            implementation_types={"llm_judge"},
            implementation_field="backend",
            options=options,
        )
    if image_path is None and payload.get("warning") != "No image/volume provided":
        raise ValueError("Likert checkpoint is missing the no-image warning")
    return payload


def _validate_finding_graph_checkpoint(
    payload: dict[str, Any],
    *,
    strict: bool,
    role: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    validated = FindingGraph.model_validate(payload).model_dump(mode="json")
    if strict:
        metadata = dict((validated.get("metadata") or {}).get("llm_correction") or {})
        _validate_strict_llm_metadata(
            metadata,
            role=role,
            implementation_types={"llm_extractor"},
            implementation_field="backend",
            options=options,
        )
    return validated


def _validate_strict_llm_metadata(
    metadata: dict[str, Any],
    *,
    role: str,
    implementation_types: set[str],
    implementation_field: str,
    options: dict[str, Any],
) -> None:
    if not metadata:
        raise ValueError(f"Strict {role} checkpoint is missing provenance metadata")
    implementation = str(metadata.get(implementation_field) or "")
    if implementation not in implementation_types:
        raise ValueError(
            f"Strict {role} checkpoint has invalid implementation {implementation!r}; "
            f"expected {sorted(implementation_types)}"
        )
    if metadata.get("fallback_used") is not False:
        raise ValueError(f"Strict {role} checkpoint cannot contain fallback output")
    provider = str(metadata.get("provider") or "")
    if not provider or provider.lower() == "mock":
        raise ValueError(f"Strict {role} checkpoint requires a non-mock provider")
    if str(metadata.get("role") or "") != role:
        raise ValueError(f"Strict checkpoint role mismatch for {role}")
    for field_name in ("provider", "model"):
        expected = str(options.get(field_name) or "")
        if expected and str(metadata.get(field_name) or "") != expected:
            raise ValueError(f"Strict {role} checkpoint {field_name} mismatch")
    expected_host = (urlparse(str(options.get("base_url") or "")).hostname or "").lower()
    if expected_host and str(metadata.get("endpoint_host") or "").lower() != expected_host:
        raise ValueError(f"Strict {role} checkpoint endpoint mismatch")
