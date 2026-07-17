from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from medharness2.annotation.models import AnnotationCase, CandidateReportForAnnotation, ReaderAnnotation
from medharness2.modality import normalize_modality
from medharness2.config import PROJECT_ROOT
from medharness2.privacy import ExternalPayloadPolicy
from medharness2.utils.io import read_json


def build_pilot_annotation_package(
    run_dir: str | Path,
    output_dir: str | Path,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be positive")
    root = Path(run_dir)
    output = Path(output_dir)
    if not root.is_dir():
        raise ValueError("run_dir_not_found")

    # Resolve and validate the source selection before touching an existing
    # package.  A malformed source run must never delete an older, still
    # usable annotation package as a side effect of a failed rebuild.
    selected = _stratified_cases(_load_case_payloads(root), limit=limit)
    if not selected:
        raise ValueError("no_cases_discovered")

    cases_dir = output / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    for stale in cases_dir.glob("*.json"):
        try:
            existing_case = AnnotationCase.model_validate_json(stale.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError(f"Refusing to rebuild annotation package with invalid case: {stale}") from exc
        if any(annotation.status != "not_started" for annotation in existing_case.annotations.values()):
            raise ValueError(
                "Refusing to rebuild annotation package after annotation started; "
                f"use a new output directory: {stale}"
            )
        stale.unlink()
    policy = ExternalPayloadPolicy()
    manifest_rows = []
    internal_maps: list[dict[str, Any]] = []
    for index, (source_case_id, payload) in enumerate(selected, start=1):
        pilot_case_id = f"pilot-{index:03d}"
        input_payload = _input_payload(payload, case_id=source_case_id)
        reference_text = _reference_report(root, input_payload, payload, policy, case_id=source_case_id)
        raw_generated_reports = payload.get("generated_reports")
        if not isinstance(raw_generated_reports, list):
            raise ValueError(f"case {source_case_id} generated_reports must be a list of objects")
        if not raw_generated_reports:
            raise ValueError(f"case {source_case_id} has no generated_reports for annotation")
        candidate_items: list[dict[str, Any]] = []
        for candidate_index, item in enumerate(raw_generated_reports, start=1):
            if not isinstance(item, dict):
                raise ValueError(
                    f"case {source_case_id} generated_reports[{candidate_index - 1}] must be an object"
                )
            report = item.get("report")
            if not isinstance(report, str) or not report.strip():
                raise ValueError(
                    f"case {source_case_id} generated_reports[{candidate_index - 1}].report must be a non-empty string"
                )
            # Model/source are part of the private blinding map.  Keep their
            # types strict so malformed JSON cannot be stringified into a
            # seemingly valid identity.
            for field in ("model", "source"):
                value = item.get(field)
                if value is not None and not isinstance(value, str):
                    raise ValueError(
                        f"case {source_case_id} generated_reports[{candidate_index - 1}].{field} must be a string"
                    )
            candidate_items.append(item)
        candidates = [
            CandidateReportForAnnotation(
                candidate_id=f"candidate-{candidate_index:02d}",
                blinded_model_id=f"model-{candidate_index:02d}",
                report_text=policy.deidentify_clinical_text(item["report"]),
            )
            for candidate_index, item in enumerate(candidate_items, start=1)
        ]
        modality = normalize_modality(input_payload.get("modality"))
        body_part = _body_part(input_payload.get("body_part"))
        annotation_case = AnnotationCase(
            pilot_case_id=pilot_case_id,
            source_case_sha256=_source_case_sha256(payload),
            modality=modality,
            body_part=body_part,
            reference_report=reference_text,
            candidate_reports=candidates,
            annotations={
                slot: ReaderAnnotation(reader_slot=slot)
                for slot in ("reader_a", "reader_b", "adjudication")
            },
        )
        filename = f"{pilot_case_id}.json"
        raw = annotation_case.model_dump_json(indent=2)
        scan = _scan_annotation_payload(raw, policy)
        if not scan.allowed:
            categories = ",".join(sorted({finding.category for finding in scan.findings}))
            raise ValueError(f"Annotation case failed privacy scan: {pilot_case_id}: {categories}")
        (cases_dir / filename).write_text(raw + "\n", encoding="utf-8")
        manifest_rows.append(
            {
                "pilot_case_id": pilot_case_id,
                "modality": annotation_case.modality,
                "body_part": annotation_case.body_part,
                "candidate_count": len(candidates),
                "annotation_path": f"cases/{filename}",
                "status": "not_started",
            }
        )
        # Keep model identities out of the reader-facing case JSON.  This
        # internal map is never referenced by the annotation UI/package
        # validator and is intended only for later adjudication analysis.
        internal_maps.append(
            {
                "pilot_case_id": pilot_case_id,
                "source_case_sha256": annotation_case.source_case_sha256,
                "candidates": [
                    {
                        "candidate_id": candidate.candidate_id,
                        "blinded_model_id": candidate.blinded_model_id,
                        "source_model": str(item.get("model") or "unknown"),
                        "source": str(item.get("source") or "unknown"),
                    }
                    for candidate, item in zip(candidates, candidate_items)
                ],
            }
        )
    (output / "manifest.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in manifest_rows),
        encoding="utf-8",
    )
    (output / "annotation.schema.json").write_text(
        json.dumps(AnnotationCase.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    internal_dir = output / "internal"
    internal_dir.mkdir(parents=True, exist_ok=True)
    (internal_dir / "model_blinding_map.json").write_text(
        json.dumps({"schema_version": "1.0", "maps": internal_maps}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(_package_readme(len(manifest_rows)), encoding="utf-8")
    return {
        "schema_version": "2.0",
        "case_count": len(manifest_rows),
        "manifest": str(output / "manifest.jsonl"),
        "output_dir": str(output),
    }


def validate_pilot_annotation_package(package_dir: str | Path) -> dict[str, Any]:
    """Validate package/file/reader state without upgrading incomplete labels."""
    root = Path(package_dir)
    manifest_path = root / "manifest.jsonl"
    errors: list[str] = []
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    if not manifest_path.exists():
        return {"status": "blocked", "case_count": 0, "complete_case_count": 0, "errors": ["missing_manifest"]}
    try:
        manifest_lines = manifest_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return {
            "status": "blocked",
            "case_count": 0,
            "complete_case_count": 0,
            "in_progress_case_count": 0,
            "not_started_case_count": 0,
            "errors": [f"manifest:read_error:{type(exc).__name__}"],
            "warnings": [],
        }
    for index, line in enumerate(manifest_lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"manifest:row_{index}:invalid_json")
            continue
        if not isinstance(row, dict):
            errors.append(f"manifest:row_{index}:not_an_object")
            continue
        rows.append(row)

    complete = 0
    in_progress = 0
    not_started = 0
    referenced_paths: set[Path] = set()
    seen_case_ids: dict[str, int] = {}
    seen_annotation_paths: dict[Path, int] = {}
    cases_root = (root / "cases").resolve()
    root_resolved = root.resolve()
    if root_resolved not in cases_root.parents:
        errors.append("cases:outside_package")
    for row_index, row in enumerate(rows, start=1):
        raw_case_id = row.get("pilot_case_id")
        raw_relative = row.get("annotation_path")
        pilot_case_id = raw_case_id.strip() if isinstance(raw_case_id, str) else ""
        relative = raw_relative.strip() if isinstance(raw_relative, str) else ""
        row_label = pilot_case_id or f"row_{row_index}"
        if not pilot_case_id:
            errors.append(f"manifest:{row_label}:missing_identity")
            continue
        if pilot_case_id in seen_case_ids:
            errors.append(
                f"manifest:{pilot_case_id}:duplicate_case_id:rows_{seen_case_ids[pilot_case_id]}_{row_index}"
            )
        else:
            seen_case_ids[pilot_case_id] = row_index
        if not relative:
            errors.append(f"manifest:{pilot_case_id}:missing_annotation_path")
            continue
        raw_path = Path(relative)
        if raw_path.is_absolute():
            errors.append(f"case:{pilot_case_id}:annotation_path_absolute")
            continue
        try:
            case_path = (root / raw_path).resolve(strict=False)
        except OSError as exc:
            errors.append(f"case:{pilot_case_id}:annotation_path_resolution:{type(exc).__name__}")
            continue
        # Case files are package inputs, so never follow a manifest path outside
        # the package's cases directory (including symlinks and ``..`` paths).
        if cases_root not in case_path.parents or case_path == cases_root:
            errors.append(f"case:{pilot_case_id}:annotation_path_outside_cases")
            continue
        if case_path in seen_annotation_paths:
            errors.append(
                f"manifest:{pilot_case_id}:duplicate_annotation_path:rows_{seen_annotation_paths[case_path]}_{row_index}"
            )
        else:
            seen_annotation_paths[case_path] = row_index
        referenced_paths.add(case_path)
        if not case_path.is_file():
            errors.append(f"case:{pilot_case_id}:missing_file")
            continue
        try:
            case = AnnotationCase.model_validate_json(case_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"case:{pilot_case_id}:invalid_contract:{type(exc).__name__}")
            continue
        if case.pilot_case_id != pilot_case_id:
            errors.append(f"case:{pilot_case_id}:id_mismatch")
        if case.modality != str(row.get("modality") or "unknown"):
            errors.append(f"case:{pilot_case_id}:modality_mismatch")
        if case.body_part != str(row.get("body_part") or "unknown"):
            errors.append(f"case:{pilot_case_id}:body_part_mismatch")
        if not case.reference_report.strip():
            errors.append(f"case:{pilot_case_id}:empty_reference_report")
        candidate_count = row.get("candidate_count")
        if candidate_count is not None and (
            isinstance(candidate_count, bool) or not isinstance(candidate_count, int) or candidate_count < 0
        ):
            errors.append(f"case:{pilot_case_id}:invalid_candidate_count")
        elif candidate_count is not None and candidate_count != len(case.candidate_reports):
            errors.append(f"case:{pilot_case_id}:candidate_count_mismatch:{candidate_count}!={len(case.candidate_reports)}")
        if not case.candidate_reports:
            errors.append(f"case:{pilot_case_id}:no_candidate_reports")
        candidate_ids = [candidate.candidate_id for candidate in case.candidate_reports]
        if len(candidate_ids) != len(set(candidate_ids)):
            errors.append(f"case:{pilot_case_id}:duplicate_candidate_id")
        blinded_ids = [candidate.blinded_model_id for candidate in case.candidate_reports]
        if len(blinded_ids) != len(set(blinded_ids)):
            errors.append(f"case:{pilot_case_id}:duplicate_blinded_model_id")
        for candidate in case.candidate_reports:
            if not candidate.report_text.strip():
                errors.append(f"case:{pilot_case_id}:empty_candidate_report:{candidate.candidate_id}")
        expected_slots = ("reader_a", "reader_b", "adjudication")
        missing_slots = [slot for slot in expected_slots if slot not in case.annotations]
        if missing_slots:
            for slot in missing_slots:
                errors.append(f"case:{pilot_case_id}:missing_annotation_slot:{slot}")
            continue
        statuses = {slot: case.annotations[slot].status for slot in expected_slots}
        if statuses["adjudication"] != "not_started" and not (
            statuses["reader_a"] == "complete" and statuses["reader_b"] == "complete"
        ):
            errors.append(f"case:{pilot_case_id}:adjudication_before_readers")
        for slot, annotation in case.annotations.items():
            if annotation.status == "not_started" and (
                annotation.findings
                or annotation.hazards
                or annotation.overall_notes.strip()
                or annotation.confidence is not None
            ):
                errors.append(f"case:{pilot_case_id}:{slot}:content_before_start")
        derived = _annotation_status(statuses)
        declared = row.get("status")
        if not isinstance(declared, str) or not declared.strip():
            errors.append(f"case:{pilot_case_id}:missing_status")
            declared = ""
        else:
            declared = declared.strip()
        if declared != derived:
            errors.append(f"case:{pilot_case_id}:status_mismatch:{declared}!={derived}")
        if derived == "complete":
            complete += 1
        elif derived == "in_progress":
            in_progress += 1
        else:
            not_started += 1

    # A package must not silently omit a generated case file from its manifest.
    # This catches partial/corrupt uploads and stale rows after manual edits.
    if cases_root.exists() and cases_root.is_dir():
        try:
            case_files = {
                path.resolve()
                for path in cases_root.rglob("*")
                if path.is_file() and path.suffix.lower() == ".json"
            }
        except OSError as exc:
            errors.append(f"cases:scan_error:{type(exc).__name__}")
        else:
            for case_path in sorted(case_files - referenced_paths, key=str):
                try:
                    relative_path = case_path.relative_to(root_resolved)
                except ValueError:
                    relative_path = case_path
                errors.append(f"case:{relative_path.as_posix()}:unlisted_file")

    if not rows:
        errors.append("manifest:empty")
    status = "blocked" if errors else ("complete" if complete == len(rows) and rows else "in_progress" if in_progress else "not_started")
    if status == "not_started" and rows:
        warnings.append("no_reader_annotations_started")
    return {
        "status": status,
        "case_count": len(rows),
        "complete_case_count": complete,
        "in_progress_case_count": in_progress,
        "not_started_case_count": not_started,
        "errors": list(dict.fromkeys(errors)),
        "warnings": warnings,
    }


def _annotation_status(statuses: dict[str, str]) -> str:
    if all(statuses[slot] == "complete" for slot in ("reader_a", "reader_b", "adjudication")):
        return "complete"
    if any(status != "not_started" for status in statuses.values()):
        return "in_progress"
    return "not_started"


def _input_payload(case_payload: dict[str, Any], *, case_id: str) -> dict[str, Any]:
    """Return a validated shallow copy of the source input block.

    Annotation preparation consumes the input metadata as a routing boundary;
    silently treating a missing/non-object block as an empty dict would turn a
    malformed source case into an apparently valid ``unknown`` case.
    """
    raw_input = case_payload.get("input")
    if not isinstance(raw_input, dict):
        raise ValueError(f"case {case_id} input must be an object")
    return dict(raw_input)


def _body_part(value: Any) -> str:
    """Normalize the optional body-part label without imposing a hard route."""
    if value is None:
        return "unknown"
    if not isinstance(value, str):
        value = str(value)
    normalized = " ".join(value.strip().lower().split())
    return normalized or "unknown"


def _load_case_payloads(root: Path) -> list[tuple[str, dict[str, Any]]]:
    workflow2_path = root / "workflow2.json"
    workflow2 = read_json(workflow2_path) if workflow2_path.exists() else {}
    manifest_cases = workflow2.get("cases") or []
    if manifest_cases:
        rows: list[tuple[str, dict[str, Any]]] = []
        for index, case in enumerate(manifest_cases, start=1):
            source_case_id = str(case.get("case_id") or "")
            raw_reference = str(case.get("workflow1_output") or "").strip()
            case_label = source_case_id or f"row_{index}"
            if not raw_reference:
                raise ValueError(f"workflow2 case {case_label} is missing workflow1_output")
            path = Path(raw_reference)
            candidates = [path] if path.is_absolute() else [root / path, path]
            candidate = next((item for item in candidates if item.exists()), None)
            if candidate is None:
                raise ValueError(
                    f"workflow2 case {case_label} workflow1_output does not exist: {raw_reference}"
                )
            try:
                payload = read_json(candidate)
            except (OSError, UnicodeError, ValueError) as exc:
                raise ValueError(
                    f"workflow2 case {case_label} workflow1_output is unreadable: {candidate}"
                ) from exc
            rows.append((source_case_id or candidate.stem, payload))
        return rows

    # Older runs may only contain workflow2_cases/*.json and no manifest rows.
    case_dir = root / "workflow2_cases"
    return [(path.stem, read_json(path)) for path in sorted(case_dir.glob("*.json"))]


def _stratified_cases(rows: list[tuple[str, dict[str, Any]]], *, limit: int) -> list[tuple[str, dict[str, Any]]]:
    groups: dict[tuple[str, str], deque[tuple[str, dict[str, Any]]]] = defaultdict(deque)
    for row in sorted(rows, key=lambda item: item[0]):
        input_payload = row[1].get("input") or {}
        key = (normalize_modality(input_payload.get("modality")), str(input_payload.get("body_part") or "unknown").lower())
        groups[key].append(row)
    selected: list[tuple[str, dict[str, Any]]] = []
    keys = sorted(groups)
    # Guarantee modality-family coverage whenever the source run contains all
    # three families and the requested package is large enough.
    family_keys: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in keys:
        family_keys[key[0]].append(key)
    families = [family for family in ("cxr", "ct", "mri") if family_keys.get(family)]
    for family in families:
        key = family_keys[family][0]
        if len(selected) < limit and groups[key]:
            selected.append(groups[key].popleft())
    while keys and len(selected) < min(limit, len(rows)):
        next_keys = []
        for key in keys:
            if groups[key] and len(selected) < limit:
                selected.append(groups[key].popleft())
            if groups[key]:
                next_keys.append(key)
        keys = next_keys
    return selected


def _reference_report(
    run_root: Path,
    input_payload: dict[str, Any],
    case_payload: dict[str, Any],
    policy: ExternalPayloadPolicy,
    *,
    case_id: str,
) -> str:
    raw_report_path = str(input_payload.get("report_path") or "").strip()
    if not raw_report_path:
        raise ValueError(f"case {case_id} is missing input.report_path for clinical reference report")
    report_path = Path(raw_report_path)
    candidates = [report_path] if report_path.is_absolute() else [run_root / report_path, PROJECT_ROOT / report_path]
    report_path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
    if not report_path.is_file():
        raise ValueError(f"case {case_id} reference report does not exist: {report_path}")
    try:
        raw_text = report_path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"case {case_id} reference report is unreadable: {report_path}") from exc
    if not raw_text.strip():
        raise ValueError(f"case {case_id} reference report is empty: {report_path}")
    return policy.deidentify_clinical_text(raw_text)


def _source_case_sha256(payload: dict[str, Any]) -> str:
    """Bind annotation provenance to source case content without exposing its ID."""
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _scan_annotation_payload(raw: str, policy: ExternalPayloadPolicy):
    """Backward-compatible wrapper for the shared structured payload scanner."""
    return policy.scan(raw)


def _package_readme(case_count: int) -> str:
    return (
        "# medHarness2 Finding/Hazard Pilot Annotation Package\n\n"
        f"- Cases: {case_count}\n"
        "- Blinding: model identities and source case identifiers are not included.\n"
        "- Readers: reader_a and reader_b annotate independently; adjudication is completed only after both readers finish.\n"
        "- Finding guidance: `annotation/guidelines/finding_annotation.md`.\n"
        "- Hazard guidance: `annotation/guidelines/hazard_annotation.md`.\n"
        "- This pilot is for guideline calibration and must not be used as a formal test set.\n"
    )
