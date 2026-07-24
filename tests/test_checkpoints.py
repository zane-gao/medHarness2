from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from medharness2.checkpoints import (
    CheckpointIntegrityError,
    StageCheckpointStore,
    stable_sha256,
)
from medharness2.config import AppConfig, GeneratorConfig, ModelRoleConfig
from medharness2.modules.pairwise_report import evaluate_pairwise
from medharness2.modules.pairwise_report import _valid_error_index
from medharness2.modules.single_report import evaluate_single_report
from medharness2.schema import GeneratedReport
from medharness2.tools.tool1_likert import LIKERT_METRICS
from medharness2.workflows.single_case import run_single_case


def test_pairwise_error_index_accepts_nonnegative_nonboolean_ints_only():
    assert _valid_error_index(0) is True
    assert _valid_error_index(3) is True
    assert _valid_error_index(True) is False
    assert _valid_error_index(-1) is False


def _validate_value(payload: dict) -> dict:
    if not isinstance(payload.get("value"), int):
        raise ValueError("value must be an integer")
    return {"value": payload["value"]}


def test_stage_checkpoint_reuses_validated_output_across_store_instances(tmp_path: Path):
    calls = 0

    def produce() -> dict:
        nonlocal calls
        calls += 1
        return {"value": 7}

    first_store = StageCheckpointStore(tmp_path / "checkpoints")
    first = first_store.get_or_compute(
        "reference.tool1_likert",
        {"report": "normal", "route": {"model": "model-a"}},
        produce,
        validator=_validate_value,
    )
    second_store = StageCheckpointStore(tmp_path / "checkpoints")
    second = second_store.get_or_compute(
        "reference.tool1_likert",
        {"report": "normal", "route": {"model": "model-a"}},
        produce,
        validator=_validate_value,
    )

    assert first == second == {"value": 7}
    assert calls == 1
    assert first_store.summary()["stats"] == {"hits": 0, "misses": 1, "writes": 1}
    assert second_store.summary()["stats"] == {"hits": 1, "misses": 0, "writes": 0}
    assert second_store.summary()["events"][0]["status"] == "hit"


def test_stage_checkpoint_input_change_creates_a_new_entry(tmp_path: Path):
    calls = 0

    def produce() -> dict:
        nonlocal calls
        calls += 1
        return {"value": calls}

    store = StageCheckpointStore(tmp_path / "checkpoints")
    first = store.get_or_compute(
        "candidate.tool2_findings",
        {"report": "first"},
        produce,
        validator=_validate_value,
    )
    second = store.get_or_compute(
        "candidate.tool2_findings",
        {"report": "second"},
        produce,
        validator=_validate_value,
    )

    assert first == {"value": 1}
    assert second == {"value": 2}
    assert calls == 2
    assert len(list((tmp_path / "checkpoints").rglob("*.json"))) == 2


def test_llm_route_fingerprint_changes_when_seed_changes():
    from medharness2.checkpoints import llm_route_fingerprint

    first = llm_route_fingerprint(object(), {"model": "m", "seed": 1})
    second = llm_route_fingerprint(object(), {"model": "m", "seed": 2})
    assert first != second


def test_stage_checkpoint_rejects_tampered_output_before_recompute(tmp_path: Path):
    store = StageCheckpointStore(tmp_path / "checkpoints")
    store.get_or_compute(
        "pairwise.tool5_alignment_audit",
        {"alignment": {"matched": []}},
        lambda: {"value": 1},
        validator=_validate_value,
    )
    checkpoint_path = Path(store.summary()["events"][-1]["path"])
    envelope = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    envelope["output"]["value"] = 999
    checkpoint_path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(CheckpointIntegrityError, match="output SHA-256 mismatch"):
        StageCheckpointStore(tmp_path / "checkpoints").get_or_compute(
            "pairwise.tool5_alignment_audit",
            {"alignment": {"matched": []}},
            lambda: pytest.fail("tampered checkpoint must not be recomputed silently"),
            validator=_validate_value,
        )


@pytest.mark.parametrize("field", ["input_sha256", "output_sha256"])
def test_stage_checkpoint_rejects_non_string_hash_fields(tmp_path: Path, field: str):
    store = StageCheckpointStore(tmp_path / "checkpoints")
    store.get_or_compute(
        "reference.tool1_likert",
        {"report": "normal"},
        lambda: {"value": 1},
        validator=_validate_value,
    )
    checkpoint_path = Path(store.summary()["events"][-1]["path"])
    envelope = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    envelope[field] = 123
    checkpoint_path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(CheckpointIntegrityError, match=f"{field}.*string"):
        StageCheckpointStore(tmp_path / "checkpoints").get_or_compute(
            "reference.tool1_likert",
            {"report": "normal"},
            lambda: pytest.fail("malformed checkpoint must not be recomputed silently"),
            validator=_validate_value,
        )


@pytest.mark.parametrize("failure_mode", ["producer", "validator"])
def test_stage_checkpoint_does_not_persist_failed_computation(
    tmp_path: Path,
    failure_mode: str,
):
    store = StageCheckpointStore(tmp_path / "checkpoints")

    def produce() -> dict:
        if failure_mode == "producer":
            raise RuntimeError("provider failed")
        return {"value": "invalid"}

    with pytest.raises((RuntimeError, ValueError)):
        store.get_or_compute(
            "reference.tool1_likert",
            {"report": "normal"},
            produce,
            validator=_validate_value,
        )

    assert list((tmp_path / "checkpoints").rglob("*.json")) == []


def test_single_report_reuses_t1_and_t2_validated_checkpoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    calls = {"likert": 0, "findings": 0}

    def fake_likert(*args, **kwargs) -> dict:
        calls["likert"] += 1
        return _likert_artifact()

    def fake_findings(*args, **kwargs) -> dict:
        calls["findings"] += 1
        return _finding_graph()

    monkeypatch.setattr("medharness2.modules.single_report.evaluate_likert", fake_likert)
    monkeypatch.setattr("medharness2.modules.single_report.extract_findings", fake_findings)
    config = _strict_config()
    checkpoint_root = tmp_path / "single-checkpoints"

    first_store = StageCheckpointStore(checkpoint_root)
    first = evaluate_single_report(
        "FINDINGS: No focal airspace opacity. IMPRESSION: No acute disease.",
        modality="cxr",
        config=config,
        llm_client=object(),
        checkpoint_store=first_store,
        checkpoint_namespace="reference",
    )
    second_store = StageCheckpointStore(checkpoint_root)
    second = evaluate_single_report(
        "FINDINGS: No focal airspace opacity. IMPRESSION: No acute disease.",
        modality="cxr",
        config=config,
        llm_client=object(),
        checkpoint_store=second_store,
        checkpoint_namespace="reference",
    )

    assert first == second
    assert calls == {"likert": 1, "findings": 1}
    assert first_store.summary()["stats"] == {"hits": 0, "misses": 2, "writes": 2}
    assert second_store.summary()["stats"] == {"hits": 2, "misses": 0, "writes": 0}


def test_strict_single_report_checkpoint_rejects_fallback_before_persisting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fallback_likert = _likert_artifact()
    fallback_likert["_metadata"]["backend"] = "deterministic_fallback"
    fallback_likert["_metadata"]["fallback_used"] = True
    monkeypatch.setattr(
        "medharness2.modules.single_report.evaluate_likert",
        lambda *args, **kwargs: fallback_likert,
    )
    monkeypatch.setattr(
        "medharness2.modules.single_report.extract_findings",
        lambda *args, **kwargs: pytest.fail("fallback T1 must fail before T2"),
    )
    store = StageCheckpointStore(tmp_path / "checkpoints")

    with pytest.raises(ValueError, match="fallback"):
        evaluate_single_report(
            "FINDINGS: Clear lungs.",
            modality="cxr",
            config=_strict_config(),
            llm_client=object(),
            checkpoint_store=store,
            checkpoint_namespace="reference",
        )

    assert list((tmp_path / "checkpoints").rglob("*.json")) == []


def test_pairwise_reuses_llm_stages_but_recomputes_deterministic_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    calls = {
        "align": 0,
        "alignment_audit": 0,
        "hazard_primary": 0,
        "hazard_review": 0,
        "structure_diff": 0,
        "structure_audit": 0,
    }
    alignment = {
        "matched": [],
        "approximate_match": [],
        "mismatched": [],
        "candidate_only": [],
        "reference_only": [],
        "a_only": [],
        "b_only": [],
        "metrics": {"precision": 0.0, "recall": 0.0, "f1": 0.0},
        "error_candidates": [],
    }

    def fake_align(*args, **kwargs) -> dict:
        calls["align"] += 1
        return alignment

    def fake_alignment_audit(*args, **kwargs) -> dict:
        calls["alignment_audit"] += 1
        return _alignment_audit(alignment)

    def fake_hazard_primary(*args, **kwargs) -> dict:
        calls["hazard_primary"] += 1
        return _hazard_result("hazard_primary", "gpt-5.6-terra")

    def fake_hazard_review(primary, *args, **kwargs) -> dict:
        calls["hazard_review"] += 1
        reviewer = _hazard_result("hazard_reviewer", "gpt-5.6-sol")
        return {
            "schema_version": "2.0",
            "artifact_type": "hazard_review",
            "primary_result_sha256": stable_sha256(primary),
            "primary_provenance": primary["provenance"],
            "reviewer_result": reviewer,
            "disagreements": [],
            "agreement_summary": {"compared_count": 0},
            "primary_preserved": True,
            "requires_adjudication": False,
        }

    structure_diff = {
        "schema_version": "2.0",
        "artifact_type": "structure_diff",
        "metric_version": "tool6-structure-v2",
        "score_a": 1.0,
        "score_b": 1.0,
        "score_delta": 0.0,
        "section_diff": {},
        "ordering": {"report_a": [], "report_b": [], "same_order": True},
        "structure_a": {},
        "structure_b": {},
    }

    def fake_structure_diff(*args, **kwargs) -> dict:
        calls["structure_diff"] += 1
        return structure_diff

    def fake_structure_audit(*args, **kwargs) -> dict:
        calls["structure_audit"] += 1
        return {
            "schema_version": "2.0",
            "artifact_type": "structure_audit",
            "structure_diff_sha256": stable_sha256(structure_diff),
            "assessor_provenance": _provenance("llm_assessment", "structure_auditor", "gpt-5.6-terra"),
            "verdict": "no_material_issue",
            "clinical_impact": 1,
            "confidence": 0.95,
            "summary": "No clinically material structure difference.",
            "issues": [],
            "primary_preserved": True,
            "requires_review": False,
            "metadata": {},
        }

    monkeypatch.setattr("medharness2.modules.pairwise_report.align_graphs", fake_align)
    monkeypatch.setattr("medharness2.modules.pairwise_report.audit_alignment", fake_alignment_audit)
    monkeypatch.setattr("medharness2.modules.pairwise_report.evaluate_hazards", fake_hazard_primary)
    monkeypatch.setattr("medharness2.modules.pairwise_report.review_hazards", fake_hazard_review)
    monkeypatch.setattr("medharness2.modules.pairwise_report.compare_structure", fake_structure_diff)
    monkeypatch.setattr(
        "medharness2.modules.pairwise_report.assess_structure_clinical_significance",
        fake_structure_audit,
    )
    checkpoint_root = tmp_path / "pairwise-checkpoints"
    kwargs = {
        "report_a": "FINDINGS: Clear lungs. IMPRESSION: No acute disease.",
        "report_b": "FINDINGS: Clear lungs. IMPRESSION: No acute disease.",
        "modality": "cxr",
        "reference_graph": _finding_graph(),
        "candidate_graph": _finding_graph(),
        "config": _strict_config(),
        "llm_client": object(),
        "checkpoint_namespace": "candidate_0",
    }

    first_store = StageCheckpointStore(checkpoint_root)
    first = evaluate_pairwise(**kwargs, checkpoint_store=first_store)
    second_store = StageCheckpointStore(checkpoint_root)
    second = evaluate_pairwise(**kwargs, checkpoint_store=second_store)

    assert first == second
    assert calls == {
        "align": 2,
        "alignment_audit": 1,
        "hazard_primary": 1,
        "hazard_review": 1,
        "structure_diff": 2,
        "structure_audit": 1,
    }
    assert first_store.summary()["stats"] == {"hits": 0, "misses": 4, "writes": 4}
    assert second_store.summary()["stats"] == {"hits": 4, "misses": 0, "writes": 0}


def test_strict_pairwise_checkpoint_rejects_fallback_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    alignment = {
        "matched": [],
        "approximate_match": [],
        "mismatched": [],
        "candidate_only": [],
        "reference_only": [],
        "a_only": [],
        "b_only": [],
        "metrics": {"precision": 0.0, "recall": 0.0, "f1": 0.0},
        "error_candidates": [],
    }
    fallback_audit = _alignment_audit(alignment)
    fallback_audit["auditor_provenance"]["implementation_type"] = "deterministic_fallback"
    fallback_audit["auditor_provenance"]["fallback_used"] = True
    monkeypatch.setattr("medharness2.modules.pairwise_report.align_graphs", lambda *args, **kwargs: alignment)
    monkeypatch.setattr(
        "medharness2.modules.pairwise_report.audit_alignment",
        lambda *args, **kwargs: fallback_audit,
    )
    monkeypatch.setattr(
        "medharness2.modules.pairwise_report.evaluate_hazards",
        lambda *args, **kwargs: pytest.fail("fallback T5 must fail before T4"),
    )
    store = StageCheckpointStore(tmp_path / "checkpoints")

    with pytest.raises(ValueError, match="fallback"):
        evaluate_pairwise(
            "FINDINGS: Clear lungs.",
            "FINDINGS: Clear lungs.",
            modality="cxr",
            reference_graph=_finding_graph(),
            candidate_graph=_finding_graph(),
            config=_strict_config(),
            llm_client=object(),
            checkpoint_store=store,
            checkpoint_namespace="candidate_0",
        )

    assert list((tmp_path / "checkpoints").rglob("*.json")) == []


def test_run_single_case_propagates_stable_checkpoint_namespaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    seen_single: list[tuple[object, str]] = []
    seen_pairwise: list[tuple[object, str]] = []

    def fake_single(*args, checkpoint_store=None, checkpoint_namespace="", **kwargs) -> dict:
        seen_single.append((checkpoint_store, checkpoint_namespace))
        return {
            "likert": _likert_artifact(),
            "finding_graph": _finding_graph(),
            "structure": {"score": 1.0},
            "composite_inputs": {
                "likert_mean": 4.0,
                "structure_score": 1.0,
                "finding_coverage": 0.0,
            },
        }

    def fake_pairwise(*args, checkpoint_store=None, checkpoint_namespace="", **kwargs) -> dict:
        seen_pairwise.append((checkpoint_store, checkpoint_namespace))
        return {"alignment": {"error_candidates": []}}

    monkeypatch.setattr("medharness2.workflows.single_case.evaluate_single_report", fake_single)
    monkeypatch.setattr("medharness2.workflows.single_case.evaluate_pairwise", fake_pairwise)
    image = tmp_path / "image.png"
    Image.new("L", (4, 4), color=0).save(image)
    store = StageCheckpointStore(tmp_path / "checkpoints")
    config = AppConfig(
        generator=GeneratorConfig(
            default_models=["model-a"],
            include_legacy_ready_models=False,
            local_models=[
                {
                    "key": "model-a",
                    "source": "local",
                    "supported_modalities": ["cxr"],
                    "supported_body_parts": ["chest"],
                    "ready": True,
                    "runtime_state": "runnable",
                    "validation_state": "engineering_smoke_only",
                    "input_capabilities": ["image_2d"],
                }
            ],
        )
    )

    run_single_case(
        report_text="FINDINGS: Clear lungs.",
        image_path=image,
        output_path=tmp_path / "case-1.json",
        modality="cxr",
        top_n=1,
        precomputed_generated_reports=[
            GeneratedReport(
                model="model-a",
                source="local",
                report="FINDINGS: Clear lungs.",
                modality="cxr",
                evidence_tier="exploratory_fresh",
                metadata={
                    "generator_key": "model-a",
                    "case_id": "case-1",
                    "reference_report_used": False,
                    "fresh_inference": True,
                },
            )
        ],
        config=config,
        llm_client=object(),
        checkpoint_store=store,
    )

    assert seen_single == [(store, "reference"), (store, "candidate_0")]
    assert seen_pairwise == [(store, "candidate_0")]


def _strict_config() -> AppConfig:
    primary = ModelRoleConfig(
        provider="chat_completions",
        model="gpt-5.6-terra",
        api_key_env="PRIMARY_KEY",
        base_url="https://primary.example/v1",
        schema_max_attempts=2,
        transport_max_retries=1,
    )
    return AppConfig(
        model_roles={
            "general_judge": primary,
            "finding_extractor": primary,
            "alignment_auditor": primary,
            "hazard_primary": primary,
            "hazard_reviewer": ModelRoleConfig(
                provider="chat_completions",
                model="gpt-5.6-sol",
                api_key_env="REVIEWER_KEY",
                base_url="https://reviewer.example/v1",
            ),
            "structure_auditor": primary,
        }
    )


def _likert_artifact() -> dict:
    payload = {
        metric: {"score": 4, "explanation": f"Evidence for {metric}."}
        for metric in LIKERT_METRICS
    }
    payload["_metadata"] = {
        "backend": "llm_judge",
        "provider": "chat_completions",
        "model": "gpt-5.6-terra",
        "role": "general_judge",
        "endpoint_host": "primary.example",
        "fallback_used": False,
        "attempt_count": 1,
        "judge_error_count": 0,
        "judge_errors": [],
    }
    payload["warning"] = "No image/volume provided"
    return payload


def _finding_graph() -> dict:
    return {
        "schema_version": "2.0",
        "artifact_type": "finding_graph",
        "modality": "cxr",
        "backend": "template_llm",
        "findings": [],
        "relations": [],
        "missing": ["findings"],
        "coverage": 0.0,
        "nodes": [],
        "template_coverage": {},
        "warnings": ["template_llm_correction"],
        "metadata": {
            "llm_correction": {
                "backend": "llm_extractor",
                "provider": "chat_completions",
                "model": "gpt-5.6-terra",
                "role": "finding_extractor",
                "endpoint_host": "primary.example",
                "fallback_used": False,
                "attempt_count": 1,
            }
        },
    }


def _alignment_audit(alignment: dict) -> dict:
    return {
        "schema_version": "2.0",
        "artifact_type": "alignment_audit",
        "alignment_sha256": stable_sha256(alignment),
        "auditor_provenance": _provenance("llm_audit", "alignment_auditor", "gpt-5.6-terra"),
        "verdict": "pass",
        "confidence": 0.95,
        "summary": "Alignment is supported.",
        "issues": [],
        "error_judgements": [],
        "adjudicated_error_candidates": [],
        "adjudication_summary": {
            "deterministic_error_count": 0,
            "retained_error_count": 0,
            "rejected_error_count": 0,
            "modified_error_count": 0,
            "abstained_error_count": 0,
            "complete": True,
        },
        "primary_preserved": True,
        "requires_adjudication": False,
        "metadata": {},
    }


def _hazard_result(role: str, model: str) -> dict:
    return {
        "schema_version": "2.0",
        "artifact_type": "hazard_result",
        "errors": [],
        "provenance": _provenance("llm_judge", role, model),
        "metadata": {},
    }


def _provenance(implementation_type: str, role: str, model: str) -> dict:
    endpoint_hosts = {
        "hazard_reviewer": "reviewer.example",
        "hazard_adjudicator": "adjudicator.example",
    }
    return {
        "implementation_type": implementation_type,
        "provider": "chat_completions",
        "model": model,
        "version": "2.0",
        "role": role,
        "prompt_version": f"{role}-test-v1",
        "fallback_used": False,
        "metadata": {
            "endpoint_host": endpoint_hosts.get(role, "primary.example"),
            "attempt_count": 1,
        },
    }
