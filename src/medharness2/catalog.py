from __future__ import annotations

from dataclasses import asdict
from typing import Any
from urllib.parse import urlparse

from medharness2.config import AppConfig, load_config
from medharness2.generators.registry import (
    ReportGeneratorRegistry,
    load_legacy_status_export,
)


TOOL_CATALOG: list[dict[str, Any]] = [
    {
        "id": "tool1_likert",
        "name": "Likert report evaluation",
        "inputs": ["report_text", "image_path"],
        "outputs": ["likert", "judge_provenance"],
        "implementation_type": "strict_llm_judge",
        "implementation": "Role-routed LLM five-dimension rubric judge with complete-schema validation, retry, provenance, and strict no-mock/no-fallback production mode",
        "medical_model_required": False,
    },
    {
        "id": "tool2_extract",
        "name": "Finding extraction",
        "inputs": ["report_text", "modality"],
        "outputs": ["finding_graph"],
        "implementation_type": "template_llm_hybrid",
        "implementation": "Registry-based CXR/CT/MRI plugins produce a deterministic template candidate, followed by grounded LLM correction with evidence spans, measurement validation, FindingGraph schema validation, retry, and provenance",
        "medical_model_required": True,
    },
    {
        "id": "tool3_structure",
        "name": "Report structure check",
        "inputs": ["report_text"],
        "outputs": ["sections", "structure_score"],
        "implementation_type": "deterministic_code",
        "implementation": "Section parser and weighted score",
        "medical_model_required": False,
    },
    {
        "id": "tool4_hazard",
        "name": "Error hazard evaluation",
        "inputs": ["error_candidates"],
        "outputs": ["hazard_result", "hazard_review"],
        "implementation_type": "template_llm_with_independent_review",
        "implementation": "Deterministic hazard priors plus strict primary LLM schema retry, evidence-preserving provenance, and an independent reviewer that emits a hash-linked disagreement artifact without overwriting primary judgements",
        "medical_model_required": False,
    },
    {
        "id": "tool5_align",
        "name": "Cross-report graph alignment",
        "inputs": ["candidate_graph", "reference_graph"],
        "outputs": ["alignment", "error_candidates", "alignment_audit"],
        "implementation_type": "deterministic_with_llm_audit",
        "implementation": "maximum-weight bipartite finding matching with clinical attribute comparison, followed by a strict hash-linked LLM audit that cannot mutate the deterministic alignment",
        "medical_model_required": False,
    },
    {
        "id": "tool6_structure_diff",
        "name": "Structure difference",
        "inputs": ["report_a", "report_b"],
        "outputs": ["structure_diff", "structure_audit"],
        "implementation_type": "deterministic_with_llm_assessment",
        "implementation": "Shared bilingual section parsing with presence, length, ordering, and score deltas, followed by a strict LLM assessment of clinical communication impact",
        "medical_model_required": False,
    },
    {
        "id": "tool7_modality",
        "name": "Modality recognition",
        "inputs": ["image_path"],
        "outputs": ["modality"],
        "implementation_type": "dicom_rules_or_vlm",
        "implementation": "DICOM header and suffix rules; optional VLM fallback",
        "medical_model_required": False,
    },
    {
        "id": "tool8_generate",
        "name": "2D/3D report generation",
        "inputs": ["image_path", "modality", "body_part", "reference_report"],
        "outputs": ["generated_reports"],
        "implementation_type": "local_model_or_fallback",
        "implementation": "ReportGeneratorRegistry local models first; LLM/VLM fallback if enabled",
        "medical_model_required": True,
    },
    {
        "id": "tool9_rank",
        "name": "Top-K report selection",
        "inputs": ["generated_evaluations"],
        "outputs": ["rankings"],
        "implementation_type": "deterministic_code",
        "implementation": "Weighted normalized composite score",
        "medical_model_required": False,
    },
    {
        "id": "tool10_modelwise",
        "name": "Modelwise weighted metrics",
        "inputs": ["model_metric_rows"],
        "outputs": ["modelwise_metrics"],
        "implementation_type": "deterministic_code",
        "implementation": "Weighted mean over numeric metrics",
        "medical_model_required": False,
    },
    {
        "id": "tool11_hazardwise",
        "name": "Hazardwise weighted metrics",
        "inputs": ["hazard_rows"],
        "outputs": ["hazard_weighted_rows"],
        "implementation_type": "deterministic_code",
        "implementation": "Hazard-type and level weight lookup",
        "medical_model_required": False,
    },
    {
        "id": "tool12_statistics",
        "name": "Statistics",
        "inputs": ["metric_rows"],
        "outputs": ["mean", "std", "ci", "percentile"],
        "implementation_type": "deterministic_code",
        "implementation": "Python statistics over numeric fields",
        "medical_model_required": False,
    },
]


WORKFLOW_STAGE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "workflow.preflight",
        "name": "Sample preflight",
        "category": "validation",
        "development_status": "implemented_v1",
        "implementation_type": "workflow_validation",
        "implementation": "Builds a route plan, checks OCR/provider readiness, and reports blockers before a costly run.",
        "inputs": [
            {"name": "sample_root", "format": "directory", "required": True},
            {"name": "model_keys", "format": "list[str]", "required": False},
            {"name": "require_real_ocr", "format": "bool", "required": False},
        ],
        "outputs": [
            {"name": "preflight", "format": "json", "path_template": "<OUTPUT>.json"},
            {"name": "route_plan", "format": "json", "path_template": "<OUTPUT_STEM>_route_plan/route_plan.json"},
            {"name": "run_registry", "format": "json", "path_template": "<OUTPUT_DIR>/run_registry.json"},
        ],
        "model_policy": {
            "general_model": "optional_for_json_judgement",
            "medical_specialist_model": "preferred_for_ocr_or_vlm_preflight",
            "local_model": "preferred_when_available",
            "api_model": "acceptable_for_ocr_or_judge_when_real_model_required",
        },
    },
    {
        "id": "workflow.sample-data",
        "name": "Sample data preparation",
        "category": "data",
        "development_status": "implemented_v1",
        "implementation_type": "data_preparation",
        "implementation": "Builds manifest rows, prepares derived image assets, and optionally runs OCR.",
        "inputs": [
            {"name": "sample_root", "format": "directory", "required": True},
            {"name": "limit", "format": "int", "required": False},
            {"name": "run_ocr", "format": "bool", "required": False},
        ],
        "outputs": [
            {"name": "manifest", "format": "jsonl", "path_template": "<RUN>/manifest.jsonl"},
            {"name": "summary", "format": "json", "path_template": "<RUN>/summary.json"},
            {"name": "derived_assets", "format": "files", "path_template": "<RUN>/derived/"},
            {"name": "run_registry", "format": "json", "path_template": "<RUN>/run_registry.json"},
        ],
        "model_policy": {
            "general_model": "not_required",
            "medical_specialist_model": "preferred_for_real_ocr",
            "local_model": "preferred_for_private_data",
            "api_model": "acceptable_for_ocr_when_policy_allows",
        },
    },
    {
        "id": "workflow.sample-full",
        "name": "End-to-end sample run",
        "category": "orchestration",
        "development_status": "implemented_v1",
        "implementation_type": "workflow_orchestration",
        "implementation": "Runs sample-data, batch-readers, department comparison, validation, and run summary writing.",
        "inputs": [
            {"name": "sample_root", "format": "directory", "required": True},
            {"name": "output_dir", "format": "directory", "required": True},
            {"name": "expected_cases", "format": "int", "required": False},
            {"name": "model_keys", "format": "list[str]", "required": False},
            {"name": "model_sources", "format": "list[str]", "required": False},
        ],
        "outputs": [
            {"name": "manifest", "format": "jsonl", "path_template": "<RUN>/manifest.jsonl"},
            {"name": "workflow2", "format": "json", "path_template": "<RUN>/workflow2.json"},
            {"name": "workflow3", "format": "json", "path_template": "<RUN>/workflow3.json"},
            {"name": "run_summary", "format": "json", "path_template": "<RUN>/run_summary.json"},
            {"name": "run_registry", "format": "json", "path_template": "<RUN>/run_registry.json"},
        ],
        "model_policy": {
            "general_model": "acceptable_for_text_judgement_or_fallback",
            "medical_specialist_model": "preferred_for_generation",
            "local_model": "preferred_for_fresh_report_generation",
            "api_model": "fallback_when_local_route_unavailable",
        },
    },
    {
        "id": "workflow.sample-full.dry-run",
        "name": "End-to-end route planning",
        "category": "routing",
        "development_status": "implemented_v1",
        "implementation_type": "routing_plan",
        "implementation": "Plans compatible local and fallback model routes without writing workflow2/3 outputs.",
        "inputs": [
            {"name": "sample_root", "format": "directory", "required": True},
            {"name": "model_keys", "format": "list[str]", "required": False},
            {"name": "model_sources", "format": "list[str]", "required": False},
        ],
        "outputs": [
            {"name": "route_plan", "format": "json", "path_template": "<RUN>/route_plan.json"},
            {"name": "raw_manifest", "format": "jsonl", "path_template": "<RUN>/route_plan.manifest.raw.jsonl"},
            {"name": "run_registry", "format": "json", "path_template": "<RUN>/run_registry.json"},
        ],
        "model_policy": {
            "general_model": "not_required",
            "medical_specialist_model": "used_for_route_selection_metadata",
            "local_model": "preferred_when_compatible",
            "api_model": "not_required",
        },
    },
    {
        "id": "workflow.single-case",
        "name": "Single case evaluation",
        "category": "evaluation",
        "development_status": "implemented_v1",
        "implementation_type": "workflow_orchestration",
        "implementation": "Evaluates a human report, generates candidate reports, ranks top-k, and runs pairwise comparison.",
        "inputs": [
            {"name": "report", "format": "txt/pdf-derived text", "required": True},
            {"name": "image", "format": "image_or_volume_path", "required": True},
            {"name": "modality", "format": "string", "required": False},
            {"name": "top_n", "format": "int", "required": False},
        ],
        "outputs": [
            {"name": "workflow1_result", "format": "json", "path_template": "<OUTPUT>.json"},
            {"name": "run_registry", "format": "json", "path_template": "<OUTPUT_DIR>/run_registry.json"},
        ],
        "model_policy": {
            "general_model": "acceptable_for_judgement",
            "medical_specialist_model": "preferred_for_report_generation",
            "local_model": "preferred_when_modality_supported",
            "api_model": "fallback_or_judge",
        },
    },
    {
        "id": "workflow.batch-readers",
        "name": "Batch reader evaluation",
        "category": "evaluation",
        "development_status": "implemented_v1",
        "implementation_type": "batch_workflow",
        "implementation": "Runs single-case workflow over a manifest and aggregates per-reader metrics.",
        "inputs": [
            {"name": "manifest", "format": "jsonl", "required": True},
            {"name": "model_keys", "format": "list[str]", "required": False},
            {"name": "model_sources", "format": "list[str]", "required": False},
        ],
        "outputs": [
            {"name": "workflow2", "format": "json", "path_template": "<RUN>/workflow2.json"},
            {"name": "case_outputs", "format": "json files", "path_template": "<RUN>/workflow2_cases/*.json"},
            {"name": "run_registry", "format": "json", "path_template": "<RUN>/run_registry.json"},
        ],
        "model_policy": {
            "general_model": "acceptable_for_judgement",
            "medical_specialist_model": "preferred_for_generation",
            "local_model": "preferred_for_batch_generation",
            "api_model": "fallback_when_local_route_unavailable",
        },
    },
    {
        "id": "workflow.department",
        "name": "Department comparison",
        "category": "statistics",
        "development_status": "implemented_v1",
        "implementation_type": "deterministic_statistics",
        "implementation": "Computes reader percentiles and model group statistics from workflow2.",
        "inputs": [{"name": "workflow2", "format": "json", "required": True}],
        "outputs": [
            {"name": "workflow3", "format": "json", "path_template": "<RUN>/workflow3.json"},
            {"name": "run_registry", "format": "json", "path_template": "<RUN>/run_registry.json"},
        ],
        "model_policy": {
            "general_model": "not_required",
            "medical_specialist_model": "not_required",
            "local_model": "not_required",
            "api_model": "not_required",
        },
    },
    {
        "id": "workflow.merge-batches",
        "name": "Merge batch outputs",
        "category": "orchestration",
        "development_status": "implemented_v1",
        "implementation_type": "merge_and_validate",
        "implementation": "Merges sub-batch workflow2 outputs, copies case JSONs, rebuilds workflow3, and validates coverage.",
        "inputs": [
            {"name": "batch_results", "format": "list[json]", "required": True},
            {"name": "manifest", "format": "jsonl", "required": False},
            {"name": "expected_cases", "format": "int", "required": False},
        ],
        "outputs": [
            {"name": "workflow2", "format": "json", "path_template": "<RUN>/workflow2.json"},
            {"name": "workflow3", "format": "json", "path_template": "<RUN>/workflow3.json"},
            {"name": "run_summary", "format": "json", "path_template": "<RUN>/run_summary.json"},
            {"name": "run_registry", "format": "json", "path_template": "<RUN>/run_registry.json"},
        ],
        "model_policy": {
            "general_model": "not_required",
            "medical_specialist_model": "not_required",
            "local_model": "not_required",
            "api_model": "not_required",
        },
    },
    {
        "id": "workflow.analyze-run",
        "name": "Run analysis tables",
        "category": "analysis",
        "development_status": "implemented_v1",
        "implementation_type": "deterministic_analysis",
        "implementation": "Reads workflow outputs and emits CSV/Markdown/JSON summaries for audit and figures.",
        "inputs": [{"name": "run_dir", "format": "directory", "required": True}],
        "outputs": [
            {"name": "analysis_summary", "format": "json+md", "path_template": "<RUN>/analysis/analysis_summary.*"},
            {"name": "analysis_tables", "format": "csv", "path_template": "<RUN>/analysis/*.csv"},
            {"name": "run_registry", "format": "json", "path_template": "<RUN>/run_registry.json"},
        ],
        "model_policy": {
            "general_model": "not_required",
            "medical_specialist_model": "not_required",
            "local_model": "not_required",
            "api_model": "not_required",
        },
    },
    {
        "id": "workflow.reevaluate-run",
        "name": "Low-cost run reevaluation",
        "category": "evaluation",
        "development_status": "implemented_v1",
        "implementation_type": "deterministic_reevaluation",
        "implementation": (
            "Recomputes Workflow 1/2/3 evaluation artifacts from an existing run; "
            "reuses existing generated_reports and does not call report generation models."
        ),
        "inputs": [
            {"name": "source_run_dir", "format": "directory", "required": True},
            {"name": "output_dir", "format": "directory", "required": True},
            {"name": "config", "format": "yaml", "required": False},
        ],
        "outputs": [
            {"name": "workflow2", "format": "json", "path_template": "<REEVAL_RUN>/workflow2.json"},
            {"name": "workflow3", "format": "json", "path_template": "<REEVAL_RUN>/workflow3.json"},
            {"name": "case_outputs", "format": "json files", "path_template": "<REEVAL_RUN>/workflow2_cases/*.json"},
            {"name": "run_summary", "format": "json", "path_template": "<REEVAL_RUN>/run_summary.json"},
            {"name": "run_registry", "format": "json", "path_template": "<REEVAL_RUN>/run_registry.json"},
        ],
        "model_policy": {
            "general_model": "not_required",
            "medical_specialist_model": "not_required",
            "local_model": "not_required",
            "api_model": "not_required",
        },
    },
    {
        "id": "workflow.validate-run",
        "name": "Run validation",
        "category": "validation",
        "development_status": "implemented_v1",
        "implementation_type": "deterministic_validation",
        "implementation": (
            "Checks manifest, workflow counts, OCR provenance, failures, expected case count, core case artifacts, "
            "optional alignment, hazard-review, and structure-audit contracts, and their canonical SHA-256 bindings."
        ),
        "inputs": [
            {"name": "run_dir", "format": "directory", "required": True},
            {"name": "expected_cases", "format": "int", "required": False},
            {"name": "require_real_ocr", "format": "bool", "required": False},
        ],
        "outputs": [{"name": "run_registry", "format": "json", "path_template": "<RUN>/run_registry.json"}],
        "model_policy": {
            "general_model": "not_required",
            "medical_specialist_model": "not_required",
            "local_model": "not_required",
            "api_model": "not_required",
        },
    },
    {
        "id": "workflow.education",
        "name": "Education suggestions",
        "category": "education",
        "development_status": "implemented_v1",
        "implementation_type": "deterministic_or_llm_json",
        "implementation": "Generates case-level or reader-level suggestions from workflow1/workflow2 outputs with deterministic fallback.",
        "inputs": [
            {"name": "eval_report", "format": "workflow1 json", "required": False},
            {"name": "eval_radiologist", "format": "workflow2 json", "required": False},
        ],
        "outputs": [
            {"name": "education", "format": "json", "path_template": "<OUTPUT>.json"},
            {"name": "run_registry", "format": "json", "path_template": "<OUTPUT_DIR>/run_registry.json"},
        ],
        "model_policy": {
            "general_model": "acceptable_for_education_text",
            "medical_specialist_model": "preferred_for_medical_feedback",
            "local_model": "optional",
            "api_model": "acceptable_when_configured",
        },
    },
    {
        "id": "tools.catalog",
        "name": "Capability catalog",
        "category": "documentation",
        "development_status": "implemented_v1",
        "implementation_type": "metadata_export",
        "implementation": "Exports tool, workflow, model, and provider capability metadata without exposing secret values.",
        "inputs": [{"name": "config", "format": "yaml", "required": False}],
        "outputs": [
            {"name": "capability_catalog", "format": "json", "path_template": "outputs/capability_catalog.json"},
            {"name": "run_registry", "format": "json", "path_template": "<OUTPUT_DIR>/run_registry.json"},
        ],
        "model_policy": {
            "general_model": "not_required",
            "medical_specialist_model": "not_required",
            "local_model": "not_required",
            "api_model": "not_required",
        },
    },
    {
        "id": "experiments.run",
        "name": "Notion experiment aggregation",
        "category": "experiment",
        "development_status": "implemented_v1",
        "implementation_type": "deterministic_aggregation",
        "implementation": (
            "Aggregates six v1 experiment summaries from existing workflow and analysis outputs; "
            "auto-generates deterministic reader-level education suggestions when education outputs are missing."
        ),
        "inputs": [{"name": "run_dir", "format": "directory", "required": True}],
        "outputs": [
            {"name": "results", "format": "json", "path_template": "<EXP>/results.json"},
            {"name": "results_markdown", "format": "markdown", "path_template": "<EXP>/results.md"},
            {"name": "summary_csv", "format": "csv", "path_template": "<EXP>/experiment_summary.csv"},
            {"name": "education_summary", "format": "json", "path_template": "<RUN>/education/radiologist_summary.json"},
        ],
        "model_policy": {
            "general_model": "not_required",
            "medical_specialist_model": "not_required",
            "local_model": "not_required",
            "api_model": "not_required",
        },
    },
    {
        "id": "figures.build",
        "name": "Figure generation",
        "category": "visualization",
        "development_status": "implemented_v1",
        "implementation_type": "deterministic_svg",
        "implementation": (
            "Builds reproducible Notion v1 SVG figures and CSV/Markdown tables from experiment results, "
            "including Fig.1, Fig.2, Fig.3, Fig.4, Fig.5, Fig.6, Fig.7, Fig.8, Fig.9, Table 1, and Table 2."
        ),
        "inputs": [{"name": "experiment_dir", "format": "directory", "required": True}],
        "outputs": [
            {"name": "figure_manifest", "format": "json", "path_template": "<FIG>/figure_manifest.json"},
            {"name": "fig1_system_overview", "format": "svg", "path_template": "<FIG>/fig1_system_overview.svg"},
            {"name": "fig2_single_case_evidence_chain", "format": "svg", "path_template": "<FIG>/fig2_single_case_evidence_chain.svg"},
            {"name": "fig3_finding_graph_alignment", "format": "svg", "path_template": "<FIG>/fig3_finding_graph_alignment.svg"},
            {"name": "fig4_feedback_card", "format": "svg", "path_template": "<FIG>/fig4_feedback_card.svg"},
            {"name": "fig5_protocol", "format": "svg", "path_template": "<FIG>/fig5_experiment_protocol.svg"},
            {"name": "fig6_main_results", "format": "svg", "path_template": "<FIG>/fig6_main_results.svg"},
            {"name": "fig7_case_distribution", "format": "svg", "path_template": "<FIG>/fig7_case_level_distribution.svg"},
            {"name": "fig8_error_hazard", "format": "svg", "path_template": "<FIG>/fig8_error_hazard.svg"},
            {"name": "fig9_auxiliary_metrics", "format": "svg", "path_template": "<FIG>/fig9_auxiliary_metrics.svg"},
            {"name": "table1_dataset_run_summary", "format": "csv+markdown", "path_template": "<FIG>/table1_dataset_run_summary.csv"},
            {"name": "table2_metric_taxonomy", "format": "csv+markdown", "path_template": "<FIG>/table2_metric_taxonomy.csv"},
        ],
        "model_policy": {
            "general_model": "not_required",
            "medical_specialist_model": "not_required",
            "local_model": "not_required",
            "api_model": "not_required",
        },
    },
    {
        "id": "dashboard.build",
        "name": "Control panel",
        "category": "documentation",
        "development_status": "implemented_v1",
        "implementation_type": "static_html",
        "implementation": "Builds a static dashboard with run summary, workflow progress, tool implementation, model routing, experiments, and registry.",
        "inputs": [{"name": "run_dir", "format": "directory", "required": True}],
        "outputs": [{"name": "control_panel", "format": "html", "path_template": "web/control_panel.html"}],
        "model_policy": {
            "general_model": "not_required",
            "medical_specialist_model": "not_required",
            "local_model": "not_required",
            "api_model": "not_required",
        },
    },
]


def build_capability_catalog(config: AppConfig | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    registry = ReportGeneratorRegistry(cfg)
    status_export = load_legacy_status_export(cfg.generator.legacy_config_path)
    model_statuses = status_export.get("models") or []
    if not isinstance(model_statuses, list):
        model_statuses = []
    return {
        "schema_version": "1.0",
        "tools": TOOL_CATALOG,
        "workflow_stages": WORKFLOW_STAGE_CATALOG,
        "models": [_model_entry(entry) for entry in registry.entries.values()],
        "model_statuses": model_statuses,
        "model_status_summary": {
            key: value
            for key, value in status_export.items()
            if key != "models"
        },
        "providers": {
            "llm": {
                "provider": cfg.llm.provider,
                "model": cfg.llm.model,
                "api_key_env": cfg.llm.api_key_env,
                "base_url": cfg.llm.base_url,
                "secret_values_exposed": False,
            },
            "extractor": asdict(cfg.extractor),
            "model_roles": {
                role: {
                    "provider": route.provider,
                    "model": route.model,
                    "api_key_env": route.api_key_env,
                    "endpoint_host": (urlparse(route.base_url).hostname or "").lower(),
                    "max_retries": route.max_retries,
                    "schema_max_attempts": route.schema_attempts(
                        default=cfg.llm.max_retries
                    ),
                    "transport_max_retries": route.as_call_options().get(
                        "max_retries",
                        cfg.llm.max_retries,
                    ),
                    "timeout_sec": route.timeout_sec,
                    "temperature": route.temperature,
                    "omit_temperature": route.omit_temperature,
                    "max_tokens": route.max_tokens,
                    "secret_values_exposed": False,
                }
                for role, route in cfg.model_roles.items()
            },
            "generator": {
                "cloud_fallback_enabled": cfg.generator.cloud_fallback_enabled,
                "include_legacy_ready_models": cfg.generator.include_legacy_ready_models,
                "default_models": list(cfg.generator.default_models),
                "legacy_config_path": cfg.generator.legacy_config_path,
            },
        },
    }


def _model_entry(entry: Any) -> dict[str, Any]:
    return {
        "key": entry.key,
        "title": entry.title,
        "supported_modalities": list(entry.supported_modalities),
        "supported_body_parts": list(entry.supported_body_parts),
        **entry.readiness_metadata(),
    }
