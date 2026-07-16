from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from medharness2.catalog import build_capability_catalog
from medharness2.config import AppConfig
from medharness2.utils.io import read_json
from medharness2.workflows.experiments import build_experiment_protocol, build_experiment_results

# 控制面板模板随包分发（pyproject 的 package-data 已含 templates/*.html）
_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "control_panel_template.html"


def build_dashboard(
    run_dir: str | Path,
    output_path: str | Path,
    *,
    config: AppConfig | None = None,
) -> dict[str, Any]:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = build_dashboard_payload(run_dir, config=config)
    output.write_text(_render_html(payload), encoding="utf-8")
    return {
        "output_path": str(output),
        "summary": summarize_dashboard_payload(payload),
    }


def build_dashboard_summary(
    run_dir: str | Path,
    *,
    registry_entry_count_delta: int = 0,
    config: AppConfig | None = None,
) -> dict[str, int]:
    summary = summarize_dashboard_payload(build_dashboard_payload(run_dir, config=config))
    summary["registry_entry_count"] += registry_entry_count_delta
    return summary


def build_dashboard_payload(run_dir: str | Path, *, config: AppConfig | None = None) -> dict[str, Any]:
    root = Path(run_dir)
    if not root.is_dir():
        raise ValueError("run_dir_not_found")
    run_summary = _read_optional(root / "run_summary.json")
    analysis = _read_optional(root / "analysis" / "analysis_summary.json")
    workflow3 = _read_optional(root / "workflow3.json")
    registry = _read_optional(root / "run_registry.json")
    catalog = build_capability_catalog(config)
    experiments = build_experiment_results(root)
    protocol = _experiment_protocol_from_registry(registry, experiments)
    figures = _figure_manifest_from_registry(registry)
    return {
        "run_dir": str(root),
        "run_summary": run_summary,
        "analysis": analysis,
        "analysis_tables": _read_analysis_tables(root),
        "workflow3": workflow3,
        "run_registry": registry,
        "catalog": catalog,
        "experiments": experiments,
        "experiment_protocol": protocol,
        "figures": figures,
    }


# 面板要展示的 analysis CSV：键名 -> (文件名, 最多保留行数)
_ANALYSIS_TABLES = {
    "readers": ("reader_summary.csv", 64),
    "model_source": ("model_source_summary.csv", 128),
    "modality_body_part": ("modality_body_part_summary.csv", 128),
    "quality_gate_failures": ("quality_gate_failures.csv", 200),
    "case_routes": ("case_routes.csv", 400),
}


def _read_analysis_tables(root: Path) -> dict[str, list[dict[str, str]]]:
    tables: dict[str, list[dict[str, str]]] = {}
    for key, (filename, limit) in _ANALYSIS_TABLES.items():
        path = root / "analysis" / filename
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                tables[key] = list(csv.DictReader(handle))[:limit]
        except (OSError, csv.Error):
            continue
    return tables


def summarize_dashboard_payload(payload: dict[str, Any]) -> dict[str, int]:
    run_summary = payload.get("run_summary") or {}
    analysis = payload.get("analysis") or {}
    registry = payload.get("run_registry") or {}
    figures = payload.get("figures") or {}
    catalog = payload.get("catalog") or {}
    experiments = payload.get("experiments") or {}
    run_summary_values = run_summary.get("summary") or {}
    case_count = _first_present(
        run_summary_values.get("case_count") if "case_count" in run_summary_values else None,
        analysis.get("case_count") if "case_count" in analysis else None,
        0,
    )
    figure_count = _first_present(
        figures.get("figure_count") if "figure_count" in figures else None,
        len(figures.get("figures") or []),
    )
    return {
        "case_count": int(case_count),
        "tool_count": len(catalog.get("tools") or []),
        "model_count": len(catalog.get("models") or []),
        "experiment_count": int(experiments.get("experiment_count", 0)),
        "figure_count": int(figure_count),
        "registry_entry_count": len(registry.get("entries") or []),
    }


def _first_present(*values: Any) -> Any:
    """Return the first non-None value, preserving explicit zeroes."""
    for value in values:
        if value is not None:
            return value
    return 0


def _read_optional(path: Path) -> dict[str, Any]:
    return read_json(path) if path.exists() else {}


def _render_html(payload: dict[str, Any]) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = _build_template_fragments(payload)
    html = template
    for token, fragment in replacements.items():
        html = html.replace(token, fragment)
    return html


# ---------------------------------------------------------------------------
# 模板片段渲染（模板含大量 CSS/JS 花括号，故用 token 替换而非 str.format）
# ---------------------------------------------------------------------------

_STATUS_BADGE_CLASSES = {
    "implemented_v1": "b-ok",
    "v1_complete": "b-ok",
    "passed": "b-ok",
    "pilot": "b-warn",
    "partial": "b-warn",
    "validated": "b-ok",
    "not_ready": "b-critical",
    "designed": "b-critical",
    "not_implemented": "b-critical",
    "failed": "b-critical",
}

# 工具实现类型 -> (徽章样式, 中文短标)，回答“API / 本地模型 / 代码模板”这一问题
_TOOL_TYPE_BADGES = {
    "llm_or_deterministic": ("b-hybrid", "LLM API + 确定性兜底"),
    "llm_or_rules": ("b-hybrid", "LLM API + 规则兜底"),
    "rules_or_placeholder": ("b-rule", "规则 + 占位"),
    "dicom_rules_or_vlm": ("b-local", "DICOM 规则 + VLM"),
    "local_model_or_fallback": ("b-local", "本地模型 + 兜底"),
    "deterministic_code": ("b-code", "规则 / 代码"),
}

_SOURCE_LABELS = {
    "medharness_cli": "CLI 新推理",
    "artifact_reuse": "工件复用",
    "local_vlm_fallback": "VLM 兜底",
}


def _status_badge(status: Any) -> str:
    text = str(status or "unknown")
    cls = _STATUS_BADGE_CLASSES.get(text, "b-plain")
    return f'<span class="badge {cls}">{_esc(text)}</span>'


def _tool_type_badge(impl_type: Any) -> str:
    cls, label = _TOOL_TYPE_BADGES.get(str(impl_type or ""), ("b-plain", str(impl_type or "unknown")))
    return f'<span class="badge {cls}" title="{_esc(impl_type)}">{_esc(label)}</span>'


def _source_chip(source: Any) -> str:
    text = str(source or "")
    label = _SOURCE_LABELS.get(text, text)
    return f'<span class="mchip" title="{_esc(text)}"><b>{_esc(label)}</b></span>'


def _warning_chips(raw: Any, sep: str = ";") -> str:
    parts = [p.strip() for p in str(raw or "").split(sep) if p.strip()]
    if not parts:
        return '<span style="color:var(--ink-3)">—</span>'
    return "".join(f'<span class="mchip">{_esc(p)}</span>' for p in parts)


def _empty_row(colspan: int, message: str = "暂无数据") -> str:
    return f'<tr><td colspan="{colspan}" style="color:var(--ink-3);text-align:center">{_esc(message)}</td></tr>'


def _build_template_fragments(payload: dict[str, Any]) -> dict[str, str]:
    catalog = payload["catalog"]
    experiments = payload["experiments"]
    protocol = payload.get("experiment_protocol") or {}
    run_summary = payload.get("run_summary") or {}
    summary = run_summary.get("summary") or {}
    validation = run_summary.get("validation") or {}
    analysis = payload.get("analysis") or {}
    tables = payload.get("analysis_tables") or {}
    registry = payload.get("run_registry") or {}
    figures = payload.get("figures") or {}

    # JSON 嵌入 <script type="application/json">：转义 "</" 防止提前闭合标签
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    return {
        "__MH2_RUN_ID__": _esc(Path(payload.get("run_dir") or ".").name or "(无运行目录)"),
        "__MH2_STATUS_CHIP__": _render_status_chip(validation),
        "__MH2_GENERATED__": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "__MH2_KPI__": _render_kpis(summary, validation, analysis, catalog, experiments, figures),
        "__MH2_HEALTH__": _render_health_strip(validation, analysis),
        "__MH2_READER_ROWS__": _render_reader_rows(tables.get("readers") or []),
        "__MH2_MODBP_ROWS__": _render_modbp_rows(tables.get("modality_body_part") or []),
        "__MH2_MODELSRC_ROWS__": _render_modelsrc_rows(tables.get("model_source") or []),
        "__MH2_QGF_BLOCK__": _render_qgf_block(tables.get("quality_gate_failures") or []),
        "__MH2_ROUTES_BLOCK__": _render_routes_block(tables.get("case_routes") or []),
        "__MH2_WORKFLOW_ROWS__": _render_workflow_rows(catalog.get("workflow_stages") or []),
        "__MH2_TOOL_CARDS__": _render_tool_cards(catalog.get("tools") or []),
        "__MH2_TOOL_TABLE_ROWS__": _render_tool_table_rows(catalog.get("tools") or []),
        "__MH2_MODEL_COUNT__": str(len(catalog.get("models") or [])),
        "__MH2_MODEL_ROWS__": _render_model_rows(catalog.get("models") or []),
        "__MH2_ROLE_CARDS__": _render_role_cards(catalog.get("providers") or {}),
        "__MH2_EXPERIMENT_CARDS__": _render_experiment_cards(experiments.get("experiments") or []),
        "__MH2_PROTOCOL_CARDS__": _render_protocol_cards(protocol.get("experiments") or []),
        "__MH2_FIGURE_GALLERY__": _render_figure_gallery(figures.get("figures") or []),
        "__MH2_REGISTRY_ROWS__": _render_registry_rows(registry.get("entries") or []),
        "__MH2_PAYLOAD__": payload_json,
    }


def _render_status_chip(validation: dict[str, Any]) -> str:
    if not validation:
        return '<span class="chip"><span class="dot"></span>未运行验证</span>'
    if validation.get("passed"):
        return '<span class="chip ok"><span class="dot"></span>验证通过</span>'
    return '<span class="chip bad"><span class="dot"></span>验证未通过</span>'


def _count_or_zero(value: Any, label: str) -> int:
    if value is None:
        return 0
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _render_kpis(
    summary: dict[str, Any],
    validation: dict[str, Any],
    analysis: dict[str, Any],
    catalog: dict[str, Any],
    experiments: dict[str, Any],
    figures: dict[str, Any],
) -> str:
    case_count = _count_or_zero(_first_present(summary.get("case_count"), analysis.get("case_count"), 0), "case_count")
    reader_count = _count_or_zero(_first_present(summary.get("reader_count"), analysis.get("reader_count"), 0), "reader_count")
    generated = _count_or_zero(_first_present(analysis.get("generated_report_count"), 0), "generated_report_count")
    ranking = _count_or_zero(_first_present(analysis.get("ranking_count"), 0), "ranking_count")
    qg_pass = _count_or_zero(_first_present(analysis.get("quality_gate_passed_count"), 0), "quality_gate_passed_count")
    qg_fail = _count_or_zero(_first_present(analysis.get("quality_gate_failed_count"), 0), "quality_gate_failed_count")
    qg_total = qg_pass + qg_fail
    pass_rate = f"{qg_pass / qg_total * 100:.0f}%" if qg_total else "—"
    tiles = [
        ("病例 Cases", case_count, f"真实 OCR {_count_or_zero(validation.get('real_ocr_count'), 'real_ocr_count')} 例"),
        ("读者 Readers", reader_count, "doctor vs model"),
        ("候选报告", generated, f"排名 {ranking} 组"),
        ("质量门控通过率", pass_rate, f"{qg_pass} 过 / {qg_fail} 失败"),
        ("注册模型", len(catalog.get("models") or []), "报告生成注册表"),
        ("工具 / 阶段", f"{len(catalog.get('tools') or [])} / {len(catalog.get('workflow_stages') or [])}", "Tool / Workflow stage"),
        ("实验研究", _count_or_zero(_first_present(experiments.get("experiment_count"), 0), "experiment_count"), "Notion 协议映射"),
        ("图表产物", _count_or_zero(_first_present(figures.get("figure_count"), 0), "figure_count"), "Fig + Table"),
    ]
    return "".join(
        '<div class="kpi">'
        f'<span class="kpi-lab">{_esc(label)}</span>'
        f'<span class="kpi-val">{_esc(value)}</span>'
        f'<span class="kpi-sub">{_esc(sub)}</span>'
        "</div>"
        for label, value, sub in tiles
    )


def _render_health_strip(validation: dict[str, Any], analysis: dict[str, Any]) -> str:
    chips: list[str] = []

    def chip(ok: bool, text: str) -> str:
        cls = "ok" if ok else "bad"
        return f'<span class="chip {cls}"><span class="dot"></span>{_esc(text)}</span>'

    if validation:
        chips.append(chip(bool(validation.get("passed")), "validate-run " + ("passed" if validation.get("passed") else "failed")))
        mock = _count_or_zero(validation.get("mock_ocr_count"), "mock_ocr_count")
        chips.append(chip(mock == 0, f"mock OCR {mock}"))
        ocr = validation.get("ocr") or {}
        if ocr:
            ocr_status = str(ocr.get("status") or "unknown")
            ocr_ready = bool(ocr.get("real_ocr_capable")) and ocr_status == "ready"
            label = "OCR ready" if ocr_ready else f"OCR 未就绪: {ocr.get('blocker') or ocr_status}"
            chips.append(chip(ocr_ready, label))
        else:
            required = bool(validation.get("require_real_ocr"))
            real = _count_or_zero(validation.get("real_ocr_count"), "real_ocr_count")
            unknown = _count_or_zero(validation.get("unknown_ocr_count"), "unknown_ocr_count")
            if required and real > 0 and mock == 0 and unknown == 0:
                chips.append(chip(True, "OCR ready（运行证据）"))
            else:
                chips.append(chip(False, "OCR 就绪状态未知"))
    failed_cases = _count_or_zero(analysis.get("failed_case_count"), "failed_case_count")
    chips.append(chip(failed_cases == 0, f"失败病例 {failed_cases}"))
    qg_fail = _count_or_zero(analysis.get("quality_gate_failed_count"), "quality_gate_failed_count")
    chips.append(chip(qg_fail == 0, f"质量门控失败 {qg_fail}"))
    warn_counts = analysis.get("generated_report_warning_counts") or {}
    fallback = _count_or_zero(warn_counts.get("local_vlm_fallback_used"), "local_vlm_fallback_used")
    if fallback:
        chips.append(chip(False, f"VLM 兜底 {fallback} 份"))
    artifact = _count_or_zero(warn_counts.get("artifact_reuse_not_fresh_inference"), "artifact_reuse_not_fresh_inference")
    if artifact:
        chips.append(chip(False, f"工件复用 {artifact} 份（非新推理）"))
    return "".join(chips)


def _esc(value: Any) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _figure_manifest_from_registry(registry: dict[str, Any]) -> dict[str, Any]:
    for entry in reversed(registry.get("entries") or []):
        if entry.get("stage") != "figures.build":
            continue
        manifest = ((entry.get("outputs") or {}).get("figure_manifest") or "")
        if not manifest:
            continue
        payload = _read_optional(Path(str(manifest)))
        if payload:
            return payload
    return {"schema_version": "1.0", "figure_count": 0, "figures": []}


def _experiment_protocol_from_registry(registry: dict[str, Any], experiments: dict[str, Any]) -> dict[str, Any]:
    for entry in reversed(registry.get("entries") or []):
        if entry.get("stage") != "experiments.run":
            continue
        protocol = ((entry.get("outputs") or {}).get("experiment_protocol") or "")
        if not protocol:
            continue
        payload = _read_optional(Path(str(protocol)))
        if payload:
            return payload
    return build_experiment_protocol(experiments)


def _format_io(rows: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for row in rows:
        name = row.get("name", "")
        data_format = row.get("format", "")
        path = row.get("path_template", "")
        required = "required" if row.get("required") else "optional"
        if path:
            parts.append(f"{name}: {data_format} -> {path}")
        else:
            parts.append(f"{name}: {data_format} ({required})")
    return "; ".join(parts)


def _format_medical_model_policy(required: Any) -> str:
    return "Required" if bool(required) else "Optional"


def _format_gate_status(item: dict[str, Any]) -> str:
    summary = item.get("gate_summary") or {}
    failed = [str(gate.get("id") or "") for gate in item.get("validation_gates") or [] if not gate.get("passed")]
    counts = f"{int(summary.get('passed') or 0)}/{int(summary.get('total') or 0)} passed"
    return counts if not failed else f"{counts}; pending={','.join(failed)}"


# ---------------------------------------------------------------------------
# 各版块片段渲染
# ---------------------------------------------------------------------------


def _render_reader_rows(rows: list[dict[str, str]]) -> str:
    # Reader tables represent the scored population.  Do not render a missing
    # overall_score as 0, otherwise the dashboard invents a valid-looking
    # score for readers excluded from the statistics.
    scored_rows = [row for row in rows if _to_optional_float(row.get("overall_score")) is not None]
    if not scored_rows:
        return _empty_row(4)
    ordered = sorted(scored_rows, key=lambda r: -(_to_optional_float(r.get("overall_score")) or 0.0))
    return "".join(
        "<tr>"
        f'<td class="primary">{_esc(r.get("reader", ""))}</td>'
        f'<td class="num">{_esc(r.get("case_count", ""))}</td>'
        f'<td class="num">{_to_float(r.get("overall_score")):.4f}</td>'
        f'<td class="num">{_format_percentile(r.get("percentile"))}</td>'
        "</tr>"
        for r in ordered
    )


def _render_modbp_rows(rows: list[dict[str, str]]) -> str:
    if not rows:
        return _empty_row(6)
    return "".join(
        "<tr>"
        f'<td class="primary">{_esc(r.get("modality", ""))}</td>'
        f"<td>{_esc(r.get('body_part', ''))}</td>"
        f'<td class="num">{_esc(r.get("case_count", ""))}</td>'
        f'<td class="num">{_esc(r.get("generated_report_count", ""))}</td>'
        f'<td class="num">{_esc(r.get("quality_passed", ""))}</td>'
        f'<td class="num">{_render_fail_count(r.get("quality_failed"))}</td>'
        "</tr>"
        for r in rows
    )


def _render_modelsrc_rows(rows: list[dict[str, str]]) -> str:
    if not rows:
        return _empty_row(7)
    ordered = sorted(rows, key=lambda r: -_to_float(r.get("report_count")))
    return "".join(
        "<tr>"
        f'<td class="primary mono">{_esc(r.get("model", ""))}</td>'
        f"<td>{_source_chip(r.get('source'))}</td>"
        f'<td class="num">{_esc(r.get("report_count", ""))}</td>'
        f'<td class="num">{_esc(r.get("quality_passed", ""))}</td>'
        f'<td class="num">{_render_fail_count(r.get("quality_failed"))}</td>'
        f'<td class="num">{_esc(r.get("selected_top_n_count", ""))}</td>'
        f"<td>{_warning_chips(r.get('warnings'))}</td>"
        "</tr>"
        for r in ordered
    )


def _render_fail_count(value: Any) -> str:
    n = int(_to_float(value))
    if n <= 0:
        return '<span style="color:var(--ink-3)">0</span>'
    return f'<span style="color:var(--s-serious);font-weight:600">{n}</span>'


def _render_qgf_block(rows: list[dict[str, str]]) -> str:
    if not rows:
        return ""
    body = "".join(
        "<tr>"
        f'<td class="primary mono">{_esc(r.get("case_id", ""))}</td>'
        f"<td>{_esc(r.get('reader', ''))}</td>"
        f"<td>{_esc(r.get('modality', ''))} / {_esc(r.get('body_part', ''))}</td>"
        f'<td class="mono">{_esc(r.get("model", ""))}</td>'
        f"<td>{_source_chip(r.get('source'))}</td>"
        f"<td>{_warning_chips(r.get('warnings'))}</td>"
        f"<td><code>{_esc(r.get('conflicts', ''))}</code></td>"
        "</tr>"
        for r in rows
    )
    return (
        '<details class="fold">'
        f"<summary>质量门控失败清单（{len(rows)} 条）</summary>"
        '<div class="fold-body tbl-wrap"><table>'
        "<thead><tr><th>病例</th><th>读者</th><th>模态/部位</th><th>模型</th><th>来源</th><th>警告</th><th>冲突</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div></details>"
    )


def _render_routes_block(rows: list[dict[str, str]]) -> str:
    if not rows:
        return ""
    body = "".join(
        "<tr>"
        f'<td class="primary mono">{_esc(r.get("case_id", ""))}</td>'
        f"<td>{_esc(r.get('reader', ''))}</td>"
        f"<td>{_esc(r.get('modality', ''))} / {_esc(r.get('body_part', ''))}</td>"
        f'<td class="mono">{_esc(r.get("models", ""))}</td>'
        f"<td>{_esc(r.get('sources', ''))}</td>"
        f'<td class="num">{_esc(r.get("quality_passed", ""))}</td>'
        f'<td class="num">{_render_fail_count(r.get("quality_failed"))}</td>'
        "</tr>"
        for r in rows
    )
    return (
        '<details class="fold">'
        f"<summary>全病例路由表（{len(rows)} 例，支持搜索）</summary>"
        '<div class="fold-body">'
        '<div class="filter-row"><input class="filter-input" id="route-filter" type="search" '
        'placeholder="过滤病例 / 读者 / 模型…" autocomplete="off">'
        f'<span class="filter-count" id="route-count">{len(rows)} 例</span></div>'
        '<div class="tbl-wrap"><table id="route-table">'
        "<thead><tr><th>病例</th><th>读者</th><th>模态/部位</th><th>模型</th><th>来源</th><th>通过</th><th>失败</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div></div></details>"
    )


def _render_workflow_rows(stages: list[dict[str, Any]]) -> str:
    if not stages:
        return _empty_row(6)
    return "".join(
        "<tr>"
        f'<td class="primary mono">{_esc(stage.get("id", ""))}</td>'
        f"<td>{_status_badge(stage.get('development_status'))}</td>"
        f'<td><span class="mchip">{_esc(stage.get("implementation_type", ""))}</span></td>'
        f"<td><code>{_esc(_format_io(stage.get('inputs') or []))}</code></td>"
        f"<td><code>{_esc(_format_io(stage.get('outputs') or []))}</code></td>"
        f"<td><code>{_esc(json.dumps(stage.get('model_policy') or {}, ensure_ascii=False))}</code></td>"
        "</tr>"
        for stage in stages
    )


def _render_tool_cards(tools: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for tool in tools:
        medical = (
            '<span class="badge b-critical">需医学专用模型</span>'
            if tool.get("medical_model_required")
            else '<span class="badge b-plain">医学模型可选</span>'
        )
        inputs = ", ".join(tool.get("inputs") or [])
        outputs = ", ".join(tool.get("outputs") or [])
        cards.append(
            '<article class="tool-card">'
            "<header>"
            f'<h4><span class="tid">{_esc(tool.get("id", ""))}</span> · {_esc(tool.get("name", ""))}</h4>'
            f"{_tool_type_badge(tool.get('implementation_type'))}"
            "</header>"
            f'<p class="tdesc">{_esc(tool.get("implementation", ""))}</p>'
            '<div class="io">'
            f'<span class="io-in">{_esc(inputs)}</span>'
            '<span class="io-arrow">→</span>'
            f'<span class="io-out">{_esc(outputs)}</span>'
            "</div>"
            f"<footer>{medical}</footer>"
            "</article>"
        )
    return "".join(cards)


def _render_tool_table_rows(tools: list[dict[str, Any]]) -> str:
    if not tools:
        return _empty_row(6)
    return "".join(
        "<tr>"
        f'<td class="primary mono">{_esc(tool.get("id", ""))}</td>'
        f"<td>{_esc(tool.get('implementation_type', ''))}</td>"
        f"<td>{_esc(tool.get('implementation', ''))}</td>"
        f"<td>{_esc(_format_medical_model_policy(tool.get('medical_model_required')))}</td>"
        f"<td>{_esc(', '.join(tool.get('inputs') or []))}</td>"
        f"<td>{_esc(', '.join(tool.get('outputs') or []))}</td>"
        "</tr>"
        for tool in tools
    )


def _render_model_rows(models: list[dict[str, Any]]) -> str:
    if not models:
        return _empty_row(6)
    rows: list[str] = []
    for model in models:
        fresh = (
            '<span class="badge b-ok">fresh</span>'
            if model.get("fresh_inference")
            else '<span class="badge b-warn">artifact</span>'
        )
        tier = model.get("evidence_tier")
        tier_chip = f'<span class="mchip">{_esc(tier)}</span>' if tier else ""
        rows.append(
            "<tr>"
            f'<td class="primary mono">{_esc(model.get("key", ""))}<br>'
            f'<span style="color:var(--ink-3);font-size:11px">{_esc(model.get("title", ""))}</span></td>'
            f"<td>{_source_chip(model.get('source'))}{tier_chip}</td>"
            f'<td><span class="mchip">{_esc(model.get("route_role", ""))}</span></td>'
            f"<td>{_esc(', '.join(model.get('supported_modalities') or []))}</td>"
            f"<td>{fresh}</td>"
            f"<td>{_esc(model.get('notes', ''))}</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_role_cards(providers: dict[str, Any]) -> str:
    roles = providers.get("model_roles") or {}
    cards: list[str] = []
    for role, route in roles.items():
        cards.append(
            '<article class="role-card">'
            "<header>"
            f'<h4 class="tid">{_esc(role)}</h4>'
            f'<span class="badge b-hybrid">{_esc(route.get("provider", ""))}</span>'
            "</header>"
            f'<div class="rc-model">{_esc(route.get("model", ""))}</div>'
            '<div class="rc-rows">'
            f"<span><b>端点</b>{_esc(route.get('endpoint_host', 'local/default'))}</span>"
            f"<span><b>密钥</b><code>{_esc(route.get('api_key_env', 'not_required'))}</code></span>"
            f"<span><b>重试</b>{_esc(route.get('max_retries', '—'))} 次 · 超时 {_esc(route.get('timeout_sec', '—'))}s"
            f" · temp {_esc(route.get('temperature', '—'))}</span>"
            "</div></article>"
        )
    if not cards:
        llm = providers.get("llm") or {}
        cards.append(
            '<article class="role-card">'
            f'<header><h4 class="tid">default</h4><span class="badge b-plain">{_esc(llm.get("provider", ""))}</span></header>'
            f'<div class="rc-model">{_esc(llm.get("model", ""))}</div>'
            '<div class="rc-rows">'
            f"<span><b>端点</b>{_esc(llm.get('base_url', ''))}</span>"
            f"<span><b>密钥</b><code>{_esc(llm.get('api_key_env', ''))}</code></span>"
            "</div></article>"
        )
    return "".join(cards)


def _render_experiment_cards(items: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for item in items:
        metric_bits = "".join(
            f'<span class="mchip"><b>{_esc(k)}</b> {_esc(_compact_metric(v))}</span>'
            for k, v in (item.get("metrics") or {}).items()
        )
        cards.append(
            '<article class="exp-card">'
            "<header>"
            f"<h4>{_esc(item.get('title') or item.get('id', ''))}</h4>"
            f"{_status_badge(item.get('status'))}"
            "</header>"
            f'<p class="tdesc mono" style="font-size:11px;color:var(--ink-3)">{_esc(item.get("id", ""))}</p>'
            f"<div>{metric_bits}</div>"
            "</article>"
        )
    return "".join(cards)


def _compact_metric(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k}:{v}" for k, v in value.items())
    return str(value)


def _render_protocol_cards(items: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for item in items:
        policy = item.get("model_policy") or {}
        policy_bits = "".join(f'<span class="mchip"><b>{_esc(k)}</b> {_esc(v)}</span>' for k, v in policy.items())
        evidence = (item.get("current_evidence") or {}).get("metrics") or {}
        evidence_bits = "".join(
            f'<span class="mchip"><b>{_esc(k)}</b> {_esc(_compact_metric(v))}</span>' for k, v in evidence.items()
        )
        limitations = "".join(f"<li>{_esc(t)}</li>" for t in item.get("limitations") or [])
        gate = _format_gate_status(item) if (item.get("gate_summary") or item.get("validation_gates")) else ""
        gate_html = f"<dt>Validation Gates</dt><dd><code>{_esc(gate)}</code></dd>" if gate else ""
        cards.append(
            '<article class="proto-card">'
            "<header>"
            f"<h4>{_esc(item.get('notion_section') or item.get('id', ''))}</h4>"
            f"{_status_badge(item.get('status'))}"
            "</header>"
            f'<p class="rq">{_esc(item.get("research_question", ""))}</p>'
            "<dl>"
            f"<div><dt>Implementation · 实现</dt><dd>{_esc((item.get('implementation') or {}).get('method', ''))}</dd></div>"
            f"<div><dt>Model/API Policy · 模型策略</dt><dd>{policy_bits or '—'}</dd></div>"
            f"<div><dt>Current Evidence · 当前证据</dt><dd>{evidence_bits or '—'}</dd></div>"
            f"<div>{gate_html}</div>"
            f"<div><dt>Limitations · 局限</dt><dd><ul>{limitations or '<li>—</li>'}</ul></dd></div>"
            "</dl></article>"
        )
    return "".join(cards)


# 内联 SVG 预览的单文件大小上限；超限只列路径，防止面板体积失控
_MAX_INLINE_SVG_BYTES = 300_000


def _render_figure_gallery(items: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for item in items:
        path = str(item.get("path") or "")
        preview = '<span class="fig-none">非 SVG 或文件缺失，仅列路径</span>'
        if path.endswith(".svg"):
            svg = _read_svg_for_inline(Path(path))
            if svg:
                preview = svg
        cards.append(
            '<figure class="fig-card" style="margin:0">'
            f'<div class="fig-frame">{preview}</div>'
            '<figcaption class="fig-meta">'
            '<div class="fm-top">'
            f'<strong>{_esc(item.get("title") or item.get("id", ""))}</strong>'
            f'<span class="badge b-plain">{_esc(item.get("format", ""))}</span>'
            "</div>"
            f"<code>{_esc(path)}</code>"
            "</figcaption></figure>"
        )
    if not cards:
        return '<div class="card" style="color:var(--ink-3)">尚未生成图表产物；先运行 <code>medharness2 figures build</code>。</div>'
    return "".join(cards)


def _read_svg_for_inline(path: Path) -> str:
    try:
        if not path.exists() or path.stat().st_size > _MAX_INLINE_SVG_BYTES:
            return ""
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    start = text.find("<svg")
    # 含脚本的 SVG 一律不内联，避免把外部产物里的 JS 注入面板
    if start < 0 or "<script" in text.lower():
        return ""
    return text[start:]


def _render_registry_rows(entries: list[dict[str, Any]]) -> str:
    recent = list(reversed((entries or [])[-20:]))  # 最新在前
    if not recent:
        return '<li class="reg-item"><span class="dot"></span><div class="reg-body" style="color:var(--ink-3)">暂无台账记录</div></li>'
    items: list[str] = []
    for entry in recent:
        ok = str(entry.get("status", "")) == "passed"
        metrics = entry.get("metrics") or {}
        metric_bits = "".join(
            f'<span class="mchip"><b>{_esc(k)}</b> {_esc(_compact_metric(v))}</span>' for k, v in metrics.items()
        )
        created = str(entry.get("created_at_utc", ""))[:19].replace("T", " ")
        items.append(
            '<li class="reg-item">'
            f'<span class="dot {"ok" if ok else "bad"}"></span>'
            '<div class="reg-body">'
            '<div class="reg-head">'
            f'<span class="stage">{_esc(entry.get("stage", ""))}</span>'
            f"{_status_badge(entry.get('status'))}"
            f"<time>{_esc(created)}</time>"
            "</div>"
            f'<div class="reg-metrics">{metric_bits}</div>'
            "</div></li>"
        )
    return "".join(items)


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_optional_float(value: Any) -> float | None:
    """Parse a numeric dashboard value without turning missing data into zero."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _format_percentile(value: Any) -> str:
    number = _to_optional_float(value)
    return "—" if number is None else f"P{number:.0f}"
