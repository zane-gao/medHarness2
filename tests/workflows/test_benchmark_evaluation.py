from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from medharness2.config import AppConfig, ModelRoleConfig
from medharness2.checkpoints import StageCheckpointStore
from medharness2.utils.io import write_json
from medharness2.workflows.benchmark_evaluation import (
    _case_evaluation_metrics,
    _formal_statistical_comparisons,
    evaluate_generation_benchmark,
    verify_real_llm_case_evaluation,
)


def test_formal_statistical_comparisons_apply_holm_and_block_small_groups():
    rows = [
        {"status": "succeeded", "model": "a", "metrics": {"candidate_likert_mean": 4.0, "alignment_f1": 0.8}},
        {"status": "succeeded", "model": "a", "metrics": {"candidate_likert_mean": 4.2, "alignment_f1": 0.9}},
        {"status": "succeeded", "model": "b", "metrics": {"candidate_likert_mean": 2.0, "alignment_f1": 0.4}},
        {"status": "succeeded", "model": "b", "metrics": {"candidate_likert_mean": 2.2, "alignment_f1": 0.5}},
    ]
    result = _formal_statistical_comparisons(rows)
    assert result["status"] == "succeeded"
    assert result["method"] == "welch_normal_approximation+holm"
    assert result["comparisons"][0]["metric"] == "candidate_likert_mean"
    assert "p_value_holm" in result["comparisons"][0]
    blocked = _formal_statistical_comparisons(rows[:2])
    assert blocked["status"] == "blocked"


def test_evaluate_generation_benchmark_writes_hash_bound_resumable_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    case_manifest, benchmark_dir = _benchmark_fixture(tmp_path)
    calls: list[dict] = []

    def fake_run_single_case(**kwargs):
        calls.append(kwargs)
        payload = _strict_case_evaluation()
        write_json(kwargs["output_path"], payload)
        return payload

    monkeypatch.setattr(
        "medharness2.workflows.benchmark_evaluation.run_single_case",
        fake_run_single_case,
    )
    output_dir = tmp_path / "evaluation"
    progress_events: list[dict] = []

    summary = evaluate_generation_benchmark(
        benchmark_dir,
        case_manifest,
        output_dir,
        config=_strict_config(),
        llm_client=object(),
        progress_callback=progress_events.append,
    )

    assert summary["status"] == "succeeded"
    assert summary["evaluation_count"] == 1
    assert summary["failure_count"] == 0
    assert summary["resumed_count"] == 0
    assert summary["checkpoint_stats"] == {"hits": 0, "misses": 0, "writes": 0}
    assert summary["metrics"]["candidate_likert_mean"]["mean"] == 4.0
    assert summary["metrics"]["alignment_f1"]["mean"] == 0.0
    assert summary["metrics"]["hazard_error_count"] == 0
    assert summary["metrics"]["deterministic_alignment_error_count"] == 0
    assert summary["metrics"]["t5_rejected_error_count"] == 0
    assert summary["metrics"]["alignment_audit_verdict_counts"] == {"pass": 1}
    assert summary["metrics"]["structure_audit_verdict_counts"] == {
        "minor_issue": 1
    }
    assert summary["metrics"]["hazard_disagreement_count"] == 0
    assert len(calls) == 1
    assert isinstance(calls[0]["checkpoint_store"], StageCheckpointStore)
    assert [event["event"] for event in progress_events] == [
        "case_started",
        "case_succeeded",
    ]
    assert calls[0]["report_text"] == "FINDINGS: No focal opacity. IMPRESSION: No acute disease."
    assert calls[0]["precomputed_generated_reports"][0].report == "FINDINGS: Clear lungs."

    result_row = json.loads(
        (output_dir / "benchmark_evaluation_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    artifact_path = Path(result_row["evaluation_artifact"])
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["source_isolation"] == {
        "generation_reference_report_used": False,
        "generated_report_reference_report_used": False,
        "reference_usage_phase": "posthoc_evaluation_only",
    }
    assert artifact["llm_verification"]["passed"] is True
    assert artifact["llm_verification"]["fallback_count"] == 0
    assert summary["fallback_count"] == 0
    assert artifact["checkpointing"]["stats"] == {"hits": 0, "misses": 0, "writes": 0}
    assert artifact["benchmark_result_sha256"] == _stable_sha256(
        json.loads((benchmark_dir / "benchmark_results.jsonl").read_text().splitlines()[0])
    )
    assert artifact["evaluation_spec_snapshot"]["source_sha256"]
    assert {
        "workflows/benchmark_evaluation.py",
        "workflows/single_case.py",
        "modules/single_report.py",
        "modules/pairwise_report.py",
        "tools/tool1_likert.py",
        "tools/tool2_extract.py",
        "tools/tool3_structure.py",
        "tools/tool4_hazard.py",
        "tools/tool5_align.py",
        "tools/tool6_structure_diff.py",
        "alignment/audit.py",
        "alignment/matcher.py",
        "alignment/scoring.py",
        "ontology/cxr.py",
    }.issubset(artifact["evaluation_spec_snapshot"]["source_sha256"])
    assert artifact["evaluation_spec_sha256"] == _stable_sha256(
        artifact["evaluation_spec_snapshot"]
    )
    assert artifact["evaluation_config_sha256"] == _stable_sha256(
        artifact["evaluation_config_snapshot"]
    )

    manifest = json.loads(
        (output_dir / "benchmark_evaluation_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["artifact_sha256"]["results"] == _file_sha256(
        output_dir / "benchmark_evaluation_results.jsonl"
    )
    assert manifest["artifact_sha256"]["summary"] == _file_sha256(
        output_dir / "benchmark_evaluation_summary.json"
    )
    assert manifest["evaluation_spec_sha256"] == _stable_sha256(
        manifest["evaluation_spec_snapshot"]
    )
    assert manifest["evaluation_config_sha256"] == _stable_sha256(
        manifest["evaluation_config_snapshot"]
    )

    monkeypatch.setattr(
        "medharness2.workflows.benchmark_evaluation.run_single_case",
        lambda **_: pytest.fail("resume should not rerun a verified case"),
    )
    resumed = evaluate_generation_benchmark(
        benchmark_dir,
        case_manifest,
        output_dir,
        config=_strict_config(),
        llm_client=object(),
    )
    assert resumed["status"] == "succeeded"
    assert resumed["resumed_count"] == 1
    assert resumed["checkpoint_stats"] == {"hits": 0, "misses": 0, "writes": 0}
    assert resumed["artifact_checkpoint_stats"] == {
        "hits": 0,
        "misses": 0,
        "writes": 0,
    }


def test_evaluate_generation_benchmark_rejects_whole_case_resume_with_changed_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    case_manifest, benchmark_dir = _benchmark_fixture(tmp_path)

    def fake_run_single_case(**kwargs):
        payload = _strict_case_evaluation()
        write_json(kwargs["output_path"], payload)
        return payload

    monkeypatch.setattr(
        "medharness2.workflows.benchmark_evaluation.run_single_case",
        fake_run_single_case,
    )
    output_dir = tmp_path / "evaluation"
    first = evaluate_generation_benchmark(
        benchmark_dir,
        case_manifest,
        output_dir,
        config=_strict_config(),
        llm_client=object(),
    )
    changed = _strict_config()
    changed.model_roles["general_judge"] = ModelRoleConfig(
        provider="chat_completions",
        model="gpt-5.6-luna",
        api_key_env="CHANGED_KEY",
        base_url="https://changed.example/v1",
    )
    monkeypatch.setattr(
        "medharness2.workflows.benchmark_evaluation.run_single_case",
        lambda **_: pytest.fail("route mismatch must not silently rerun or reuse"),
    )

    resumed = evaluate_generation_benchmark(
        benchmark_dir,
        case_manifest,
        output_dir,
        config=changed,
        llm_client=object(),
    )

    assert first["status"] == "succeeded"
    assert resumed["status"] == "completed_with_failures"
    assert resumed["evaluation_count"] == 0
    assert resumed["failure_count"] == 1
    row = json.loads(
        (output_dir / "benchmark_evaluation_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert "route snapshot mismatch" in row["error"].lower()


def test_evaluate_generation_benchmark_rejects_resume_after_implementation_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    case_manifest, benchmark_dir = _benchmark_fixture(tmp_path)

    def fake_run_single_case(**kwargs):
        payload = _strict_case_evaluation()
        write_json(kwargs["output_path"], payload)
        return payload

    monkeypatch.setattr(
        "medharness2.workflows.benchmark_evaluation.run_single_case",
        fake_run_single_case,
    )
    output_dir = tmp_path / "evaluation"
    first = evaluate_generation_benchmark(
        benchmark_dir,
        case_manifest,
        output_dir,
        config=_strict_config(),
        llm_client=object(),
    )
    monkeypatch.setattr(
        "medharness2.workflows.benchmark_evaluation._evaluation_spec_snapshot",
        lambda: {
            "version": "changed",
            "source_sha256": {"changed.py": "f" * 64},
        },
    )
    monkeypatch.setattr(
        "medharness2.workflows.benchmark_evaluation.run_single_case",
        lambda **_: pytest.fail("implementation mismatch must fail closed"),
    )

    resumed = evaluate_generation_benchmark(
        benchmark_dir,
        case_manifest,
        output_dir,
        config=_strict_config(),
        llm_client=object(),
    )

    assert first["status"] == "succeeded"
    assert resumed["status"] == "completed_with_failures"
    row = json.loads(
        (output_dir / "benchmark_evaluation_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert "implementation snapshot mismatch" in row["error"].lower()


def test_evaluate_generation_benchmark_rejects_resume_after_evaluation_config_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    case_manifest, benchmark_dir = _benchmark_fixture(tmp_path)

    def fake_run_single_case(**kwargs):
        payload = _strict_case_evaluation()
        write_json(kwargs["output_path"], payload)
        return payload

    monkeypatch.setattr(
        "medharness2.workflows.benchmark_evaluation.run_single_case",
        fake_run_single_case,
    )
    output_dir = tmp_path / "evaluation"
    first = evaluate_generation_benchmark(
        benchmark_dir,
        case_manifest,
        output_dir,
        config=_strict_config(),
        llm_client=object(),
    )
    changed = _strict_config()
    changed.alignment.tolerance_mm = 9.0
    monkeypatch.setattr(
        "medharness2.workflows.benchmark_evaluation.run_single_case",
        lambda **_: pytest.fail("config mismatch must fail closed"),
    )

    resumed = evaluate_generation_benchmark(
        benchmark_dir,
        case_manifest,
        output_dir,
        config=changed,
        llm_client=object(),
    )

    assert first["status"] == "succeeded"
    assert resumed["status"] == "completed_with_failures"
    row = json.loads(
        (output_dir / "benchmark_evaluation_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert "evaluation config snapshot mismatch" in row["error"].lower()


def test_evaluate_generation_benchmark_resumes_validated_in_case_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    case_manifest, benchmark_dir = _benchmark_fixture(tmp_path)
    producer_calls = 0
    workflow_calls = 0

    def fake_run_single_case(**kwargs):
        nonlocal producer_calls, workflow_calls
        workflow_calls += 1

        def produce() -> dict:
            nonlocal producer_calls
            producer_calls += 1
            return {"validated": True}

        checkpoint = kwargs["checkpoint_store"].get_or_compute(
            "reference.tool1_likert",
            {"report_sha256": "a" * 64, "route": "model-a"},
            produce,
            validator=lambda payload: payload
            if payload == {"validated": True}
            else (_ for _ in ()).throw(ValueError("invalid checkpoint")),
        )
        assert checkpoint == {"validated": True}
        if workflow_calls == 1:
            raise RuntimeError("simulated interruption after T1")
        payload = _strict_case_evaluation()
        write_json(kwargs["output_path"], payload)
        return payload

    monkeypatch.setattr(
        "medharness2.workflows.benchmark_evaluation.run_single_case",
        fake_run_single_case,
    )
    output_dir = tmp_path / "evaluation"

    failed = evaluate_generation_benchmark(
        benchmark_dir,
        case_manifest,
        output_dir,
        config=_strict_config(),
        llm_client=object(),
    )
    resumed = evaluate_generation_benchmark(
        benchmark_dir,
        case_manifest,
        output_dir,
        config=_strict_config(),
        llm_client=object(),
    )

    assert failed["status"] == "completed_with_failures"
    assert failed["checkpoint_stats"] == {"hits": 0, "misses": 1, "writes": 1}
    assert resumed["status"] == "succeeded"
    assert resumed["resumed_count"] == 0
    assert resumed["checkpoint_stats"] == {"hits": 1, "misses": 0, "writes": 0}
    assert resumed["artifact_checkpoint_stats"] == {
        "hits": 1,
        "misses": 0,
        "writes": 0,
    }
    assert resumed["historical_failure_count"] == 1
    assert workflow_calls == 2
    assert producer_calls == 1

    manifest = json.loads(
        (output_dir / "benchmark_evaluation_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["historical_failures"]["count"] == 1
    historical = manifest["historical_failures"]["artifacts"][0]
    assert Path(historical["path"]).is_file()
    assert historical["sha256"] == _file_sha256(Path(historical["path"]))

    whole_case_resume = evaluate_generation_benchmark(
        benchmark_dir,
        case_manifest,
        output_dir,
        config=_strict_config(),
        llm_client=object(),
    )
    assert whole_case_resume["resumed_count"] == 1
    assert whole_case_resume["checkpoint_stats"] == {
        "hits": 0,
        "misses": 0,
        "writes": 0,
    }
    assert whole_case_resume["artifact_checkpoint_stats"] == {
        "hits": 1,
        "misses": 0,
        "writes": 0,
    }


def test_evaluate_generation_benchmark_no_resume_bypasses_stage_checkpoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    case_manifest, benchmark_dir = _benchmark_fixture(tmp_path)

    def fake_run_single_case(**kwargs):
        assert kwargs["checkpoint_store"] is None
        payload = _strict_case_evaluation()
        write_json(kwargs["output_path"], payload)
        return payload

    monkeypatch.setattr(
        "medharness2.workflows.benchmark_evaluation.run_single_case",
        fake_run_single_case,
    )
    output_dir = tmp_path / "evaluation"

    summary = evaluate_generation_benchmark(
        benchmark_dir,
        case_manifest,
        output_dir,
        config=_strict_config(),
        llm_client=object(),
        resume=False,
    )

    assert summary["status"] == "succeeded"
    assert summary["checkpoint_stats"] == {"hits": 0, "misses": 0, "writes": 0}
    artifact = json.loads(
        next((output_dir / "cases").rglob("evaluation_artifacts/*.json")).read_text(
            encoding="utf-8"
        )
    )
    assert artifact["checkpointing"]["enabled"] is False
    assert artifact["checkpointing"]["reason"] == "resume_disabled"


def test_evaluate_generation_benchmark_rejects_reference_assisted_generation(
    tmp_path: Path,
):
    case_manifest, benchmark_dir = _benchmark_fixture(
        tmp_path,
        reference_report_used=True,
    )

    with pytest.raises(ValueError, match="reference_report_used"):
        evaluate_generation_benchmark(
            benchmark_dir,
            case_manifest,
            tmp_path / "evaluation",
            config=_strict_config(),
            llm_client=object(),
        )


def test_verify_real_llm_case_evaluation_rejects_any_fallback():
    payload = _strict_case_evaluation()
    payload["generated_evaluations"][0]["likert"]["_metadata"]["fallback_used"] = True

    with pytest.raises(ValueError, match="fallback"):
        verify_real_llm_case_evaluation(payload)


def test_verify_real_llm_case_evaluation_counts_validated_attempts_by_role():
    verification = verify_real_llm_case_evaluation(_strict_case_evaluation())

    assert verification["validated_attempt_counts"]["general_judge"] == 2
    assert verification["validated_attempt_counts"]["finding_extractor"] == 2
    assert verification["validated_attempt_counts"]["alignment_auditor"] == 1


def test_verify_real_llm_case_evaluation_rejects_incomplete_t5_adjudication():
    payload = _strict_case_evaluation()
    audit = payload["pairwise_comparisons"][0]["comparison"]["alignment_audit"]
    audit["adjudication_summary"]["complete"] = False

    with pytest.raises(ValueError, match="T5 adjudication is incomplete"):
        verify_real_llm_case_evaluation(payload)


def test_verify_real_llm_case_evaluation_requires_third_hazard_adjudication():
    payload = _strict_case_evaluation()
    _add_hazard_disagreement(payload, include_adjudication=False)

    with pytest.raises(ValueError, match="T4 hazard adjudication is missing"):
        verify_real_llm_case_evaluation(payload)

    _add_hazard_disagreement(payload, include_adjudication=True)
    verification = verify_real_llm_case_evaluation(payload)

    assert verification["role_counts"]["hazard_adjudicator"] == 1
    assert any(
        item["model"] == "gpt-5.6-terra-ultra"
        for item in verification["evidence"]
        if item["role"] == "hazard_adjudicator"
    )


def test_case_evaluation_metrics_include_third_hazard_adjudication():
    payload = _strict_case_evaluation()
    _add_hazard_disagreement(payload, include_adjudication=True)

    metrics = _case_evaluation_metrics(payload)

    assert metrics["hazard_adjudication_decision_count"] == 1
    assert metrics["hazard_adjudication_abstained_count"] == 0
    assert metrics["adjudicated_hazard_levels"] == [3]
    assert metrics["consensus_hazard_levels"] == [3]
    assert metrics["consensus_max_hazard_level"] == 3
    assert metrics["consensus_nontrivial_error_count"] == 1
    assert metrics["consensus_material_error_count"] == 1
    assert metrics["consensus_unresolved_error_count"] == 0
    assert metrics["third_hazard_adjudication_required"] is True
    assert metrics["clinical_validation_required"] is True


def test_case_evaluation_metrics_require_clinical_validation_without_llm_disagreement():
    metrics = _case_evaluation_metrics(_strict_case_evaluation())

    assert metrics["third_hazard_adjudication_required"] is False
    assert metrics["clinical_validation_required"] is True
    assert metrics["t5_retained_error_count"] == 0


def test_case_evaluation_metrics_preserve_explicit_zero_agreement_counts():
    payload = _strict_case_evaluation()
    comparison = payload["pairwise_comparisons"][0]["comparison"]
    comparison["hazards"]["errors"] = [{"hazard_level": 2}]
    comparison["hazard_review"]["agreement_summary"] = {
        "compared_count": 0,
        "exact_agreement_count": 0,
        "within_one_count": 0,
        "action_agreement_count": 0,
    }

    metrics = _case_evaluation_metrics(payload)

    assert metrics["hazard_compared_count"] == 0
    assert metrics["hazard_exact_agreement_count"] == 0


def _benchmark_fixture(
    root: Path,
    *,
    reference_report_used: bool = False,
) -> tuple[Path, Path]:
    image = root / "image.png"
    image.write_bytes(b"png")
    reference = root / "reference.txt"
    reference.write_text(
        "FINDINGS: No focal opacity. IMPRESSION: No acute disease.",
        encoding="utf-8",
    )
    case_manifest = root / "manifest.jsonl"
    case_manifest.write_text(
        json.dumps(
            {
                "case_id": "case-1",
                "reader": "reader-a",
                "modality": "cxr",
                "body_part": "chest",
                "report_pdf": "",
                "report_text": str(reference),
                "image_paths": [str(image)],
                "derived_assets": {"primary_image": str(image)},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    benchmark_dir = root / "benchmark"
    benchmark_dir.mkdir()
    generated_report = {
        "schema_version": "2.0",
        "artifact_type": "generated_report",
        "model": "model-a",
        "source": "medharness_cli",
        "report": "FINDINGS: Clear lungs.",
        "modality": "cxr",
        "evidence_tier": "exploratory_fresh",
        "warnings": [],
        "metadata": {
            "reference_report_used": reference_report_used,
            "fresh_inference": True,
        },
    }
    result = {
        "schema_version": "2.0",
        "artifact_type": "generation_benchmark_result",
        "case_id": "case-1",
        "modality": "cxr",
        "body_part": "chest",
        "model": "model-a",
        "status": "succeeded",
        "latency_sec": 1.0,
        "execution": {"mode": "batch", "batch_size": 1, "batch_latency_sec": 1.0},
        "input_asset_sha256": _file_sha256(image),
        "input_asset_kind": "image",
        "input_asset_selection_policy": "2d_image_required",
        "reference_report_used": reference_report_used,
        "generated_report": generated_report,
    }
    results_path = benchmark_dir / "benchmark_results.jsonl"
    results_path.write_text(json.dumps(result) + "\n", encoding="utf-8")
    summary_path = benchmark_dir / "benchmark_summary.json"
    write_json(
        summary_path,
        {
            "schema_version": "2.0",
            "artifact_type": "generation_benchmark_summary",
            "status": "succeeded",
            "mode": "exploratory",
            "case_count": 1,
            "result_count": 1,
            "failure_count": 0,
        },
    )
    write_json(
        benchmark_dir / "benchmark_manifest.json",
        {
            "schema_version": "2.0",
            "artifact_type": "generation_benchmark_manifest",
            "mode": "exploratory",
            "input_manifest_sha256": _file_sha256(case_manifest),
            "artifacts": {
                "results": str(results_path),
                "summary": str(summary_path),
            },
            "artifact_sha256": {
                "results": _file_sha256(results_path),
                "summary": _file_sha256(summary_path),
            },
        },
    )
    return case_manifest, benchmark_dir


def _strict_config() -> AppConfig:
    gpt = ModelRoleConfig(
        provider="chat_completions",
        model="gpt-5.6-terra",
        api_key_env="GPT_KEY",
        base_url="https://gpt.example/v1",
    )
    return AppConfig(
        model_roles={
            "general_judge": gpt,
            "finding_extractor": gpt,
            "alignment_auditor": gpt,
            "hazard_primary": gpt,
            "structure_auditor": gpt,
            "hazard_adjudicator": ModelRoleConfig(
                provider="chat_completions",
                model="gpt-5.6-terra-ultra",
                api_key_env="ADJUDICATOR_KEY",
                base_url="https://adjudicator.example/v1",
            ),
            "hazard_reviewer": ModelRoleConfig(
                provider="chat_completions",
                model="claude-opus-4-8",
                api_key_env="CLAUDE_KEY",
                base_url="https://claude.example/v1",
                omit_temperature=True,
            ),
        }
    )


def _strict_case_evaluation() -> dict:
    likert = {
        metric: {"score": 4, "explanation": "Specific evidence."}
        for metric in (
            "Completeness and Accuracy",
            "Conciseness and Clarity",
            "Terminological Accuracy",
            "Structure and Style",
            "Overall Writing Quality",
        )
    }
    likert["_metadata"] = {
        "backend": "llm_judge",
        "provider": "chat_completions",
        "model": "gpt-5.6-terra",
        "role": "general_judge",
        "endpoint_host": "gpt.example",
        "fallback_used": False,
        "attempt_count": 1,
    }
    graph = {
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
                "endpoint_host": "gpt.example",
                "fallback_used": False,
                "attempt_count": 1,
            }
        },
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
    alignment_audit = {
        "schema_version": "2.0",
        "artifact_type": "alignment_audit",
        "alignment_sha256": _stable_sha256(alignment),
        "auditor_provenance": _provenance("llm_audit", "alignment_auditor"),
        "verdict": "pass",
        "confidence": 0.9,
        "summary": "Alignment is sound.",
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
    hazards = {
        "schema_version": "2.0",
        "artifact_type": "hazard_result",
        "errors": [],
        "provenance": _provenance("llm_judge", "hazard_primary"),
        "metadata": {},
    }
    reviewer = {
        "schema_version": "2.0",
        "artifact_type": "hazard_result",
        "errors": [],
        "provenance": {
            **_provenance("llm_judge", "hazard_reviewer"),
            "model": "claude-opus-4-8",
        },
        "metadata": {},
    }
    hazard_review = {
        "schema_version": "2.0",
        "artifact_type": "hazard_review",
        "primary_result_sha256": _stable_sha256(hazards),
        "primary_provenance": hazards["provenance"],
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
        "score_b": 0.5,
        "score_delta": -0.5,
        "section_diff": {},
        "ordering": {"report_a": [], "report_b": [], "same_order": True},
        "structure_a": {},
        "structure_b": {},
    }
    structure_audit = {
        "schema_version": "2.0",
        "artifact_type": "structure_audit",
        "structure_diff_sha256": _stable_sha256(structure_diff),
        "assessor_provenance": _provenance("llm_assessment", "structure_auditor"),
        "verdict": "minor_issue",
        "clinical_impact": 2,
        "confidence": 0.8,
        "summary": "Minor structure issue.",
        "issues": [],
        "primary_preserved": True,
        "requires_review": True,
        "metadata": {},
    }
    single = {
        "likert": likert,
        "finding_graph": graph,
        "structure": {},
        "composite_inputs": {
            "likert_mean": 4.0,
            "structure_score": 0.5,
            "finding_coverage": 0.0,
        },
    }
    return {
        "schema_version": "2.0",
        "artifact_type": "case_evaluation",
        "case_id": "case-1",
        "input": {},
        "human_evaluation": copy.deepcopy(single),
        "generated_reports": [],
        "generated_evaluations": [copy.deepcopy(single)],
        "rankings": [],
        "pairwise_comparisons": [
            {
                "model": "model-a",
                "comparison": {
                    "graph_a": copy.deepcopy(graph),
                    "graph_b": copy.deepcopy(graph),
                    "alignment": alignment,
                    "alignment_audit": alignment_audit,
                    "hazards": hazards,
                    "hazard_review": hazard_review,
                    "structure_diff": structure_diff,
                    "structure_audit": structure_audit,
                },
            }
        ],
    }


def _add_hazard_disagreement(payload: dict, *, include_adjudication: bool) -> None:
    comparison = payload["pairwise_comparisons"][0]["comparison"]
    error_candidate = {"error_type": "omission_finding", "observation": "nodule"}
    comparison["alignment"]["error_candidates"] = [error_candidate]
    audit = comparison["alignment_audit"]
    audit["alignment_sha256"] = _stable_sha256(comparison["alignment"])
    audit["error_judgements"] = [
        {
            "error_index": 0,
            "disposition": "valid",
            "suggested_error_type": None,
            "explanation": "The omission is valid.",
            "confidence": 0.95,
        }
    ]
    audit["adjudicated_error_candidates"] = [error_candidate]
    audit["adjudication_summary"] = {
        "deterministic_error_count": 1,
        "retained_error_count": 1,
        "rejected_error_count": 0,
        "modified_error_count": 0,
        "abstained_error_count": 0,
        "complete": True,
    }
    primary_error = {
        "error_type": "omission_finding",
        "hazard_level": 4,
        "explanation": "Potentially important omission.",
        "recommended_action": "radiologist_review",
        "confidence": 0.9,
        "evidence_ids": ["e1"],
        "abstain": False,
    }
    reviewer_error = {
        **primary_error,
        "hazard_level": 2,
        "explanation": "Limited impact.",
        "recommended_action": "review_if_relevant",
    }
    hazards = comparison["hazards"]
    hazards["errors"] = [primary_error]
    review = comparison["hazard_review"]
    review["primary_result_sha256"] = _stable_sha256(hazards)
    review["reviewer_result"]["errors"] = [reviewer_error]
    review["disagreements"] = [
        {
            "error_index": 0,
            "error_type": "omission_finding",
            "primary_hazard_level": 4,
            "reviewer_hazard_level": 2,
            "level_delta": 2,
            "primary_recommended_action": "radiologist_review",
            "reviewer_recommended_action": "review_if_relevant",
            "disagreement_types": ["hazard_level", "recommended_action"],
            "requires_adjudication": True,
        }
    ]
    review["requires_adjudication"] = True
    if not include_adjudication:
        comparison["hazard_adjudication"] = None
        return
    comparison["hazard_adjudication"] = {
        "schema_version": "2.0",
        "artifact_type": "hazard_adjudication",
        "primary_result_sha256": _stable_sha256(hazards),
        "hazard_review_sha256": _stable_sha256(review),
        "adjudicator_provenance": {
            **_provenance("llm_adjudication", "hazard_adjudicator"),
            "model": "gpt-5.6-terra-ultra",
        },
        "decisions": [
            {
                "error_index": 0,
                "error_type": "omission_finding",
                "hazard_level": 3,
                "recommended_action": "radiologist_review",
                "explanation": "Moderate risk is best supported.",
                "confidence": 0.85,
                "evidence_ids": ["d1"],
                "abstain": False,
                "primary_hazard_level": 4,
                "reviewer_hazard_level": 2,
                "primary_recommended_action": "radiologist_review",
                "reviewer_recommended_action": "review_if_relevant",
            }
        ],
        "disagreement_count": 1,
        "resolved_count": 1,
        "abstained_count": 0,
        "primary_preserved": True,
        "reviewer_preserved": True,
        "clinical_validation_required": True,
    }


def _provenance(implementation_type: str, role: str) -> dict:
    return {
        "implementation_type": implementation_type,
        "provider": "chat_completions",
        "model": "gpt-5.6-terra",
        "version": "2.0",
        "role": role,
        "prompt_version": "test-v1",
        "fallback_used": False,
        "metadata": {"endpoint_host": "gpt.example", "attempt_count": 1},
    }


def _stable_sha256(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
