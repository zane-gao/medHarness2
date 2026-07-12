from __future__ import annotations

from pathlib import Path
import re
import subprocess

import yaml


def test_project_status_has_current_release_evidence():
    payload = yaml.safe_load(Path("docs/project_status.yaml").read_text(encoding="utf-8"))

    assert payload["schema_version"] == "1.0"
    assert payload["current_phase"]
    assert payload["baseline"]["pytest_passed"] >= 210
    assert Path(payload["baseline"]["current_run"]).exists()
    assert set(payload["workstreams"]) >= {
        "contracts",
        "tools",
        "generation",
        "clinical_validation",
        "experiments",
        "figures",
    }

    allowed = {"not_started", "in_progress", "validated", "deferred"}
    for workstream in payload["workstreams"].values():
        assert workstream["status"] in allowed
        assert workstream["next_gate"]
        for evidence_path in workstream.get("evidence_paths", []):
            assert Path(evidence_path).exists(), evidence_path


def test_generated_web_pages_are_ignored_but_templates_are_trackable():
    generated_pages = [
        "web/index.html",
        "web/control_panel.html",
        "web/legacy/index.html",
        "web/legacy/control_panel.html",
    ]
    templates = [
        "web/panel_template.html",
        "web/legacy/template.html",
        "src/medharness2/templates/control_panel_template.html",
    ]

    for path in generated_pages:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", path],
            check=False,
        )
        assert result.returncode == 0, path

    for path in templates:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", path],
            check=False,
        )
        assert result.returncode == 1, path


def test_web_builder_does_not_hardcode_clinical_case_ids():
    builder = Path("web/build_panel.py").read_text(encoding="utf-8")

    assert re.search(r"\b(?:CT|MR|MRI|DX|CR|XR)\d{8,}\b", builder) is None
