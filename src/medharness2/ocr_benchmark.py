from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from medharness2.utils.io import write_json


NEGATION_TOKENS = ("no", "not", "without", "否认", "未见", "未发现", "无")


def evaluate_ocr_candidates(manifest_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    """Evaluate frozen OCR candidate text against line-verified gold text.

    Manifest rows require ``case_id``, ``gold_text`` and ``candidates``. Candidate
    values may be text or a JSON path containing ``text``. Missing gold/candidate
    artifacts produce a blocked summary instead of a misleading zero score.
    """
    manifest = _read_manifest(Path(manifest_path))
    rows: list[dict[str, Any]] = []
    blocked: list[str] = []
    for item in manifest:
        case_id = str(item.get("case_id") or "")
        gold = _resolve_text(item.get("gold_text"))
        candidates = item.get("candidates") or {}
        if not case_id or not gold or not isinstance(candidates, dict):
            blocked.append(case_id or "unknown_case")
            continue
        for model, value in candidates.items():
            text = _resolve_text(value)
            if not text:
                blocked.append(f"{case_id}:{model}")
                continue
            rows.append({"case_id": case_id, "model": str(model), **_metrics(gold, text)})
    summary = _aggregate(rows)
    status = (
        "blocked"
        if not manifest or (not rows and blocked)
        else "completed_with_blockers"
        if blocked
        else "succeeded"
    )
    result = {
        "schema_version": "1.0",
        "artifact_type": "ocr_candidate_benchmark",
        "status": status,
        "manifest": str(manifest_path),
        "case_count": len(manifest),
        "evaluated_count": len(rows),
        "blocked_items": blocked,
        "metrics": rows,
        "by_model": summary,
        "selection": _selection(summary) if not blocked else {"status": "blocked", "reason": "missing_gold_or_candidate_artifacts"},
    }
    write_json(output_path, result)
    return result


def _metrics(gold: str, candidate: str) -> dict[str, Any]:
    gold_norm, candidate_norm = _normalize(gold), _normalize(candidate)
    distance = _levenshtein(gold_norm, candidate_norm)
    gold_tokens = _clinical_tokens(gold)
    candidate_tokens = _clinical_tokens(candidate)
    return {
        "clinical_cer": round(distance / max(len(gold_norm), 1), 6),
        "full_char_count": len(candidate_norm),
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
        result[model] = {
            "case_count": len(items),
            "clinical_cer_mean": round(sum(float(x["clinical_cer"]) for x in items) / len(items), 6),
            "digit_token_accuracy_mean": round(sum(float(x["digit_token_accuracy"]) for x in items) / len(items), 6),
            "negation_token_accuracy_mean": round(sum(float(x["negation_token_accuracy"]) for x in items) / len(items), 6),
            "truncation_count": sum(bool(x["possible_truncation"]) for x in items),
        }
    return result


def _selection(summary: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not summary:
        return {"status": "blocked", "reason": "no_evaluated_candidates"}
    winner = min(summary, key=lambda model: (summary[model]["clinical_cer_mean"], summary[model]["truncation_count"], -summary[model]["negation_token_accuracy_mean"]))
    return {"status": "provisional", "primary_model": winner, "rule": "lowest clinical CER, then truncation count, then negation accuracy; clinical review required"}


def _read_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload if isinstance(payload, list) else payload.get("cases") or [])


def _resolve_text(value: Any) -> str:
    if isinstance(value, str) and Path(value).is_file():
        path = Path(value)
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            return str(payload.get("text") or payload.get("ocr_text") or "").strip()
        return path.read_text(encoding="utf-8").strip()
    if isinstance(value, dict):
        return str(value.get("text") or value.get("ocr_text") or "").strip()
    return str(value or "").strip()


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
