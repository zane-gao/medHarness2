from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, field_validator

from medharness2.contracts import (
    AlignmentAuditArtifact,
    AlignmentAuditIssue,
    AlignmentErrorJudgement,
)
from medharness2.llm_client import LLMClient, LLMClientError
from medharness2.utils.io import parse_json_object


def _strict_positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


_ERROR_TYPE_VALUES = (
    "false_finding",
    "omission_finding",
    "incorrect_location",
    "incorrect_severity",
    "mismatched_finding",
    "contradiction",
    "other",
)
_ERROR_TYPES = frozenset(_ERROR_TYPE_VALUES)


class _AuditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["pass", "issues_found", "abstain"]
    confidence: StrictFloat = Field(ge=0, le=1)
    summary: str = Field(min_length=1)
    issues: list[AlignmentAuditIssue]
    error_judgements: list[AlignmentErrorJudgement] = Field(default_factory=list)

    @field_validator("confidence", mode="before")
    @classmethod
    def _require_real_float(cls, value: Any) -> Any:
        """Reject JSON number coercion for the LLM confidence contract.

        Pydantic's ``StrictFloat`` still accepts an integer (``1``) and
        converts it to ``1.0``.  LLM responses are an external contract, so
        keep the distinction explicit: only an actual, non-boolean float is
        valid here.
        """
        if isinstance(value, bool) or not isinstance(value, float):
            raise TypeError("confidence must be a float")
        return value


def audit_alignment(
    candidate_graph: dict[str, Any],
    reference_graph: dict[str, Any],
    alignment_result: dict[str, Any],
    llm_client: LLMClient | None = None,
    *,
    max_retries: int = 1,
    model_role: str = "alignment_auditor",
    auditor_options: dict[str, Any] | None = None,
    require_llm: bool = True,
    allow_fallback: bool = False,
    max_errors_per_call: int = 5,
) -> dict[str, Any]:
    options = dict(auditor_options or {})
    client = llm_client or LLMClient()
    provider, model = _client_identity(client, options)
    if require_llm and provider.lower() == "mock":
        raise LLMClientError("Tool 5 alignment audit strict mode requires a non-mock provider")

    bundle, valid_candidate_ids, valid_reference_ids = _audit_bundle(
        candidate_graph,
        reference_graph,
        alignment_result,
    )
    error_count = len(alignment_result.get("error_candidates") or [])
    chunk_size = _strict_positive_int(max_errors_per_call, "max_errors_per_call")
    target_chunks = [
        list(range(start, min(start + chunk_size, error_count)))
        for start in range(0, error_count, chunk_size)
    ] or [[]]
    errors: list[str] = []
    attempts = _strict_positive_int(max_retries, "max_retries")
    responses: list[_AuditResponse] = []
    chunk_attempt_counts: list[int] = []
    for chunk_index, target_indices in enumerate(target_chunks):
        chunk_errors: list[str] = []
        response: _AuditResponse | None = None
        for attempt in range(attempts):
            prompt = _audit_prompt(
                bundle,
                chunk_errors if attempt else [],
                target_error_indices=target_indices,
            )
            try:
                raw = client.call(
                    prompt,
                    response_format="json",
                    response_json={
                        "verdict": "pass",
                        "confidence": 0.0,
                        "summary": "Mock alignment audit response.",
                        "issues": [],
                        "error_judgements": [
                            {
                                "error_index": index,
                                "disposition": "valid",
                                "suggested_error_type": None,
                                "explanation": "Mock judgement.",
                                "confidence": 0.0,
                            }
                            for index in target_indices
                        ],
                    },
                    payload_classification="deidentified_structured",
                    **options,
                )
                parsed = parse_json_object(raw, context="Tool 5 Alignment Audit")
                candidate_response = _AuditResponse.model_validate(parsed)
                _validate_response_references(
                    candidate_response,
                    valid_candidate_ids=valid_candidate_ids,
                    valid_reference_ids=valid_reference_ids,
                    error_count=error_count,
                    expected_error_indices=target_indices,
                )
                response = candidate_response
                chunk_attempt_counts.append(attempt + 1)
                break
            except Exception as exc:
                chunk_errors.append(f"{type(exc).__name__}: {exc}")
        errors.extend(
            f"chunk={chunk_index + 1}: {error}"
            for error in chunk_errors
        )
        if response is None:
            if not allow_fallback:
                detail = chunk_errors[-1] if chunk_errors else "unknown audit error"
                raise LLMClientError(
                    "Tool 5 Alignment Audit failed schema validation for "
                    f"chunk {chunk_index + 1}/{len(target_chunks)} after "
                    f"{attempts} attempts: {detail}"
                )
            break
        responses.append(response)

    if len(responses) == len(target_chunks):
        response = _merge_audit_responses(responses)
        return _artifact(
            response,
            alignment_result=alignment_result,
            provider=provider,
            model=model,
            role=model_role,
            options=options,
            fallback_used=False,
            attempt_count=sum(chunk_attempt_counts),
            errors=errors,
            execution_metadata={
                "chunk_count": len(target_chunks),
                "chunk_size": chunk_size,
                "chunk_attempt_counts": chunk_attempt_counts,
            },
        )

    fallback = _AuditResponse(
        verdict="abstain",
        confidence=0.0,
        summary="Alignment audit unavailable; deterministic alignment is preserved for adjudication.",
        issues=[],
    )
    return _artifact(
        fallback,
        alignment_result=alignment_result,
        provider=provider,
        model=model,
        role=model_role,
        options=options,
        fallback_used=True,
        attempt_count=sum(chunk_attempt_counts) + attempts,
        errors=errors,
        execution_metadata={
            "chunk_count": len(target_chunks),
            "chunk_size": chunk_size,
            "chunk_attempt_counts": chunk_attempt_counts,
        },
    )


def _object_list(value: Any, label: str) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be a list of objects")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _audit_bundle(
    candidate_graph: dict[str, Any],
    reference_graph: dict[str, Any],
    alignment_result: dict[str, Any],
) -> tuple[dict[str, Any], set[str], set[str]]:
    candidate_findings = _object_list(candidate_graph.get("findings"), "candidate findings")
    reference_findings = _object_list(reference_graph.get("findings"), "reference findings")
    candidate_rows, candidate_ids = _minimal_findings(candidate_findings, "candidate")
    reference_rows, reference_ids = _minimal_findings(reference_findings, "reference")

    pair_rows = []
    for category in ("matched", "approximate_match", "mismatched"):
        for row in _object_list(alignment_result.get(category), category):
            pair_rows.append(
                {
                    "category": category,
                    "candidate_id": _resolve_id(row.get("candidate") or row.get("a"), candidate_findings, candidate_ids),
                    "reference_id": _resolve_id(row.get("reference") or row.get("b"), reference_findings, reference_ids),
                    "differences": _string_list(row.get("differences"), f"{category}.differences"),
                }
            )
    error_rows = []
    for index, error in enumerate(_object_list(alignment_result.get("error_candidates"), "error_candidates")):
        error_rows.append(
            {
                "error_index": index,
                "error_type": str(error.get("error_type") or "other"),
                "candidate_id": _resolve_id(
                    error.get("candidate") or error.get("a"), candidate_findings, candidate_ids, required=False
                ),
                "reference_id": _resolve_id(
                    error.get("reference") or error.get("b"), reference_findings, reference_ids, required=False
                ),
            }
        )
    return (
        {
            "candidate_findings": candidate_rows,
            "reference_findings": reference_rows,
            "deterministic_pairs": pair_rows,
            "candidate_only_ids": [
                _resolve_id(finding, candidate_findings, candidate_ids)
                for finding in alignment_result.get("candidate_only") or []
            ],
            "reference_only_ids": [
                _resolve_id(finding, reference_findings, reference_ids)
                for finding in alignment_result.get("reference_only") or []
            ],
            "error_candidates": error_rows,
            "metrics": _object(alignment_result.get("metrics"), "metrics"),
        },
        set(candidate_ids),
        set(reference_ids),
    )


def _minimal_findings(findings: list[dict[str, Any]], namespace: str) -> tuple[list[dict[str, Any]], list[str]]:
    rows = []
    identifiers = []
    for index, finding in enumerate(findings, start=1):
        raw_id = str(finding.get("finding_id") or f"f{index}")
        identifier = f"{namespace}:{raw_id}"
        if identifier in identifiers:
            raise ValueError(f"Tool 5 alignment audit found duplicate {namespace} finding ID {raw_id!r}")
        identifiers.append(identifier)
        measurements = []
        for measurement in finding.get("measurements") or []:
            if isinstance(measurement, dict):
                measurements.append(
                    {
                        key: measurement.get(key)
                        for key in ("value", "unit", "normalized_mm")
                        if measurement.get(key) is not None
                    }
                )
        rows.append(
            {
                "id": identifier,
                "observation": finding.get("observation_code")
                or finding.get("observation_text")
                or finding.get("observation"),
                "location": finding.get("anatomy_code")
                or finding.get("location_text")
                or finding.get("location"),
                "laterality": finding.get("laterality") or "unknown",
                "certainty": finding.get("certainty") or "present",
                "severity": finding.get("severity"),
                "measurements": measurements,
            }
        )
    return rows, identifiers


def _resolve_id(
    finding: Any,
    findings: list[dict[str, Any]],
    identifiers: list[str],
    *,
    required: bool = True,
) -> str | None:
    if not isinstance(finding, dict):
        if required:
            raise ValueError("Tool 5 alignment audit could not resolve a finding reference")
        return None
    for index, candidate in enumerate(findings):
        if candidate is finding:
            return identifiers[index]
    equal_indices = [index for index, candidate in enumerate(findings) if candidate == finding]
    if len(equal_indices) == 1:
        return identifiers[equal_indices[0]]
    if required:
        raise ValueError("Tool 5 alignment audit found an ambiguous finding reference")
    return None


def _audit_prompt(
    bundle: dict[str, Any],
    previous_errors: list[str],
    *,
    target_error_indices: list[int] | None = None,
) -> str:
    allowed_error_types = "|".join(_ERROR_TYPE_VALUES)
    allowed_issue_types = "missed_match|incorrect_match|incorrect_error_type|unsupported_error|missing_error|other"
    schema = {
        "verdict": "pass|issues_found|abstain",
        "confidence": "number 0-1",
        "summary": "short clinical audit summary",
        "issues": [
            {
                "issue_type": "missed_match|incorrect_match|incorrect_error_type|unsupported_error|missing_error|other",
                "candidate_id": "candidate finding ID or null",
                "reference_id": "reference finding ID or null",
                "error_index": "integer or null",
                "suggested_error_type": f"{allowed_error_types}|null",
                "explanation": "short clinical rationale",
                "confidence": "number 0-1",
            }
        ],
        "error_judgements": [
            {
                "error_index": "integer matching every input error exactly once",
                "disposition": "valid|unsupported|incorrect_error_type|abstain",
                "suggested_error_type": (
                    f"one of {allowed_error_types} only for incorrect_error_type, otherwise null"
                ),
                "explanation": "short clinical rationale",
                "confidence": "number 0-1",
            }
        ],
    }
    selected_indices = (
        list(target_error_indices)
        if target_error_indices is not None
        else [
            int(error["error_index"])
            for error in bundle.get("error_candidates") or []
        ]
    )
    selected = set(selected_indices)
    prompt_bundle = {
        **bundle,
        "target_error_indices": selected_indices,
        "error_candidates": [
            error
            for error in bundle.get("error_candidates") or []
            if int(error["error_index"]) in selected
        ],
    }
    retry_note = (
        f"\nPrevious validation errors: {json.dumps(previous_errors[-3:], ensure_ascii=False)}"
        "\nFix every error and return only valid JSON. For issues with issue_type=incorrect_match "
        "or missed_match, candidate_id and reference_id are both mandatory and must be copied "
        "exactly from the structured audit bundle; do not omit either field. "
        f"issue_type must be exactly one of [{allowed_issue_types}] and never an input error_type. "
        f"suggested_error_type may be only one of exactly [{allowed_error_types}] or null; "
        "never use a description, synonym, or free-form explanation in that field."
        if previous_errors
        else ""
    )
    return (
        "You are a senior radiologist auditing a deterministic finding-graph alignment. "
        "Check semantic equivalence, anatomy, laterality, certainty, severity, measurements, and whether each error type is justified. "
        "Judge every error listed in target_error_indices exactly once in error_judgements and do not judge other indices. "
        "Mark semantically equivalent false-finding/omission "
        "pairs as unsupported, and use incorrect_error_type only with a valid replacement type. Use abstain when evidence is insufficient. "
        f"The only allowed issue_type values are {allowed_issue_types}; never use an input error_type in issue_type. "
        f"The only allowed suggested_error_type values are {allowed_error_types}, or null. "
        "For this audit, always return issues as an empty list and use error_judgements only. "
        "Do not rewrite the alignment and do not invent IDs. "
        "Set suggested_error_type to null unless disposition=incorrect_error_type and you can copy one exact allowed value. "
        "Use pass only when issues is empty and every error is valid; use issues_found when an issue or non-valid error judgement exists; "
        "use abstain when the overall evidence is insufficient.\n"
        f"Required JSON shape: {json.dumps(schema, ensure_ascii=False)}\n"
        f"Structured audit bundle: {json.dumps(prompt_bundle, ensure_ascii=False)}"
        f"{retry_note}"
    )


def _validate_response_references(
    response: _AuditResponse,
    *,
    valid_candidate_ids: set[str],
    valid_reference_ids: set[str],
    error_count: int,
    expected_error_indices: list[int] | None = None,
) -> None:
    for index, issue in enumerate(response.issues):
        if issue.candidate_id is not None and issue.candidate_id not in valid_candidate_ids:
            raise ValueError(f"Tool 5 alignment audit issue {index} references unknown candidate_id")
        if issue.reference_id is not None and issue.reference_id not in valid_reference_ids:
            raise ValueError(f"Tool 5 alignment audit issue {index} references unknown reference_id")
        if issue.error_index is not None and issue.error_index >= error_count:
            raise ValueError(f"Tool 5 alignment audit issue {index} references unknown error_index")
        if (
            issue.error_index is not None
            and expected_error_indices is not None
            and issue.error_index not in expected_error_indices
        ):
            raise ValueError(
                f"Tool 5 alignment audit issue {index} references an error outside the current chunk"
            )
        if issue.suggested_error_type is not None and issue.suggested_error_type not in _ERROR_TYPES:
            raise ValueError(f"Tool 5 alignment audit issue {index} has invalid suggested_error_type")
    judgement_indices = [
        judgement.error_index for judgement in response.error_judgements
    ]
    if len(judgement_indices) != len(set(judgement_indices)):
        raise ValueError("Tool 5 alignment audit has duplicate error judgements")
    expected = (
        sorted(expected_error_indices)
        if expected_error_indices is not None
        else list(range(error_count))
    )
    if sorted(judgement_indices) != expected:
        raise ValueError(
            "Tool 5 alignment audit must judge every requested error exactly once"
        )
    for judgement in response.error_judgements:
        if (
            judgement.suggested_error_type is not None
            and judgement.suggested_error_type not in _ERROR_TYPES
        ):
            raise ValueError(
                "Tool 5 alignment audit error judgement "
                f"{judgement.error_index} has invalid suggested_error_type"
            )


def _merge_audit_responses(
    responses: list[_AuditResponse],
) -> _AuditResponse:
    judgements = sorted(
        [
            judgement
            for response in responses
            for judgement in response.error_judgements
        ],
        key=lambda item: item.error_index,
    )
    issue_payloads: dict[str, AlignmentAuditIssue] = {}
    for response in responses:
        for issue in response.issues:
            key = json.dumps(
                issue.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            issue_payloads[key] = issue
    issues = list(issue_payloads.values())
    if any(
        response.verdict == "abstain" for response in responses
    ) or any(judgement.disposition == "abstain" for judgement in judgements):
        verdict = "abstain"
    elif issues or any(
        judgement.disposition != "valid" for judgement in judgements
    ):
        verdict = "issues_found"
    else:
        verdict = "pass"
    summaries = [response.summary.strip() for response in responses]
    return _AuditResponse(
        verdict=verdict,
        confidence=min(response.confidence for response in responses),
        summary=" ".join(
            f"Chunk {index}: {summary}"
            for index, summary in enumerate(summaries, start=1)
        ),
        issues=issues,
        error_judgements=judgements,
    )


def _artifact(
    response: _AuditResponse,
    *,
    alignment_result: dict[str, Any],
    provider: str,
    model: str,
    role: str,
    options: dict[str, Any],
    fallback_used: bool,
    attempt_count: int,
    errors: list[str],
    execution_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    alignment_sha256 = hashlib.sha256(
        json.dumps(alignment_result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    endpoint_host = urlparse(str(options.get("base_url") or "")).hostname or ""
    metadata = {
        "attempt_count": attempt_count,
        "error_count": len(errors),
        "errors": errors[-3:],
        "endpoint_host": endpoint_host.lower(),
        "prompt_version": "tool5-alignment-audit-v2",
        **dict(execution_metadata or {}),
    }
    adjudicated_error_candidates, adjudication_summary = _adjudicate_errors(
        alignment_result,
        response.error_judgements,
    )
    payload = {
        "schema_version": "2.0",
        "artifact_type": "alignment_audit",
        "alignment_sha256": alignment_sha256,
        "auditor_provenance": {
            "implementation_type": "deterministic_fallback" if fallback_used else "llm_audit",
            "provider": provider,
            "model": model,
            "version": "2.0",
            "role": role or "default",
            "prompt_version": "tool5-alignment-audit-v2",
            "fallback_used": fallback_used,
            "metadata": metadata,
        },
        "verdict": response.verdict,
        "confidence": response.confidence,
        "summary": response.summary.strip(),
        "issues": [issue.model_dump(mode="json") for issue in response.issues],
        "error_judgements": [
            judgement.model_dump(mode="json")
            for judgement in response.error_judgements
        ],
        "adjudicated_error_candidates": adjudicated_error_candidates,
        "adjudication_summary": adjudication_summary,
        "primary_preserved": True,
        "requires_adjudication": response.verdict != "pass",
        "metadata": metadata,
    }
    return AlignmentAuditArtifact.model_validate(payload).model_dump(mode="json")


def _adjudicate_errors(
    alignment_result: dict[str, Any],
    judgements: list[AlignmentErrorJudgement],
    *,
    minimum_confidence: float = 0.8,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    deterministic = _object_list(alignment_result.get("error_candidates"), "error_candidates")
    by_index = {judgement.error_index: judgement for judgement in judgements}
    retained: list[dict[str, Any]] = []
    rejected_count = 0
    modified_count = 0
    abstained_count = 0
    for index, source in enumerate(deterministic):
        judgement = by_index.get(index)
        if judgement is None:
            retained.append(copy.deepcopy(source))
            abstained_count += 1
            continue
        effective_disposition = judgement.disposition
        if judgement.confidence < minimum_confidence:
            effective_disposition = "abstain"
        if effective_disposition == "unsupported":
            rejected_count += 1
            continue
        candidate = copy.deepcopy(source)
        candidate["alignment_error_index"] = index
        candidate["alignment_audit_judgement"] = {
            **judgement.model_dump(mode="json"),
            "effective_disposition": effective_disposition,
            "minimum_confidence": minimum_confidence,
        }
        if effective_disposition == "incorrect_error_type":
            candidate["original_error_type"] = candidate.get("error_type")
            candidate["error_type"] = judgement.suggested_error_type
            modified_count += 1
        elif effective_disposition == "abstain":
            abstained_count += 1
        retained.append(candidate)
    return retained, {
        "deterministic_error_count": len(deterministic),
        "retained_error_count": len(retained),
        "rejected_error_count": rejected_count,
        "modified_error_count": modified_count,
        "abstained_error_count": abstained_count,
        "complete": len(by_index) == len(deterministic),
    }


def _client_identity(client: Any, options: dict[str, Any]) -> tuple[str, str]:
    llm = getattr(getattr(client, "config", None), "llm", None)
    provider = str(options.get("provider") or getattr(llm, "provider", None) or "custom")
    model = str(options.get("model") or getattr(llm, "model", None) or type(client).__name__)
    return provider, model
