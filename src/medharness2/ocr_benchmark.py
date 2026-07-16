from __future__ import annotations

import json
import hashlib
import math
import re
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from medharness2.utils.io import write_json


NEGATION_TOKENS = ("no", "not", "without", "否认", "未见", "未发现", "无")
_TEXT_PATH_SUFFIXES = frozenset({".txt", ".text", ".md", ".json", ".jsonl", ".csv", ".tsv", ".ocr"})


def evaluate_ocr_candidates(manifest_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    """Evaluate frozen OCR candidate text against line-verified gold text.

    Manifest rows require ``case_id``, ``gold_text`` and ``candidates``. Candidate
    values may be text or a JSON path containing ``text``. Missing gold/candidate
    artifacts produce a blocked summary instead of a misleading zero score.
    """
    manifest_file = Path(manifest_path)
    manifest = _read_manifest(manifest_file)
    rows: list[dict[str, Any]] = []
    blocked: list[str] = []
    hard_blocked = False
    if not manifest_file.exists():
        blocked.append("manifest:missing_file")
        hard_blocked = True
    elif not manifest:
        blocked.append("manifest:empty")
        hard_blocked = True
    for index, item in enumerate(manifest):
        if not isinstance(item, dict):
            blocked.append(f"manifest:row_{index}:not_an_object")
            hard_blocked = True
            continue
        if item.get("_manifest_error"):
            blocked.append(f"manifest:{item['_manifest_error']}")
            hard_blocked = True
            continue
        case_id = str(item.get("case_id") or "")
        gold_value = item.get("gold_text")
        gold = _resolve_text(gold_value, base_dir=manifest_file.parent)
        candidates = item.get("candidates") or {}
        if not case_id or not gold or not isinstance(candidates, dict):
            blocked.append(case_id or "unknown_case")
            if _is_declared_text_path(gold_value, base_dir=manifest_file.parent) and not gold:
                blocked[-1] = f"missing_gold:{case_id or 'unknown_case'}"
                hard_blocked = True
            continue
        if not candidates:
            # An otherwise valid gold row with no candidates must never be
            # treated as a successful one-model benchmark.
            blocked.append(f"missing_candidates:{case_id}")
            hard_blocked = True
            continue
        for model, value in candidates.items():
            model_name = str(model).strip()
            if not model_name:
                blocked.append(f"manifest:{case_id}:empty_model_key")
                hard_blocked = True
                continue
            text = _resolve_text(value, base_dir=manifest_file.parent)
            if not text:
                if _is_declared_text_path(value, base_dir=manifest_file.parent):
                    blocked.append(f"missing_candidate:{case_id}:{model_name}")
                    hard_blocked = True
                else:
                    blocked.append(f"{case_id}:{model_name}")
                continue
            provenance_blockers = _validate_candidate_provenance(
                item,
                model_name,
                value,
                manifest_dir=manifest_file.parent,
            )
            if provenance_blockers:
                blocked.extend(provenance_blockers)
                hard_blocked = True
                continue
            rows.append({"case_id": case_id, "model": model_name, **_metrics(gold, text)})
    summary = _aggregate(rows)
    coverage_blockers = _coverage_blockers(rows, manifest)
    duplicate_blockers = _duplicate_blockers(rows)
    all_blockers = [*blocked, *coverage_blockers, *duplicate_blockers]
    status = (
        "blocked"
        if not manifest or hard_blocked or (not rows and all_blockers)
        else "completed_with_blockers"
        if all_blockers
        else "succeeded"
    )
    result = {
        "schema_version": "1.0",
        "artifact_type": "ocr_candidate_benchmark",
        "status": status,
        "manifest": str(manifest_path),
        "case_count": len(manifest),
        "evaluated_count": len(rows),
        "blocked_items": all_blockers,
        "metrics": rows,
        "by_model": summary,
        "selection": _selection(summary, blockers=all_blockers),
    }
    write_json(output_path, result)
    return result


def _metrics(gold: str, candidate: str) -> dict[str, Any]:
    clinical_gold, clinical_candidate = _clinical_text(gold), _clinical_text(candidate)
    gold_norm, candidate_norm = _normalize(clinical_gold), _normalize(clinical_candidate)
    gold_tokens = _clinical_tokens(gold)
    candidate_tokens = _clinical_tokens(candidate)
    full_gold_norm, full_candidate_norm = _normalize(gold), _normalize(candidate)
    return {
        # CER intentionally excludes administrative/header text outside the
        # Findings/Impression sections.  Reports without recognizable sections
        # fall back to the full text and expose that fact for auditability.
        "clinical_cer": round(_levenshtein(gold_norm, candidate_norm) / max(len(gold_norm), 1), 6),
        "clinical_text_source": "sections" if clinical_gold != gold else "full_text_fallback",
        "full_char_count": len(full_candidate_norm),
        "digit_token_accuracy": _token_accuracy(gold_tokens["digits"], candidate_tokens["digits"]),
        "negation_token_accuracy": _token_accuracy(gold_tokens["negations"], candidate_tokens["negations"]),
        "possible_truncation": _possible_truncation(candidate),
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["model"], []).append(row)
    result = {}
    for model, items in grouped.items():
        valid_items = [
            item
            for item in items
            if all(
                isinstance(item.get(field), (int, float))
                and not isinstance(item.get(field), bool)
                and math.isfinite(float(item[field]))
                for field in (
                    "clinical_cer",
                    "digit_token_accuracy",
                    "negation_token_accuracy",
                )
            )
        ]
        if not valid_items:
            continue
        result[model] = {
            "case_count": len(valid_items),
            "clinical_cer_mean": round(sum(float(x["clinical_cer"]) for x in valid_items) / len(valid_items), 6),
            "digit_token_accuracy_mean": round(sum(float(x["digit_token_accuracy"]) for x in valid_items) / len(valid_items), 6),
            "negation_token_accuracy_mean": round(sum(float(x["negation_token_accuracy"]) for x in valid_items) / len(valid_items), 6),
            "truncation_count": sum(bool(x["possible_truncation"]) for x in valid_items),
        }
    return result


def _selection(summary: dict[str, dict[str, Any]], *, blockers: list[str] | None = None) -> dict[str, Any]:
    if blockers:
        if any(item.startswith("manifest:") for item in blockers):
            reason = "invalid_manifest"
        elif any(item.startswith("provenance:") for item in blockers):
            reason = "invalid_candidate_provenance"
        elif any(item.startswith("missing_candidates:") for item in blockers):
            reason = "missing_candidates"
        elif any(not item.startswith(("coverage:", "duplicate:")) for item in blockers):
            reason = "missing_gold_or_candidate_artifacts"
        elif any(item.startswith("coverage:") for item in blockers):
            reason = "unequal_candidate_coverage"
        elif any(item.startswith("duplicate:") for item in blockers):
            reason = "duplicate_case_model_rows"
        else:
            reason = "missing_gold_or_candidate_artifacts"
        return {"status": "blocked", "reason": reason, "blocked_items": list(blockers)}
    if not summary:
        return {"status": "blocked", "reason": "no_evaluated_candidates"}
    winner = min(summary, key=lambda model: (summary[model]["clinical_cer_mean"], summary[model]["truncation_count"], -summary[model]["negation_token_accuracy_mean"]))
    return {"status": "provisional", "primary_model": winner, "rule": "lowest clinical CER, then truncation count, then negation accuracy; clinical review required"}


def _coverage_blockers(rows: list[dict[str, Any]], manifest: list[Any] | None = None) -> list[str]:
    """Reject model comparisons when candidates do not share the same cases."""
    cases_by_model: dict[str, set[str]] = {}
    for row in rows:
        cases_by_model.setdefault(str(row["model"]), set()).add(str(row["case_id"]))
    # Include models that have a missing/empty candidate in the manifest.  If
    # we only inspect successful rows, an entirely missing model disappears and
    # unequal coverage can be mistaken for a clean single-model benchmark.
    manifest_cases_by_model: dict[str, set[str]] = {}
    for item in manifest or []:
        if not isinstance(item, dict) or item.get("_manifest_error"):
            continue
        case_id = str(item.get("case_id") or "")
        candidates = item.get("candidates")
        if not case_id or not isinstance(candidates, dict):
            continue
        for model in candidates:
            manifest_cases_by_model.setdefault(str(model).strip(), set()).add(case_id)
    for model, cases in manifest_cases_by_model.items():
        cases_by_model.setdefault(model, set()).update(cases & cases_by_model.get(model, set()))
    if len(cases_by_model) < 2:
        return []
    # A model is covered only when it produced a non-empty candidate for every
    # case in its declared manifest coverage.  Compare all models to the common
    # case set, rather than choosing an arbitrary baseline set.
    declared_cases = set().union(*manifest_cases_by_model.values()) if manifest_cases_by_model else set().union(*cases_by_model.values())
    evaluated_cases_by_model = {
        model: {str(row["case_id"]) for row in rows if str(row["model"]) == model}
        for model in cases_by_model
    }
    return [
        f"coverage:{model}"
        for model in sorted(cases_by_model)
        if evaluated_cases_by_model.get(model, set()) != declared_cases
    ]


def _duplicate_blockers(rows: list[dict[str, Any]]) -> list[str]:
    seen: set[tuple[str, str]] = set()
    duplicates: set[tuple[str, str]] = set()
    for row in rows:
        key = (str(row["case_id"]), str(row["model"]))
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    return [f"duplicate:{case_id}:{model}" for case_id, model in sorted(duplicates)]


def _read_manifest(path: Path) -> list[Any]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".jsonl":
        rows: list[Any] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            return [{"_manifest_error": f"read_error:{type(exc).__name__}"}]
        for line_no, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except (TypeError, ValueError) as exc:
                rows.append({"_manifest_error": f"line_{line_no}:invalid_json:{type(exc).__name__}"})
        return rows
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        return [{"_manifest_error": f"invalid_json:{type(exc).__name__}"}]
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        return list(payload["cases"])
    return [{"_manifest_error": "root_must_be_list_or_cases_array"}]


def _resolve_text(value: Any, *, base_dir: Path | None = None) -> str:
    path, declared_path = _declared_text_path(value, base_dir=base_dir)
    if path is not None and path.is_file():
        try:
            if path.suffix.lower() == ".json":
                payload = json.loads(path.read_text(encoding="utf-8"))
                return str(payload.get("text") or payload.get("ocr_text") or "").strip() if isinstance(payload, dict) else ""
            return path.read_text(encoding="utf-8").strip()
        except (OSError, TypeError, ValueError):
            return ""
    if declared_path:
        return ""
    if isinstance(value, dict):
        return str(value.get("text") or value.get("ocr_text") or "").strip()
    return str(value or "").strip()


def _declared_text_path(value: Any, *, base_dir: Path | None = None) -> tuple[Path | None, bool]:
    """Return a manifest-declared text path without mistaking prose for one.

    Structured ``{"path": ...}`` values are always path declarations.  For
    legacy string manifests, common text/artifact suffixes and path-like
    strings retain the historical file-loading behavior; ordinary inline prose
    remains inline text.
    """
    raw: str | None = None
    if isinstance(value, dict):
        for key in ("path", "file", "file_path", "text_path"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                raw = candidate.strip()
                break
    elif isinstance(value, str):
        candidate = value.strip()
        if candidate:
            path = Path(candidate)
            path_like = (
                path.is_absolute()
                or path.exists()
                or path.suffix.lower() in _TEXT_PATH_SUFFIXES
                or (not any(char.isspace() for char in candidate) and ("/" in candidate or "\\" in candidate))
                or candidate.startswith(("./", "../", "~"))
            )
            if path_like:
                raw = candidate
    if raw is None:
        return None, False
    path = Path(raw).expanduser()
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return path, True


def _is_declared_text_path(value: Any, *, base_dir: Path | None = None) -> bool:
    """Return whether a value explicitly or unambiguously names a text file."""
    _, declared = _declared_text_path(value, base_dir=base_dir)
    return declared


_CLINICAL_HEADING_RE = re.compile(
    r"(?:findings?|impression|conclusion|clinical\s+history|history|所见|影像所见|印象|诊断意见|诊断结论|临床资料|病史)\s*[:：]",
    re.IGNORECASE,
)


def _clinical_text(text: str) -> str:
    """Extract Findings/Impression clinical sections for CER scoring."""
    matches = list(_CLINICAL_HEADING_RE.finditer(text))
    if not matches:
        return text
    sections: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        heading = match.group(0).split(":", 1)[0].strip().lower().replace("：", "")
        if heading in {"clinical history", "history", "临床资料", "病史"}:
            continue
        content = text[match.end() : end].strip()
        if content:
            sections.append(content)
    return "\n".join(sections) if sections else text


def _candidate_payload(value: Any, *, base_dir: Path | None = None) -> dict[str, Any]:
    if isinstance(value, dict):
        path, declared_path = _declared_text_path(value, base_dir=base_dir)
        if declared_path and path is not None and path.is_file() and path.suffix.lower() == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError):
                return {}
            return payload if isinstance(payload, dict) else {}
        return value
    path = Path(value) if isinstance(value, str) else None
    if path is not None and not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    if path is not None and path.is_file() and path.suffix.lower() == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _first_value(payload: dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _validate_candidate_provenance(
    item: dict[str, Any],
    model: str,
    value: Any,
    *,
    manifest_dir: Path,
) -> list[str]:
    """Validate hashes/routes when a manifest carries provenance metadata.

    Legacy text-only manifests remain supported; validation is fail-closed only
    for metadata that is actually declared by the manifest or candidate.
    """
    candidate = _candidate_payload(value, base_dir=manifest_dir)
    nested = candidate.get("provenance") if isinstance(candidate.get("provenance"), dict) else {}
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    observed = {**metadata, **nested, **candidate}
    expected_route: dict[str, Any] = {}
    for key in ("candidate_provenance", "candidate_routes", "routes", "models"):
        routes = item.get(key)
        if isinstance(routes, dict) and isinstance(routes.get(model), dict):
            expected_route = dict(routes[model])
            break
    blockers: list[str] = []
    expected_modality = item.get("modality")
    expected_pdf_hash = _first_value(item, ("source_pdf_sha256", "pdf_sha256", "source_hash"))
    source_pdf = _first_value(item, ("source_pdf", "pdf_path", "source_pdf_path"))
    declared_fields = bool(
        expected_modality
        or expected_pdf_hash
        or source_pdf
        or any(item.get(key) is not None for key in ("page_count", "source_page_count", "retained_page_count", "render_hash", "render_sha256", "page_hashes", "rendered_page_sha256"))
        or expected_route
    )
    # A structured candidate sidecar carrying an identity is itself a
    # provenance declaration, even when the manifest uses the legacy text-only
    # form.  Never score a sidecar under a different case ID.
    candidate_case_id = str(observed.get("case_id") or "")
    if candidate_case_id:
        declared_fields = True
    candidate_model = _first_value(observed, ("model_key", "model", "model_name"))
    if candidate_model not in (None, ""):
        declared_fields = True
    quality_status = str(observed.get("quality_status") or "").strip().lower()
    if quality_status in {"blocked", "review_required"}:
        blockers.append(f"provenance:{item.get('case_id')}:{model}:ocr_quality_{quality_status}")
    elif quality_status and quality_status != "passed":
        blockers.append(f"provenance:{item.get('case_id')}:{model}:ocr_quality_status")
    if source_pdf and not expected_pdf_hash:
        pdf_path = Path(str(source_pdf))
        if not pdf_path.is_absolute():
            pdf_path = manifest_dir / pdf_path
        if pdf_path.is_file():
            expected_pdf_hash = _hash_file(pdf_path)
        elif declared_fields:
            blockers.append(f"provenance:{item.get('case_id')}:{model}:source_pdf_missing")
    if expected_modality and str(observed.get("modality") or "").lower() != str(expected_modality).lower():
        blockers.append(f"provenance:{item.get('case_id')}:{model}:modality")
    observed_pdf_hash = _first_value(observed, ("source_pdf_sha256", "pdf_sha256", "source_hash"))
    if expected_pdf_hash and str(observed_pdf_hash or "") != str(expected_pdf_hash):
        blockers.append(f"provenance:{item.get('case_id')}:{model}:source_pdf_sha256")
    for field, aliases in {
        "page_count": ("page_count",),
        "source_page_count": ("source_page_count", "page_count"),
        "retained_page_count": ("retained_page_count",),
        "render_hash": ("render_hash", "render_sha256", "page_render_hash"),
        "page_hashes": ("page_hashes", "rendered_page_sha256"),
    }.items():
        expected = _first_value(item, aliases)
        observed_value = _first_value(observed, aliases)
        if expected is not None and observed_value != expected:
            blockers.append(f"provenance:{item.get('case_id')}:{model}:{field}")
    for field in ("provider", "model", "role"):
        expected = expected_route.get(field)
        observed_value = observed.get(field)
        if expected is not None and str(observed_value or "") != str(expected):
            blockers.append(f"provenance:{item.get('case_id')}:{model}:{field}")
    if declared_fields:
        observed_case_id = candidate_case_id
        if observed_case_id and observed_case_id != str(item.get("case_id")):
            blockers.append(f"provenance:{item.get('case_id')}:{model}:case_id")
        elif not observed_case_id:
            blockers.append(f"provenance:{item.get('case_id')}:{model}:case_id_missing")
        if candidate_model not in (None, "") and str(candidate_model) != str(model):
            blockers.append(f"provenance:{item.get('case_id')}:{model}:model_key")
    return blockers


def _normalize(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split())


def _clinical_tokens(text: str) -> dict[str, list[str]]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    digit_matches = re.finditer(
        r"\d+(?:\.\d+)?\s*(?:mm|cm|ml|%|毫米|厘米)?",
        normalized,
    )
    negation_matches = re.finditer(
        r"\b(?:no|not|without)\b|否认|未见|未发现|无",
        normalized,
    )
    return {
        # Keep source order and duplicate mentions: repeated measurements and
        # changed values must affect the score rather than collapsing to a set.
        "digits": [match.group(0).replace(" ", "") for match in digit_matches],
        # English terms use word boundaries to avoid matching e.g. ``not`` in
        # ``notation``; Chinese terms are intentionally matched as phrases.
        "negations": [match.group(0) for match in negation_matches],
    }


def _token_accuracy(gold: Sequence[str], candidate: Sequence[str]) -> float:
    """Return an order-sensitive token accuracy in ``[0, 1]``.

    This is a normalized edit accuracy rather than a presence check. It
    penalizes substitutions, missing mentions, extra mentions and reordering,
    while preserving the historical perfect score for two empty sequences.
    """
    if not gold:
        return 1.0 if not candidate else 0.0
    distance = _sequence_levenshtein(gold, candidate)
    return round(1.0 - distance / max(len(gold), len(candidate), 1), 6)


def _possible_truncation(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    # Terminal punctuation is strong evidence that the page response ended
    # naturally.  Chinese reports often omit a final full stop, so only flag
    # an unpunctuated ASCII word/number (the common cut-off pattern) and retain
    # the existing short/empty-response safety behavior.
    if stripped[-1] in "。！？.!?)]】}」』”\"'":
        return False
    if len(stripped) < 8:
        return True
    return stripped[-1].isascii() and stripped[-1].isalnum() and not stripped.lower().endswith(
        ("stable", "normal", "negative", "正常")
    )


def _sequence_levenshtein(a: Sequence[str], b: Sequence[str]) -> int:
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        current = [i]
        for j, right in enumerate(b, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (left != right),
                )
            )
        previous = current
    return previous[-1]


def _levenshtein(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        current = [i]
        for j, right in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]
