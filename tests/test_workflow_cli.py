from __future__ import annotations

import json
from pathlib import Path

import pytest
import medharness2.cli as cli_module

from medharness2.checkpoints import StageCheckpointStore
from medharness2.cli import main
from medharness2.cli import _count_or_zero
from medharness2.config import AppConfig, GeneratorConfig, LLMConfig, ModelRoleConfig, load_config
from medharness2.llm_client import build_mock_client
from medharness2.modules.pairwise_report import evaluate_pairwise
from medharness2.modules.single_report import evaluate_single_report
from medharness2.schema import GeneratedReport
from medharness2.workflows.single_case import run_single_case


def test_single_report_module_returns_composite_inputs():
    result = evaluate_single_report("FINDINGS: Mild right lung opacity. IMPRESSION: Mild opacity.", modality="cxr", llm_client=build_mock_client())
    assert result["composite_inputs"]["likert_mean"] > 0
    assert result["finding_graph"]["findings"]


@pytest.mark.parametrize("bad", [True, 1.5, -1, "2"])
def test_cli_registry_counts_reject_invalid_values(bad):
    with pytest.raises(ValueError, match="count"):
        _count_or_zero(bad, "count")


def test_cli_validate_run_rejects_malformed_result(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cli_module, "validate_sample_run", lambda *args, **kwargs: {"passed": "true", "errors": []})
    code = main(["workflow", "validate-run", "--output-dir", str(tmp_path)])
    assert code == 1
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


def test_cli_preflight_rejects_malformed_result(tmp_path: Path, monkeypatch):
    output = tmp_path / "preflight.json"
    monkeypatch.setattr(
        cli_module,
        "run_sample_preflight",
        lambda *args, **kwargs: {"passed": 1, "sample": {}, "paths": {}, "blockers": [], "warnings": []},
    )
    code = main(["workflow", "preflight", "--sample-root", str(tmp_path / "sample"), "--output", str(output)])
    assert code == 1
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


def test_cli_single_case_rejects_malformed_result(tmp_path: Path, monkeypatch):
    report = tmp_path / "report.txt"
    image = tmp_path / "image.dcm"
    output = tmp_path / "single.json"
    report.write_text("report", encoding="utf-8")
    image.write_text("image", encoding="utf-8")
    monkeypatch.setattr(
        cli_module,
        "run_single_case",
        lambda *args, **kwargs: {"generated_reports": "bad", "rankings": [], "pairwise_comparisons": [], "errors": []},
    )
    code = main(["workflow", "single-case", "--report", str(report), "--image", str(image), "--output", str(output)])
    assert code == 1
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


def test_cli_analyze_run_rejects_malformed_result(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        cli_module,
        "analyze_run",
        lambda *args, **kwargs: {"analysis_dir": "bad", "case_count": 1, "errors": "bad"},
    )
    code = main(["workflow", "analyze-run", "--output-dir", str(tmp_path)])
    assert code == 1
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


def test_cli_sample_full_rejects_malformed_validation_result(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        cli_module,
        "run_sample_full",
        lambda *args, **kwargs: {
            "summary": {
                "case_count": 1,
                "workflow2_case_count": 0,
                "workflow2_failed_case_count": 0,
                "workflow3_case_count": 0,
                "reader_count": 0,
            },
            "validation": {"passed": "true", "errors": []},
            "paths": {},
        },
    )
    code = main(
        [
            "workflow",
            "sample-full",
            "--sample-root",
            str(tmp_path / "sample"),
            "--output-dir",
            str(tmp_path / "run"),
        ]
    )
    assert code == 1
    registry = json.loads((tmp_path / "run" / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


def test_cli_merge_batches_rejects_malformed_validation_result(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        cli_module,
        "merge_batch_results",
        lambda *args, **kwargs: {"case_count": 1, "failed_case_count": 0, "per_reader": {}},
    )
    monkeypatch.setattr(cli_module, "validate_sample_run", lambda *args, **kwargs: {"passed": "true"})
    code = main(
        [
            "workflow",
            "merge-batches",
            "--batch-result",
            str(tmp_path / "batch.json"),
            "--output-dir",
            str(tmp_path / "run"),
        ]
    )
    assert code == 1
    registry = json.loads((tmp_path / "run" / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


def test_reference_report_coverage_is_self_recall_not_template_size():
    result = evaluate_single_report(
        "FINDINGS: Mild right lung opacity. IMPRESSION: Mild opacity.",
        modality="cxr",
        llm_client=build_mock_client(),
    )
    assert result["composite_inputs"]["finding_coverage"] == 1.0


@pytest.mark.parametrize("bad", [[], "bad", {"primary_image": 7}])
def test_single_case_rejects_malformed_prepared_assets(tmp_path: Path, bad):
    report = tmp_path / "report.txt"
    image = tmp_path / "image.png"
    report.write_text("FINDINGS: clear. IMPRESSION: normal.", encoding="utf-8")
    image.write_bytes(b"png")
    with pytest.raises(ValueError, match="prepared_assets"):
        run_single_case(
            report_path=report,
            image_path=image,
            output_path=tmp_path / "case.json",
            prepared_assets=bad,  # type: ignore[arg-type]
            config=AppConfig(llm=LLMConfig(provider="mock")),
        )


def test_single_case_rejects_malformed_generated_composite_inputs(tmp_path: Path, monkeypatch):
    report = tmp_path / "report.txt"
    image = tmp_path / "image.png"
    report.write_text("FINDINGS: clear. IMPRESSION: normal.", encoding="utf-8")
    image.write_bytes(b"png")

    original = evaluate_single_report
    calls = 0

    def malformed(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls > 1:
            result["composite_inputs"] = "bad"
        return result

    monkeypatch.setattr("medharness2.workflows.single_case.evaluate_single_report", malformed)
    with pytest.raises(ValueError, match="generated_evaluation.composite_inputs"):
        run_single_case(
            report_path=report,
            image_path=image,
            output_path=tmp_path / "case.json",
            config=AppConfig(llm=LLMConfig(provider="mock")),
        )


def test_single_report_routes_likert_through_general_judge_role():
    response = {
        metric: {"score": 4, "explanation": "Evidence-based score."}
        for metric in [
            "Completeness and Accuracy",
            "Conciseness and Clarity",
            "Terminological Accuracy",
            "Structure and Style",
            "Overall Writing Quality",
        ]
    }
    client = _SequenceClient([response])
    cfg = AppConfig(
        llm=LLMConfig(provider="mock", max_retries=1),
        model_roles={
            "general_judge": ModelRoleConfig(
                provider="chat_completions",
                model="gpt-5.5",
                api_key_env="DMX_API_KEY",
                base_url="https://www.DMXAPI.cn/v1",
                max_retries=2,
            )
        },
    )

    result = evaluate_single_report(
        "FINDINGS: Clear lungs. IMPRESSION: No acute disease.",
        modality="cxr",
        config=cfg,
        llm_client=client,
    )

    assert client.call_kwargs[0]["provider"] == "chat_completions"
    assert client.call_kwargs[0]["model"] == "gpt-5.5"
    assert result["likert"]["_metadata"]["backend"] == "llm_judge"
    assert result["likert"]["_metadata"]["role"] == "general_judge"


def test_single_report_passes_general_judge_consistency_runs():
    response = {
        metric: {"score": 4, "explanation": "Evidence-based score."}
        for metric in [
            "Completeness and Accuracy",
            "Conciseness and Clarity",
            "Terminological Accuracy",
            "Structure and Style",
            "Overall Writing Quality",
        ]
    }
    client = _SequenceClient([response, response])
    cfg = AppConfig(
        model_roles={
            "general_judge": ModelRoleConfig(
                provider="chat_completions",
                model="gpt-5.6-sol",
                consistency_runs=2,
            )
        }
    )

    result = evaluate_single_report("FINDINGS: Clear lungs.", modality="cxr", config=cfg, llm_client=client)

    assert client.call_count == 2
    assert result["likert"]["_metadata"]["consistency_runs"] == 2
    assert result["likert"]["_metadata"]["consistency_exact"] is True


def test_single_report_uses_separate_schema_and_transport_retry_budgets():
    complete = {
        metric: {"score": 4, "explanation": "Evidence-based score."}
        for metric in [
            "Completeness and Accuracy",
            "Conciseness and Clarity",
            "Terminological Accuracy",
            "Structure and Style",
            "Overall Writing Quality",
        ]
    }
    client = _SequenceClient([{"invalid": True}, complete])
    cfg = AppConfig(
        model_roles={
            "general_judge": ModelRoleConfig(
                provider="chat_completions",
                model="gpt-5.6-terra",
                schema_max_attempts=2,
                transport_max_retries=1,
            )
        }
    )

    result = evaluate_single_report(
        "FINDINGS: Clear lungs.",
        modality="cxr",
        config=cfg,
        llm_client=client,
    )

    assert client.call_count == 2
    assert [kwargs["max_retries"] for kwargs in client.call_kwargs] == [1, 1]
    assert result["likert"]["_metadata"]["attempt_count"] == 2


def test_single_report_routes_template_candidate_through_finding_extractor_role():
    likert_response = {
        metric: {"score": 4, "explanation": "Evidence-based score."}
        for metric in [
            "Completeness and Accuracy",
            "Conciseness and Clarity",
            "Terminological Accuracy",
            "Structure and Style",
            "Overall Writing Quality",
        ]
    }
    extraction_response = {
        "findings": [
            {
                "observation_code": "nodule",
                "observation_text": "pulmonary nodule",
                "anatomy_code": "right upper lobe",
                "location_text": "right upper lobe",
                "laterality": "right",
                "certainty": "present",
                "severity": None,
                "measurements": [{"value": 6, "unit": "mm"}],
                "evidence": "A 6 mm nodule is present in the right upper lobe.",
                "attributes": {},
            }
        ],
        "relations": [],
    }
    client = _SequenceClient([likert_response, extraction_response])
    cfg = AppConfig(
        llm=LLMConfig(provider="mock", max_retries=1),
        model_roles={
            "finding_extractor": ModelRoleConfig(
                provider="chat_completions",
                model="gpt-5.5",
                api_key_env="DMX_API_KEY",
                base_url="https://www.DMXAPI.cn/v1",
                max_retries=2,
            )
        },
    )

    result = evaluate_single_report(
        "FINDINGS: A 6 mm nodule is present in the right upper lobe.",
        modality="cxr",
        config=cfg,
        llm_client=client,
    )

    assert client.call_kwargs[1]["provider"] == "chat_completions"
    assert client.call_kwargs[1]["model"] == "gpt-5.5"
    assert result["finding_graph"]["backend"] == "template_llm"
    assert result["finding_graph"]["metadata"]["llm_correction"]["role"] == "finding_extractor"


def test_pairwise_module_returns_alignment():
    result = evaluate_pairwise(
        "FINDINGS: Mild right lung opacity. IMPRESSION: Opacity.",
        "FINDINGS: Mild right lung opacity. IMPRESSION: Opacity.",
        modality="cxr",
        llm_client=build_mock_client(),
    )
    assert result["alignment"]["metrics"]["f1"] == 1.0


def test_pairwise_reuses_precomputed_finding_graphs_without_reextracting():
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
        "warnings": [],
        "metadata": {},
    }
    client = _SequenceClient([])
    cfg = AppConfig(
        model_roles={
            "finding_extractor": ModelRoleConfig(
                provider="chat_completions",
                model="gpt-5.5",
            )
        }
    )

    result = evaluate_pairwise(
        "FINDINGS: Clear lungs.",
        "FINDINGS: Clear lungs.",
        modality="cxr",
        config=cfg,
        llm_client=client,
        reference_graph=graph,
        candidate_graph=graph,
    )

    assert client.call_count == 0
    assert result["graph_a"] is graph
    assert result["graph_b"] is graph


def test_pairwise_routes_both_template_graphs_through_finding_extractor_role():
    extraction_response = {
        "findings": [
            {
                "observation_code": "nodule",
                "observation_text": "pulmonary nodule",
                "anatomy_code": "right upper lobe",
                "location_text": "right upper lobe",
                "laterality": "right",
                "certainty": "present",
                "severity": None,
                "measurements": [{"value": 6, "unit": "mm"}],
                "evidence": "A 6 mm nodule is present in the right upper lobe.",
                "attributes": {},
            }
        ],
        "relations": [],
    }
    client = _SequenceClient([extraction_response, extraction_response])
    cfg = AppConfig(
        model_roles={
            "finding_extractor": ModelRoleConfig(
                provider="chat_completions",
                model="gpt-5.5",
                max_retries=2,
            )
        }
    )

    result = evaluate_pairwise(
        "FINDINGS: A 6 mm nodule is present in the right upper lobe.",
        "FINDINGS: A 6 mm nodule is present in the right upper lobe.",
        modality="cxr",
        config=cfg,
        llm_client=client,
    )

    assert client.call_count == 2
    assert all(kwargs["provider"] == "chat_completions" for kwargs in client.call_kwargs)
    assert result["graph_a"]["backend"] == "template_llm"
    assert result["graph_b"]["backend"] == "template_llm"


def test_pairwise_routes_deterministic_alignment_through_llm_auditor():
    client = _SequenceClient(
        [
            {
                "verdict": "pass",
                "confidence": 0.97,
                "summary": "The deterministic alignment is clinically coherent.",
                "issues": [],
            }
        ]
    )
    cfg = AppConfig(
        model_roles={
            "alignment_auditor": ModelRoleConfig(
                provider="chat_completions",
                model="gpt-5.5",
                max_retries=2,
            )
        }
    )

    result = evaluate_pairwise(
        "FINDINGS: A 6 mm nodule is present in the right upper lobe.",
        "FINDINGS: A 6 mm nodule is present in the right upper lobe.",
        modality="cxr",
        config=cfg,
        llm_client=client,
    )

    assert client.call_count == 1
    assert client.call_kwargs[0]["provider"] == "chat_completions"
    assert client.call_kwargs[0]["model"] == "gpt-5.5"
    assert result["alignment"]["metrics"]["f1"] == 1.0
    assert result["alignment_audit"]["verdict"] == "pass"
    assert result["alignment_audit"]["primary_preserved"] is True


def test_pairwise_hazard_judge_uses_t5_adjudicated_error_candidates():
    client = _SequenceClient(
        [
            {
                "verdict": "issues_found",
                "confidence": 0.99,
                "summary": "The normal-lung statements are equivalent.",
                "issues": [],
                "error_judgements": [
                    {
                        "error_index": 0,
                        "disposition": "unsupported",
                        "suggested_error_type": None,
                        "explanation": "Candidate statement is supported.",
                        "confidence": 0.99,
                    },
                    {
                        "error_index": 1,
                        "disposition": "unsupported",
                        "suggested_error_type": None,
                        "explanation": "Reference statement is covered.",
                        "confidence": 0.99,
                    },
                ],
            },
            {"errors": []},
        ]
    )
    cfg = AppConfig(
        model_roles={
            "alignment_auditor": ModelRoleConfig(
                provider="chat_completions",
                model="gpt-5.5",
            ),
            "hazard_primary": ModelRoleConfig(
                provider="chat_completions",
                model="gpt-5.5",
            ),
        }
    )
    reference_graph = {
        "findings": [
            {
                "finding_id": "f1",
                "observation_code": "normal lung appearance",
                "anatomy_code": "lungs",
                "laterality": "bilateral",
                "certainty": "present",
            }
        ]
    }
    candidate_graph = {
        "findings": [
            {
                "finding_id": "f1",
                "observation_code": "clear lungs",
                "anatomy_code": "lungs",
                "laterality": "bilateral",
                "certainty": "present",
            }
        ]
    }

    result = evaluate_pairwise(
        "FINDINGS: Normal lung appearance.",
        "FINDINGS: Clear lungs.",
        modality="cxr",
        reference_graph=reference_graph,
        candidate_graph=candidate_graph,
        config=cfg,
        llm_client=client,
    )

    assert len(result["alignment"]["error_candidates"]) == 2
    assert result["alignment_audit"]["adjudicated_error_candidates"] == []
    assert result["hazards"]["errors"] == []
    assert client.call_count == 2


def test_pairwise_uses_tool6_and_routes_structure_through_llm_assessor():
    client = _SequenceClient(
        [
            {
                "verdict": "no_material_issue",
                "clinical_impact": 1,
                "confidence": 0.96,
                "summary": "Both reports have equivalent clinically usable structure.",
                "issues": [],
            }
        ]
    )
    cfg = AppConfig(
        model_roles={
            "structure_auditor": ModelRoleConfig(
                provider="chat_completions",
                model="gpt-5.5",
                max_retries=2,
            )
        }
    )
    report = "FINDINGS: Clear lungs.\nIMPRESSION: No acute cardiopulmonary disease."

    result = evaluate_pairwise(
        report,
        report,
        modality="cxr",
        config=cfg,
        llm_client=client,
    )

    assert client.call_count == 1
    assert client.call_kwargs[0]["provider"] == "chat_completions"
    assert result["structure_diff"]["artifact_type"] == "structure_diff"
    assert result["structure_diff"]["metric_version"] == "tool6-structure-v2"
    assert result["structure_audit"]["verdict"] == "no_material_issue"
    assert result["structure_audit"]["primary_preserved"] is True


def test_pairwise_aligns_candidate_against_human_reference():
    result = evaluate_pairwise(
        "FINDINGS: Mild right lung opacity. No pneumothorax.",
        "FINDINGS: Mild right lung opacity. Small pleural effusion.",
        modality="cxr",
        llm_client=build_mock_client(),
    )
    error_types = [item["error_type"] for item in result["alignment"]["error_candidates"]]
    assert "false_finding" in error_types
    assert "omission_finding" in error_types
    assert result["alignment"]["candidate_only"][0]["observation_code"] == "effusion"


def test_pairwise_uses_configured_hazard_schema_retries():
    client = _SequenceClient(["not json", {"errors": [{"error_type": "incorrect_severity", "hazard_level": 5, "explanation": "clinically important severity mismatch"}]}])
    cfg = AppConfig(llm=LLMConfig(provider="mock", max_retries=2))

    result = evaluate_pairwise(
        "FINDINGS: Mild pneumothorax.",
        "FINDINGS: Severe pneumothorax.",
        modality="cxr",
        config=cfg,
        llm_client=client,
    )

    assert client.call_count == 2
    assert result["hazards"]["metadata"]["backend"] == "llm_judge"
    assert result["hazards"]["metadata"]["attempt_count"] == 2
    assert result["hazards"]["errors"][0]["hazard_level"] == 5


def test_pairwise_routes_hazard_judge_through_configured_model_role():
    client = _SequenceClient(
        [
            {
                "errors": [
                    {
                        "error_type": "incorrect_severity",
                        "hazard_level": 4,
                        "explanation": "important",
                        "recommended_action": "radiologist_review",
                        "confidence": 0.9,
                        "evidence_ids": ["e1"],
                        "abstain": False,
                    }
                ]
            }
        ]
    )
    cfg = AppConfig(
        llm=LLMConfig(provider="mock", max_retries=1),
        model_roles={
            "hazard_primary": ModelRoleConfig(
                provider="chat_completions",
                model="gpt-5.5",
                api_key_env="DMX_API_KEY",
                base_url="https://www.DMXAPI.cn/v1",
                max_retries=2,
            )
        },
    )

    result = evaluate_pairwise(
        "FINDINGS: Mild pneumothorax.",
        "FINDINGS: Severe pneumothorax.",
        modality="cxr",
        config=cfg,
        llm_client=client,
    )

    assert client.call_kwargs[0]["provider"] == "chat_completions"
    assert client.call_kwargs[0]["model"] == "gpt-5.5"
    assert result["hazards"]["metadata"]["role"] == "hazard_primary"
    assert result["hazards"]["metadata"]["fallback_used"] is False


def test_pairwise_runs_independent_hazard_reviewer_and_preserves_primary():
    primary_response = {
        "errors": [
            {
                "error_type": "incorrect_severity",
                "hazard_level": 4,
                "explanation": "Potentially important undercall.",
                "recommended_action": "radiologist_review",
                "confidence": 0.9,
                "evidence_ids": ["e1"],
                "abstain": False,
            }
        ]
    }
    reviewer_response = {
        "errors": [
            {
                "error_type": "incorrect_severity",
                "hazard_level": 2,
                "explanation": "Limited immediate impact.",
                "recommended_action": "review_if_relevant",
                "confidence": 0.8,
                "evidence_ids": ["e1"],
                "abstain": False,
            }
        ]
    }
    client = _SequenceClient([primary_response, reviewer_response])
    cfg = AppConfig(
        model_roles={
            "hazard_primary": ModelRoleConfig(
                provider="chat_completions",
                model="gpt-5.5",
                max_retries=2,
            ),
            "hazard_reviewer": ModelRoleConfig(
                provider="chat_completions",
                model="claude-opus-4-6",
                max_retries=2,
                consistency_runs=2,
            ),
        }
    )

    result = evaluate_pairwise(
        "FINDINGS: Mild pneumothorax.",
        "FINDINGS: Severe pneumothorax.",
        modality="cxr",
        config=cfg,
        llm_client=client,
    )

    assert client.call_count == 3
    assert client.call_kwargs[0]["model"] == "gpt-5.5"
    assert client.call_kwargs[1]["model"] == "claude-opus-4-6"
    assert result["hazards"]["errors"][0]["hazard_level"] == 4
    assert result["hazard_review"]["reviewer_result"]["errors"][0]["hazard_level"] == 2
    assert result["hazard_review"]["primary_preserved"] is True
    assert result["hazard_review"]["requires_adjudication"] is True
    assert result["hazard_review"]["reviewer_consistency"]["runs"] == 2


def test_pairwise_routes_hazard_disagreements_to_third_adjudicator(tmp_path: Path):
    primary_response = {
        "errors": [
            {
                "error_type": "incorrect_severity",
                "hazard_level": 4,
                "explanation": "Potentially important undercall.",
                "recommended_action": "radiologist_review",
                "confidence": 0.9,
                "evidence_ids": ["e1"],
                "abstain": False,
            }
        ]
    }
    reviewer_response = {
        "errors": [
            {
                "error_type": "incorrect_severity",
                "hazard_level": 2,
                "explanation": "Limited impact.",
                "recommended_action": "review_if_relevant",
                "confidence": 0.8,
                "evidence_ids": ["e1"],
                "abstain": False,
            }
        ]
    }
    adjudicator_response = {
        "decisions": [
            {
                "error_index": 0,
                "error_type": "incorrect_severity",
                "hazard_level": 3,
                "recommended_action": "radiologist_review",
                "explanation": "Moderate risk best fits the available evidence.",
                "confidence": 0.85,
                "evidence_ids": ["d1"],
                "abstain": False,
            }
        ]
    }
    client = _SequenceClient(
        [primary_response, reviewer_response, adjudicator_response]
    )
    cfg = AppConfig(
        model_roles={
            "hazard_primary": ModelRoleConfig(
                provider="chat_completions",
                model="gpt-5.6-terra",
            ),
            "hazard_reviewer": ModelRoleConfig(
                provider="chat_completions",
                model="claude-opus-4-8",
            ),
            "hazard_adjudicator": ModelRoleConfig(
                provider="chat_completions",
                model="gpt-5.6-terra-ultra",
            ),
        }
    )

    checkpoint_root = tmp_path / "checkpoints"
    first_store = StageCheckpointStore(checkpoint_root)
    result = evaluate_pairwise(
        "FINDINGS: Mild pneumothorax.",
        "FINDINGS: Severe pneumothorax.",
        modality="cxr",
        config=cfg,
        llm_client=client,
        checkpoint_store=first_store,
        checkpoint_namespace="candidate_0",
    )

    assert client.call_count == 3
    assert client.call_kwargs[2]["model"] == "gpt-5.6-terra-ultra"
    assert result["hazard_adjudication"]["decisions"][0]["hazard_level"] == 3
    assert first_store.summary()["stats"] == {"hits": 0, "misses": 3, "writes": 3}

    replay_client = _SequenceClient(["cached stages must not call the provider"])
    second_store = StageCheckpointStore(checkpoint_root)
    replay = evaluate_pairwise(
        "FINDINGS: Mild pneumothorax.",
        "FINDINGS: Severe pneumothorax.",
        modality="cxr",
        config=cfg,
        llm_client=replay_client,
        checkpoint_store=second_store,
        checkpoint_namespace="candidate_0",
    )

    assert replay == result
    assert replay_client.call_count == 0
    assert second_store.summary()["stats"] == {"hits": 3, "misses": 0, "writes": 0}


def test_single_case_workflow_writes_json(tmp_path: Path):
    report = tmp_path / "human.txt"
    image = tmp_path / "dummy.dcm"
    output = tmp_path / "result.json"
    report.write_text("FINDINGS: Mild right lung opacity measuring 1.2 cm.\nIMPRESSION: Mild opacity.", encoding="utf-8")
    image.write_text("dummy", encoding="utf-8")
    result = run_single_case(report, image, output, modality="cxr", top_n=1, llm_client=build_mock_client(), config=load_config())
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["human_evaluation"]
    assert payload["generated_reports"]
    assert payload["rankings"][0]["selected_top_n"] is True
    assert result["pairwise_comparisons"]


def test_single_case_preserves_legacy_fourth_positional_report_text(tmp_path: Path):
    image = tmp_path / "dummy.dcm"
    output = tmp_path / "result.json"
    image.write_text("dummy", encoding="utf-8")

    run_single_case(
        None,
        image,
        output,
        "FINDINGS: Positional report text. IMPRESSION: Normal.",
        modality="cxr",
        top_n=1,
        llm_client=build_mock_client(),
        config=load_config(),
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "Positional report text" in payload["human_evaluation"]["finding_graph"]["findings"][0]["source_text"]


def test_single_case_keyword_case_id_is_preserved_without_changing_legacy_positionals(tmp_path: Path):
    report = tmp_path / "human.txt"
    image = tmp_path / "dummy.dcm"
    output = tmp_path / "result.json"
    report.write_text("FINDINGS: No pneumothorax. IMPRESSION: Normal.", encoding="utf-8")
    image.write_text("dummy", encoding="utf-8")

    result = run_single_case(
        report,
        image,
        output,
        case_id="explicit-case-id",
        modality="cxr",
        top_n=1,
        llm_client=build_mock_client(),
        config=load_config(),
    )

    assert result["case_id"] == "explicit-case-id"
    assert result["input"]["case_id"] == "explicit-case-id"
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["case_id"] == "explicit-case-id"
    assert payload["input"]["case_id"] == "explicit-case-id"


def test_cli_single_case(tmp_path: Path):
    report = tmp_path / "human.txt"
    image = tmp_path / "dummy.dcm"
    output = tmp_path / "result.json"
    report.write_text("FINDINGS: No pneumothorax. IMPRESSION: No acute disease.", encoding="utf-8")
    image.write_text("dummy", encoding="utf-8")
    code = main(["workflow", "single-case", "--report", str(report), "--image", str(image), "--output", str(output), "--modality", "cxr", "--top-n", "1"])
    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "pairwise_comparisons" in payload
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    entry = registry["entries"][-1]
    assert entry["stage"] == "workflow.single-case"
    assert entry["outputs"]["result"] == str(output)
    assert entry["metrics"]["generated_report_count"] == len(payload["generated_reports"])


def test_cli_single_case_rejects_when_no_generator_is_available(tmp_path: Path):
    report = tmp_path / "human.txt"
    image = tmp_path / "dummy.dcm"
    output = tmp_path / "result.json"
    report.write_text("FINDINGS: No pneumothorax. IMPRESSION: No acute disease.", encoding="utf-8")
    image.write_text("dummy", encoding="utf-8")
    config = tmp_path / "no_generator.yaml"
    config.write_text(
        "llm:\n  provider: mock\ngenerator:\n  cloud_fallback_enabled: false\n  default_models: []\n  local_models: []\n",
        encoding="utf-8",
    )

    code = main([
        "workflow", "single-case", "--report", str(report), "--image", str(image),
        "--output", str(output), "--modality", "cxr", "--config", str(config),
    ])

    assert code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["errors"] == ["no_generated_reports"]
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


def test_cli_single_case_preserves_explicit_case_id(tmp_path: Path):
    report = tmp_path / "human.txt"
    image = tmp_path / "dummy.dcm"
    output = tmp_path / "result.json"
    report.write_text("FINDINGS: No pneumothorax. IMPRESSION: Normal.", encoding="utf-8")
    image.write_text("dummy", encoding="utf-8")

    code = main(
        [
            "workflow",
            "single-case",
            "--report",
            str(report),
            "--image",
            str(image),
            "--output",
            str(output),
            "--modality",
            "cxr",
            "--case-id",
            "cli-explicit-case",
            "--top-n",
            "1",
        ]
    )

    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["case_id"] == "cli-explicit-case"
    assert payload["input"]["case_id"] == "cli-explicit-case"


def test_cli_benchmark_evaluate_uses_explicit_config_and_resume_flag(
    tmp_path: Path,
    monkeypatch,
):
    captured = {}

    def fake_evaluate(benchmark_dir, manifest, output_dir, **kwargs):
        captured.update(
            {
                "benchmark_dir": benchmark_dir,
                "manifest": manifest,
                "output_dir": output_dir,
                **kwargs,
            }
        )
        return {"status": "succeeded", "evaluation_count": 1, "failure_count": 0}

    monkeypatch.setattr(
        "medharness2.cli.evaluate_generation_benchmark",
        fake_evaluate,
    )
    benchmark_dir = tmp_path / "benchmark"
    manifest = tmp_path / "manifest.jsonl"
    output_dir = tmp_path / "evaluation"

    code = main(
        [
            "benchmark",
            "evaluate",
            "--benchmark-dir",
            str(benchmark_dir),
            "--manifest",
            str(manifest),
            "--output-dir",
            str(output_dir),
            "--config",
            "config/codex_yunwu_strong.yaml",
            "--no-resume",
        ]
    )

    assert code == 0
    assert captured["benchmark_dir"] == str(benchmark_dir)
    assert captured["manifest"] == str(manifest)
    assert captured["output_dir"] == str(output_dir)
    assert captured["resume"] is False
    assert captured["config"].model_roles["general_judge"].model == "gpt-5.6-terra"


class _SequenceClient:
    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0
        self.call_kwargs = []

    def call(self, prompt: str, image_path: str | None = None, **kwargs):
        self.call_count += 1
        self.call_kwargs.append(kwargs)
        response = self.responses[min(self.call_count - 1, len(self.responses) - 1)]
        if isinstance(response, str):
            return response
        return json.dumps(response, ensure_ascii=False)


def test_single_case_quality_gate_blocks_off_domain_generated_report(tmp_path: Path):
    report = tmp_path / "human.txt"
    image = tmp_path / "brain.nii.gz"
    output = tmp_path / "result.json"
    report.write_text("FINDINGS: Brain MRI without acute infarct. IMPRESSION: No acute intracranial abnormality.", encoding="utf-8")
    image.write_text("dummy", encoding="utf-8")
    generated = GeneratedReport(
        model="brain_gemma3d",
        source="medharness_cli",
        report="Findings: A left hip radiograph shows sclerosis of the femoral head.",
        modality="mri",
    )
    result = run_single_case(
        report_path=report,
        image_path=image,
        output_path=output,
        modality="mri",
        body_part="brain",
        precomputed_generated_reports=[generated],
        config=AppConfig(generator=GeneratorConfig(default_models=[], local_models=[])),
        llm_client=build_mock_client(),
    )
    blocked = result["generated_reports"][0]
    assert "quality_gate_failed" in blocked["warnings"]
    assert "body_part_mismatch" in blocked["warnings"]
    assert "modality_mismatch" in blocked["warnings"]
    assert blocked["metadata"]["quality_gate"]["passed"] is False
    assert result["rankings"] == []
    assert result["pairwise_comparisons"] == []


def test_single_case_keeps_body_part_only_mismatch_in_ranking(tmp_path: Path):
    report = tmp_path / "human.txt"
    image = tmp_path / "head.nii.gz"
    output = tmp_path / "result.json"
    report.write_text("FINDINGS: Head CT without hemorrhage. IMPRESSION: No acute abnormality.", encoding="utf-8")
    image.write_text("dummy", encoding="utf-8")
    generated = GeneratedReport(
        model="head_ct_reader",
        source="medharness_cli",
        report="FINDINGS: CT shows a small lung nodule. IMPRESSION: Follow-up recommended.",
        modality="ct",
    )
    result = run_single_case(
        report_path=report,
        image_path=image,
        output_path=output,
        modality="ct",
        body_part="head",
        precomputed_generated_reports=[generated],
        config=AppConfig(generator=GeneratorConfig(default_models=[], local_models=[])),
        llm_client=build_mock_client(),
    )
    kept = result["generated_reports"][0]
    assert kept["metadata"]["quality_gate"]["passed"] is True
    assert "body_part_mismatch" in kept["metadata"]["quality_gate"]["warnings"]
    assert len(result["rankings"]) == 1


def test_single_case_quality_gate_keeps_matching_cxr_report(tmp_path: Path):
    report = tmp_path / "human.txt"
    image = tmp_path / "chest.png"
    output = tmp_path / "result.json"
    report.write_text("FINDINGS: No pneumothorax. IMPRESSION: Normal chest.", encoding="utf-8")
    image.write_text("dummy", encoding="utf-8")
    generated = GeneratedReport(
        model="chexagent_srrg_findings_full",
        source="medharness_cli",
        report="FINDINGS: Lungs are clear. No pleural effusion or pneumothorax.",
        modality="cxr",
    )
    result = run_single_case(
        report_path=report,
        image_path=image,
        output_path=output,
        modality="cxr",
        body_part="chest",
        top_n=1,
        precomputed_generated_reports=[generated],
        config=AppConfig(generator=GeneratorConfig(default_models=[], local_models=[])),
        llm_client=build_mock_client(),
    )
    kept = result["generated_reports"][0]
    assert kept["metadata"]["quality_gate"]["passed"] is True
    assert "quality_gate_failed" not in kept["warnings"]
    assert result["rankings"][0]["model"] == "chexagent_srrg_findings_full"
    assert len(result["pairwise_comparisons"]) == 1


def test_single_case_quality_gate_blocks_mock_fallback_report(tmp_path: Path):
    from medharness2.schema import GeneratedReport
    from medharness2.tools.quality_gate import apply_generation_quality_gate

    report = GeneratedReport(
        model="mock",
        source="mock_fallback",
        report="mock response",
        modality="cxr",
        metadata={"fallback_used": True},
    )
    gated = apply_generation_quality_gate(report, modality="cxr", body_part="chest")
    assert gated.metadata["quality_gate"]["passed"] is False
    assert "fallback_generation" in gated.metadata["quality_gate"]["warnings"]


def test_quality_gate_blocks_malformed_fallback_provenance(tmp_path: Path):
    from medharness2.schema import GeneratedReport
    from medharness2.tools.quality_gate import apply_generation_quality_gate

    report = GeneratedReport(
        model="candidate",
        source="artifact_reuse",
        report="FINDINGS: Clear lungs.",
        modality="cxr",
        metadata={"fallback_used": 0},
    )
    gated = apply_generation_quality_gate(report, modality="cxr", body_part="chest")
    assert gated.metadata["quality_gate"]["passed"] is False
    assert "fallback_generation" in gated.metadata["quality_gate"]["warnings"]


def test_single_case_fallback_uses_primary_image_instead_of_volume(tmp_path: Path):
    report = tmp_path / "human.txt"
    primary = tmp_path / "contact_sheet.png"
    volume = tmp_path / "volume.nii.gz"
    output = tmp_path / "result.json"
    report.write_text("FINDINGS: Head CT without hemorrhage. IMPRESSION: No acute abnormality.", encoding="utf-8")
    primary.write_bytes(b"\x89PNG\r\n\x1a\n")
    volume.write_text("volume", encoding="utf-8")

    class RecordingClient:
        def __init__(self):
            self.generation_image_path = None

        def call(self, prompt, image_path=None, **kwargs):
            if kwargs.get("response_json") is not None:
                return json.dumps(kwargs["response_json"])
            if prompt.startswith("Generate a concise radiology report"):
                self.generation_image_path = image_path
                return "FINDINGS: No acute intracranial hemorrhage. IMPRESSION: No acute abnormality."
            return "{}"

    client = RecordingClient()
    cfg = AppConfig(
        generator=GeneratorConfig(
            cloud_fallback_enabled=True,
            default_models=[],
            local_models=[],
            include_legacy_ready_models=False,
        )
    )
    run_single_case(
        report_path=report,
        image_path=primary,
        output_path=output,
        prepared_assets={"primary_image": str(primary), "volume_path": str(volume)},
        modality="ct",
        body_part="head",
        config=cfg,
        llm_client=client,
    )
    assert client.generation_image_path == str(primary)


def test_cli_sample_data_writes_run_registry(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    (case_dir / "Y1").write_text("dummy", encoding="utf-8")
    (sample_root / "CR" / "CR001" / "report.pdf").write_text("dummy pdf", encoding="utf-8")
    output_dir = tmp_path / "dataset"

    code = main(["workflow", "sample-data", "--sample-root", str(sample_root), "--output-dir", str(output_dir), "--limit", "1", "--skip-ocr"])

    assert code == 0
    assert (output_dir / "manifest.jsonl").exists()
    registry = json.loads((output_dir / "run_registry.json").read_text(encoding="utf-8"))
    entry = registry["entries"][-1]
    assert entry["stage"] == "workflow.sample-data"
    assert entry["outputs"]["manifest"] == str(output_dir / "manifest.jsonl")
    assert entry["metrics"]["case_count"] == 1


def test_cli_sample_data_rejects_empty_sample_root(tmp_path: Path):
    output_dir = tmp_path / "empty_dataset"
    code = main(["workflow", "sample-data", "--sample-root", str(tmp_path / "empty"), "--output-dir", str(output_dir), "--skip-ocr"])
    assert code == 1
    registry = json.loads((output_dir / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["metrics"]["case_count"] == 0
    assert registry["entries"][-1]["status"] == "failed"


def test_cli_sample_full(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    (case_dir / "Y1").write_text("dummy", encoding="utf-8")
    (sample_root / "CR" / "CR001" / "report.pdf").write_text("dummy pdf", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "llm:",
                "  provider: mock",
                "extractor:",
                "  backend: placeholder",
                "generator:",
                "  cloud_fallback_enabled: true",
                "  default_models: []",
                "  local_models: []",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "run"
    code = main(
        [
            "workflow",
            "sample-full",
            "--sample-root",
            str(sample_root),
            "--output-dir",
            str(output_dir),
            "--limit",
            "1",
            "--expected-cases",
            "1",
            "--config",
            str(config_path),
        ]
    )
    assert code == 0
    payload = json.loads((output_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert payload["validation"]["passed"] is True
    registry = json.loads((output_dir / "run_registry.json").read_text(encoding="utf-8"))
    entry = registry["entries"][-1]
    assert entry["stage"] == "workflow.sample-full"
    assert entry["metrics"]["case_count"] == 1
    assert entry["metrics"]["validation_passed"] is True


def test_cli_sample_full_dry_run_all_compatible(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    (case_dir / "Y1").write_text("dummy", encoding="utf-8")
    (sample_root / "CR" / "CR001" / "report.pdf").write_text("dummy pdf", encoding="utf-8")
    output_dir = tmp_path / "run"
    code = main(
        [
            "workflow",
            "sample-full",
            "--sample-root",
            str(sample_root),
            "--output-dir",
            str(output_dir),
            "--limit",
            "1",
            "--dry-run",
            "--all-compatible-local-models",
        ]
    )
    assert code == 0
    route_plan = json.loads((output_dir / "route_plan.json").read_text(encoding="utf-8"))
    assert "maira_2" in route_plan["cases"][0]["compatible_model_keys"]
    assert not (output_dir / "workflow2.json").exists()
    registry = json.loads((output_dir / "run_registry.json").read_text(encoding="utf-8"))
    entry = registry["entries"][-1]
    assert entry["stage"] == "workflow.sample-full.dry-run"
    assert entry["metrics"]["case_count"] == 1


def test_cli_sample_full_dry_run_filters_model_source(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    (case_dir / "Y1").write_text("dummy", encoding="utf-8")
    (sample_root / "CR" / "CR001" / "report.pdf").write_text("dummy pdf", encoding="utf-8")
    output_dir = tmp_path / "run"
    code = main(
        [
            "workflow",
            "sample-full",
            "--sample-root",
            str(sample_root),
            "--output-dir",
            str(output_dir),
            "--limit",
            "1",
            "--dry-run",
            "--all-compatible-local-models",
            "--model-source",
            "artifact_reuse",
        ]
    )
    assert code == 0
    route_plan = json.loads((output_dir / "route_plan.json").read_text(encoding="utf-8"))
    assert "chexagent" in route_plan["cases"][0]["compatible_model_keys"]
    assert "maira_2" not in route_plan["cases"][0]["compatible_model_keys"]


def test_cli_models_list_shows_local_ready_generators(capsys):
    code = main(["models", "list", "--modality", "cxr", "--body-part", "chest"])
    captured = capsys.readouterr()
    assert code == 0
    assert "maira_2" in captured.out
    assert "chexagent_srrg_findings_full" in captured.out
    assert "brain_gemma3d" not in captured.out


def test_cli_batch_readers_and_department_write_run_registry(tmp_path: Path):
    report = tmp_path / "report.txt"
    image = tmp_path / "image.dcm"
    manifest = tmp_path / "manifest.jsonl"
    config_path = _mock_no_local_config(tmp_path)
    report.write_text("FINDINGS: No pneumothorax. IMPRESSION: No acute disease.", encoding="utf-8")
    image.write_text("dummy", encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "case_id": "case1",
                "reader": "reader_a",
                "modality": "cxr",
                "body_part": "chest",
                "report_text": str(report),
                "image_paths": [str(image)],
                "derived_assets": {"primary_image": str(image)},
                "warnings": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    workflow2 = tmp_path / "workflow2.json"
    workflow3 = tmp_path / "workflow3.json"

    batch_code = main(
        [
            "workflow",
            "batch-readers",
            "--manifest",
            str(manifest),
            "--output",
            str(workflow2),
            "--config",
            str(config_path),
        ]
    )
    dept_code = main(["workflow", "department", "--batch-result", str(workflow2), "--output", str(workflow3)])

    assert batch_code == 0
    assert dept_code == 0
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    stages = [entry["stage"] for entry in registry["entries"]]
    assert stages[-2:] == ["workflow.batch-readers", "workflow.department"]
    assert registry["entries"][-2]["metrics"]["case_count"] == 1
    assert registry["entries"][-1]["outputs"]["workflow3"] == str(workflow3)


def test_cli_batch_readers_rejects_empty_manifest(tmp_path: Path):
    manifest = tmp_path / "empty.jsonl"
    manifest.write_text("", encoding="utf-8")
    output = tmp_path / "workflow2.json"

    code = main(
        [
            "workflow",
            "batch-readers",
            "--manifest",
            str(manifest),
            "--output",
            str(output),
        ]
    )

    assert code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["case_count"] == 0
    assert payload["failed_case_count"] == 0
    assert payload["errors"] == ["no_cases_discovered"]


def test_cli_exploratory_benchmark_returns_nonzero_when_no_results(tmp_path: Path):
    manifest = tmp_path / "empty.jsonl"
    manifest.write_text("", encoding="utf-8")
    output_dir = tmp_path / "benchmark"

    code = main(
        [
            "benchmark",
            "run",
            "--manifest",
            str(manifest),
            "--output-dir",
            str(output_dir),
            "--exploratory",
        ]
    )

    assert code == 1
    summary = json.loads((output_dir / "benchmark_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["result_count"] == 0


def test_cli_department_rejects_empty_batch(tmp_path: Path):
    batch = tmp_path / "workflow2.json"
    batch.write_text(
        json.dumps(
            {
                "case_count": 0,
                "failed_case_count": 0,
                "cases": [],
                "failed_cases": [],
                "per_reader": {},
                "denominator": {
                    "manifest_case_count": 0,
                    "successful_case_count": 0,
                    "failed_case_count": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "workflow3.json"

    code = main(
        [
            "workflow",
            "department",
            "--batch-result",
            str(batch),
            "--output",
            str(output),
        ]
    )

    assert code == 1
    assert json.loads(output.read_text(encoding="utf-8"))["errors"] == ["no_cases_discovered"]
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"


def test_cli_validate_run_writes_failed_run_registry(tmp_path: Path):
    output_dir = tmp_path / "run"
    output_dir.mkdir()

    code = main(["workflow", "validate-run", "--output-dir", str(output_dir), "--expected-cases", "1"])

    assert code == 1
    registry = json.loads((output_dir / "run_registry.json").read_text(encoding="utf-8"))
    entry = registry["entries"][-1]
    assert entry["stage"] == "workflow.validate-run"
    assert entry["status"] == "failed"
    assert entry["metrics"]["passed"] is False
    assert entry["metrics"]["error_count"] >= 1


def test_cli_preflight_returns_nonzero_when_real_ocr_is_blocked(tmp_path: Path):
    sample_root = tmp_path / "sample"
    case_dir = sample_root / "CR" / "CR001" / "W1"
    case_dir.mkdir(parents=True)
    (case_dir / "Y1").write_text("dummy", encoding="utf-8")
    (sample_root / "CR" / "CR001" / "report.pdf").write_text("dummy pdf", encoding="utf-8")
    output = tmp_path / "preflight.json"
    code = main(
        [
            "workflow",
            "preflight",
            "--sample-root",
            str(sample_root),
            "--output",
            str(output),
            "--limit",
            "1",
            "--require-real-ocr",
            "--all-compatible-local-models",
        ]
    )
    assert code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "real_ocr_required_but_provider_is_mock" in payload["blockers"]
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    entry = registry["entries"][-1]
    assert entry["stage"] == "workflow.preflight"
    assert entry["status"] == "failed"
    assert entry["metrics"]["passed"] is False


def test_cli_preflight_records_failed_registry_on_exception(tmp_path: Path):
    output = tmp_path / "preflight.json"

    code = main(["workflow", "preflight", "--sample-root", str(tmp_path / "missing_sample"), "--output", str(output)])

    assert code == 1
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    entry = registry["entries"][-1]
    assert entry["stage"] == "workflow.preflight"
    assert entry["status"] == "failed"
    assert entry["metrics"]["exception_type"] == "FileNotFoundError"


def _mock_no_local_config(root: Path) -> Path:
    config_path = root / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "llm:",
                "  provider: mock",
                "extractor:",
                "  backend: placeholder",
                "generator:",
                "  cloud_fallback_enabled: true",
                "  default_models: []",
                "  local_models: []",
                "  include_legacy_ready_models: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path


def test_cli_ocr_benchmark_returns_blocked_for_missing_candidate(tmp_path: Path):
    manifest = tmp_path / "ocr.json"
    output = tmp_path / "summary.json"
    manifest.write_text(
        json.dumps([{"case_id": "c1", "gold_text": "gold", "candidates": {"model": ""}}]),
        encoding="utf-8",
    )
    code = main(["ocr-benchmark", "--manifest", str(manifest), "--output", str(output)])
    assert code == 2
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "blocked"


def test_cli_single_case_returns_nonzero_and_failed_registry_on_malformed_config(tmp_path: Path):
    report = tmp_path / "report.txt"
    image = tmp_path / "image.dcm"
    output = tmp_path / "single.json"
    config = tmp_path / "malformed.yaml"
    report.write_text("FINDINGS: Normal. IMPRESSION: Normal.", encoding="utf-8")
    image.write_text("dummy", encoding="utf-8")
    config.write_text("- not-a-mapping\n", encoding="utf-8")

    code = main([
        "workflow", "single-case",
        "--report", str(report),
        "--image", str(image),
        "--output", str(output),
        "--config", str(config),
    ])

    assert code == 1
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    entry = registry["entries"][-1]
    assert entry["stage"] == "workflow.single-case"
    assert entry["status"] == "failed"
    assert entry["metrics"]["exception_type"] == "ValueError"


def test_cli_dashboard_returns_nonzero_and_failed_registry_on_malformed_config(tmp_path: Path):
    config = tmp_path / "malformed.yaml"
    config.write_text("- not-a-mapping\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    output = tmp_path / "dashboard.html"

    code = main([
        "dashboard", "build",
        "--run-dir", str(run_dir),
        "--output", str(output),
        "--config", str(config),
    ])

    assert code == 1
    registry = json.loads((run_dir / "run_registry.json").read_text(encoding="utf-8"))
    entry = registry["entries"][-1]
    assert entry["stage"] == "dashboard.build"
    assert entry["status"] == "failed"
    assert entry["metrics"]["exception_type"] == "ValueError"


def test_cli_preflight_returns_nonzero_and_failed_registry_on_malformed_config(tmp_path: Path):
    config = tmp_path / "malformed.yaml"
    config.write_text("- not-a-mapping\n", encoding="utf-8")
    output = tmp_path / "preflight.json"
    code = main([
        "workflow", "preflight",
        "--sample-root", str(tmp_path / "sample"),
        "--output", str(output),
        "--config", str(config),
    ])
    assert code == 1
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"
    assert registry["entries"][-1]["metrics"]["exception_type"] == "ValueError"


def test_cli_education_returns_nonzero_and_failed_registry_on_malformed_config(tmp_path: Path):
    config = tmp_path / "malformed.yaml"
    config.write_text("- not-a-mapping\n", encoding="utf-8")
    output = tmp_path / "education.json"
    eval_report = tmp_path / "eval.json"
    eval_report.write_text("{}", encoding="utf-8")
    code = main([
        "workflow", "education",
        "--eval-report", str(eval_report),
        "--output", str(output),
        "--config", str(config),
    ])
    assert code == 1
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"
    assert registry["entries"][-1]["metrics"]["exception_type"] == "ValueError"


def test_cli_benchmark_run_writes_failed_summary_on_malformed_config(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    output_dir = tmp_path / "benchmark"
    config = tmp_path / "malformed.yaml"
    manifest.write_text("{}\n", encoding="utf-8")
    config.write_text("- not-a-mapping\n", encoding="utf-8")
    code = main(["benchmark", "run", "--manifest", str(manifest), "--output-dir", str(output_dir), "--config", str(config)])
    assert code == 1
    payload = json.loads((output_dir / "benchmark_summary.json").read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["error_type"] == "ValueError"


def test_cli_benchmark_evaluate_writes_failed_summary_on_malformed_config(tmp_path: Path):
    benchmark_dir = tmp_path / "benchmark"
    manifest = tmp_path / "manifest.jsonl"
    output_dir = tmp_path / "evaluation"
    config = tmp_path / "malformed.yaml"
    config.write_text("- not-a-mapping\n", encoding="utf-8")
    code = main(["benchmark", "evaluate", "--benchmark-dir", str(benchmark_dir), "--manifest", str(manifest), "--output-dir", str(output_dir), "--config", str(config)])
    assert code == 1
    payload = json.loads((output_dir / "benchmark_evaluation_summary.json").read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["error_type"] == "ValueError"

@pytest.mark.parametrize(
    ("workflow_args", "registry_dir", "stage"),
    [
        (
            lambda tmp, cfg: [
                "workflow", "sample-data", "--sample-root", str(tmp / "sample"),
                "--output-dir", str(tmp / "sample-data"), "--config", str(cfg),
            ],
            lambda tmp: tmp / "sample-data",
            "workflow.sample-data",
        ),
        (
            lambda tmp, cfg: [
                "workflow", "sample-full", "--sample-root", str(tmp / "sample"),
                "--output-dir", str(tmp / "sample-full"), "--dry-run", "--config", str(cfg),
            ],
            lambda tmp: tmp / "sample-full",
            "workflow.sample-full.dry-run",
        ),
        (
            lambda tmp, cfg: [
                "workflow", "batch-readers", "--manifest", str(tmp / "manifest.jsonl"),
                "--output", str(tmp / "batch.json"), "--config", str(cfg),
            ],
            lambda tmp: tmp,
            "workflow.batch-readers",
        ),
        (
            lambda tmp, cfg: [
                "workflow", "reevaluate-run", "--source-run-dir", str(tmp / "source"),
                "--output-dir", str(tmp / "reevaluated"), "--config", str(cfg),
            ],
            lambda tmp: tmp / "reevaluated",
            "workflow.reevaluate-run",
        ),
    ],
)
def test_cli_workflow_config_failures_are_recorded(tmp_path: Path, workflow_args, registry_dir, stage):
    config = tmp_path / "malformed.yaml"
    config.write_text("- not-a-mapping\n", encoding="utf-8")
    (tmp_path / "manifest.jsonl").write_text("{}\n", encoding="utf-8")
    code = main(workflow_args(tmp_path, config))
    assert code == 1
    registry = json.loads((registry_dir(tmp_path) / "run_registry.json").read_text(encoding="utf-8"))
    entry = registry["entries"][-1]
    assert entry["stage"] == stage
    assert entry["status"] == "failed"
    assert entry["metrics"]["exception_type"] == "ValueError"


def test_cli_live_smoke_writes_failed_artifact_on_malformed_config(tmp_path: Path):
    config = tmp_path / "malformed.yaml"
    output = tmp_path / "smoke.json"
    config.write_text("- not-a-mapping\n", encoding="utf-8")
    code = main(["live-smoke", "--output", str(output), "--config", str(config)])
    assert code == 2
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["error_type"] == "ValueError"


def test_cli_models_list_returns_nonzero_on_malformed_config(tmp_path: Path):
    config = tmp_path / "malformed.yaml"
    config.write_text("- not-a-mapping\n", encoding="utf-8")
    code = main(["models", "list", "--config", str(config)])
    assert code == 1


def test_cli_tools_catalog_writes_failed_registry_on_malformed_config(tmp_path: Path):
    config = tmp_path / "malformed.yaml"
    output = tmp_path / "catalog.json"
    config.write_text("- not-a-mapping\n", encoding="utf-8")
    code = main(["tools", "catalog", "--config", str(config), "--output", str(output)])
    assert code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    registry = json.loads((tmp_path / "run_registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][-1]["status"] == "failed"
