from __future__ import annotations

from medharness2.config import AppConfig, GeneratorConfig, ModelRoleConfig
from medharness2.generators.fusion import fuse_candidate_reports
from medharness2.llm_client import LLMClient
from medharness2.privacy import PrivacyViolation
from medharness2.schema import CandidateReport, GeneratedReport
from medharness2.tools.report_structure import structure_report
from medharness2.tools.tool9_rank import select_production_top_k


def _candidate(candidate_id: str, route_tier: str, entity: str) -> CandidateReport:
    return _candidate_from_text(
        candidate_id,
        route_tier,
        f"FINDINGS: {entity}. IMPRESSION: {entity}.",
    )


def _candidate_from_text(
    candidate_id: str,
    route_tier: str,
    report: str,
    *,
    metadata: dict[str, object] | None = None,
) -> CandidateReport:
    return CandidateReport(
        candidate_id=candidate_id,
        generated=GeneratedReport(
            model=candidate_id,
            source="medharness_cli",
            report=report,
            modality="cxr",
            metadata=dict(metadata or {}),
        ),
        route_tier=route_tier,
        route_reason="test",
        runtime_state="runnable",
        validation_state="unvalidated",
        structure=structure_report(
            report,
            modality="cxr",
            body_part="chest",
        ),
    )


def test_production_top_k_is_reference_free_and_returns_at_most_requested_count():
    candidates = [
        _candidate("exact", "exact_modality_body_part", "left pleural effusion"),
        _candidate("same-modality", "same_modality", "left pleural effusion"),
        _candidate("universal", "universal", "left pleural effusion"),
    ]

    ranking = select_production_top_k(candidates, top_k=2)

    assert [row["candidate_id"] for row in ranking] == ["exact", "same-modality"]
    assert all(row["ranking_mode"] == "production_reference_free" for row in ranking)
    assert all("finding_coverage" not in row["metrics"] for row in ranking)


def test_production_ranking_exposes_attribute_conflicts_in_metrics_and_reasons():
    candidates = [
        _candidate_from_text(
            "candidate-a",
            "exact_modality_body_part",
            "FINDINGS: A mild right upper lobe nodule measures 8 mm.",
        ),
        _candidate_from_text(
            "candidate-b",
            "exact_modality_body_part",
            "FINDINGS: A severe left lower lobe nodule measures 12 mm.",
        ),
    ]

    ranking = select_production_top_k(candidates, top_k=2)

    assert len(ranking) == 2
    for row in ranking:
        metrics = row["metrics"]
        assert metrics["laterality_consensus_score"] == 0.0
        assert metrics["anatomy_consensus_score"] == 0.0
        assert metrics["measurement_consensus_score"] == 0.0
        assert metrics["severity_consensus_score"] == 0.0
        assert metrics["laterality_conflict_count"] == 1.0
        assert metrics["anatomy_conflict_count"] == 1.0
        assert metrics["measurement_conflict_count"] == 1.0
        assert metrics["severity_conflict_count"] == 1.0
        assert "conflict:laterality:nodule" in row["ranking_reason"]
        assert "conflict:anatomy:nodule" in row["ranking_reason"]
        assert "conflict:measurement:nodule" in row["ranking_reason"]
        assert "conflict:severity:nodule" in row["ranking_reason"]


def test_production_ranking_penalizes_and_explains_internal_conflicts():
    candidates = [
        _candidate_from_text(
            "conflicted",
            "exact_modality_body_part",
            "FINDINGS: No pneumothorax. A small pneumothorax is present.",
        ),
        _candidate_from_text(
            "consistent",
            "exact_modality_body_part",
            "FINDINGS: No pneumothorax.",
        ),
    ]

    ranking = select_production_top_k(candidates, top_k=2)

    assert [row["candidate_id"] for row in ranking] == ["consistent", "conflicted"]
    conflicted = next(row for row in ranking if row["candidate_id"] == "conflicted")
    assert conflicted["metrics"]["internal_consistency_score"] == 0.0
    assert conflicted["metrics"]["internal_conflict_count"] == 1.0
    assert "internal_conflict:internal_status:pneumothorax" in conflicted["ranking_reason"]


def test_production_ranking_treats_missing_attribute_signals_as_neutral():
    candidates = [
        _candidate_from_text(
            candidate_id,
            "exact_modality_body_part",
            "FINDINGS: No pneumothorax.",
        )
        for candidate_id in ("candidate-a", "candidate-b")
    ]

    ranking = select_production_top_k(candidates, top_k=2)

    for row in ranking:
        metrics = row["metrics"]
        assert metrics["laterality_consensus_score"] == 0.5
        assert metrics["measurement_consensus_score"] == 0.5
        assert metrics["severity_consensus_score"] == 0.5
        assert metrics["laterality_signal_available"] == 0.0
        assert metrics["measurement_signal_available"] == 0.0
        assert metrics["severity_signal_available"] == 0.0
        assert "signal_missing:laterality:neutral" in row["ranking_reason"]
        assert "signal_missing:measurement:neutral" in row["ranking_reason"]
        assert "signal_missing:severity:neutral" in row["ranking_reason"]


def test_production_ranking_breaks_true_ties_by_candidate_id():
    candidates = [
        _candidate("zeta", "same_modality", "no pneumothorax"),
        _candidate("alpha", "same_modality", "no pneumothorax"),
    ]

    ranking = select_production_top_k(candidates, top_k=2)

    assert [row["candidate_id"] for row in ranking] == ["alpha", "zeta"]


def test_production_ranking_excludes_quality_gate_blocked_candidates():
    candidates = [
        _candidate("eligible", "same_modality", "no pneumothorax"),
        _candidate_from_text(
            "blocked",
            "exact_modality_body_part",
            "FINDINGS: No pneumothorax.",
            metadata={"quality_gate": {"passed": False}},
        ),
    ]

    ranking = select_production_top_k(candidates, top_k=2)

    assert [row["candidate_id"] for row in ranking] == ["eligible"]


def test_fusion_uses_all_eligible_candidates_and_returns_provenance():
    config = AppConfig(
        generator=GeneratorConfig(fusion_enabled=True, fusion_model_role="report_fusion"),
        model_roles={"report_fusion": ModelRoleConfig(provider="mock", model="yunwu-fusion", max_tokens=256)},
    )
    candidates = [
        _candidate("candidate-a", "exact_modality_body_part", "left pleural effusion"),
        _candidate("candidate-b", "universal", "no pneumothorax"),
    ]

    fusion = fuse_candidate_reports(
        candidates,
        modality="cxr",
        body_part="chest",
        config=config,
        llm_client=LLMClient(config),
    )

    assert fusion.fusion_status == "succeeded"
    assert fusion.fusion_model == "yunwu-fusion"
    assert fusion.input_candidate_ids == ["candidate-a", "candidate-b"]
    assert fusion.report
    assert fusion.provenance["model_role"] == "report_fusion"


def test_fusion_returns_explicit_disabled_status_without_hiding_candidates():
    fusion = fuse_candidate_reports(
        [_candidate("candidate-a", "exact_modality_body_part", "left pleural effusion")],
        modality="cxr",
        body_part="chest",
        config=AppConfig(generator=GeneratorConfig(fusion_enabled=False)),
    )

    assert fusion.fusion_status == "disabled"
    assert fusion.report == ""


def test_fusion_prompt_receives_candidate_agreements_and_conflicts():
    class RecordingClient:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def call(self, prompt: str, **kwargs: object) -> str:
            del kwargs
            self.prompts.append(prompt)
            return "FINDINGS: Small left pleural effusion."

    config = AppConfig(
        generator=GeneratorConfig(fusion_enabled=True, fusion_model_role="report_fusion"),
        model_roles={"report_fusion": ModelRoleConfig(provider="mock", model="yunwu-fusion", max_tokens=256)},
    )
    comparison = {
        "agreement_count": 1,
        "conflict_count": 1,
        "agreements": [{"entity": "effusion", "candidate_ids": ["candidate-a", "candidate-b"]}],
        "conflicts": [
            {
                "entity": "pneumothorax",
                "comparison_type": "observation_status",
                "candidate_values": {"candidate-a": ["absent"], "candidate-b": ["present"]},
            }
        ],
        "omissions": [],
        "internal_conflicts": [],
    }
    client = RecordingClient()

    fusion = fuse_candidate_reports(
        [
            _candidate("candidate-a", "exact_modality_body_part", "left pleural effusion"),
            _candidate("candidate-b", "universal", "pneumothorax"),
        ],
        modality="cxr",
        body_part="chest",
        comparison=comparison,
        config=config,
        llm_client=client,
    )

    assert fusion.fusion_status == "succeeded"
    assert '"candidate_comparison"' in client.prompts[0]
    assert '"pneumothorax"' in client.prompts[0]
    assert fusion.provenance["comparison_included"] is True


def test_fusion_converts_privacy_and_payload_errors_to_failed_status():
    class FailingClient:
        def __init__(self, error: Exception) -> None:
            self.error = error

        def call(self, *args: object, **kwargs: object) -> str:
            del args, kwargs
            raise self.error

    config = AppConfig(
        generator=GeneratorConfig(fusion_enabled=True, fusion_model_role="report_fusion"),
        model_roles={"report_fusion": ModelRoleConfig(provider="mock", model="yunwu-fusion", max_tokens=256)},
    )
    candidates = [_candidate("candidate-a", "exact_modality_body_part", "left pleural effusion")]

    for error in (
        PrivacyViolation("blocked"),
        ValueError("invalid fusion payload"),
        TypeError("non-serializable fusion payload"),
        RuntimeError("fusion backend crashed"),
    ):
        fusion = fuse_candidate_reports(
            candidates,
            modality="cxr",
            body_part="chest",
            config=config,
            llm_client=FailingClient(error),
        )

        assert fusion.fusion_status == "failed"
        assert fusion.input_candidate_ids == ["candidate-a"]
        assert type(error).__name__ in fusion.warnings[1]
