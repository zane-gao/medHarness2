from __future__ import annotations

from medharness2.statistics.agreement import cohen_kappa, weighted_kappa


def test_cohen_kappa_perfect_and_chance_cases():
    perfect = cohen_kappa([0, 1, 1, 0], [0, 1, 1, 0])
    assert perfect["status"] == "complete"
    assert perfect["kappa"] == 1.0
    chance = cohen_kappa([0, 0, 1, 1], [0, 1, 0, 1])
    assert chance["status"] == "complete"
    assert chance["kappa"] == 0.0


def test_weighted_kappa_uses_explicit_ordinal_weights():
    result = weighted_kappa([1, 2, 3, 4], [1, 2, 3, 4], minimum=0, maximum=4)
    assert result["status"] == "complete"
    assert result["kappa"] == 1.0
    assert result["weighting"] == "quadratic"


def test_agreement_returns_insufficient_data_without_fabricated_zero():
    result = cohen_kappa([], [])
    assert result == {"status": "insufficient_data", "n": 0, "kappa": None}
