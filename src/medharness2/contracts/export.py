from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from medharness2.contracts.case import CaseEvaluationArtifact
from medharness2.contracts.common import SCHEMA_VERSION, ArtifactReference
from medharness2.contracts.evaluation import (
    AlignmentAuditArtifact,
    FindingGraph,
    GeneratedReportArtifact,
    HazardAdjudicationArtifact,
    HazardResult,
    HazardReviewArtifact,
    StructureAuditArtifact,
)
from medharness2.contracts.run import RunManifest


SCHEMA_MODELS = {
    "artifact_reference": ArtifactReference,
    "alignment_audit": AlignmentAuditArtifact,
    "case_evaluation": CaseEvaluationArtifact,
    "finding_graph": FindingGraph,
    "generated_report": GeneratedReportArtifact,
    "hazard_adjudication": HazardAdjudicationArtifact,
    "hazard_result": HazardResult,
    "hazard_review": HazardReviewArtifact,
    "structure_audit": StructureAuditArtifact,
    "run_manifest": RunManifest,
}


def export_json_schemas(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for name, model in SCHEMA_MODELS.items():
        filename = f"{name}.schema.json"
        (root / filename).write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        files[name] = filename
    index = {"schema_version": SCHEMA_VERSION, "schemas": files}
    (root / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return index
