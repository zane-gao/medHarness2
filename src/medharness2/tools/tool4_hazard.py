from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from medharness2.contracts import (
    HazardAdjudicationArtifact,
    HazardResult,
    HazardReviewArtifact,
)
from medharness2.llm_client import LLMClient, LLMClientError
from medharness2.privacy import ExternalPayloadPolicy
from medharness2.utils.io import parse_json_object


DEFAULT_HAZARD = {
    "false_finding": 3,
    "omission_finding": 4,
    "incorrect_location": 3,
    "incorrect_severity": 2,
    "mismatched_finding": 3,
    "contradiction": 4,
}


class _HazardAdjudicationDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_index: int = Field(ge=0)
    error_type: str = Field(min_length=1)
    hazard_level: int = Field(ge=1, le=5)
    recommended_action: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str]
    abstain: bool


class _HazardAdjudicationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[_HazardAdjudicationDecisionResponse]


def evaluate_hazards(
    error_candidates: list[dict[str, Any]],
    llm_client: LLMClient | None = None,
    *,
    max_retries: int = 1,
    model_role: str = "",
    judge_options: dict[str, Any] | None = None,
    require_llm: bool = False,
    allow_fallback: bool = True,
) -> dict[str, Any]:
    options = dict(judge_options or {})
    deterministic = {"errors": [_default_error(error) for error in error_candidates]}
    if not error_candidates and not require_llm:
        return _result(
            [],
            _metadata("deterministic", False, 0, [], "none", "none", model_role, options),
        )
    client = llm_client or LLMClient()
    provider, model = _client_identity(client, options)
    if require_llm and provider.lower() == "mock":
        raise LLMClientError("Tool 4 strict mode requires a non-mock provider")
    judge_backend = "mock_judge" if provider == "mock" else "llm_judge"
    judge_errors: list[str] = []
    attempts = max(1, int(max_retries))
    judge_candidates = ExternalPayloadPolicy().sanitize_hazard_candidates(
        [_minimal_judge_candidate(candidate) for candidate in error_candidates]
    )
    for index, candidate in enumerate(judge_candidates, start=1):
        error_type = str(candidate.get("error_type") or "mismatched_finding")
        candidate["evidence_id"] = f"e{index}"
        candidate["template_hazard_level"] = DEFAULT_HAZARD.get(error_type, 3)
    for attempt in range(attempts):
        prompt = _judge_prompt(judge_candidates, judge_errors if attempt else [])
        try:
            raw = client.call(
                prompt,
                response_format="json",
                response_json=deterministic,
                payload_classification="deidentified_structured",
                **options,
            )
        # Only transport/client failures are retryable here.  A programming
        # error in the client (for example AttributeError/KeyError) must
        # surface immediately instead of being mislabeled as an LLM failure
        # and silently converted into a deterministic fallback.
        except (LLMClientError, TimeoutError, ConnectionError, OSError) as exc:
            judge_errors.append(f"{type(exc).__name__}: {exc}")
            continue
        try:
            result = parse_json_object(raw, context="Tool 4 Hazard")
            errors = _validated_errors(result, error_candidates, strict=require_llm)
        except ValueError as exc:
            judge_errors.append(str(exc))
            continue
        return _result(
            [_normalize_error({**candidate, **judgement}) for candidate, judgement in zip(error_candidates, errors)],
            _metadata(judge_backend, False, attempt + 1, judge_errors, provider, model, model_role, options),
        )
    if not allow_fallback:
        detail = judge_errors[-1] if judge_errors else "unknown judge error"
        raise LLMClientError(
            f"Tool 4 Hazard failed schema validation after {attempts} attempts: {detail}"
        )
    return _result(
        [_normalize_error(error) for error in deterministic["errors"]],
        _metadata(
            "deterministic_fallback", True, attempts, judge_errors, provider, model, model_role, options
        ),
    )


def review_hazards(
    primary_result: dict[str, Any],
    error_candidates: list[dict[str, Any]],
    llm_client: LLMClient | None = None,
    *,
    max_retries: int = 1,
    model_role: str = "hazard_reviewer",
    judge_options: dict[str, Any] | None = None,
    require_llm: bool = True,
    allow_fallback: bool = False,
    consistency_runs: int = 1,
) -> dict[str, Any]:
    primary = HazardResult.model_validate(primary_result)
    reviewer_payload = evaluate_hazards(
        error_candidates,
        llm_client=llm_client,
        max_retries=max_retries,
        model_role=model_role,
        judge_options=judge_options,
        require_llm=require_llm,
        allow_fallback=allow_fallback,
    )
    reviewer = HazardResult.model_validate(reviewer_payload)
    consistency_runs = max(1, int(consistency_runs))
    reviewer_retests: list[HazardResult] = []
    for _ in range(consistency_runs - 1):
        retest_payload = evaluate_hazards(
            error_candidates,
            llm_client=llm_client,
            max_retries=max_retries,
            model_role=model_role,
            judge_options=judge_options,
            require_llm=require_llm,
            allow_fallback=allow_fallback,
        )
        reviewer_retests.append(HazardResult.model_validate(retest_payload))
    if len(primary.errors) != len(reviewer.errors):
        raise ValueError("Tool 4 reviewer error count does not match the primary result")

    disagreements = []
    exact_agreement_count = 0
    within_one_count = 0
    action_agreement_count = 0
    for index, (primary_error, reviewer_error) in enumerate(zip(primary.errors, reviewer.errors)):
        if primary_error.error_type != reviewer_error.error_type:
            raise ValueError(f"Tool 4 reviewer error_type mismatch at index {index}")
        level_delta = abs(primary_error.hazard_level - reviewer_error.hazard_level)
        same_action = primary_error.recommended_action == reviewer_error.recommended_action
        if level_delta == 0:
            exact_agreement_count += 1
        if level_delta <= 1:
            within_one_count += 1
        if same_action:
            action_agreement_count += 1
        disagreement_types = []
        if level_delta:
            disagreement_types.append("hazard_level")
        if not same_action:
            disagreement_types.append("recommended_action")
        if disagreement_types:
            disagreements.append(
                {
                    "error_index": index,
                    "error_type": primary_error.error_type,
                    "primary_hazard_level": primary_error.hazard_level,
                    "reviewer_hazard_level": reviewer_error.hazard_level,
                    "level_delta": level_delta,
                    "primary_recommended_action": primary_error.recommended_action,
                    "reviewer_recommended_action": reviewer_error.recommended_action,
                    "disagreement_types": disagreement_types,
                    "requires_adjudication": True,
                }
            )

    compared_count = len(primary.errors)
    primary_json = primary.model_dump(mode="json")
    primary_sha256 = hashlib.sha256(
        json.dumps(primary_json, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    payload = {
        "schema_version": "2.0",
        "artifact_type": "hazard_review",
        "primary_result_sha256": primary_sha256,
        "primary_provenance": primary.provenance.model_dump(mode="json"),
        "reviewer_result": reviewer.model_dump(mode="json"),
        "reviewer_consistency": _reviewer_consistency(reviewer, reviewer_retests),
        "disagreements": disagreements,
        "agreement_summary": {
            "compared_count": compared_count,
            "exact_agreement_count": exact_agreement_count,
            "within_one_count": within_one_count,
            "action_agreement_count": action_agreement_count,
            "exact_agreement_rate": round(exact_agreement_count / compared_count, 4) if compared_count else 1.0,
            "within_one_rate": round(within_one_count / compared_count, 4) if compared_count else 1.0,
            "action_agreement_rate": round(action_agreement_count / compared_count, 4) if compared_count else 1.0,
        },
        "primary_preserved": True,
        "requires_adjudication": bool(disagreements),
    }
    return HazardReviewArtifact.model_validate(payload).model_dump(mode="json")


def _reviewer_consistency(
    primary: HazardResult,
    repeats: list[HazardResult],
) -> dict[str, Any]:
    runs = 1 + len(repeats)
    retest_provenance = [
        {
            **repeat.provenance.model_dump(mode="json"),
            "implementation_type": (
                "deterministic_fallback" if repeat.provenance.fallback_used else "llm_json"
            ),
        }
        for repeat in repeats
    ]
    fallback_used = bool(primary.provenance.fallback_used) or any(
        bool(item.get("fallback_used")) for item in retest_provenance
    )
    base = {
        "runs": runs,
        "retest_provenance": retest_provenance,
        "fallback_used": fallback_used,
        "evidence_tier": "debug_fallback" if fallback_used else "real_llm",
        "status": "blocked" if fallback_used else "complete",
    }
    if not repeats:
        return {**base, "exact_rate": None, "within_one_rate": None, "action_rate": None}
    if fallback_used:
        return {
            **base,
            "compared_count": 0,
            "exact_rate": None,
            "within_one_rate": None,
            "action_rate": None,
        }
    compared = 0
    exact = within_one = action = 0
    for repeat in repeats:
        if len(repeat.errors) != len(primary.errors):
            continue
        for first, other in zip(primary.errors, repeat.errors):
            compared += 1
            delta = abs(first.hazard_level - other.hazard_level)
            exact += delta == 0
            within_one += delta <= 1
            action += first.recommended_action == other.recommended_action
    return {
        **base,
        "compared_count": compared,
        "exact_rate": round(exact / compared, 4) if compared else None,
        "within_one_rate": round(within_one / compared, 4) if compared else None,
        "action_rate": round(action / compared, 4) if compared else None,
    }


def adjudicate_hazard_disagreements(
    primary_result: dict[str, Any],
    hazard_review: dict[str, Any],
    error_candidates: list[dict[str, Any]],
    llm_client: LLMClient | None = None,
    *,
    max_retries: int = 1,
    model_role: str = "hazard_adjudicator",
    adjudicator_options: dict[str, Any] | None = None,
    require_llm: bool = True,
    allow_fallback: bool = False,
) -> dict[str, Any]:
    primary = HazardResult.model_validate(primary_result)
    review = HazardReviewArtifact.model_validate(hazard_review)
    primary_json = primary.model_dump(mode="json")
    if review.primary_result_sha256 != _stable_sha256(primary_json):
        raise ValueError("Tool 4 adjudicator primary result hash mismatch")
    if len(primary.errors) != len(error_candidates):
        raise ValueError("Tool 4 adjudicator candidate count mismatch")

    options = dict(adjudicator_options or {})
    client = llm_client or LLMClient()
    provider, model = _client_identity(client, options)
    if require_llm and provider.lower() == "mock":
        raise LLMClientError("Tool 4 adjudicator strict mode requires a non-mock provider")

    disagreements = list(review.disagreements)
    evidence = []
    for position, disagreement in enumerate(disagreements, start=1):
        index = disagreement.error_index
        primary_error = primary.errors[index]
        reviewer_error = review.reviewer_result.errors[index]
        evidence.append(
            {
                "evidence_id": f"d{position}",
                "error_index": index,
                "error_type": primary_error.error_type,
                "candidate": _minimal_judge_candidate(error_candidates[index]),
                "primary": {
                    "hazard_level": primary_error.hazard_level,
                    "recommended_action": primary_error.recommended_action,
                    "explanation": primary_error.explanation,
                    "confidence": primary_error.confidence,
                    "abstain": primary_error.abstain,
                },
                "reviewer": {
                    "hazard_level": reviewer_error.hazard_level,
                    "recommended_action": reviewer_error.recommended_action,
                    "explanation": reviewer_error.explanation,
                    "confidence": reviewer_error.confidence,
                    "abstain": reviewer_error.abstain,
                },
            }
        )

    errors: list[str] = []
    attempts = max(1, int(max_retries))
    response: _HazardAdjudicationResponse | None = None
    used_fallback = False
    for attempt in range(attempts):
        try:
            raw = client.call(
                _adjudication_prompt(evidence, errors if attempt else []),
                response_format="json",
                response_json={
                    "decisions": [
                        {
                            "error_index": item["error_index"],
                            "error_type": item["error_type"],
                            "hazard_level": item["primary"]["hazard_level"],
                            "recommended_action": item["primary"]["recommended_action"],
                            "explanation": "Mock adjudication response.",
                            "confidence": 0.0,
                            "evidence_ids": [item["evidence_id"]],
                            "abstain": True,
                        }
                        for item in evidence
                    ]
                },
                payload_classification="deidentified_structured",
                **options,
            )
            parsed = parse_json_object(raw, context="Tool 4 Hazard Adjudication")
            candidate_response = _HazardAdjudicationResponse.model_validate(parsed)
            _validate_adjudication_response(candidate_response, evidence)
            response = candidate_response
            attempt_count = attempt + 1
            break
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    if response is None:
        if not allow_fallback:
            detail = errors[-1] if errors else "unknown adjudication error"
            raise LLMClientError(
                "Tool 4 Hazard Adjudication failed schema validation after "
                f"{attempts} attempts: {detail}"
            )
        response = _HazardAdjudicationResponse(
            decisions=[
                _HazardAdjudicationDecisionResponse(
                    error_index=item["error_index"],
                    error_type=item["error_type"],
                    hazard_level=item["primary"]["hazard_level"],
                    recommended_action=item["primary"]["recommended_action"],
                    explanation="Adjudication unavailable; clinician review required.",
                    confidence=0.0,
                    evidence_ids=[item["evidence_id"]],
                    abstain=True,
                )
                for item in evidence
            ]
        )
        attempt_count = attempts
        used_fallback = True

    decisions = []
    for decision in response.decisions:
        primary_error = primary.errors[decision.error_index]
        reviewer_error = review.reviewer_result.errors[decision.error_index]
        decisions.append(
            {
                **decision.model_dump(mode="json"),
                "primary_hazard_level": primary_error.hazard_level,
                "reviewer_hazard_level": reviewer_error.hazard_level,
                "primary_recommended_action": primary_error.recommended_action,
                "reviewer_recommended_action": reviewer_error.recommended_action,
            }
        )
    endpoint_host = urlparse(str(options.get("base_url") or "")).hostname or ""
    artifact = {
        "schema_version": "2.0",
        "artifact_type": "hazard_adjudication",
        "primary_result_sha256": _stable_sha256(primary_json),
        "hazard_review_sha256": _stable_sha256(review.model_dump(mode="json")),
        "adjudicator_provenance": {
            "implementation_type": "deterministic_fallback" if used_fallback else "llm_adjudication",
            "provider": provider,
            "model": model,
            "version": "2.0",
            "role": model_role,
            "prompt_version": "tool4-hazard-adjudication-v1",
            "fallback_used": used_fallback,
            "metadata": {
                "attempt_count": attempt_count,
                "error_count": len(errors),
                "errors": errors[-3:],
                "endpoint_host": endpoint_host.lower(),
            },
        },
        "decisions": decisions,
        "disagreement_count": len(disagreements),
        "resolved_count": sum(not item["abstain"] for item in decisions),
        "abstained_count": sum(bool(item["abstain"]) for item in decisions),
        "primary_preserved": True,
        "reviewer_preserved": True,
        "clinical_validation_required": True,
    }
    return HazardAdjudicationArtifact.model_validate(artifact).model_dump(mode="json")


def _adjudication_prompt(
    evidence: list[dict[str, Any]],
    previous_errors: list[str],
) -> str:
    schema = {
        "decisions": [
            {
                "error_index": "matching integer",
                "error_type": "matching error type",
                "hazard_level": "integer 1-5",
                "recommended_action": "no_action|review_if_relevant|radiologist_review|urgent_review",
                "explanation": "independent evidence-based rationale",
                "confidence": "number 0-1",
                "evidence_ids": ["matching dN evidence ID"],
                "abstain": "boolean",
            }
        ]
    }
    retry_note = (
        f"\nPrevious validation errors: {json.dumps(previous_errors[-3:], ensure_ascii=False)}"
        "\nFix every error and return only valid JSON."
        if previous_errors
        else ""
    )
    return (
        "You are the third independent senior-radiologist adjudicator for hazard disagreements. "
        "Review the structured clinical error evidence and both prior judgements. Decide independently; "
        "do not average scores mechanically and do not assume either prior judge is correct. Use 1=no meaningful risk, "
        "2=minor, 3=moderate, 4=high, 5=critical. Return one decision for every input item and preserve its error_index, "
        "error_type, and evidence_id. Abstain when the evidence cannot support a reliable decision.\n"
        f"Required JSON shape: {json.dumps(schema, ensure_ascii=False)}\n"
        f"Disagreements: {json.dumps(evidence, ensure_ascii=False)}"
        f"{retry_note}"
    )


def _validate_adjudication_response(
    response: _HazardAdjudicationResponse,
    evidence: list[dict[str, Any]],
) -> None:
    expected = {int(item["error_index"]): item for item in evidence}
    if len(response.decisions) != len(expected):
        raise ValueError("Tool 4 adjudicator decision count mismatch")
    indices = [decision.error_index for decision in response.decisions]
    if len(indices) != len(set(indices)) or set(indices) != set(expected):
        raise ValueError("Tool 4 adjudicator must decide every disagreement exactly once")
    evidence_id_by_index = {
        int(item["error_index"]): str(item["evidence_id"])
        for item in evidence
    }
    for decision in response.decisions:
        if decision.error_type != expected[decision.error_index]["error_type"]:
            raise ValueError(
                f"Tool 4 adjudicator error_type mismatch at index {decision.error_index}"
            )
        if evidence_id_by_index[decision.error_index] not in decision.evidence_ids:
            raise ValueError(
                f"Tool 4 adjudicator missing evidence ID at index {decision.error_index}"
            )


def _stable_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _default_error(error: dict[str, Any]) -> dict[str, Any]:
    error_type = str(error.get("error_type") or "mismatched_finding")
    return {
        **error,
        "hazard_level": DEFAULT_HAZARD.get(error_type, 3),
        "explanation": f"Deterministic hazard template for {error_type}.",
        "recommended_action": "review_if_relevant",
    }


def _normalize_error(error: dict[str, Any]) -> dict[str, Any]:
    error_type = str(error.get("error_type") or "mismatched_finding")
    try:
        level = int(error.get("hazard_level", DEFAULT_HAZARD.get(error_type, 3)))
    except (TypeError, ValueError):
        level = DEFAULT_HAZARD.get(error_type, 3)
    normalized = {
        **error,
        "error_type": error_type,
        "hazard_level": max(1, min(5, level)),
        "explanation": str(error.get("explanation") or f"MVP hazard estimate for {error_type}."),
        "recommended_action": str(error.get("recommended_action") or "review_if_relevant"),
    }
    for field in ("observation", "location"):
        if normalized.get(field) not in (None, ""):
            continue
        sources = [error.get("finding"), error.get("candidate"), error.get("reference"), error.get("a"), error.get("b")]
        for source in sources:
            value = _canonical_judge_field(source, field)
            if value not in (None, ""):
                normalized[field] = value
                break
    return normalized


def _validated_errors(
    result: dict[str, Any],
    error_candidates: list[dict[str, Any]],
    *,
    strict: bool = False,
) -> list[dict[str, Any]]:
    errors = result.get("errors")
    if not isinstance(errors, list):
        raise ValueError("Tool 4 Hazard: missing errors list")
    if len(errors) != len(error_candidates):
        raise ValueError(f"Tool 4 Hazard: error count mismatch {len(errors)} != {len(error_candidates)}")
    validated: list[dict[str, Any]] = []
    for index, (error, candidate) in enumerate(zip(errors, error_candidates)):
        if not isinstance(error, dict):
            raise ValueError(f"Tool 4 Hazard: errors[{index}] is not an object")
        if not error.get("error_type"):
            raise ValueError(f"Tool 4 Hazard: errors[{index}] missing error_type")
        if str(error.get("error_type")) != str(candidate.get("error_type")):
            raise ValueError(f"Tool 4 Hazard: errors[{index}] error_type mismatch")
        if "hazard_level" not in error:
            raise ValueError(f"Tool 4 Hazard: errors[{index}] missing hazard_level")
        if strict:
            level = error.get("hazard_level")
            if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 5:
                raise ValueError(f"Tool 4 Hazard: errors[{index}] hazard_level must be an integer from 1 to 5")
            explanation = error.get("explanation")
            if not isinstance(explanation, str) or not explanation.strip():
                raise ValueError(f"Tool 4 Hazard: errors[{index}] missing explanation")
            action = error.get("recommended_action")
            if action not in {"no_action", "review_if_relevant", "radiologist_review", "urgent_review"}:
                raise ValueError(f"Tool 4 Hazard: errors[{index}] has invalid recommended_action")
            confidence = error.get("confidence")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                raise ValueError(f"Tool 4 Hazard: errors[{index}] confidence must be from 0 to 1")
            if not isinstance(error.get("abstain"), bool):
                raise ValueError(f"Tool 4 Hazard: errors[{index}] abstain must be boolean")
            expected_evidence_id = f"e{index + 1}"
            evidence_ids = error.get("evidence_ids")
            if not isinstance(evidence_ids, list) or expected_evidence_id not in evidence_ids:
                raise ValueError(
                    f"Tool 4 Hazard: errors[{index}] evidence_ids must include {expected_evidence_id!r}"
                )
        validated.append(error)
    return validated


def _judge_prompt(error_candidates: list[dict[str, Any]], previous_errors: list[str]) -> str:
    schema = {
        "errors": [
            {
                "error_type": "omission_finding|false_finding|incorrect_location|incorrect_severity|mismatched_finding|contradiction|other",
                "hazard_level": "integer 1-5",
                "explanation": "short clinical rationale",
                "recommended_action": "no_action|review_if_relevant|radiologist_review|urgent_review",
                "confidence": "number 0-1",
                "evidence_ids": ["matching input evidence_id"],
                "abstain": "boolean; true when evidence is insufficient",
            }
        ]
    }
    retry_note = f"\nPrevious invalid responses: {previous_errors}\nReturn only valid JSON." if previous_errors else ""
    return (
        "You are a radiology report safety judge. Assign clinical hazard levels to report comparison errors.\n"
        "Use 1=no meaningful risk, 2=minor, 3=moderate, 4=high, 5=critical.\n"
        "The template_hazard_level is a deterministic prior, not a conclusion; revise it when clinical context warrants.\n"
        "Preserve each error_type and cite the matching evidence_id. Include a concise explanation, "
        "recommended_action, confidence, and abstain flag.\n"
        f"Required JSON schema example: {json.dumps(schema, ensure_ascii=False)}\n"
        f"Errors to judge: {json.dumps(error_candidates, ensure_ascii=False)}"
        f"{retry_note}"
    )


def _minimal_judge_candidate(error: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"error_type": str(error.get("error_type") or "mismatched_finding")}
    if isinstance(error.get("alignment_error_index"), int):
        result["alignment_error_index"] = error["alignment_error_index"]
    audit_judgement = error.get("alignment_audit_judgement")
    if isinstance(audit_judgement, dict):
        result["alignment_audit_judgement"] = {
            key: audit_judgement.get(key)
            for key in (
                "disposition",
                "effective_disposition",
                "explanation",
                "confidence",
                "minimum_confidence",
            )
            if audit_judgement.get(key) is not None
        }
    if error.get("original_error_type"):
        result["original_error_type"] = str(error["original_error_type"])
    finding_sources = [error.get("finding"), error.get("candidate"), error.get("reference")]
    scalar_fields = ("observation", "location", "severity", "measurement", "certainty")
    for field in scalar_fields:
        value = error.get(field)
        if value not in (None, ""):
            result[field] = value
            continue
        for source in finding_sources:
            extracted = _canonical_judge_field(source, field)
            if extracted not in (None, ""):
                result[field] = extracted
                break
        if field == "observation" and field not in result:
            for source in finding_sources:
                if isinstance(source, str) and source.strip():
                    result[field] = source.strip()
                    break
    return result


def _canonical_judge_field(source: Any, field: str) -> Any:
    if not isinstance(source, dict):
        return None
    if source.get(field) not in (None, ""):
        return source[field]
    aliases = {
        "observation": ("observation_code", "observation_text"),
        "location": ("anatomy_code", "location_text"),
    }
    for alias in aliases.get(field, ()):
        if source.get(alias) not in (None, ""):
            return source[alias]
    if field == "measurement":
        measurements = source.get("measurements") or []
        if isinstance(measurements, list) and measurements and isinstance(measurements[0], dict):
            value = measurements[0].get("value")
            unit = str(measurements[0].get("unit") or "")
            if isinstance(value, (int, float)) and unit in {"mm", "cm"}:
                return f"{value:g} {unit}"
    return None


def _client_identity(client: Any, options: dict[str, Any]) -> tuple[str, str]:
    llm = getattr(getattr(client, "config", None), "llm", None)
    provider = str(options.get("provider") or getattr(llm, "provider", None) or "custom")
    model = str(options.get("model") or getattr(llm, "model", None) or type(client).__name__)
    return provider, model


def _metadata(
    backend: str,
    fallback_used: bool,
    attempt_count: int,
    judge_errors: list[str],
    provider: str,
    model: str,
    role: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    endpoint_host = urlparse(str(options.get("base_url") or "")).hostname or ""
    return {
        "backend": backend,
        "provider": provider,
        "model": model,
        "role": role or "default",
        "endpoint_host": endpoint_host.lower(),
        "fallback_used": fallback_used,
        "attempt_count": attempt_count,
        "judge_error_count": len(judge_errors),
        "judge_errors": judge_errors[-3:],
        "prompt_version": "tool4-hazard-v2",
    }


def _result(errors: list[dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    provenance_metadata = {
        key: value
        for key, value in metadata.items()
        if key not in {"backend", "provider", "model", "role", "fallback_used"}
    }
    payload = {
        "schema_version": "2.0",
        "artifact_type": "hazard_result",
        "errors": errors,
        "provenance": {
            "implementation_type": str(metadata.get("backend") or "unknown"),
            "provider": str(metadata.get("provider") or ""),
            "model": str(metadata.get("model") or ""),
            "version": "2.0",
            "role": str(metadata.get("role") or ""),
            "prompt_version": str(metadata.get("prompt_version") or ""),
            "fallback_used": bool(metadata.get("fallback_used", False)),
            "metadata": provenance_metadata,
        },
        "metadata": metadata,
    }
    return HazardResult.model_validate(payload).model_dump(mode="json")
