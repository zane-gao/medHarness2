from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

from medharness2.config import AppConfig, LLMConfig
from medharness2.experiment_protocols import (
    ExperimentProtocol,
    evaluate_readiness,
    load_experiment_protocols,
    load_validation_evidence,
)
from medharness2.workflows.education import run_education_suggestions
from medharness2.utils.io import read_json, write_json


EXPERIMENT_IDS = [
    "radiologist_evaluation",
    "finding_extraction",
    "hazard_evaluation",
    "educational_study",
    "image_to_text_models",
    "modality_recognition",
]


def run_experiments(
    run_dir: str | Path,
    output_dir: str | Path,
    *,
    protocol_dir: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(run_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    education_generation = _ensure_education_outputs(root)
    result = build_experiment_results(root, protocol_dir=protocol_dir)
    result["automation"] = {"education_generation": education_generation}
    result["warnings"] = list(education_generation.get("warnings") or [])
    protocol = build_experiment_protocol(result, protocol_dir=protocol_dir)
    result["protocol"] = protocol
    write_json(out / "results.json", result)
    _write_summary_csv(out / "experiment_summary.csv", result["experiments"])
    write_json(out / "experiment_protocol.json", protocol)
    _write_protocol_csv(out / "experiment_protocol.csv", protocol["experiments"])
    (out / "results.md").write_text(_render_markdown(result), encoding="utf-8")
    (out / "experiment_protocol.md").write_text(_render_protocol_markdown(protocol), encoding="utf-8")
    return result


def experiment_registry_metrics(result: dict[str, Any]) -> dict[str, Any]:
    education = ((result.get("automation") or {}).get("education_generation") or {})
    status_counts = Counter(str(item.get("status") or "unknown") for item in result.get("experiments") or [])
    return {
        "experiment_count": int(result.get("experiment_count") or 0),
        "experiment_status_counts": dict(sorted(status_counts.items())),
        "validated_experiment_count": int(status_counts.get("validated", 0)),
        "pilot_experiment_count": int(status_counts.get("pilot", 0)),
        "not_ready_experiment_count": int(status_counts.get("not_ready", 0)),
        "education_generation_status": str(education.get("status") or "unknown"),
        "education_suggestion_count": int(education.get("suggestion_count") or 0),
    }


def build_experiment_results(
    run_dir: str | Path,
    *,
    protocol_dir: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(run_dir)
    protocols = load_experiment_protocols(protocol_dir)
    validation_evidence = load_validation_evidence(root)
    analysis = _read_optional(root / "analysis" / "analysis_summary.json")
    workflow2 = _read_optional(root / "workflow2.json")
    workflow3 = _read_optional(root / "workflow3.json")
    run_summary = _read_optional(root / "run_summary.json")
    cases = _case_payloads(root, workflow2)
    experiments = [
        _radiologist_evaluation(analysis, workflow2, workflow3),
        _finding_extraction(cases),
        _hazard_evaluation(cases),
        _educational_study(root),
        _image_to_text_models(root, analysis),
        _modality_recognition(run_summary, workflow2),
    ]
    for experiment in experiments:
        protocol = protocols[experiment["id"]]
        evidence_status = str(experiment.get("status") or "missing_inputs")
        readiness = evaluate_readiness(
            protocol,
            evidence_status=evidence_status,
            validation_evidence=validation_evidence,
            run_dir=root,
        )
        experiment["evidence_status"] = evidence_status
        experiment.update(readiness)
        experiment["protocol_source"] = str(protocol.source_path)
    return {
        "schema_version": "2.0",
        "run_dir": str(root),
        "experiment_count": len(experiments),
        "experiments": experiments,
        "protocol_source_files": {key: str(protocol.source_path) for key, protocol in protocols.items()},
    }


def build_experiment_protocol(
    result: dict[str, Any],
    *,
    protocol_dir: str | Path | None = None,
) -> dict[str, Any]:
    protocols = load_experiment_protocols(protocol_dir)
    experiments = {item["id"]: item for item in result.get("experiments") or []}
    entries = [
        _protocol_entry(experiments[experiment_id], protocols[experiment_id])
        for experiment_id in EXPERIMENT_IDS
        if experiment_id in experiments
    ]
    return {
        "schema_version": "2.0",
        "run_dir": str(result.get("run_dir") or ""),
        "source": "notion/Radiology Report Evaluation and Education Agent/评估实验安排",
        "experiment_count": len(entries),
        "experiments": entries,
    }


def _protocol_entry(experiment: dict[str, Any], spec: ExperimentProtocol) -> dict[str, Any]:
    experiment_id = str(experiment.get("id") or "")
    return {
        "id": experiment_id,
        "notion_section": spec.notion_section,
        "research_question": spec.research_question,
        "status": experiment.get("status", "unknown"),
        "inputs": list(spec.inputs),
        "outputs": list(spec.outputs),
        "implementation": dict(spec.implementation),
        "model_policy": dict(spec.model_policy),
        "cohort": dict(spec.cohort),
        "primary_endpoints": list(spec.primary_endpoints),
        "secondary_endpoints": list(spec.secondary_endpoints),
        "statistics": list(spec.statistics),
        "validation_gates": list(experiment.get("validation_gates") or []),
        "gate_summary": dict(experiment.get("gate_summary") or {}),
        "protocol_source": str(spec.source_path),
        "current_evidence": {
            "status": experiment.get("evidence_status", "unknown"),
            "metrics": dict(experiment.get("metrics") or {}),
            "source_inputs": list(experiment.get("inputs") or []),
            "source_outputs": list(experiment.get("outputs") or []),
        },
        "limitations": list(spec.limitations),
        "next_steps": list(spec.next_steps),
    }


def _radiologist_evaluation(analysis: dict[str, Any], workflow2: dict[str, Any], workflow3: dict[str, Any]) -> dict[str, Any]:
    readers = workflow2.get("per_reader") or {}
    percentiles = workflow3.get("reader_percentiles") or {}
    return {
        "id": "radiologist_evaluation",
        "title": "Radiologist Evaluation Study",
        "status": "evidence_available" if readers else "missing_inputs",
        "inputs": ["workflow2.json", "workflow3.json", "analysis/reader_summary.csv"],
        "outputs": ["reader_count", "reader_percentiles", "overall_score"],
        "metrics": {
            "case_count": int(analysis.get("case_count") or workflow2.get("case_count") or 0),
            "reader_count": int(analysis.get("reader_count") or len(readers)),
            "percentile_count": len(percentiles),
        },
    }


def _finding_extraction(cases: list[dict[str, Any]]) -> dict[str, Any]:
    backends: Counter[str] = Counter()
    finding_count = 0
    for case in cases:
        graph = (case.get("human_evaluation") or {}).get("finding_graph") or {}
        backends[str(graph.get("backend") or "unknown")] += 1
        finding_count += len(graph.get("findings") or [])
    return {
        "id": "finding_extraction",
        "title": "Radiologist Finding Extraction Study",
        "status": "evidence_available" if cases else "missing_inputs",
        "inputs": ["workflow2_cases/*.json"],
        "outputs": ["finding_backend_counts", "finding_count"],
        "metrics": {
            "case_count": len(cases),
            "finding_count": finding_count,
            "backend_counts": dict(sorted(backends.items())),
        },
    }


def _hazard_evaluation(cases: list[dict[str, Any]]) -> dict[str, Any]:
    error_types: Counter[str] = Counter()
    hazard_levels: Counter[str] = Counter()
    for case in cases:
        for comparison in case.get("pairwise_comparisons") or []:
            hazards = ((comparison.get("comparison") or {}).get("hazards") or {}).get("errors") or []
            for error in hazards:
                error_types[str(error.get("error_type") or "unknown")] += 1
                hazard_levels[str(error.get("hazard_level") or "unknown")] += 1
    return {
        "id": "hazard_evaluation",
        "title": "Radiologist Error Hazard Evaluation Study",
        "status": "evidence_available" if cases else "missing_inputs",
        "inputs": ["workflow2_cases/*.json pairwise_comparisons"],
        "outputs": ["error_type_counts", "hazard_level_counts"],
        "metrics": {
            "case_count": len(cases),
            "error_type_counts": dict(sorted(error_types.items())),
            "hazard_level_counts": dict(sorted(hazard_levels.items())),
        },
    }


def _educational_study(run_dir: Path) -> dict[str, Any]:
    education_dir = run_dir / "education"
    files = sorted(education_dir.glob("*.json")) if education_dir.exists() else []
    suggestion_count = 0
    for path in files:
        payload = _read_optional(path)
        suggestion_count += len(payload.get("suggestions") or [])
        suggestion_count += len(payload.get("general_suggestions") or [])
    return {
        "id": "educational_study",
        "title": "Radiologist Educational Study",
        "status": (
            "evidence_available"
            if files
            else "ready_for_generation"
            if (run_dir / "workflow2.json").exists()
            else "missing_inputs"
        ),
        "inputs": ["workflow education outputs", "workflow2_cases/*.json"],
        "outputs": ["education/*.json suggestions"],
        "metrics": {
            "education_file_count": len(files),
            "suggestion_count": suggestion_count,
        },
    }


def _ensure_education_outputs(run_dir: Path) -> dict[str, Any]:
    education_dir = run_dir / "education"
    existing_files = sorted(education_dir.glob("*.json")) if education_dir.exists() else []
    if existing_files:
        return {
            "status": "existing_outputs",
            "outputs": [str(path) for path in existing_files],
            "suggestion_count": _education_suggestion_count(existing_files),
            "warnings": [],
        }
    workflow2 = run_dir / "workflow2.json"
    if not workflow2.exists():
        return {
            "status": "skipped_missing_workflow2",
            "outputs": [],
            "suggestion_count": 0,
            "warnings": ["workflow2.json not found; educational_study remains ready_for_generation."],
        }
    output_path = education_dir / "radiologist_summary.json"
    try:
        result = run_education_suggestions(
            eval_radiologist=workflow2,
            output_path=output_path,
            config=AppConfig(llm=LLMConfig(provider="mock")),
        )
    except Exception as exc:  # Keep experiment aggregation usable when optional education generation fails.
        return {
            "status": "generation_failed",
            "outputs": [],
            "suggestion_count": 0,
            "warnings": [f"education generation failed: {type(exc).__name__}: {exc}"],
        }
    return {
        "status": "generated",
        "outputs": [str(output_path)],
        "suggestion_count": len(result.get("suggestions") or []) + len(result.get("general_suggestions") or []),
        "warnings": [],
    }


def _education_suggestion_count(paths: list[Path]) -> int:
    count = 0
    for path in paths:
        payload = _read_optional(path)
        count += len(payload.get("suggestions") or [])
        count += len(payload.get("general_suggestions") or [])
    return count


def _image_to_text_models(run_dir: Path, analysis: dict[str, Any]) -> dict[str, Any]:
    rows = _read_csv(run_dir / "analysis" / "model_source_summary.csv")
    source_counts = dict(analysis.get("generated_report_source_counts") or {})
    evidence_tier_counts = dict(analysis.get("generated_report_evidence_tier_counts") or {})
    model_count = len(analysis.get("generated_report_model_counts") or {})
    return {
        "id": "image_to_text_models",
        "title": "Validation of Image-to-text AI Models",
        "status": "evidence_available" if rows or source_counts else "missing_inputs",
        "inputs": ["analysis/model_source_summary.csv", "workflow2_cases/*.json"],
        "outputs": ["model_source_counts", "quality_pass_rate", "top_n_selection_count"],
        "metrics": {
            "model_count": model_count or len({row.get("model") for row in rows}),
            "source_counts": source_counts,
            "evidence_tier_counts": evidence_tier_counts,
            "formal_fresh_count": int(evidence_tier_counts.get("formal_fresh") or 0),
            "quality_failed_count": int(analysis.get("quality_gate_failed_count") or 0),
            "generated_report_count": int(analysis.get("generated_report_count") or 0),
        },
    }


def _modality_recognition(run_summary: dict[str, Any], workflow2: dict[str, Any]) -> dict[str, Any]:
    validation = run_summary.get("validation") or {}
    summary = validation.get("summary") or {}
    modalities = summary.get("modality_counts") or Counter(str(case.get("modality") or "unknown") for case in workflow2.get("cases") or [])
    return {
        "id": "modality_recognition",
        "title": "Validation of Modality Recognition VLM",
        "status": "evidence_available" if modalities else "missing_inputs",
        "inputs": ["manifest.jsonl", "run_summary.json"],
        "outputs": ["modality_counts", "ocr_provenance_counts"],
        "metrics": {
            "modality_counts": dict(modalities),
            "real_ocr_count": int(validation.get("real_ocr_count") or 0),
            "mock_ocr_count": int(validation.get("mock_ocr_count") or 0),
            "unknown_ocr_count": int(validation.get("unknown_ocr_count") or 0),
        },
    }


def _case_payloads(root: Path, workflow2: dict[str, Any]) -> list[dict[str, Any]]:
    payloads = []
    for case in workflow2.get("cases") or []:
        path = Path(str(case.get("workflow1_output") or ""))
        candidates = [path] if path.is_absolute() else [root / path, path]
        for candidate in candidates:
            if candidate.exists():
                payloads.append(read_json(candidate))
                break
    if payloads:
        return payloads
    case_dir = root / "workflow2_cases"
    return [read_json(path) for path in sorted(case_dir.glob("*.json"))] if case_dir.exists() else []


def _read_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return read_json(path)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_summary_csv(path: Path, experiments: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "title", "status", "metrics"])
        writer.writeheader()
        for item in experiments:
            writer.writerow(
                {
                    "id": item["id"],
                    "title": item["title"],
                    "status": item["status"],
                    "metrics": item["metrics"],
                }
            )


def _write_protocol_csv(path: Path, experiments: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "notion_section",
                "status",
                "research_question",
                "inputs",
                "outputs",
                "implementation",
                "model_policy",
                "metrics",
                "primary_endpoints",
                "statistics",
                "gate_summary",
                "validation_gates",
                "protocol_source",
                "limitations",
                "next_steps",
            ],
        )
        writer.writeheader()
        for item in experiments:
            writer.writerow(
                {
                    "id": item["id"],
                    "notion_section": item["notion_section"],
                    "status": item["status"],
                    "research_question": item["research_question"],
                    "inputs": "; ".join(item.get("inputs") or []),
                    "outputs": "; ".join(item.get("outputs") or []),
                    "implementation": str((item.get("implementation") or {}).get("method") or ""),
                    "model_policy": item.get("model_policy") or {},
                    "metrics": (item.get("current_evidence") or {}).get("metrics") or {},
                    "primary_endpoints": "; ".join(item.get("primary_endpoints") or []),
                    "statistics": "; ".join(item.get("statistics") or []),
                    "gate_summary": item.get("gate_summary") or {},
                    "validation_gates": item.get("validation_gates") or [],
                    "protocol_source": item.get("protocol_source") or "",
                    "limitations": "; ".join(item.get("limitations") or []),
                    "next_steps": "; ".join(item.get("next_steps") or []),
                }
            )


def _render_markdown(result: dict[str, Any]) -> str:
    lines = ["# medHarness2 Experiment Results", ""]
    lines.append(f"- Run dir: `{result['run_dir']}`")
    lines.append(f"- Experiments: {result['experiment_count']}")
    lines.append("")
    lines.append("| Experiment | Status | Key metrics |")
    lines.append("| --- | --- | --- |")
    for item in result["experiments"]:
        lines.append(f"| `{item['id']}` | {item['status']} | `{item['metrics']}` |")
    lines.append("")
    return "\n".join(lines)


def _render_protocol_markdown(protocol: dict[str, Any]) -> str:
    lines = ["# medHarness2 Experiment Protocol", ""]
    lines.append(f"- Run dir: `{protocol['run_dir']}`")
    lines.append(f"- Source: `{protocol['source']}`")
    lines.append(f"- Experiments: {protocol['experiment_count']}")
    lines.append("")
    for item in protocol.get("experiments") or []:
        lines.append(f"## {item['notion_section']}")
        lines.append("")
        lines.append(f"- ID: `{item['id']}`")
        lines.append(f"- Status: `{item['status']}`")
        lines.append(f"- Gate status: `{item.get('gate_summary') or {}}`")
        lines.append(f"- Research question: {item['research_question']}")
        lines.append(f"- Inputs: `{'; '.join(item.get('inputs') or [])}`")
        lines.append(f"- Outputs: `{'; '.join(item.get('outputs') or [])}`")
        lines.append(f"- Implementation: `{(item.get('implementation') or {}).get('method', '')}`")
        lines.append(f"- Model/API policy: `{item.get('model_policy') or {}}`")
        lines.append(f"- Primary endpoints: `{'; '.join(item.get('primary_endpoints') or [])}`")
        lines.append(f"- Statistics: `{'; '.join(item.get('statistics') or [])}`")
        lines.append(f"- Validation gates: `{item.get('validation_gates') or []}`")
        lines.append(f"- Protocol source: `{item.get('protocol_source') or ''}`")
        lines.append(f"- Current evidence: `{(item.get('current_evidence') or {}).get('metrics') or {}}`")
        lines.append(f"- Limitations: {'; '.join(item.get('limitations') or [])}")
        lines.append(f"- Next steps: {'; '.join(item.get('next_steps') or [])}")
        lines.append("")
    return "\n".join(lines)
