from __future__ import annotations

from collections import Counter
from typing import Sequence


def cohen_kappa(labels_a: Sequence[int], labels_b: Sequence[int]) -> dict[str, object]:
    """Compute Cohen's kappa with fail-closed small/constant sample handling."""
    if len(labels_a) != len(labels_b):
        raise ValueError("agreement label lengths must match")
    n = len(labels_a)
    if n == 0:
        return {"status": "insufficient_data", "n": 0, "kappa": None}
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (*labels_a, *labels_b)):
        raise ValueError("agreement labels must be integers")
    observed = sum(a == b for a, b in zip(labels_a, labels_b)) / n
    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    categories = set(counts_a) | set(counts_b)
    expected = sum((counts_a[item] / n) * (counts_b[item] / n) for item in categories)
    if expected == 1.0:
        kappa = 1.0 if observed == 1.0 else None
    else:
        kappa = (observed - expected) / (1.0 - expected)
    return {
        "status": "complete" if kappa is not None else "undefined",
        "n": n,
        "observed_agreement": observed,
        "expected_agreement": expected,
        "kappa": kappa,
        "categories": sorted(categories),
    }


def weighted_kappa(
    labels_a: Sequence[int],
    labels_b: Sequence[int],
    *,
    minimum: int,
    maximum: int,
) -> dict[str, object]:
    """Compute quadratic weighted kappa for an ordinal scale."""
    if minimum >= maximum:
        raise ValueError("weighted kappa range must contain at least two values")
    result = cohen_kappa(labels_a, labels_b)
    if result["status"] == "insufficient_data":
        return {**result, "weighting": "quadratic"}
    scale = maximum - minimum
    categories = list(range(minimum, maximum + 1))
    n = len(labels_a)
    if any(value not in categories for value in (*labels_a, *labels_b)):
        raise ValueError("weighted kappa labels outside declared ordinal range")
    observed = sum(
        1.0 - ((a - b) / scale) ** 2 for a, b in zip(labels_a, labels_b)
    ) / n
    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    expected = sum(
        (counts_a[a] / n) * (counts_b[b] / n) * (1.0 - ((a - b) / scale) ** 2)
        for a in categories
        for b in categories
    )
    kappa = None if expected == 1.0 else (observed - expected) / (1.0 - expected)
    return {
        "status": "complete" if kappa is not None else "undefined",
        "n": n,
        "observed_agreement": observed,
        "expected_agreement": expected,
        "kappa": kappa,
        "categories": categories,
        "weighting": "quadratic",
        "minimum": minimum,
        "maximum": maximum,
    }
