from __future__ import annotations

from typing import Any

from medharness2.checkpoints import (
    StageCheckpointStore,
    llm_route_fingerprint,
    stable_sha256,
)
from medharness2.config import AppConfig, load_config
from medharness2.contracts import (
    AlignmentAuditArtifact,
    HazardAdjudicationArtifact,
    HazardResult,
    HazardReviewArtifact,
    StructureAuditArtifact,
)
from medharness2.llm_client import LLMClient
from medharness2.tools.tool2_extract import extract_findings
from medharness2.tools.tool4_hazard import (
    adjudicate_hazard_disagreements,
    evaluate_hazards,
    review_hazards,
)
from medharness2.tools.tool5_align import align_graphs, audit_alignment
from medharness2.tools.tool6_structure_diff import assess_structure_clinical_significance, compare_structure


def evaluate_pairwise(
    report_a: str,
    report_b: str,
    image_path: str | None = None,
    modality: str | None = None,
    reference_graph: dict[str, Any] | None = None,
    candidate_graph: dict[str, Any] | None = None,
    config: AppConfig | None = None,
    llm_client: LLMClient | None = None,
    checkpoint_store: StageCheckpointStore | None = None,
    checkpoint_namespace: str = "pairwise",
) -> dict[str, Any]:
    cfg = config or load_config()
    client = llm_client or LLMClient(cfg)
    modality_key = modality or "unknown"
    extractor_role = cfg.model_roles.get("finding_extractor")
    extractor_options = extractor_role.as_call_options() if extractor_role else {}
    extractor_retries = (
        extractor_role.schema_attempts(default=cfg.llm.max_retries)
        if extractor_role
        else cfg.llm.max_retries
    )
    extraction_kwargs = {
        "modality": modality_key,
        "backend": cfg.extractor.backend,
        "llm_client": client if extractor_role else None,
        "extractor_options": extractor_options,
        "model_role": "finding_extractor" if extractor_role else "",
        "max_retries": extractor_retries,
        "require_llm": extractor_role is not None,
        "allow_fallback": extractor_role is None,
    }
    graph_a = reference_graph or extract_findings(report_a, **extraction_kwargs)
    graph_b = candidate_graph or extract_findings(report_b, **extraction_kwargs)
    # Align candidate (B) against human/reference (A), so false_finding and omission
    # match the usual AI-vs-human interpretation.
    alignment = align_graphs(graph_b, graph_a, tolerance_mm=cfg.alignment.tolerance_mm)
    alignment_auditor_role = cfg.model_roles.get("alignment_auditor")
    alignment_audit = None
    if alignment_auditor_role:
        alignment_auditor_retries = alignment_auditor_role.schema_attempts(
            default=cfg.llm.max_retries
        )
        alignment_auditor_options = alignment_auditor_role.as_call_options()

        def compute_alignment_audit() -> dict[str, Any]:
            return audit_alignment(
                graph_b,
                graph_a,
                alignment,
                llm_client=client,
                max_retries=alignment_auditor_retries,
                model_role="alignment_auditor",
                auditor_options=alignment_auditor_options,
                require_llm=True,
                allow_fallback=False,
            )

        alignment_audit = _checkpointed(
            checkpoint_store,
            f"{checkpoint_namespace}.tool5_alignment_audit",
            {
                "stage_version": "tool5-alignment-audit-v2",
                "candidate_graph": graph_b,
                "reference_graph": graph_a,
                "alignment": alignment,
                "schema_attempts": alignment_auditor_retries,
                "model_role": "alignment_auditor",
                "require_llm": True,
                "allow_fallback": False,
                "route": llm_route_fingerprint(client, alignment_auditor_options),
            },
            compute_alignment_audit,
            validator=lambda payload: _validate_alignment_audit_checkpoint(
                payload,
                alignment=alignment,
                error_candidate_count=len(alignment.get("error_candidates") or []),
                role="alignment_auditor",
                options=alignment_auditor_options,
            ),
        )
    hazard_role = cfg.model_roles.get("hazard_primary")
    hazard_options = hazard_role.as_call_options() if hazard_role else {}
    hazard_retries = (
        hazard_role.schema_attempts(default=cfg.llm.max_retries)
        if hazard_role
        else cfg.llm.max_retries
    )
    hazard_candidates = (
        list(alignment_audit.get("adjudicated_error_candidates") or [])
        if alignment_audit is not None
        else list(alignment.get("error_candidates") or [])
    )
    def compute_hazards() -> dict[str, Any]:
        return evaluate_hazards(
            hazard_candidates,
            llm_client=client,
            max_retries=hazard_retries,
            model_role="hazard_primary" if hazard_role else "",
            judge_options=hazard_options,
            require_llm=hazard_role is not None,
            allow_fallback=hazard_role is None,
        )

    hazards = _checkpointed(
        checkpoint_store,
        f"{checkpoint_namespace}.tool4_hazard_primary",
        {
            "stage_version": "tool4-hazard-v2",
            "error_candidates": hazard_candidates,
            "schema_attempts": hazard_retries,
            "model_role": "hazard_primary" if hazard_role else "",
            "require_llm": hazard_role is not None,
            "allow_fallback": hazard_role is None,
            "route": llm_route_fingerprint(client, hazard_options),
        },
        compute_hazards,
        validator=lambda payload: _validate_hazard_checkpoint(
            payload,
            error_candidate_count=len(hazard_candidates),
            role="hazard_primary" if hazard_role else "",
            options=hazard_options,
            strict=hazard_role is not None,
        ),
    )
    reviewer_role = cfg.model_roles.get("hazard_reviewer")
    hazard_review = None
    if reviewer_role:
        reviewer_retries = reviewer_role.schema_attempts(
            default=cfg.llm.max_retries
        )
        reviewer_options = reviewer_role.as_call_options()

        def compute_hazard_review() -> dict[str, Any]:
            return review_hazards(
                hazards,
                hazard_candidates,
                llm_client=client,
                max_retries=reviewer_retries,
                model_role="hazard_reviewer",
                judge_options=reviewer_options,
                require_llm=True,
                allow_fallback=False,
                consistency_runs=reviewer_role.consistency_runs,
            )

        hazard_review = _checkpointed(
            checkpoint_store,
            f"{checkpoint_namespace}.tool4_hazard_review",
            {
                "stage_version": "tool4-hazard-review-v2",
                "primary_result": hazards,
                "error_candidates": hazard_candidates,
                "schema_attempts": reviewer_retries,
                "model_role": "hazard_reviewer",
                "require_llm": True,
                "allow_fallback": False,
                "consistency_runs": reviewer_role.consistency_runs,
                "route": llm_route_fingerprint(client, reviewer_options),
            },
            compute_hazard_review,
            validator=lambda payload: _validate_hazard_review_checkpoint(
                payload,
                primary=hazards,
                error_candidate_count=len(hazard_candidates),
                role="hazard_reviewer",
                options=reviewer_options,
            ),
        )
    adjudicator_role = cfg.model_roles.get("hazard_adjudicator")
    hazard_adjudication = None
    if (
        adjudicator_role
        and hazard_review
        and hazard_review.get("disagreements")
    ):
        adjudicator_retries = adjudicator_role.schema_attempts(
            default=cfg.llm.max_retries
        )
        adjudicator_options = adjudicator_role.as_call_options()

        def compute_hazard_adjudication() -> dict[str, Any]:
            return adjudicate_hazard_disagreements(
                hazards,
                hazard_review,
                hazard_candidates,
                llm_client=client,
                max_retries=adjudicator_retries,
                model_role="hazard_adjudicator",
                adjudicator_options=adjudicator_options,
                require_llm=True,
                allow_fallback=False,
            )

        hazard_adjudication = _checkpointed(
            checkpoint_store,
            f"{checkpoint_namespace}.tool4_hazard_adjudication",
            {
                "stage_version": "tool4-hazard-adjudication-v1",
                "primary_result": hazards,
                "hazard_review": hazard_review,
                "error_candidates": hazard_candidates,
                "schema_attempts": adjudicator_retries,
                "model_role": "hazard_adjudicator",
                "require_llm": True,
                "allow_fallback": False,
                "route": llm_route_fingerprint(client, adjudicator_options),
            },
            compute_hazard_adjudication,
            validator=lambda payload: _validate_hazard_adjudication_checkpoint(
                payload,
                primary=hazards,
                review=hazard_review,
                role="hazard_adjudicator",
                options=adjudicator_options,
            ),
        )
    structure_diff = compare_structure(report_a, report_b)
    structure_auditor_role = cfg.model_roles.get("structure_auditor")
    structure_audit = None
    if structure_auditor_role:
        structure_auditor_retries = structure_auditor_role.schema_attempts(
            default=cfg.llm.max_retries
        )
        structure_auditor_options = structure_auditor_role.as_call_options()

        def compute_structure_audit() -> dict[str, Any]:
            return assess_structure_clinical_significance(
                report_a,
                report_b,
                structure_diff,
                llm_client=client,
                max_retries=structure_auditor_retries,
                model_role="structure_auditor",
                assessor_options=structure_auditor_options,
                require_llm=True,
                allow_fallback=False,
            )

        structure_audit = _checkpointed(
            checkpoint_store,
            f"{checkpoint_namespace}.tool6_structure_audit",
            {
                "stage_version": "tool6-structure-audit-v1",
                "reference_report": report_a,
                "candidate_report": report_b,
                "structure_diff": structure_diff,
                "schema_attempts": structure_auditor_retries,
                "model_role": "structure_auditor",
                "require_llm": True,
                "allow_fallback": False,
                "route": llm_route_fingerprint(client, structure_auditor_options),
            },
            compute_structure_audit,
            validator=lambda payload: _validate_structure_audit_checkpoint(
                payload,
                structure_diff=structure_diff,
                role="structure_auditor",
                options=structure_auditor_options,
            ),
        )
    return {
        "report_a": "human_or_reference",
        "report_b": "candidate",
        "modality": modality_key,
        "graph_a": graph_a,
        "graph_b": graph_b,
        "alignment": alignment,
        "alignment_audit": alignment_audit,
        "hazards": hazards,
        "hazard_review": hazard_review,
        "hazard_adjudication": hazard_adjudication,
        "structure_diff": structure_diff,
        "structure_audit": structure_audit,
        "warnings": ["image_path_unused_in_mvp_pairwise"] if image_path else [],
    }


def _checkpointed(
    store: StageCheckpointStore | None,
    stage: str,
    inputs: dict[str, Any],
    producer: Any,
    *,
    validator: Any,
) -> dict[str, Any]:
    if store is None:
        return producer()
    return store.get_or_compute(
        stage,
        inputs,
        producer,
        validator=validator,
    )


def _validate_alignment_audit_checkpoint(
    payload: dict[str, Any],
    *,
    alignment: dict[str, Any],
    error_candidate_count: int,
    role: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    validated = AlignmentAuditArtifact.model_validate(payload).model_dump(mode="json")
    if validated["alignment_sha256"] != stable_sha256(alignment):
        raise ValueError("T5 checkpoint alignment SHA-256 mismatch")
    summary = dict(validated.get("adjudication_summary") or {})
    if summary.get("complete") is not True:
        raise ValueError("T5 checkpoint adjudication is incomplete")
    deterministic_error_count = summary.get("deterministic_error_count", -1)
    if (
        not isinstance(deterministic_error_count, int)
        or isinstance(deterministic_error_count, bool)
        or deterministic_error_count != error_candidate_count
    ):
        raise ValueError("T5 checkpoint deterministic error count mismatch")
    if len(validated.get("error_judgements") or []) != error_candidate_count:
        raise ValueError("T5 checkpoint error judgement coverage mismatch")
    _validate_strict_provenance(
        validated["auditor_provenance"],
        role=role,
        implementation_types={"llm_audit"},
        options=options,
    )
    return validated


def _validate_hazard_checkpoint(
    payload: dict[str, Any],
    *,
    error_candidate_count: int,
    role: str,
    options: dict[str, Any],
    strict: bool,
) -> dict[str, Any]:
    validated = HazardResult.model_validate(payload).model_dump(mode="json")
    if len(validated.get("errors") or []) != error_candidate_count:
        raise ValueError("T4 checkpoint hazard count mismatch")
    if strict:
        _validate_strict_provenance(
            validated["provenance"],
            role=role,
            implementation_types={"llm_judge"},
            options=options,
        )
    return validated


def _validate_hazard_review_checkpoint(
    payload: dict[str, Any],
    *,
    primary: dict[str, Any],
    error_candidate_count: int,
    role: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    validated = HazardReviewArtifact.model_validate(payload).model_dump(mode="json")
    if validated["primary_result_sha256"] != stable_sha256(primary):
        raise ValueError("T4 reviewer checkpoint primary SHA-256 mismatch")
    reviewer = validated["reviewer_result"]
    if len(reviewer.get("errors") or []) != error_candidate_count:
        raise ValueError("T4 reviewer checkpoint hazard count mismatch")
    _validate_strict_provenance(
        reviewer["provenance"],
        role=role,
        implementation_types={"llm_judge"},
        options=options,
    )
    return validated


def _validate_hazard_adjudication_checkpoint(
    payload: dict[str, Any],
    *,
    primary: dict[str, Any],
    review: dict[str, Any],
    role: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    validated = HazardAdjudicationArtifact.model_validate(payload).model_dump(mode="json")
    if validated["primary_result_sha256"] != stable_sha256(primary):
        raise ValueError("T4 adjudicator checkpoint primary SHA-256 mismatch")
    if validated["hazard_review_sha256"] != stable_sha256(review):
        raise ValueError("T4 adjudicator checkpoint review SHA-256 mismatch")
    expected_indices = {
        int(item["error_index"])
        for item in review.get("disagreements") or []
        if isinstance(item, dict) and _valid_error_index(item.get("error_index"))
    }
    actual_indices = {
        int(item["error_index"])
        for item in validated.get("decisions") or []
        if isinstance(item, dict) and _valid_error_index(item.get("error_index"))
    }
    if actual_indices != expected_indices:
        raise ValueError("T4 adjudicator checkpoint decision coverage mismatch")
    _validate_strict_provenance(
        validated["adjudicator_provenance"],
        role=role,
        implementation_types={"llm_adjudication"},
        options=options,
    )
    return validated


def _valid_error_index(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_structure_audit_checkpoint(
    payload: dict[str, Any],
    *,
    structure_diff: dict[str, Any],
    role: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    validated = StructureAuditArtifact.model_validate(payload).model_dump(mode="json")
    if validated["structure_diff_sha256"] != stable_sha256(structure_diff):
        raise ValueError("T6 checkpoint structure SHA-256 mismatch")
    _validate_strict_provenance(
        validated["assessor_provenance"],
        role=role,
        implementation_types={"llm_assessment"},
        options=options,
    )
    return validated


def _validate_strict_provenance(
    provenance: dict[str, Any],
    *,
    role: str,
    implementation_types: set[str],
    options: dict[str, Any],
) -> None:
    implementation = str(provenance.get("implementation_type") or "")
    if implementation not in implementation_types:
        raise ValueError(
            f"Strict {role} checkpoint has invalid implementation {implementation!r}"
        )
    if provenance.get("fallback_used") is not False:
        raise ValueError(f"Strict {role} checkpoint cannot contain fallback provenance")
    provider = str(provenance.get("provider") or "")
    if not provider or provider.lower() == "mock":
        raise ValueError(f"Strict {role} checkpoint requires a non-mock provider")
    if str(provenance.get("role") or "") != role:
        raise ValueError(f"Strict checkpoint role mismatch for {role}")
    for field_name in ("provider", "model"):
        expected = str(options.get(field_name) or "")
        if expected and str(provenance.get(field_name) or "") != expected:
            raise ValueError(f"Strict {role} checkpoint {field_name} mismatch")
    expected_host = str(options.get("base_url") or "").split("//", 1)[-1].split("/", 1)[0].lower()
    actual_host = str((provenance.get("metadata") or {}).get("endpoint_host") or "").lower()
    if expected_host and actual_host != expected_host:
        raise ValueError(f"Strict {role} checkpoint endpoint mismatch")
