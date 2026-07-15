from __future__ import annotations

import copy
import json

import pytest

from medharness2.config import AppConfig, GeneratorConfig, LLMConfig, ModelRoleConfig
from medharness2.contracts import (
    AlignmentAuditArtifact,
    FindingGraph,
    HazardAdjudicationArtifact,
    HazardResult,
    HazardReviewArtifact,
    StructureAuditArtifact,
)
from medharness2.llm_client import LLMClientError, build_mock_client
from medharness2.tools.tool1_likert import evaluate_likert, likert_mean
from medharness2.tools.tool2_extract import extract_findings
from medharness2.tools.tool3_structure import check_structure, section_order
from medharness2.tools.tool4_hazard import (
    adjudicate_hazard_disagreements,
    evaluate_hazards,
    review_hazards,
)
from medharness2.tools.tool5_align import align_graphs, audit_alignment, normalize_measurement_mm
from medharness2.tools.tool6_structure_diff import assess_structure_clinical_significance, compare_structure
from medharness2.tools.quality_gate import check_generation_quality
from medharness2.tools.tool8_generate import generate_reports
from medharness2.tools.tool9_rank import select_top_k


def _valid_likert_payload():
    return {
        metric: {"score": 4, "explanation": "Evidence-based score."}
        for metric in (
            "Completeness and Accuracy",
            "Conciseness and Clarity",
            "Terminological Accuracy",
            "Structure and Style",
            "Overall Writing Quality",
        )
    }


def test_tool1_likert_normalizes_scores():
    client = build_mock_client({"Completeness and Accuracy": {"score": 9, "explanation": "x"}})
    result = evaluate_likert("short report", llm_client=client)
    assert result["Completeness and Accuracy"]["score"] == 5
    assert likert_mean(result) >= 1
    assert result["warning"] == "No image/volume provided"


def test_tool1_uses_real_model_role_and_records_provenance():
    response = {
        metric: {"score": index, "explanation": f"Evidence-based score {index}."}
        for index, metric in enumerate(
            [
                "Completeness and Accuracy",
                "Conciseness and Clarity",
                "Terminological Accuracy",
                "Structure and Style",
                "Overall Writing Quality",
            ],
            start=1,
        )
    }
    client = _RecordingClient(response)
    role = ModelRoleConfig(
        provider="chat_completions",
        model="gpt-5.5",
        api_key_env="DMX_API_KEY",
        base_url="https://www.DMXAPI.cn/v1",
        max_retries=2,
    )

    result = evaluate_likert(
        "FINDINGS: Right upper lobe nodule. IMPRESSION: Pulmonary nodule.",
        llm_client=client,
        judge_options=role.as_call_options(),
        model_role="general_judge",
        require_llm=True,
        allow_fallback=False,
    )

    assert client.calls[0]["kwargs"]["provider"] == "chat_completions"
    assert client.calls[0]["kwargs"]["model"] == "gpt-5.5"
    assert result["Completeness and Accuracy"]["score"] == 1
    assert result["Overall Writing Quality"]["score"] == 5
    assert result["_metadata"]["backend"] == "llm_judge"
    assert result["_metadata"]["provider"] == "chat_completions"
    assert result["_metadata"]["role"] == "general_judge"
    assert result["_metadata"]["fallback_used"] is False


def test_tool1_retries_incomplete_real_llm_response():
    complete = {
        metric: {"score": 4, "explanation": "Complete response."}
        for metric in [
            "Completeness and Accuracy",
            "Conciseness and Clarity",
            "Terminological Accuracy",
            "Structure and Style",
            "Overall Writing Quality",
        ]
    }
    client = _SequenceClient(
        [
            {"Completeness and Accuracy": {"score": 4, "explanation": "Incomplete."}},
            complete,
        ]
    )

    result = evaluate_likert(
        "FINDINGS: Clear lungs. IMPRESSION: No acute disease.",
        llm_client=client,
        judge_options={"provider": "chat_completions", "model": "gpt-5.5"},
        model_role="general_judge",
        max_retries=2,
        require_llm=True,
        allow_fallback=False,
    )

    assert client.call_count == 2
    assert result["_metadata"]["attempt_count"] == 2
    assert result["_metadata"]["judge_error_count"] == 1


def test_tool1_strict_mode_rejects_mock_provider():
    with pytest.raises(LLMClientError, match="requires a non-mock provider"):
        evaluate_likert("FINDINGS: Test.", llm_client=build_mock_client(), require_llm=True)


def test_tool1_strict_mode_raises_after_invalid_responses():
    client = _SequenceClient(["not json", {"Completeness and Accuracy": {"score": 4}}])

    with pytest.raises(LLMClientError, match="failed schema validation after 2 attempts"):
        evaluate_likert(
            "FINDINGS: Clear lungs. IMPRESSION: No acute disease.",
            llm_client=client,
            judge_options={"provider": "chat_completions", "model": "gpt-5.5"},
            max_retries=2,
            require_llm=True,
            allow_fallback=False,
        )

    assert client.call_count == 2


def test_tool2_placeholder_extracts_schema_valid_graph():
    graph = extract_findings("FINDINGS: Mild right lung opacity measuring 1.2 cm.", modality="cxr")
    assert graph["backend"] == "placeholder"
    assert graph["findings"][0]["observation_code"] == "opacity"
    assert graph["findings"][0]["measurements"][0]["normalized_mm"] == 12.0


def test_tool2_cxr_rule_extracts_chinese_cxr_findings():
    graph = extract_findings("检查所见：右上肺见8mm结节影。左侧胸腔少量积液。未见气胸。", modality="cxr", backend="cxr_rule")
    by_observation = {item["observation_code"]: item for item in graph["findings"]}
    assert graph["backend"] == "cxr_rule"
    assert by_observation["nodule"]["anatomy_code"] == "right upper lobe"
    assert by_observation["nodule"]["measurements"][0]["normalized_mm"] == 8.0
    assert by_observation["effusion"]["anatomy_code"] == "left pleural"
    assert by_observation["effusion"]["severity"] == "mild"
    assert by_observation["pneumothorax"]["certainty"] == "absent"
    assert graph["coverage"] > 0


def test_tool2_non_cxr_observation_codes_are_stable_canonical_slugs():
    response = {
        "findings": [
            {
                "observation_code": "Mass lesion",
                "observation_text": "Mass lesion in left kidney",
                "anatomy_code": "left kidney",
                "location_text": "left kidney",
                "laterality": "left",
                "certainty": "present",
                "severity": None,
                "measurements": [],
                "evidence": "Mass lesion in left kidney",
                "attributes": {},
            }
        ],
        "relations": [],
    }
    graph = extract_findings(
        "FINDINGS: Mass lesion in left kidney.",
        modality="ct",
        backend="auto",
        llm_client=_RecordingClient(response),
        extractor_options={"provider": "chat_completions", "model": "test"},
        require_llm=True,
        allow_fallback=False,
    )
    assert graph["findings"][0]["observation_code"] == "mass_lesion"


def test_tool2_does_not_hide_unexpected_programming_errors():
    class BuggyClient:
        def call(self, *args, **kwargs):
            raise AssertionError("programming bug")

    with pytest.raises(AssertionError, match="programming bug"):
        extract_findings(
            "FINDINGS: opacity",
            modality="ct",
            backend="auto",
            llm_client=BuggyClient(),
            extractor_options={"provider": "chat_completions", "model": "test"},
            require_llm=True,
            allow_fallback=False,
        )


def test_tool2_hybrid_corrects_template_candidate_with_grounded_llm_output():
    report = "FINDINGS: A 6 mm spiculated nodule is present in the right upper lobe."
    response = {
        "findings": [
            {
                "observation_code": "nodule",
                "observation_text": "spiculated pulmonary nodule",
                "anatomy_code": "right upper lobe",
                "location_text": "right upper lobe",
                "laterality": "right",
                "certainty": "present",
                "severity": None,
                "measurements": [{"value": 6, "unit": "mm"}],
                "evidence": "A 6 mm spiculated nodule is present in the right upper lobe.",
                "attributes": {"morphology": "spiculated"},
            }
        ],
        "relations": [],
    }
    client = _RecordingClient(response)

    graph = extract_findings(
        report,
        modality="cxr",
        backend="auto",
        llm_client=client,
        extractor_options={"provider": "chat_completions", "model": "gpt-5.5"},
        model_role="finding_extractor",
        require_llm=True,
        allow_fallback=False,
    )

    validated = FindingGraph.model_validate(graph)
    finding = validated.findings[0]
    assert client.calls[0]["kwargs"]["provider"] == "chat_completions"
    assert client.calls[0]["kwargs"]["model"] == "gpt-5.5"
    assert '"candidate_graph"' in client.calls[0]["prompt"]
    assert validated.backend == "template_llm"
    assert finding.attributes["morphology"] == "spiculated"
    assert report[finding.source_span.start : finding.source_span.end] == finding.source_text
    assert finding.extractor.implementation_type == "template_llm_correction"
    assert finding.extractor.provider == "chat_completions"
    assert graph["metadata"]["llm_correction"]["fallback_used"] is False
    assert graph["metadata"]["llm_correction"]["candidate_backend"] == "cxr_rule"
    assert graph["metadata"]["ontology"]["version"] == "cxr-controlled-v1"
    assert graph["metadata"]["llm_correction"]["prompt_version"] == "tool2-hybrid-v2"


def test_tool2_hybrid_canonicalizes_normal_cxr_language_before_alignment():
    report = "FINDINGS: The lungs are clear. The cardiomediastinal silhouette is normal."
    response = {
        "findings": [
            {
                "observation_code": "clear lungs",
                "observation_text": "lungs are clear",
                "anatomy_code": "bilateral lungs",
                "location_text": "bilateral lungs",
                "laterality": "bilateral",
                "certainty": "present",
                "severity": None,
                "measurements": [],
                "evidence": "The lungs are clear.",
                "attributes": {},
            },
            {
                "observation_code": "normal cardiomediastinal silhouette",
                "observation_text": "cardiomediastinal silhouette is normal",
                "anatomy_code": "cardiomediastinum",
                "location_text": "cardiomediastinal silhouette",
                "laterality": "unknown",
                "certainty": "present",
                "severity": None,
                "measurements": [],
                "evidence": "The cardiomediastinal silhouette is normal.",
                "attributes": {},
            },
        ],
        "relations": [],
    }

    graph = extract_findings(
        report,
        modality="cxr",
        backend="auto",
        llm_client=_RecordingClient(response),
        extractor_options={"provider": "chat_completions", "model": "gpt-5.6-terra"},
        model_role="finding_extractor",
        require_llm=True,
        allow_fallback=False,
    )

    by_code = {item["observation_code"]: item for item in graph["findings"]}
    assert by_code["opacity"]["certainty"] == "absent"
    assert by_code["opacity"]["anatomy_code"] == "lung"
    assert by_code["cardiomegaly"]["certainty"] == "absent"
    assert by_code["cardiomegaly"]["anatomy_code"] == "heart"


def test_tool2_hybrid_retries_ungrounded_llm_evidence():
    valid = {
        "findings": [
            {
                "observation_code": "nodule",
                "observation_text": "pulmonary nodule",
                "anatomy_code": "left lower lobe",
                "location_text": "left lower lobe",
                "laterality": "left",
                "certainty": "present",
                "severity": None,
                "measurements": [{"value": 7, "unit": "mm"}],
                "evidence": "A 7 mm nodule is present in the left lower lobe.",
                "attributes": {},
            }
        ],
        "relations": [],
    }
    client = _SequenceClient(
        [
            {**valid, "findings": [{**valid["findings"][0], "evidence": "invented evidence"}]},
            valid,
        ]
    )

    graph = extract_findings(
        "FINDINGS: A 7 mm nodule is present in the left lower lobe.",
        modality="cxr",
        backend="auto",
        llm_client=client,
        extractor_options={"provider": "chat_completions", "model": "gpt-5.5"},
        max_retries=2,
        require_llm=True,
        allow_fallback=False,
    )

    assert client.call_count == 2
    assert graph["metadata"]["llm_correction"]["error_count"] == 1


def test_tool2_hybrid_strict_mode_rejects_mock_provider():
    with pytest.raises(LLMClientError, match="requires a non-mock provider"):
        extract_findings(
            "FINDINGS: A pulmonary nodule.",
            modality="cxr",
            backend="auto",
            llm_client=build_mock_client(),
            require_llm=True,
        )


def test_tool2_hybrid_fallback_is_explicit_and_preserves_template_graph():
    graph = extract_findings(
        "FINDINGS: A right upper lobe nodule.",
        modality="cxr",
        backend="auto",
        llm_client=_FailingClient(LLMClientError("provider unavailable")),
        extractor_options={"provider": "chat_completions", "model": "gpt-5.5"},
        max_retries=2,
        allow_fallback=True,
    )

    assert graph["backend"] == "cxr_rule"
    assert "llm_extraction_fallback" in graph["warnings"]
    assert graph["metadata"]["llm_correction"]["fallback_used"] is True


def test_tool2_llm_correction_preserves_placeholder_provenance():
    response = {
        "findings": [{
            "observation_code": "opacity",
            "observation_text": "opacity",
            "anatomy_code": None,
            "location_text": None,
            "laterality": "unknown",
            "certainty": "present",
            "severity": None,
            "measurements": [],
            "evidence": "no supported finding",
            "attributes": {},
        }],
        "relations": [],
    }
    graph = extract_findings(
        "FINDINGS: no supported finding",
        modality="ct",
        backend="placeholder",
        llm_client=_RecordingClient(response),
        extractor_options={"provider": "chat_completions", "model": "test"},
        require_llm=True,
        allow_fallback=False,
    )
    assert "template_candidate_had_fallback_or_placeholder" in graph["warnings"]


def test_tool3_parses_bilingual_section_headers_with_one_normalization():
    result = check_structure(
        "临床资料：咳嗽。\n检查所见：右上肺见结节。\n诊断意见：右上肺结节，建议随访。"
    )

    assert result["sections"]["clinical_history"] == "咳嗽。"
    assert result["sections"]["findings"] == "右上肺见结节。"
    assert result["sections"]["impression"] == "右上肺结节，建议随访。"
    assert result["score"] == 1.0
    assert result["warnings"] == []
    assert section_order("临床资料：咳嗽。\n检查所见：结节。\n诊断意见：建议随访。") == [
        "clinical_history",
        "findings",
        "impression",
    ]


def test_tool3_preserves_repeated_sections_in_source_order():
    result = check_structure("FINDINGS: First finding.\nFINDINGS: Second finding.\nIMPRESSION: Summary.")

    assert result["sections"]["findings"] == "First finding.\nSecond finding."


def test_tool5_normalizes_units_and_aligns_approximately():
    assert normalize_measurement_mm("1.2 cm") == 12.0
    graph_a = {"findings": [{"observation": "nodule", "location": "right lung", "severity": "mild", "measurement": "1.2 cm"}]}
    graph_b = {"findings": [{"observation": "nodule", "location": "right lung", "severity": "mild", "measurement": "13 mm"}]}
    result = align_graphs(graph_a, graph_b, tolerance_mm=5.0)
    assert len(result["approximate_match"]) == 1
    assert not result["error_candidates"]


def test_tool5_uses_candidate_reference_error_semantics():
    candidate = {
        "findings": [
            {"observation": "nodule", "location": "right lung", "severity": "mild"},
            {"observation": "opacity", "location": "left lung", "severity": "mild"},
        ]
    }
    reference = {
        "findings": [
            {"observation": "nodule", "location": "right lung", "severity": "mild"},
            {"observation": "effusion", "location": "pleural", "severity": "small"},
        ]
    }
    result = align_graphs(candidate, reference)
    error_types = [item["error_type"] for item in result["error_candidates"]]
    assert result["candidate_only"][0]["observation"] == "opacity"
    assert result["reference_only"][0]["observation"] == "effusion"
    assert error_types == ["false_finding", "omission_finding"]
    assert result["metrics"]["precision"] == 0.5
    assert result["metrics"]["recall"] == 0.5


def test_tool5_llm_audit_records_grounded_issue_without_mutating_alignment():
    candidate = {
        "findings": [
            {
                "finding_id": "f1",
                "observation_code": "nodule",
                "anatomy_code": "right upper lobe",
                "laterality": "right",
                "certainty": "present",
                "severity": "mild",
                "measurements": [],
                "source_text": "private candidate report text",
            }
        ]
    }
    reference = {
        "findings": [
            {
                "finding_id": "f1",
                "observation_code": "nodule",
                "anatomy_code": "left lower lobe",
                "laterality": "left",
                "certainty": "present",
                "severity": "mild",
                "measurements": [],
                "source_text": "private reference report text",
            }
        ]
    }
    alignment = align_graphs(candidate, reference)
    original = copy.deepcopy(alignment)
    client = _RecordingClient(
        {
            "verdict": "issues_found",
            "confidence": 0.92,
            "summary": "The deterministic pairing is clinically implausible because laterality and lobe differ.",
            "issues": [
                {
                    "issue_type": "incorrect_match",
                    "candidate_id": "candidate:f1",
                    "reference_id": "reference:f1",
                    "error_index": None,
                    "suggested_error_type": None,
                    "explanation": "These likely represent distinct nodules.",
                    "confidence": 0.95,
                }
            ],
            "error_judgements": [
                {
                    "error_index": 0,
                    "disposition": "incorrect_error_type",
                    "suggested_error_type": "other",
                    "explanation": "The deterministic pair is clinically implausible.",
                    "confidence": 0.95,
                }
            ],
        }
    )

    audit = audit_alignment(
        candidate,
        reference,
        alignment,
        llm_client=client,
        auditor_options={"provider": "chat_completions", "model": "gpt-5.5"},
        model_role="alignment_auditor",
        require_llm=True,
        allow_fallback=False,
    )

    validated = AlignmentAuditArtifact.model_validate(audit)
    assert alignment == original
    assert validated.primary_preserved is True
    assert validated.requires_adjudication is True
    assert validated.issues[0].candidate_id == "candidate:f1"
    assert validated.auditor_provenance.role == "alignment_auditor"
    assert validated.auditor_provenance.model == "gpt-5.5"
    assert "private candidate report text" not in client.calls[0]["prompt"]
    assert "private reference report text" not in client.calls[0]["prompt"]


def test_tool5_llm_adjudication_removes_complete_unsupported_error_pairs():
    candidate = {
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
    reference = {
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
    alignment = align_graphs(candidate, reference)
    assert [item["error_type"] for item in alignment["error_candidates"]] == [
        "false_finding",
        "omission_finding",
    ]
    client = _RecordingClient(
        {
            "verdict": "issues_found",
            "confidence": 0.99,
            "summary": "The two normal-lung statements are semantically equivalent.",
            "issues": [
                {
                    "issue_type": "missed_match",
                    "candidate_id": "candidate:f1",
                    "reference_id": "reference:f1",
                    "error_index": None,
                    "suggested_error_type": None,
                    "explanation": "These findings should be matched.",
                    "confidence": 0.99,
                }
            ],
            "error_judgements": [
                {
                    "error_index": 0,
                    "disposition": "unsupported",
                    "suggested_error_type": None,
                    "explanation": "Clear lungs is supported by the reference.",
                    "confidence": 0.99,
                },
                {
                    "error_index": 1,
                    "disposition": "unsupported",
                    "suggested_error_type": None,
                    "explanation": "Normal lung appearance is covered by clear lungs.",
                    "confidence": 0.99,
                },
            ],
        }
    )

    audit = audit_alignment(
        candidate,
        reference,
        alignment,
        llm_client=client,
        auditor_options={"provider": "chat_completions", "model": "gpt-5.5"},
        require_llm=True,
        allow_fallback=False,
    )

    assert audit["adjudicated_error_candidates"] == []
    assert audit["adjudication_summary"] == {
        "deterministic_error_count": 2,
        "retained_error_count": 0,
        "rejected_error_count": 2,
        "modified_error_count": 0,
        "abstained_error_count": 0,
        "complete": True,
    }


def test_tool5_chunks_large_error_sets_and_merges_complete_judgements():
    candidate = {"findings": []}
    reference = {
        "findings": [
            {
                "finding_id": f"f{index}",
                "observation_code": f"finding-{index}",
                "anatomy_code": "lungs",
                "laterality": "unknown",
                "certainty": "present",
            }
            for index in range(7)
        ]
    }
    alignment = align_graphs(candidate, reference)
    responses = []
    for indices in (range(5), range(5, 7)):
        responses.append(
            {
                "verdict": "pass",
                "confidence": 0.95,
                "summary": "All errors in this chunk are valid omissions.",
                "issues": [],
                "error_judgements": [
                    {
                        "error_index": index,
                        "disposition": "valid",
                        "suggested_error_type": None,
                        "explanation": "The reference finding is absent from the candidate.",
                        "confidence": 0.95,
                    }
                    for index in indices
                ],
            }
        )
    client = _SequenceClient(responses)

    audit = audit_alignment(
        candidate,
        reference,
        alignment,
        llm_client=client,
        auditor_options={"provider": "chat_completions", "model": "gpt-5.5"},
        max_retries=1,
        require_llm=True,
        allow_fallback=False,
    )

    assert client.call_count == 2
    assert [item["error_index"] for item in audit["error_judgements"]] == list(
        range(7)
    )
    assert audit["adjudication_summary"]["complete"] is True
    assert audit["metadata"]["chunk_count"] == 2
    assert audit["metadata"]["chunk_attempt_counts"] == [1, 1]


def test_tool5_derives_verdict_from_judgements_instead_of_retrying_conflicting_label():
    candidate = {
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
    reference = {"findings": []}
    alignment = align_graphs(candidate, reference)
    client = _RecordingClient(
        {
            "verdict": "pass",
            "confidence": 0.99,
            "summary": "The deterministic label is unsupported.",
            "issues": [],
            "error_judgements": [
                {
                    "error_index": 0,
                    "disposition": "unsupported",
                    "suggested_error_type": None,
                    "explanation": "The candidate finding should not be counted as an error.",
                    "confidence": 0.99,
                }
            ],
        }
    )

    audit = audit_alignment(
        candidate,
        reference,
        alignment,
        llm_client=client,
        auditor_options={"provider": "chat_completions", "model": "gpt-5.5"},
        max_retries=1,
        require_llm=True,
        allow_fallback=False,
    )

    assert len(client.calls) == 1
    assert audit["verdict"] == "issues_found"
    assert audit["adjudication_summary"]["rejected_error_count"] == 1


def test_tool5_does_not_accept_last_response_when_every_attempt_is_invalid():
    candidate = {
        "findings": [
            {
                "finding_id": "f1",
                "observation_code": "nodule",
                "anatomy_code": "right lung",
                "laterality": "right",
                "certainty": "present",
            }
        ]
    }
    reference = {"findings": []}
    alignment = align_graphs(candidate, reference)
    client = _RecordingClient(
        {
            "verdict": "pass",
            "confidence": 0.9,
            "summary": "Invalid because the requested error judgement is missing.",
            "issues": [],
            "error_judgements": [],
        }
    )

    with pytest.raises(LLMClientError, match="failed schema validation"):
        audit_alignment(
            candidate,
            reference,
            alignment,
            llm_client=client,
            auditor_options={"provider": "chat_completions", "model": "gpt-5.5"},
            max_retries=1,
            require_llm=True,
            allow_fallback=False,
        )


def test_tool5_llm_audit_retries_unknown_finding_references():
    candidate = {"findings": [{"finding_id": "f1", "observation": "nodule", "location": "right lung"}]}
    reference = {"findings": [{"finding_id": "f1", "observation": "nodule", "location": "right lung"}]}
    alignment = align_graphs(candidate, reference)
    invalid = {
        "verdict": "issues_found",
        "confidence": 0.8,
        "summary": "Bad reference.",
        "issues": [
            {
                "issue_type": "missed_match",
                "candidate_id": "candidate:missing",
                "reference_id": "reference:f1",
                "error_index": None,
                "suggested_error_type": None,
                "explanation": "Invalid ID.",
                "confidence": 0.8,
            }
        ],
    }
    valid = {"verdict": "pass", "confidence": 0.95, "summary": "Alignment is consistent.", "issues": []}
    client = _SequenceClient([invalid, valid])

    audit = audit_alignment(
        candidate,
        reference,
        alignment,
        llm_client=client,
        auditor_options={"provider": "chat_completions", "model": "gpt-5.5"},
        max_retries=2,
        require_llm=True,
        allow_fallback=False,
    )

    assert client.call_count == 2
    assert audit["metadata"]["attempt_count"] == 2
    assert audit["metadata"]["error_count"] == 1
    assert audit["verdict"] == "pass"


def test_tool5_retry_prompt_lists_allowed_suggested_error_types():
    candidate = {
        "findings": [
            {
                "finding_id": "f1",
                "observation_code": "opacity",
                "anatomy_code": "right lung",
                "laterality": "right",
                "certainty": "present",
            }
        ]
    }
    reference = {"findings": []}
    alignment = align_graphs(candidate, reference)
    invalid = {
        "verdict": "issues_found",
        "confidence": 0.8,
        "summary": "The error type should be changed.",
        "issues": [
            {
                "issue_type": "incorrect_error_type",
                "candidate_id": None,
                "reference_id": None,
                "error_index": 0,
                "suggested_error_type": "incorrect_certainty",
                "explanation": "The certainty is reversed.",
                "confidence": 0.8,
            }
        ],
        "error_judgements": [
            {
                "error_index": 0,
                "disposition": "valid",
                "suggested_error_type": None,
                "explanation": "The candidate finding is unsupported.",
                "confidence": 0.8,
            }
        ],
    }
    valid = {
        "verdict": "issues_found",
        "confidence": 0.9,
        "summary": "The deterministic error type is retained.",
        "issues": [],
        "error_judgements": [
            {
                "error_index": 0,
                "disposition": "valid",
                "suggested_error_type": None,
                "explanation": "The candidate finding is unsupported.",
                "confidence": 0.9,
            }
        ],
    }
    client = _PromptRecordingSequenceClient([invalid, valid])

    audit = audit_alignment(
        candidate,
        reference,
        alignment,
        llm_client=client,
        auditor_options={"provider": "chat_completions", "model": "gpt-5.6-terra"},
        max_retries=2,
        require_llm=True,
        allow_fallback=False,
    )

    assert audit["adjudication_summary"]["complete"] is True
    assert client.call_count == 2
    retry_prompt = client.prompts[1]
    for error_type in (
        "false_finding",
        "omission_finding",
        "incorrect_location",
        "incorrect_severity",
        "mismatched_finding",
        "contradiction",
        "other",
    ):
        assert error_type in retry_prompt


def test_tool5_llm_audit_strict_mode_rejects_mock_provider():
    alignment = align_graphs({"findings": []}, {"findings": []})

    with pytest.raises(LLMClientError, match="requires a non-mock provider"):
        audit_alignment(
            {"findings": []},
            {"findings": []},
            alignment,
            llm_client=build_mock_client(),
            require_llm=True,
            allow_fallback=False,
        )


def test_tool6_llm_assesses_clinical_significance_without_mutating_structure_diff():
    report_a = "FINDINGS: Clear lungs.\nIMPRESSION: No acute cardiopulmonary disease."
    report_b = "FINDINGS: Clear lungs."
    structure_diff = compare_structure(report_a, report_b)
    original = copy.deepcopy(structure_diff)
    client = _RecordingClient(
        {
            "verdict": "major_issue",
            "clinical_impact": 4,
            "confidence": 0.94,
            "summary": "The candidate omits a concise impression, reducing clinical usability.",
            "issues": [
                {
                    "issue_type": "missing_section",
                    "report_role": "candidate",
                    "section": "impression",
                    "severity": "major",
                    "explanation": "The actionable conclusion is absent.",
                    "recommended_action": "Add a concise impression with the principal conclusion.",
                }
            ],
        }
    )

    audit = assess_structure_clinical_significance(
        report_a,
        report_b,
        structure_diff,
        llm_client=client,
        assessor_options={"provider": "chat_completions", "model": "gpt-5.5"},
        model_role="structure_auditor",
        require_llm=True,
        allow_fallback=False,
    )

    validated = StructureAuditArtifact.model_validate(audit)
    assert structure_diff == original
    assert validated.primary_preserved is True
    assert validated.verdict == "major_issue"
    assert validated.issues[0].section == "impression"
    assert validated.assessor_provenance.role == "structure_auditor"
    assert validated.requires_review is True
    assert '"score_delta"' in client.calls[0]["prompt"]


def test_tool6_llm_retries_invalid_section_reference():
    report = "FINDINGS: Clear lungs.\nIMPRESSION: No acute disease."
    structure_diff = compare_structure(report, report)
    invalid = {
        "verdict": "minor_issue",
        "clinical_impact": 2,
        "confidence": 0.8,
        "summary": "Invalid section.",
        "issues": [
            {
                "issue_type": "content_placement",
                "report_role": "candidate",
                "section": "unknown_section",
                "severity": "minor",
                "explanation": "Invalid.",
                "recommended_action": "Review.",
            }
        ],
    }
    valid = {
        "verdict": "no_material_issue",
        "clinical_impact": 1,
        "confidence": 0.98,
        "summary": "No material structural difference.",
        "issues": [],
    }
    client = _SequenceClient([invalid, valid])

    audit = assess_structure_clinical_significance(
        report,
        report,
        structure_diff,
        llm_client=client,
        assessor_options={"provider": "chat_completions", "model": "gpt-5.5"},
        max_retries=2,
        require_llm=True,
        allow_fallback=False,
    )

    assert client.call_count == 2
    assert audit["verdict"] == "no_material_issue"
    assert audit["metadata"]["attempt_count"] == 2
    assert audit["metadata"]["error_count"] == 1


def test_tool6_llm_strict_mode_rejects_mock_provider():
    report = "FINDINGS: Clear lungs."
    structure_diff = compare_structure(report, report)

    with pytest.raises(LLMClientError, match="requires a non-mock provider"):
        assess_structure_clinical_significance(
            report,
            report,
            structure_diff,
            llm_client=build_mock_client(),
            require_llm=True,
            allow_fallback=False,
        )


def test_tool4_adds_hazard_levels():
    result = evaluate_hazards([{"error_type": "omission_finding"}], llm_client=build_mock_client())
    assert result["errors"][0]["hazard_level"] == 4
    assert result["metadata"]["backend"] == "mock_judge"
    assert result["metadata"]["provider"] == "mock"
    assert result["metadata"]["model"]


def test_tool4_returns_versioned_hazard_result_contract():
    result = evaluate_hazards(
        [
            {
                "error_type": "omission_finding",
                "reference": {
                    "finding_id": "f1",
                    "observation_code": "nodule",
                    "observation_text": "pulmonary nodule",
                },
            }
        ],
        llm_client=build_mock_client(),
        model_role="hazard_primary",
    )

    validated = HazardResult.model_validate(result)

    assert validated.schema_version == "2.0"
    assert validated.artifact_type == "hazard_result"
    assert validated.provenance.implementation_type == "mock_judge"
    assert validated.provenance.role == "hazard_primary"
    assert validated.errors[0].reference["finding_id"] == "f1"


def test_tool4_retries_invalid_judge_json_and_records_provenance():
    client = _SequenceClient(
        [
            "not json",
            {
                "errors": [
                    {
                        "error_type": "omission_finding",
                        "hazard_level": 9,
                        "explanation": "Potential delayed care.",
                        "recommended_action": "radiologist_review",
                    }
                ]
            },
        ]
    )

    result = evaluate_hazards([{"error_type": "omission_finding", "finding": "nodule"}], llm_client=client, max_retries=2)

    assert client.call_count == 2
    assert result["metadata"]["backend"] == "llm_judge"
    assert result["metadata"]["fallback_used"] is False
    assert result["metadata"]["attempt_count"] == 2
    assert result["errors"][0]["hazard_level"] == 5
    assert result["errors"][0]["recommended_action"] == "radiologist_review"
    assert "Potential delayed care" in result["errors"][0]["explanation"]


def test_tool4_falls_back_when_judge_schema_is_invalid():
    client = _SequenceClient(["not json", {"wrong": []}])

    result = evaluate_hazards([{"error_type": "incorrect_severity"}], llm_client=client, max_retries=2)

    assert client.call_count == 2
    assert result["metadata"]["backend"] == "deterministic_fallback"
    assert result["metadata"]["fallback_used"] is True
    assert result["metadata"]["attempt_count"] == 2
    assert result["metadata"]["judge_error_count"] == 2
    assert result["errors"][0]["hazard_level"] == 2
    assert result["errors"][0]["recommended_action"] == "review_if_relevant"


def test_tool4_falls_back_when_external_judge_call_fails():
    client = _FailingClient(RuntimeError("upstream timeout with no secret material"))

    result = evaluate_hazards(
        [{"error_type": "false_finding", "finding": {"observation": "nodule"}}],
        llm_client=client,
        max_retries=2,
        model_role="hazard_primary",
        judge_options={
            "provider": "chat_completions",
            "model": "gpt-5.5",
            "base_url": "https://www.DMXAPI.cn/v1",
        },
    )

    assert client.call_count == 2
    assert result["metadata"]["backend"] == "deterministic_fallback"
    assert result["metadata"]["fallback_used"] is True
    assert result["metadata"]["judge_error_count"] == 2
    assert "RuntimeError" in result["metadata"]["judge_errors"][0]
    assert result["errors"][0]["hazard_level"] == 3


def test_tool4_retries_incomplete_judge_output_and_preserves_candidate_evidence():
    candidates = [
        {"error_type": "false_finding", "finding": "nodule", "location": "right upper lobe"},
        {"error_type": "omission_finding", "finding": "effusion", "location": "left pleural"},
    ]
    client = _SequenceClient(
        [
            {"errors": [{"error_type": "false_finding", "hazard_level": 3, "explanation": "overcall"}]},
            {
                "errors": [
                    {"error_type": "false_finding", "hazard_level": 3, "explanation": "overcall"},
                    {"error_type": "omission_finding", "hazard_level": 4, "explanation": "missed effusion"},
                ]
            },
        ]
    )

    result = evaluate_hazards(candidates, llm_client=client, max_retries=2)

    assert client.call_count == 2
    assert result["metadata"]["backend"] == "llm_judge"
    assert result["errors"][0]["finding"] == "nodule"
    assert result["errors"][0]["location"] == "right upper lobe"
    assert result["errors"][1]["finding"] == "effusion"
    assert result["errors"][1]["location"] == "left pleural"


def test_tool4_uses_role_route_and_sends_only_minimal_structured_evidence():
    client = _RecordingClient(
        {
            "errors": [
                {
                    "error_type": "omission_finding",
                    "hazard_level": 4,
                    "explanation": "May delay treatment.",
                    "recommended_action": "radiologist_review",
                }
            ]
        }
    )
    role = ModelRoleConfig(
        provider="chat_completions",
        model="gpt-5.5",
        api_key_env="DMX_API_KEY",
        base_url="https://www.DMXAPI.cn/v1",
        max_retries=2,
        timeout_sec=120,
    )
    candidates = [
        {
            "error_type": "omission_finding",
            "finding": "nodule",
            "location": "right upper lobe",
            "severity": "small",
            "measurement": "8 mm",
            "certainty": "present",
            "text": "Patient Jane Doe has an 8 mm nodule.",
            "reference": {"observation": "nodule", "raw_text": "Jane Doe MRN 123"},
            "candidate": {"observation": "none", "source_path": "/private/case.dcm"},
        }
    ]

    result = evaluate_hazards(
        candidates,
        llm_client=client,
        max_retries=3,
        model_role="hazard_primary",
        judge_options=role.as_call_options(),
    )

    prompt = client.calls[0]["prompt"]
    assert "omission_finding" in prompt
    assert "right upper lobe" in prompt
    assert "Jane Doe" not in prompt
    assert "MRN 123" not in prompt
    assert "/private/case.dcm" not in prompt
    assert client.calls[0]["kwargs"]["provider"] == "chat_completions"
    assert client.calls[0]["kwargs"]["base_url"] == "https://www.DMXAPI.cn/v1"
    assert result["metadata"]["role"] == "hazard_primary"
    assert result["metadata"]["provider"] == "chat_completions"
    assert result["metadata"]["model"] == "gpt-5.5"
    assert result["metadata"]["endpoint_host"] == "www.dmxapi.cn"
    assert result["errors"][0]["reference"]["raw_text"] == "Jane Doe MRN 123"


def test_tool4_minimal_payload_reads_canonical_v2_finding_fields():
    client = _RecordingClient(
        {
            "errors": [
                {
                    "error_type": "omission_finding",
                    "hazard_level": 4,
                    "explanation": "May delay treatment.",
                    "recommended_action": "radiologist_review",
                }
            ]
        }
    )
    candidates = [
        {
            "error_type": "omission_finding",
            "reference": {
                "finding_id": "f1",
                "observation_code": "nodule",
                "observation_text": "pulmonary nodule",
                "anatomy_code": "right upper lobe",
                "location_text": "right upper lobe",
                "severity": "mild",
                "certainty": "present",
                "measurements": [{"value": 8.0, "unit": "mm", "normalized_mm": 8.0}],
                "source_text": "private source text must not be sent",
            },
        }
    ]

    evaluate_hazards(candidates, llm_client=client)

    prompt = client.calls[0]["prompt"]
    assert "pulmonary nodule" in prompt
    assert "right upper lobe" in prompt
    assert "8 mm" in prompt
    assert "private source text" not in prompt


def test_tool4_strict_mode_rejects_mock_provider():
    with pytest.raises(LLMClientError, match="requires a non-mock provider"):
        evaluate_hazards(
            [{"error_type": "omission_finding", "finding": "nodule"}],
            llm_client=build_mock_client(),
            require_llm=True,
            allow_fallback=False,
        )


def test_tool4_strict_mode_calls_llm_for_empty_error_set():
    client = _RecordingClient({"errors": []})

    result = evaluate_hazards(
        [],
        llm_client=client,
        model_role="hazard_primary",
        judge_options={"provider": "chat_completions", "model": "gpt-5.5"},
        require_llm=True,
        allow_fallback=False,
    )

    assert len(client.calls) == 1
    assert result["errors"] == []
    assert result["provenance"]["implementation_type"] == "llm_judge"
    assert result["provenance"]["fallback_used"] is False


def test_tool4_preserves_t5_alignment_adjudication_provenance():
    client = _RecordingClient(
        {
            "errors": [
                {
                    "error_type": "omission_finding",
                    "hazard_level": 3,
                    "explanation": "The retained omission may affect follow-up.",
                    "recommended_action": "radiologist_review",
                    "confidence": 0.88,
                    "evidence_ids": ["e1"],
                    "abstain": False,
                }
            ]
        }
    )
    candidates = [
        {
            "error_type": "omission_finding",
            "reference": {"observation_code": "nodule"},
            "alignment_error_index": 4,
            "alignment_audit_judgement": {
                "error_index": 4,
                "disposition": "valid",
                "effective_disposition": "valid",
                "explanation": "No semantically equivalent candidate finding exists.",
                "confidence": 0.94,
                "minimum_confidence": 0.8,
            },
        }
    ]

    result = evaluate_hazards(
        candidates,
        llm_client=client,
        model_role="hazard_primary",
        judge_options={"provider": "chat_completions", "model": "gpt-5.5"},
        require_llm=True,
        allow_fallback=False,
    )

    assert result["errors"][0]["alignment_error_index"] == 4
    assert result["errors"][0]["alignment_audit_judgement"]["disposition"] == "valid"
    assert '"alignment_error_index": 4' in client.calls[0]["prompt"]


def test_tool4_third_adjudicator_resolves_disagreement_and_hash_binds_inputs():
    candidates = [{"error_type": "omission_finding", "observation": "nodule"}]
    primary = evaluate_hazards(
        candidates,
        llm_client=_RecordingClient(
            {
                "errors": [
                    {
                        "error_type": "omission_finding",
                        "hazard_level": 4,
                        "explanation": "Potentially important omission.",
                        "recommended_action": "radiologist_review",
                        "confidence": 0.9,
                        "evidence_ids": ["e1"],
                        "abstain": False,
                    }
                ]
            }
        ),
        model_role="hazard_primary",
        judge_options={"provider": "chat_completions", "model": "gpt-5.6-terra"},
        require_llm=True,
        allow_fallback=False,
    )
    review = review_hazards(
        primary,
        candidates,
        llm_client=_RecordingClient(
            {
                "errors": [
                    {
                        "error_type": "omission_finding",
                        "hazard_level": 2,
                        "explanation": "Limited clinical impact.",
                        "recommended_action": "review_if_relevant",
                        "confidence": 0.8,
                        "evidence_ids": ["e1"],
                        "abstain": False,
                    }
                ]
            }
        ),
        model_role="hazard_reviewer",
        judge_options={"provider": "chat_completions", "model": "claude-opus-4-8"},
        require_llm=True,
        allow_fallback=False,
    )
    adjudicator = _RecordingClient(
        {
            "decisions": [
                {
                    "error_index": 0,
                    "error_type": "omission_finding",
                    "hazard_level": 3,
                    "recommended_action": "radiologist_review",
                    "explanation": "Intermediate risk is best supported by the evidence.",
                    "confidence": 0.86,
                    "evidence_ids": ["d1"],
                    "abstain": False,
                }
            ]
        }
    )

    artifact = adjudicate_hazard_disagreements(
        primary,
        review,
        candidates,
        llm_client=adjudicator,
        model_role="hazard_adjudicator",
        adjudicator_options={
            "provider": "chat_completions",
            "model": "gpt-5.6-terra-ultra",
        },
        require_llm=True,
        allow_fallback=False,
    )

    validated = HazardAdjudicationArtifact.model_validate(artifact)
    assert len(adjudicator.calls) == 1
    assert validated.decisions[0].hazard_level == 3
    assert validated.decisions[0].primary_hazard_level == 4
    assert validated.decisions[0].reviewer_hazard_level == 2
    assert validated.adjudicator_provenance.model == "gpt-5.6-terra-ultra"
    assert validated.primary_preserved is True
    assert validated.reviewer_preserved is True
    assert validated.clinical_validation_required is True


def test_tool4_strict_mode_raises_instead_of_using_template_fallback():
    client = _SequenceClient(["not json", {"wrong": []}])

    with pytest.raises(LLMClientError, match="failed schema validation after 2 attempts"):
        evaluate_hazards(
            [{"error_type": "omission_finding", "finding": "nodule"}],
            llm_client=client,
            max_retries=2,
            judge_options={"provider": "chat_completions", "model": "gpt-5.5"},
            require_llm=True,
            allow_fallback=False,
        )

    assert client.call_count == 2


def test_tool4_reviewer_records_disagreement_without_overwriting_primary():
    candidates = [{"error_type": "omission_finding", "finding": "pulmonary nodule", "location": "right lung"}]
    primary = evaluate_hazards(
        candidates,
        llm_client=_RecordingClient(
            {
                "errors": [
                    {
                        "error_type": "omission_finding",
                        "hazard_level": 4,
                        "explanation": "May delay cancer workup.",
                        "recommended_action": "radiologist_review",
                        "confidence": 0.9,
                        "evidence_ids": ["e1"],
                        "abstain": False,
                    }
                ]
            }
        ),
        model_role="hazard_primary",
        judge_options={"provider": "chat_completions", "model": "gpt-5.5"},
        require_llm=True,
        allow_fallback=False,
    )

    review = review_hazards(
        primary,
        candidates,
        llm_client=_RecordingClient(
            {
                "errors": [
                    {
                        "error_type": "omission_finding",
                        "hazard_level": 2,
                        "explanation": "Low near-term clinical impact.",
                        "recommended_action": "review_if_relevant",
                        "confidence": 0.8,
                        "evidence_ids": ["e1"],
                        "abstain": False,
                    }
                ]
            }
        ),
        max_retries=2,
        model_role="hazard_reviewer",
        judge_options={"provider": "chat_completions", "model": "claude-opus-4-6"},
        require_llm=True,
    )

    validated = HazardReviewArtifact.model_validate(review)
    assert primary["errors"][0]["hazard_level"] == 4
    assert validated.reviewer_result.errors[0].hazard_level == 2
    assert validated.reviewer_result.provenance.role == "hazard_reviewer"
    assert validated.primary_preserved is True
    assert validated.requires_adjudication is True
    assert validated.disagreements[0].primary_hazard_level == 4
    assert validated.disagreements[0].reviewer_hazard_level == 2
    assert validated.disagreements[0].level_delta == 2
    assert validated.agreement_summary["exact_agreement_count"] == 0
    assert len(validated.primary_result_sha256) == 64


def test_tool8_mock_fallback_returns_report_when_no_local_generator():
    cfg = AppConfig(generator=GeneratorConfig(cloud_fallback_enabled=True, default_models=[], local_models=[]))
    reports = generate_reports("dummy.dcm", "cxr", config=cfg, llm_client=build_mock_client())
    assert len(reports) == 1
    assert reports[0].source == "mock_fallback"
    assert "mock_fallback_used" in reports[0].warnings
    assert reports[0].report


def test_tool8_local_vlm_fallback_is_marked_as_local():
    cfg = AppConfig(
        llm=LLMConfig(provider="local_hf_vlm", model="qwen3-vl-4b"),
        generator=GeneratorConfig(cloud_fallback_enabled=True, default_models=[], local_models=[]),
    )
    reports = generate_reports("image.png", "ct", body_part="head", config=cfg, llm_client=build_mock_client())
    assert reports[0].source == "local_vlm_fallback"
    assert "local_vlm_fallback_used" in reports[0].warnings
    assert reports[0].metadata["fallback_provider"] == "local_hf_vlm"


def test_tool8_openai_fallback_is_marked_as_cloud():
    cfg = AppConfig(
        llm=LLMConfig(provider="openai", model="gpt-test"),
        generator=GeneratorConfig(cloud_fallback_enabled=True, default_models=[], local_models=[]),
    )
    reports = generate_reports("image.png", "ct", body_part="head", config=cfg, llm_client=build_mock_client())
    assert reports[0].source == "cloud_fallback"
    assert "cloud_fallback_used" in reports[0].warnings
    assert reports[0].metadata["fallback_provider"] == "openai"
    assert reports[0].metadata["fallback_used"] is True


def test_quality_gate_allows_followup_ct_recommendation_for_cxr():
    result = check_generation_quality(
        "FINDINGS: Abdominal radiograph is unremarkable. IMPRESSION: Consider CT if symptoms persist.",
        modality="cxr",
        body_part="abdomen",
    )
    assert result["passed"] is True


def test_quality_gate_allows_example_ct_in_followup_recommendation_for_cxr():
    result = check_generation_quality(
        "IMPRESSION: Normal abdomen. Recommendation: Consider further imaging (e.g., CT) if symptoms persist.",
        modality="cxr",
        body_part="abdomen",
    )
    assert result["passed"] is True


def test_quality_gate_blocks_current_ct_label_for_cxr():
    result = check_generation_quality(
        "FINDINGS: Computed tomography of the abdomen shows bowel obstruction.",
        modality="cxr",
        body_part="abdomen",
    )
    assert result["passed"] is False
    assert "modality_mismatch" in result["warnings"]


def test_quality_gate_allows_chinese_followup_ct_recommendation_for_cxr():
    result = check_generation_quality(
        "检查所见：腹部立位片未见膈下游离气体。诊断印象：建议结合临床，必要时行腹部CT进一步评估。",
        modality="cxr",
        body_part="abdomen",
    )
    assert result["passed"] is True


def test_quality_gate_blocks_chinese_chest_report_for_head_ct():
    result = check_generation_quality(
        "检查部位：胸部CT平扫。检查所见：双肺多发结节，右肺上叶实变。",
        modality="ct",
        body_part="head",
    )
    assert result["passed"] is False
    assert "body_part_mismatch" in result["warnings"]


def test_quality_gate_allows_incidental_lung_base_mention_for_abdomen():
    result = check_generation_quality(
        "FINDINGS: Abdominal gas pattern is nonobstructive. Lung fields appear clear at the bases.",
        modality="cxr",
        body_part="abdomen",
    )
    assert result["passed"] is True


def test_tool9_selects_top_k():
    ranked = select_top_k(
        [
            {"model": "a", "composite_inputs": {"likert_mean": 2, "structure_score": 0.1, "finding_coverage": 0.1}},
            {"model": "b", "composite_inputs": {"likert_mean": 5, "structure_score": 1.0, "finding_coverage": 1.0}},
        ],
        top_k=1,
    )
    assert ranked[0]["model"] == "b"
    assert ranked[0]["rank"] == 1


def test_tool9_normalizes_likert_five_point_scale_to_zero_one():
    ranked = select_top_k([{"model": "a", "composite_inputs": {"likert_mean": 1}}], top_k=1)
    assert ranked[0]["metrics"]["likert_mean"] == 0.0


def test_tool9_excludes_fallback_rows_from_ranking():
    ranked = select_top_k(
        [
            {"model": "real", "composite_inputs": {"likert_mean": 4}, "metadata": {"fallback_used": False}},
            {"model": "fallback", "composite_inputs": {"likert_mean": 5}, "metadata": {"fallback_used": True}},
        ],
        top_k=2,
    )
    assert [row["model"] for row in ranked] == ["real"]


def test_tool1_can_record_retest_consistency_without_replacing_primary_score():
    class StableClient:
        def __init__(self):
            self.calls = 0

        def call(self, *args, **kwargs):
            self.calls += 1
            return json.dumps(_valid_likert_payload(), ensure_ascii=False)

    client = StableClient()
    result = evaluate_likert(
        "FINDINGS: stable. IMPRESSION: stable.",
        llm_client=client,
        require_llm=True,
        allow_fallback=False,
        consistency_runs=2,
    )
    assert client.calls == 2
    assert result["_metadata"]["consistency_runs"] == 2
    assert result["_metadata"]["consistency_exact"] is True


class _SequenceClient:
    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0

    def call(self, prompt: str, image_path: str | None = None, **kwargs):
        self.call_count += 1
        response = self.responses[min(self.call_count - 1, len(self.responses) - 1)]
        if isinstance(response, str):
            return response
        return json.dumps(response, ensure_ascii=False)


class _RecordingClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def call(self, prompt: str, image_path: str | None = None, **kwargs):
        self.calls.append({"prompt": prompt, "image_path": image_path, "kwargs": kwargs})
        return json.dumps(self.response, ensure_ascii=False)


class _PromptRecordingSequenceClient(_SequenceClient):
    def __init__(self, responses):
        super().__init__(responses)
        self.prompts = []

    def call(self, prompt: str, image_path: str | None = None, **kwargs):
        self.prompts.append(prompt)
        return super().call(prompt, image_path=image_path, **kwargs)


class _FailingClient:
    def __init__(self, error):
        self.error = error
        self.call_count = 0

    def call(self, prompt: str, image_path: str | None = None, **kwargs):
        self.call_count += 1
        raise self.error
