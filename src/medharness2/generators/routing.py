from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable, Mapping

from medharness2.modality import GENERIC_MODALITIES, canonical_modality


ROUTE_TIERS = (
    "exact_modality_body_part",
    "same_modality",
    "same_body_part_cross_modality",
    "universal",
)
_ROUTE_PRIORITY = {tier: index for index, tier in enumerate(ROUTE_TIERS)}
_RUNNABLE_STATES = {"runnable", "smoke_verified"}
_UNIVERSAL_SOURCES = {"external_vlm", "yunwu_general"}

_BODY_PART_ALIASES = {
    "abd": "abdomen",
    "abdominal": "abdomen",
    "abdomenpelvis": "abdomen_pelvis",
    "abdominopelvic": "abdomen_pelvis",
    "ap": "abdomen_pelvis",
    "brain": "brain",
    "cephalic": "head",
    "chest": "chest",
    "chestlung": "chest",
    "cranial": "head",
    "cspine": "spine",
    "head": "head",
    "lung": "chest",
    "pelvic": "pelvis",
    "pelvis": "pelvis",
    "spinal": "spine",
    "spine": "spine",
    "thoracic": "chest",
    "thorax": "chest",
}


def normalize_body_part(value: Any) -> str:
    if value is None:
        return "unknown"
    raw = str(value).strip().lower()
    if not raw:
        return "unknown"
    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", raw)
    if compact in {"", "unknown", "unspecified", "na", "n/a"}:
        return "unknown"
    chinese = {
        "腹部": "abdomen",
        "腹盆": "abdomen_pelvis",
        "盆腔": "pelvis",
        "胸部": "chest",
        "肺": "chest",
        "头部": "head",
        "脑": "brain",
        "脊柱": "spine",
    }
    return chinese.get(compact, _BODY_PART_ALIASES.get(compact, compact))


@dataclass(frozen=True)
class RoutePlanEntry:
    model_key: str
    source: str
    runtime_state: str
    validation_state: str
    route_tier: str | None
    route_reason: str
    eligible: bool
    excluded_reason: str | None
    input_capabilities: tuple[str, ...] = ()
    entry: Any = field(repr=False, compare=False, default=None)

    def to_json(self) -> dict[str, Any]:
        return {
            "model_key": self.model_key,
            "source": self.source,
            "runtime_state": self.runtime_state,
            "validation_state": self.validation_state,
            "route_tier": self.route_tier,
            "route_reason": self.route_reason,
            "eligible": self.eligible,
            "excluded_reason": self.excluded_reason,
            "input_capabilities": list(self.input_capabilities),
        }


@dataclass(frozen=True)
class RoutePlan:
    modality: str
    body_part: str
    case_id: str | None
    generation_mode: str
    available_input_capabilities: tuple[str, ...]
    entries: tuple[RoutePlanEntry, ...]

    @property
    def candidates(self) -> tuple[RoutePlanEntry, ...]:
        selected = [item for item in self.entries if item.eligible]
        return tuple(sorted(selected, key=lambda item: (_ROUTE_PRIORITY[item.route_tier or "universal"], item.model_key)))

    @property
    def candidate_entries(self) -> tuple[Any, ...]:
        return tuple(item.entry for item in self.candidates)

    def to_json(self) -> dict[str, Any]:
        return {
            "normalized_modality": self.modality,
            "normalized_body_part": self.body_part,
            "case_id": self.case_id,
            "generation_mode": self.generation_mode,
            "available_input_capabilities": list(self.available_input_capabilities),
            "entries": [item.to_json() for item in self.entries],
            "candidate_model_keys": [item.model_key for item in self.candidates],
        }


def build_route_plan(
    entries: Iterable[Any],
    *,
    modality: Any,
    body_part: Any,
    case_id: str | None,
    generation_mode: str,
    available_input_capabilities: set[str] | None = None,
    requested: set[str] | None = None,
    sources: set[str] | None = None,
    entry_excluded_reasons: Mapping[str, str] | None = None,
) -> RoutePlan:
    modality_key = canonical_modality(modality)
    body_part_key = normalize_body_part(body_part)
    available = None if available_input_capabilities is None else frozenset(available_input_capabilities)
    requested_keys = set(requested or set())
    source_filter = set(sources or set())
    preexcluded = dict(entry_excluded_reasons or {})
    decisions: list[RoutePlanEntry] = []

    for entry in entries:
        key = str(getattr(entry, "key", ""))
        source = str(getattr(entry, "source", ""))
        runtime_state = str(getattr(entry, "runtime_state", "unavailable"))
        validation_state = str(getattr(entry, "validation_state", "unvalidated"))
        input_capabilities = tuple(str(item) for item in getattr(entry, "input_capabilities", []) if str(item))
        excluded_reason = _entry_excluded_reason(
            entry,
            key=key,
            source=source,
            runtime_state=runtime_state,
            validation_state=validation_state,
            case_id=case_id,
            generation_mode=generation_mode,
            available_input_capabilities=available,
            requested=requested_keys,
            sources=source_filter,
            preexcluded_reason=preexcluded.get(key),
        )
        route_tier: str | None = None
        route_reason = ""
        if excluded_reason is None:
            route_tier, route_reason, excluded_reason = _route_match(
                entry,
                modality=modality_key,
                body_part=body_part_key,
                source=source,
            )
        decisions.append(
            RoutePlanEntry(
                model_key=key,
                source=source,
                runtime_state=runtime_state,
                validation_state=validation_state,
                route_tier=route_tier,
                route_reason=route_reason,
                eligible=route_tier is not None and excluded_reason is None,
                excluded_reason=excluded_reason,
                input_capabilities=input_capabilities,
                entry=entry,
            )
        )

    return RoutePlan(
        modality=modality_key,
        body_part=body_part_key,
        case_id=case_id,
        generation_mode=generation_mode,
        available_input_capabilities=tuple(sorted(available or ())),
        entries=tuple(decisions),
    )


def _entry_excluded_reason(
    entry: Any,
    *,
    key: str,
    source: str,
    runtime_state: str,
    validation_state: str,
    case_id: str | None,
    generation_mode: str,
    available_input_capabilities: frozenset[str] | None,
    requested: set[str],
    sources: set[str],
    preexcluded_reason: str | None,
) -> str | None:
    forced_external_candidate = source == "external_vlm"
    if not forced_external_candidate:
        if requested and "*" not in requested and key not in requested:
            return "requested_model_filter"
        if sources and source not in sources:
            return "requested_source_filter"
    if validation_state == "quality_blocked":
        return "validation_quality_blocked"
    if source == "artifact_reuse":
        if generation_mode not in {"benchmark", "replay"}:
            return "artifact_mode_not_enabled"
        if not case_id:
            return "artifact_case_id_required"
        if preexcluded_reason:
            return preexcluded_reason
    if runtime_state not in _RUNNABLE_STATES:
        return "runtime_not_runnable"
    required = {str(item) for item in getattr(entry, "input_capabilities", []) if str(item)}
    required.discard("artifact")
    if available_input_capabilities is not None and required and not required.intersection(available_input_capabilities):
        return "input_asset_incompatible"
    return None


def _route_match(entry: Any, *, modality: str, body_part: str, source: str) -> tuple[str | None, str, str | None]:
    supported_modalities = {canonical_modality(item) for item in getattr(entry, "supported_modalities", [])}
    supported_modalities.discard("unknown")
    supported_body_parts = {normalize_body_part(item) for item in getattr(entry, "supported_body_parts", [])}
    supported_body_parts.discard("")
    universal = (
        bool(getattr(entry, "is_universal", False))
        or source in _UNIVERSAL_SOURCES
        or bool(supported_modalities & GENERIC_MODALITIES)
    )
    body_exact = body_part != "unknown" and body_part in supported_body_parts
    modality_exact = modality != "unknown" and modality in supported_modalities
    modality_general = "unknown" in supported_body_parts or not supported_body_parts

    if modality_exact and body_exact:
        return "exact_modality_body_part", "modality_and_body_part_exact", None
    if modality_exact:
        reason = (
            "modality_general_model"
            if modality_general
            else "modality_match_body_part_not_exact"
        )
        return "same_modality", reason, None
    if body_exact and (bool(getattr(entry, "cross_modality_allowed", False)) or universal):
        return "same_body_part_cross_modality", "explicit_cross_modality_or_universal", None
    if universal:
        return "universal", "explicit_universal_model", None
    if body_exact and modality != "unknown":
        return None, "", "cross_modality_not_declared"
    if modality == "unknown" or body_part == "unknown":
        return None, "", "unknown_input_requires_universal_model"
    return None, "", "no_route_match"


__all__ = ["ROUTE_TIERS", "RoutePlan", "RoutePlanEntry", "build_route_plan", "normalize_body_part"]
