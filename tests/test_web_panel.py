from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "web"))
import build_panel
from medharness2 import research_prep
from medharness2.dashboard import _format_gate_status, _render_fail_count, _render_modelsrc_rows, summarize_dashboard_payload
from medharness2.dashboard import _render_kpis, _render_health_strip


def test_extract_git_state_reports_branch_sha_and_dirty(tmp_path):
    state = build_panel.extract_git_state()

    assert set(state) >= {"branch", "sha", "short_sha", "dirty"}
    assert state["branch"]
    assert len(state["sha"]) == 40
    assert state["short_sha"] == state["sha"][:7]
    assert isinstance(state["dirty"], bool)


def test_extract_git_state_ignores_panel_output_itself(monkeypatch):
    responses = {
        ("branch", "--show-current"): "main\n",
        ("rev-parse", "HEAD"): "a" * 40 + "\n",
        ("rev-parse", "--short=7", "HEAD"): "aaaaaaa\n",
        ("status", "--porcelain", "--untracked-files=no"): " M web/index.html\n",
    }

    def fake_check_output(args, **kwargs):
        return responses[tuple(args[3:])]

    monkeypatch.setattr(build_panel.subprocess, "check_output", fake_check_output)
    state = build_panel.extract_git_state(build_panel.REPO)
    assert state["dirty"] is False


def test_extract_paper_gate_is_blocked_when_external_evidence_is_missing(tmp_path):
    gate = build_panel.extract_paper_evidence_gate(
        research_dir=tmp_path / "research",
        annotation_dir=tmp_path / "annotation",
        experiment_results=tmp_path / "experiments.json",
    )
    assert gate["status"] == "blocked"
    assert gate["formal_claim_allowed"] is False
    assert {item["id"] for item in gate["checks"]} == {
        "clinical_reader_annotation",
        "ocr_winner",
        "formal_experiments",
    }


def test_extract_paper_gate_rejects_status_only_experiments(tmp_path):
    experiments = tmp_path / "experiments.json"
    experiments.write_text('{"experiments": [{"status": "validated"}]}', encoding="utf-8")
    gate = build_panel.extract_paper_evidence_gate(
        research_dir=tmp_path / "research",
        annotation_dir=tmp_path / "annotation",
        experiment_results=experiments,
    )
    formal = next(item for item in gate["checks"] if item["id"] == "formal_experiments")
    assert formal["passed"] is False


def test_extract_paper_gate_rejects_thin_ocr_winner(tmp_path):
    research = tmp_path / "research"
    research.mkdir()
    (research / "ocr_manifest.json").write_text(
        '{"status":"succeeded","winner_status":"validated","benchmark_results":{"1":{"status":"succeeded"},"2":{"status":"succeeded"}}}',
        encoding="utf-8",
    )
    gate = build_panel.extract_paper_evidence_gate(
        research_dir=research,
        annotation_dir=tmp_path / "annotation",
        experiment_results=tmp_path / "experiments.json",
    )
    ocr = next(item for item in gate["checks"] if item["id"] == "ocr_winner")
    assert ocr["passed"] is False


def test_dashboard_paper_gate_reuses_research_gate_helpers():
    assert build_panel._validated_ocr_winner is research_prep._validated_ocr_winner
    assert build_panel._validated_experiments is research_prep._validated_experiments
    assert build_panel._validation_errors is research_prep._validation_errors


def test_extract_paper_gate_requires_ocr_freeze_metadata(tmp_path):
    research = tmp_path / "research"
    research.mkdir()
    (research / "ocr_manifest.json").write_text(
        '{"status":"succeeded","winner_status":"frozen",'
        '"gold_source":"beichuan_reference_report",'
        '"gold_status":"available_for_current_benchmark",'
        '"winner_model":"doubao", "freeze_id":"' + "f" * 64 + '",'
        '"benchmark_results":{"1":{"status":"succeeded","selection":{"status":"provisional","primary_model":"doubao"}},'
        '"2":{"status":"succeeded","selection":{"status":"provisional","primary_model":"doubao"}}}}',
        encoding="utf-8",
    )
    gate = build_panel.extract_paper_evidence_gate(
        research_dir=research,
        annotation_dir=tmp_path / "annotation",
        experiment_results=tmp_path / "experiments.json",
    )
    ocr = next(item for item in gate["checks"] if item["id"] == "ocr_winner")
    assert ocr["passed"] is False


def test_dashboard_summary_preserves_explicit_zero_counts():
    summary = summarize_dashboard_payload(
        {
            "run_summary": {"summary": {"case_count": 0}},
            "analysis": {"case_count": 7},
            "experiments": {"experiment_count": 0},
            "figures": {"figure_count": 0, "figures": [{"id": "stale"}]},
        }
    )

    assert summary["case_count"] == 0
    assert summary["experiment_count"] == 0
    assert summary["figure_count"] == 0


@pytest.mark.parametrize("field_path,label", [
    (("run_summary", "summary", "case_count"), "case_count"),
    (("experiments", "experiment_count"), "experiment_count"),
    (("figures", "figure_count"), "figure_count"),
])
@pytest.mark.parametrize("bad", [True, 1.5, "2", -1])
def test_dashboard_summary_rejects_invalid_external_counts(field_path, label, bad):
    payload = {"run_summary": {"summary": {"case_count": 0}}, "experiments": {"experiment_count": 0}, "figures": {"figure_count": 0}}
    target = payload
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = bad
    with pytest.raises(ValueError, match=label):
        summarize_dashboard_payload(payload)


@pytest.mark.parametrize(
    ("field_path", "bad", "label"),
    [
        (("run_summary",), "bad", "run_summary"),
        (("run_summary", "summary"), [], "run_summary.summary"),
        (("analysis",), [], "analysis"),
        (("catalog", "tools"), {}, "catalog.tools"),
        (("figures", "figures"), "bad", "figures.figures"),
        (("run_registry", "entries"), {}, "run_registry.entries"),
        (("experiments",), [], "experiments"),
    ],
)
def test_dashboard_summary_rejects_malformed_external_shapes(field_path, bad, label):
    payload = {
        "run_summary": {"summary": {"case_count": 0}},
        "analysis": {},
        "catalog": {"tools": [], "models": []},
        "figures": {"figure_count": 0, "figures": []},
        "run_registry": {"entries": []},
        "experiments": {"experiment_count": 0},
    }
    target = payload
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = bad
    with pytest.raises(ValueError, match=label):
        summarize_dashboard_payload(payload)


@pytest.mark.parametrize(
    ("field_path", "label"),
    [
        (("catalog", "tools"), "catalog.tools"),
        (("catalog", "models"), "catalog.models"),
        (("experiments", "experiments"), "experiments.experiments"),
        (("figures", "figures"), "figures.figures"),
        (("run_registry", "entries"), "run_registry.entries"),
    ],
)
def test_dashboard_summary_rejects_malformed_list_items(field_path, label):
    payload = {
        "run_summary": {"summary": {"case_count": 0}},
        "analysis": {},
        "catalog": {"tools": [], "models": []},
        "figures": {"figure_count": 0, "figures": []},
        "run_registry": {"entries": []},
        "experiments": {"experiment_count": 0, "experiments": []},
    }
    target = payload
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = ["malformed"]
    with pytest.raises(ValueError, match=label):
        if field_path[0] in {"catalog", "experiments", "figures", "run_registry"}:
            from medharness2.dashboard import _build_template_fragments

            _build_template_fragments(payload)


@pytest.mark.parametrize(
    ("field", "bad", "label"),
    [
        ("readers", ["bad"], "analysis_tables.readers"),
        ("quality_gate_failures", ["bad"], "analysis_tables.quality_gate_failures"),
    ],
)
def test_dashboard_render_rejects_malformed_analysis_table_rows(field, bad, label):
    from medharness2.dashboard import _build_template_fragments

    payload = {
        "run_dir": ".",
        "catalog": {"providers": {"model_roles": {}}, "tools": [], "models": [], "workflow_stages": []},
        "experiments": {"experiments": []},
        "experiment_protocol": {"experiments": []},
        "run_summary": {"summary": {}, "validation": {}},
        "analysis": {},
        "analysis_tables": {field: bad},
        "run_registry": {"entries": []},
        "figures": {"figures": []},
    }
    with pytest.raises(ValueError, match=label):
        _build_template_fragments(payload)


def test_dashboard_render_rejects_malformed_provider_role():
    from medharness2.dashboard import _build_template_fragments

    payload = {
        "run_dir": ".",
        "catalog": {
            "providers": {"model_roles": {"ocr_primary": "bad"}},
            "tools": [], "models": [], "workflow_stages": [],
        },
        "experiments": {"experiments": []},
        "experiment_protocol": {"experiments": []},
        "run_summary": {"summary": {}, "validation": {}},
        "analysis": {}, "analysis_tables": {},
        "run_registry": {"entries": []}, "figures": {"figures": []},
    }
    with pytest.raises(ValueError, match="catalog.providers.model_roles"):
        _build_template_fragments(payload)


@pytest.mark.parametrize("field", ["passed", "total"])
@pytest.mark.parametrize("bad", [True, 1.5, "2", -1])
def test_dashboard_gate_status_rejects_invalid_counts(field, bad):
    item = {"gate_summary": {"passed": 1, "total": 2}, "validation_gates": []}
    item["gate_summary"][field] = bad
    with pytest.raises(ValueError, match=field):
        _format_gate_status(item)


@pytest.mark.parametrize("bad", [True, 1.5, "2.5", "oops", -1])
def test_dashboard_csv_count_renderer_rejects_invalid_values(bad):
    with pytest.raises(ValueError, match="count"):
        _render_fail_count(bad)


def test_dashboard_csv_count_renderer_accepts_integer_text():
    assert ">2<" in _render_fail_count("2")


def test_dashboard_model_rows_reject_invalid_report_count():
    with pytest.raises(ValueError, match="count"):
        _render_modelsrc_rows([{"model": "m", "report_count": "2.5"}])


def test_dashboard_kpis_preserve_explicit_zero_counts():
    html = _render_kpis(
        {"case_count": 0, "reader_count": 0},
        {"real_ocr_count": 0},
        {"case_count": 9, "reader_count": 8, "generated_report_count": 0, "ranking_count": 0},
        {"models": [], "tools": [], "workflow_stages": []},
        {"experiment_count": 0},
        {"figure_count": 0},
    )

    assert "病例 Cases" in html
    assert "读者 Readers" in html
    assert html.count(">0<") >= 4


def test_health_strip_does_not_treat_validation_pass_as_ocr_ready():
    html = _render_health_strip(
        {"passed": True, "require_real_ocr": False, "mock_ocr_count": 0},
        {},
    )

    assert "OCR 就绪状态未知" in html
    assert "OCR ready（运行证据）" not in html


def test_health_strip_surfaces_preflight_ocr_blocker():
    html = _render_health_strip(
        {
            "passed": True,
            "mock_ocr_count": 0,
            "ocr": {
                "status": "missing_api_key",
                "blocker": "missing_llm_api_key",
                "real_ocr_capable": False,
            },
        },
        {},
    )

    assert "OCR 未就绪: missing_llm_api_key" in html


@pytest.mark.parametrize("bad", [1, 0, "true", [], {}])
def test_health_strip_rejects_implicit_boolean_coercion(bad):
    with pytest.raises(ValueError, match="boolean"):
        _render_health_strip(
            {"passed": bad, "require_real_ocr": False, "mock_ocr_count": 0},
            {},
        )


@pytest.mark.parametrize("bad", [1, 0, "true", [], {}])
def test_health_strip_rejects_malformed_ocr_boolean(bad):
    with pytest.raises(ValueError, match="boolean"):
        _render_health_strip(
            {
                "passed": True,
                "mock_ocr_count": 0,
                "ocr": {"status": "ready", "real_ocr_capable": bad},
            },
            {},
        )


@pytest.mark.parametrize("bad", [1, 0, "true", [], {}])
def test_status_chip_rejects_implicit_boolean_coercion(bad):
    from medharness2.dashboard import _render_status_chip

    with pytest.raises(ValueError, match="boolean"):
        _render_status_chip({"passed": bad})


@pytest.mark.parametrize("bad", [1, 0, "true", [], {}])
def test_dashboard_model_policy_rejects_implicit_boolean_coercion(bad):
    from medharness2.dashboard import _format_medical_model_policy

    with pytest.raises(ValueError, match="boolean"):
        _format_medical_model_policy(bad)


def test_extract_project_status_uses_real_yaml():
    path = Path("docs/project_status.yaml")
    status = build_panel.extract_project_status(path)

    assert status["release_readiness"] == "pilot_only"
    assert status["baseline"]["case_count"] == 52
    assert "control_panel" in status["workstreams"]


def test_extract_project_status_rejects_missing_or_invalid_ledgers(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_panel.extract_project_status(tmp_path / "missing.yaml")

    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("pilot_only\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        build_panel.extract_project_status(scalar)

    missing = tmp_path / "missing_workstreams.yaml"
    missing.write_text("release_readiness: pilot_only\n", encoding="utf-8")
    with pytest.raises(ValueError, match="workstreams"):
        build_panel.extract_project_status(missing)


def test_extract_workstreams_includes_release_readiness(tmp_path):
    path = tmp_path / "project_status.yaml"
    path.write_text(
        "release_readiness: pilot_only\nworkstreams: {}\n",
        encoding="utf-8",
    )

    assert build_panel.extract_workstreams(path)["release_readiness"] == "pilot_only"


def test_extract_workstreams_preserves_nested_yaml_values(tmp_path):
    path = tmp_path / "project_status.yaml"
    path.write_text(
        """updated_at: '2026-07-14'
current_phase: 'pilot: only'
workstreams:
  control_panel:
    status: in_progress
    summary: 'keep: quoted value'
""",
        encoding="utf-8",
    )

    workstreams = build_panel.extract_workstreams(path)

    assert workstreams["phase"] == "pilot: only"
    assert workstreams["workstreams"]["control_panel"]["summary"] == "keep: quoted value"


def test_source_health_distinguishes_required_and_optional_files(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run_summary.json").write_text("{}", encoding="utf-8")

    health = build_panel.source_health({"core_run": run_dir / "run_summary.json", "optional": run_dir / "optional.json"}, root=tmp_path)

    assert health["core_run"] == {"path": "run/run_summary.json", "available": True}
    assert health["optional"] == {"path": "run/optional.json", "available": False}


def test_require_core_run_raises_when_summary_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_panel.require_core_run(tmp_path)


def test_require_core_run_checks_all_core_inputs(tmp_path):
    (tmp_path / "run_summary.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="analysis_summary.json"):
        build_panel.require_core_run(tmp_path)


def test_build_data_exposes_project_meta_and_source_health(tmp_path, monkeypatch):
    run_dir = Path("outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_v2_qualityfix_20260710")
    monkeypatch.setattr(build_panel, "STATUS_YAML", Path("docs/project_status.yaml"))

    data = build_panel.build_data(run_dir)

    assert "project_meta" in data
    assert data["project_meta"]["status"]["release_readiness"] == "pilot_only"
    assert "source_health" in data
    assert data["source_health"]["core_run"]["available"] is True
    assert set(data["source_health"]) >= {"core_run", "dmx_evaluation", "generation_benchmark", "ocr_audit", "experiment_results", "pilot10_manifest"}
    assert "source_case_count" in data["kpi"]
    assert "failure_rate" in data["kpi"]


def test_optional_dashboard_float_preserves_missing_values_as_null():
    assert build_panel._optional_rounded_float("", 3) is None
    assert build_panel._optional_rounded_float("not-a-score", 3) is None
    assert build_panel._optional_rounded_float("0", 3) == 0.0
    assert build_panel._optional_rounded_float("0.756", 2) == 0.76


def test_legacy_dashboard_does_not_zero_fill_missing_reader_metrics():
    legacy = Path("web/legacy/control_panel.html").read_text(encoding="utf-8")
    assert "if (!Number.isFinite(rawScore)) return null;" in legacy
    assert "百分位缺失" in legacy
    assert "var score = Number(r.overall_score) || 0;" not in legacy
    assert "Math.round(Number(r.percentile) || 0)" not in legacy


def test_extract_pilot10_uses_annotation_validator_for_completion(tmp_path):
    package = tmp_path / "pilot10"
    cases = package / "cases"
    cases.mkdir(parents=True)
    (package / "manifest.jsonl").write_text(
        '{"pilot_case_id":"pilot-001","modality":"cxr","body_part":"chest","annotation_path":"cases/pilot-001.json","status":"not_started"}\n',
        encoding="utf-8",
    )
    (cases / "pilot-001.json").write_text(
        '{"schema_version":"2.0","artifact_type":"clinical_annotation_case","pilot_case_id":"pilot-001",'
        '"source_case_sha256":"' + 'a' * 64 + '","modality":"cxr","body_part":"chest","reference_report":"",'
        '"candidate_reports":[],"annotations":{"reader_a":{"reader_slot":"reader_a","status":"not_started",'
        '"findings":[],"hazards":[],"overall_notes":"","confidence":null},"reader_b":{"reader_slot":"reader_b",'
        '"status":"not_started","findings":[],"hazards":[],"overall_notes":"","confidence":null},'
        '"adjudication":{"reader_slot":"adjudication","status":"not_started","findings":[],"hazards":[],'
        '"overall_notes":"","confidence":null}}}\n',
        encoding="utf-8",
    )

    result = build_panel.extract_pilot10(package / "manifest.jsonl")

    assert result["done"] == 0
    assert result["validation_status"] == "blocked"
    assert any("no_candidate_reports" in error for error in result["validation_errors"])


def test_extract_pilot10_reports_blocked_manifest_without_crashing(tmp_path):
    package = tmp_path / "pilot10"
    package.mkdir()
    manifest = package / "manifest.jsonl"
    manifest.write_text('{"pilot_case_id":"pilot-001"}\nnot-json\n', encoding="utf-8")

    result = build_panel.extract_pilot10(manifest)

    assert result is not None
    assert result["validation_status"] == "blocked"
    assert result["done"] == 0
    assert result["validation_errors"]


def test_panel_uses_canonical_pilot10_status_labels():
    template = Path("web/panel_template.html").read_text(encoding="utf-8")

    assert 'complete:"已完成"' in template
    assert 'blocked:"已阻断"' in template


def test_panel_describes_modality_first_soft_body_part_routing():
    template = Path("web/panel_template.html").read_text(encoding="utf-8")

    assert "三种主模态" in template
    assert "部位只参与候选排序" in template
    assert "部位冲突保留为可审计 warning" in template
    assert "按「模态 + 部位」路由" not in template


def test_extract_blindspot_audit_parses_heading_and_medium_issue_formats():
    audit = build_panel.extract_blindspot_audit(Path("docs/blindspot_audit_20260714.md"))

    assert audit["critical_issues"]
    assert audit["critical_issues"][0]["id"] == "C1"
    assert audit["medium_issues"]
    assert audit["medium_issues"][0]["id"] == "M1"
    assert any(item["id"] == "H8" for item in audit["high_issues"])
    assert audit["fix_priority"]["tier1"]


def test_filter_deferred_audit_items_removes_security_findings_from_panel_payload():
    audit = {
        "critical_issues": [{"id": "C1"}, {"id": "C2"}],
        "high_issues": [{"id": "H1"}, {"id": "H5"}],
        "fix_priority": {"tier1": [{"id": "H1"}], "tier2": [{"id": "C1"}], "tier3": [{"id": "H5"}]},
    }
    filtered = build_panel.filter_deferred_audit_items(audit)
    assert [item["id"] for item in filtered["critical_issues"]] == ["C2"]
    assert [item["id"] for item in filtered["high_issues"]] == ["H5"]
    assert filtered["fix_priority"] == {"tier1": [], "tier2": [], "tier3": [{"id": "H5"}]}
