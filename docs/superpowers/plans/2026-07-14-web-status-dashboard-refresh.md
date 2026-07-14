# Web Status Dashboard Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持现有视觉和章节顺序的前提下，把 `web/` 收尾为准确反映 medHarness2 最新开发状态的自包含面板，并将代码、模板和未脱敏生成页面直接提交到远程 `main`。

**Architecture:** `web/build_panel.py` 继续负责从本地 Git、项目账本和运行产物组装单一 JSON payload，`web/panel_template.html` 继续负责静态叙事和浏览器渲染。主状态页、次级控制面板和 legacy 快照职责分离；缺失证据通过统一 source-health 数据显式呈现，核心输入缺失则构建失败。

**Tech Stack:** Python 3.10、PyYAML、静态 HTML/CSS/JavaScript、pytest、Playwright、Git。

---

## File map

- `.gitignore`：允许跟踪生成的 Web 页面，忽略视觉伴侣临时目录。
- `docs/project_status.yaml`：项目阶段、工程基线、九条战线和控制面板状态的语义账本。
- `web/build_panel.py`：Git 元数据、状态账本、来源健康、运行证据与 payload 构建。
- `web/panel_template.html`：保持原版布局的页面叙事、卡片和渲染逻辑。
- `web/README.md`：构建、页面职责、数据公开策略和验证说明。
- `web/index.html`：主状态页生成产物，随仓库提交。
- `web/control_panel.html`：包内 dashboard builder 的次级工程控制面板产物，随仓库提交。
- `web/legacy/index.html`、`web/legacy/control_panel.html`：只提交现有历史快照，不扩展旧实现。
- `tests/test_project_metadata.py`：跟踪策略、项目账本与静态隐私/元数据约束。
- `tests/test_web_panel.py`：构建器的 Git 状态、来源健康、核心文件错误和模板语义测试。
- `tests/web_panel.spec.mjs`：桌面与移动端浏览器回归测试。

### Task 1: Publish generated pages and refresh the semantic project ledger

**Files:**
- Modify: `.gitignore`
- Modify: `docs/project_status.yaml`
- Modify: `tests/test_project_metadata.py`
- Add existing artifact: `web/index.html`
- Add existing artifact: `web/legacy/index.html`
- Add existing artifact: `web/legacy/control_panel.html`

- [ ] **Step 1: Replace the old ignore-policy test with the approved publication policy**

Replace `test_generated_web_pages_are_ignored_but_templates_are_trackable` with:

```python
def test_generated_web_pages_and_templates_are_trackable():
    web_artifacts = [
        "web/index.html",
        "web/control_panel.html",
        "web/legacy/index.html",
        "web/legacy/control_panel.html",
        "web/panel_template.html",
        "web/legacy/template.html",
        "src/medharness2/templates/control_panel_template.html",
    ]

    for path in web_artifacts:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", path],
            check=False,
        )
        assert result.returncode == 1, path
```

Extend `test_project_status_has_current_release_evidence` with:

```python
    assert payload["updated_at"] == "2026-07-14"
    assert payload["release_readiness"] == "pilot_only"
    assert payload["baseline"]["branch"] == "main"
    assert payload["baseline"]["dirty_worktree"] is False
    assert payload["baseline"]["pytest_passed"] >= 332
    assert payload["workstreams"]["control_panel"]["status"] == "in_progress"
```

- [ ] **Step 2: Run the tests to verify the old policy and stale ledger fail**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_project_metadata.py -q
```

Expected: FAIL because generated HTML is ignored and `docs/project_status.yaml` still reports the old date, feature branch, dirty worktree, 330 tests, and a deferred control panel.

- [ ] **Step 3: Implement the publication policy and current ledger state**

Remove these entries from `.gitignore`:

```gitignore
web/index.html
web/control_panel.html
web/legacy/index.html
web/legacy/control_panel.html
```

Add the visual-companion scratch directory:

```gitignore
.superpowers/
```

Update the top-level project status values:

```yaml
updated_at: "2026-07-14"
current_phase: production_research_foundations
release_readiness: pilot_only

baseline:
  branch: main
  git_sha: 80672806e16c7bafb94951ff90be2162d33dde45
  dirty_worktree: false
  pytest_passed: 332
  pytest_warnings: 17
```

Update `workstreams.control_panel` to:

```yaml
  control_panel:
    status: in_progress
    summary: The internal project-status dashboard is being refreshed against the current evidence ledger while preserving the original long-page visual design; generated HTML is intentionally published by explicit user direction.
    evidence_paths:
      - web/build_panel.py
      - web/panel_template.html
      - tests/test_project_metadata.py
    next_gate: Rebuild both maintained dashboards, pass desktop/mobile browser checks, and verify the published HTML matches the latest local evidence sources.
```

- [ ] **Step 4: Run the focused metadata tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_project_metadata.py -q
```

Expected: PASS with three metadata tests.

- [ ] **Step 5: Commit the policy and ledger change**

```bash
git add .gitignore docs/project_status.yaml tests/test_project_metadata.py \
  web/index.html web/legacy/index.html web/legacy/control_panel.html
git commit -m "chore: publish web artifacts and refresh status ledger"
```

### Task 2: Add build provenance, source health, and explicit core-input errors

**Files:**
- Modify: `web/build_panel.py`
- Create: `tests/test_web_panel.py`

- [ ] **Step 1: Write failing tests for Git state, source health, YAML parsing, and core-input validation**

Create `tests/test_web_panel.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from web.build_panel import (
    REPO,
    build_data,
    extract_git_state,
    extract_project_status,
    source_health,
)


def test_extract_git_state_reports_current_repository():
    state = extract_git_state(REPO)

    assert state["branch"] == "main"
    assert len(state["sha"]) == 40
    assert state["short_sha"] == state["sha"][:7]
    assert isinstance(state["dirty"], bool)


def test_source_health_uses_relative_paths(tmp_path: Path):
    missing = tmp_path / "missing.json"
    existing = tmp_path / "existing.json"
    existing.write_text("{}", encoding="utf-8")

    result = source_health({"missing": missing, "existing": existing}, root=tmp_path)

    assert result == {
        "missing": {"path": "missing.json", "available": False},
        "existing": {"path": "existing.json", "available": True},
    }


def test_extract_project_status_reads_full_yaml():
    status = extract_project_status(REPO / "docs/project_status.yaml")

    assert status["release_readiness"] == "pilot_only"
    assert status["baseline"]["branch"] == "main"
    assert status["workstreams"]["clinical_validation"]["status"] == "not_started"


def test_build_data_rejects_missing_core_run(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="run_summary.json"):
        build_data(tmp_path)


def test_build_data_exposes_project_meta_and_source_health():
    data = build_data(REPO / "outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_v2_qualityfix_20260710")

    assert data["project_meta"]["git"]["branch"] == "main"
    assert data["project_meta"]["status"]["release_readiness"] == "pilot_only"
    assert data["source_health"]["dmx_evaluation"]["available"] is True
    assert data["source_health"]["pilot10_manifest"]["available"] is True
```

- [ ] **Step 2: Run the focused tests to verify the new API is missing**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_web_panel.py -q
```

Expected: collection FAIL because `extract_git_state`, `extract_project_status`, and `source_health` are not defined.

- [ ] **Step 3: Implement the minimal builder API**

Add imports:

```python
import subprocess

import yaml
```

Add these functions after the path constants:

```python
def _relative_path(path: Path, root: Path = REPO) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def extract_git_state(repo: Path = REPO) -> dict:
    def run(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    sha = run("rev-parse", "HEAD")
    return {
        "branch": run("branch", "--show-current") or "detached",
        "sha": sha,
        "short_sha": sha[:7],
        "dirty": bool(run("status", "--porcelain", "--untracked-files=no")),
    }


def extract_project_status(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing project status ledger: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "workstreams" not in payload:
        raise ValueError(f"Invalid project status ledger: {path}")
    return payload


def source_health(paths: dict[str, Path], *, root: Path = REPO) -> dict:
    return {
        name: {"path": _relative_path(path, root), "available": path.exists()}
        for name, path in paths.items()
    }


def require_core_run(run_dir: Path) -> None:
    required = [
        run_dir / "run_summary.json",
        run_dir / "analysis/analysis_summary.json",
        run_dir / "workflow2_cases",
    ]
    for path in required:
        if not path.exists():
            raise FileNotFoundError(f"Missing required dashboard input: {path}")
```

Replace the handwritten YAML parser with:

```python
def extract_workstreams(path: Path) -> dict:
    payload = extract_project_status(path)
    return {
        "updated_at": payload.get("updated_at"),
        "phase": payload.get("current_phase"),
        "release_readiness": payload.get("release_readiness"),
        "workstreams": payload.get("workstreams") or {},
    }
```

At the start of `build_data`, call `require_core_run(run_dir)`. Add these keys to its return value:

```python
        "project_meta": {
            "git": extract_git_state(),
            "status": extract_project_status(STATUS_YAML),
        },
        "source_health": source_health({
            "dmx_evaluation": SMOKE_EVAL_DIR / "benchmark_evaluation_summary.json",
            "generation_benchmark": BENCH_DIR / "attempt_001/benchmark_summary.json",
            "ocr_audit": OCR_AUDIT_DIR / "summary.json",
            "experiment_results": EXPERIMENTS_RESULTS,
            "pilot10_manifest": PILOT10_MANIFEST,
        }),
```

- [ ] **Step 4: Run focused builder and metadata tests**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_web_panel.py tests/test_project_metadata.py -q
```

Expected: PASS with all focused tests and no collection errors.

- [ ] **Step 5: Commit provenance and source-health support**

```bash
git add web/build_panel.py tests/test_web_panel.py
git commit -m "feat: expose dashboard provenance and source health"
```

### Task 3: Refresh the original long-page narrative without redesigning it

**Files:**
- Modify: `web/panel_template.html`
- Modify: `tests/test_web_panel.py`

- [ ] **Step 1: Add failing static narrative and section-order tests**

Append to `tests/test_web_panel.py`:

```python
def test_template_keeps_original_section_order_and_current_boundaries():
    template = (REPO / "web/panel_template.html").read_text(encoding="utf-8")
    section_ids = ["what", "flow", "arch", "wf", "tools", "run", "fresh", "map", "issues"]

    positions = [template.index(f'<section id="{section_id}"') for section_id in section_ids]
    assert positions == sorted(positions)

    stale_claims = [
        "本系统做的是<b>评估与教学</b>，不做报告生成",
        "共 4 条（见下节）",
        "同样的输入永远给同样的输出",
        "四条工作流：从一个人到一个科室",
    ]
    for claim in stale_claims:
        assert claim not in template

    required_claims = [
        "pilot-only",
        "探索性工程证据",
        "formal_fresh",
        "研究与治理流程",
        "临床金标准",
        "重测稳定性",
    ]
    for claim in required_claims:
        assert claim in template


def test_template_has_visible_project_meta_and_source_health_hosts():
    template = (REPO / "web/panel_template.html").read_text(encoding="utf-8")

    assert 'id="project-meta-strip"' in template
    assert 'id="source-health"' in template
    assert "DATA.project_meta" in template
    assert "DATA.source_health" in template
```

- [ ] **Step 2: Run the tests to verify stale narrative and missing hosts fail**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_web_panel.py -q
```

Expected: FAIL on stale claims and missing `project-meta-strip` / `source-health` containers.

- [ ] **Step 3: Update the hero, pipeline, architecture, and workflow sections**

Keep all existing section IDs. Replace the hero note with this exact boundary:

```html
<p class="hero-note">
  <span class="nb">当前边界：</span>medHarness2 已覆盖报告生成基准、质量评估、错误审计、实验与教学建议，
  但当前发布就绪度仍是 <b>pilot-only</b>。页面中的 52 例基线和 11 例纯 DMX 结果属于工程或探索性证据，
  不代表临床有效性，也不能直接形成正式模型排名。
</p>
<div class="card" id="project-meta-strip"></div>
```

Preserve the seven numbered steps, but add these concepts to the existing descriptions:

```text
输入：OCR 来源与契约版本
生成：模态/部位路由与 evidence tier
质检：formal_fresh / exploratory_fresh / artifact / debug_fallback / mock
体检与对齐：确定性主结果、LLM judge/reviewer、hash-linked audit
输出：checkpoint、schema 校验、run registry 与实验状态
```

Update the four architecture layer descriptions so that they say:

```text
工作流层负责可恢复执行、checkpoint、产物写入与 run registry；模块层组合单报告和成对比较能力；
工具层同时包含确定性算法与非确定性 LLM 角色，主结果和审计结果分开保存；
基础设施层提供契约、配置、隐私策略、本地模型、DMX 和显式备份路由。
```

Rename the workflow heading to `核心工作流与研究闭环` and add this exact research-flow model after `WFS`:

```javascript
const RESEARCH_WFS = [
  ["契约与迁移", "schema export / migrate-run", "把旧产物迁移到严格 v2 契约并递归校验"],
  ["生成与评估基准", "benchmark plan / run / evaluate", "冻结模型、数据、实现哈希和证据等级"],
  ["重评估与实验", "reevaluate-run / experiments run", "在不重新生成报告的情况下更新评估并执行六项协议"],
  ["图表与控制面板", "figures build / dashboard build", "把实验、注册表和运行状态转为可审计图表与页面"],
  ["临床标注", "annotation build-pilot", "准备双读者与仲裁任务，建立 AI 法官校准金标准"],
];
```

Render it with existing `card` and `wf-card` classes beneath `wf-grid`; do not introduce a new layout system.

- [ ] **Step 4: Update tool truthfulness, latest evidence, and issue ordering**

Apply these exact factual rules to the current cards:

```text
T1: strict non-mock LLM judge; single draws are not repeatability evidence.
T2: deterministic entity candidates plus LLM correction/judgement.
T4: independent primary and reviewer judgements plus adjudication; clinician resolution remains required.
T5/T6: deterministic primary result is preserved; LLM emits a separate hash-linked audit.
T8: only formal_fresh may enter formal comparison; the current 52-case baseline has zero formal_fresh.
```

Keep evidence cards A–F, but label the 11-case DMX result `探索性工程证据`. Reorder the issue list to:

```text
1. pilot10 clinical gold labels are 0/10.
2. OCR has 6 definite and 7 suspected truncations.
3. LLM repeatability is insufficient for formal claims.
4. The 52-case baseline has zero formal_fresh reports.
5. Six experiment protocols have zero validated results.
```

Remove DMX HTTP 403 as a current blocker; retain it only as historical context if mentioned.

- [ ] **Step 5: Render project metadata and optional-source status using existing styles**

Add this JavaScript near the start of the render code:

```javascript
const PM = DATA.project_meta || {};
const GS = PM.git || {};
const PS = PM.status || {};
document.getElementById("project-meta-strip").innerHTML = `
  <div class="kpi-grid">
    <div class="kpi"><b>${esc(PS.release_readiness || "unknown")}</b><span>发布就绪度</span></div>
    <div class="kpi"><b>${esc(GS.branch || "unknown")}</b><span>当前分支</span></div>
    <div class="kpi"><b>${esc(GS.short_sha || "unknown")}</b><span>构建提交</span></div>
    <div class="kpi"><b>${GS.dirty ? "有改动" : "干净"}</b><span>工作区</span></div>
  </div>`;
```

Add `<div class="card" id="source-health"></div>` at the top of the latest-evidence section and render every `DATA.source_health` entry as available or missing. Missing entries must remain visible with their repository-relative expected path.

- [ ] **Step 6: Run focused tests and commit the narrative update**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_web_panel.py tests/test_project_metadata.py -q
```

Expected: PASS; original section order remains unchanged and all stale-claim assertions pass.

Commit:

```bash
git add web/panel_template.html tests/test_web_panel.py
git commit -m "feat: refresh web dashboard project narrative"
```

### Task 4: Update documentation and rebuild all maintained Web artifacts

**Files:**
- Modify: `web/README.md`
- Modify: `web/index.html`
- Create: `web/control_panel.html`
- Add: `web/legacy/index.html`
- Add: `web/legacy/control_panel.html`
- Preserve: `web/legacy/template.html`
- Preserve: `web/legacy/build_demo.py`

- [ ] **Step 1: Write failing documentation assertions**

Append to `tests/test_web_panel.py`:

```python
def test_web_readme_documents_current_scope_and_publication_policy():
    readme = (REPO / "web/README.md").read_text(encoding="utf-8")

    assert "评估教学，不做生成" not in readme
    assert "生成页面与运行数据按项目负责人要求直接提交" in readme
    assert "web/index.html" in readme
    assert "web/control_panel.html" in readme
    assert "legacy" in readme
    assert "pilot-only" in readme
```

- [ ] **Step 2: Run the documentation test to verify the old README fails**

Run:

```bash
PYTHONPATH=src python -m pytest tests/test_web_panel.py::test_web_readme_documents_current_scope_and_publication_policy -q
```

Expected: FAIL because the README still says generated pages are ignored and the system does not generate reports.

- [ ] **Step 3: Rewrite README facts without changing its concise structure**

Document:

```text
- The page is an internal project-status dashboard for the project owner.
- The maintained surface is web/index.html; web/control_panel.html is the secondary engineering view.
- legacy HTML is a published historical snapshot, not the current status source.
- Generated HTML and embedded run data are committed by explicit user direction.
- Credentials remain prohibited.
- The page is pilot-only and separates the 52-case baseline from 11-case exploratory evidence.
```

- [ ] **Step 4: Regenerate the maintained pages from current local artifacts**

Run:

```bash
PYTHONPATH=src python web/build_panel.py --output web/index.html
PYTHONPATH=src python -m medharness2.cli dashboard build \
  --run-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_v2_qualityfix_20260710 \
  --output web/control_panel.html
```

Expected:

```text
web/index.html is regenerated with 52 cases, 81 candidate reports, DMX/OCR/benchmark/status sections present.
web/control_panel.html is generated successfully from the same run directory.
```

Do not run `web/legacy/build_demo.py`; retain the existing legacy snapshots exactly as archived artifacts.

- [ ] **Step 5: Verify generated payloads and Git tracking**

Run:

```bash
git check-ignore --no-index web/index.html web/control_panel.html web/legacy/index.html web/legacy/control_panel.html
git status --short web
rg -n 'pilot-only|project-meta-strip|source-health' web/index.html
```

Expected: `git check-ignore` returns nonzero, all four generated HTML paths are trackable, and the current main page contains the required status markers.

- [ ] **Step 6: Commit documentation and generated artifacts**

```bash
git add web/README.md web/index.html web/control_panel.html web/legacy/index.html web/legacy/control_panel.html
git commit -m "docs: rebuild and publish web dashboards"
```

### Task 5: Add browser regression coverage and close the control-panel workstream

**Files:**
- Create: `tests/web_panel.spec.mjs`
- Modify: `docs/project_status.yaml`
- Modify: `tests/test_project_metadata.py`

- [ ] **Step 1: Add the browser regression test**

Create `tests/web_panel.spec.mjs`:

```javascript
import { test, expect } from "@playwright/test";

const sections = ["what", "flow", "arch", "wf", "tools", "run", "fresh", "map", "issues"];

for (const viewport of [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
]) {
  test(`${viewport.name} dashboard renders without console errors or overflow`, async ({ page }) => {
    const errors = [];
    page.on("console", message => {
      if (message.type() === "error") errors.push(message.text());
    });
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("http://127.0.0.1:8080/index.html");

    for (const section of sections) {
      await expect(page.locator(`#${section}`)).toBeVisible();
    }
    await expect(page.locator("#project-meta-strip")).toContainText("pilot_only");
    await page.locator('a[href="#issues"]').click();
    await expect(page.locator("#issues")).toBeInViewport();

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    expect(overflow).toBe(false);
    expect(errors).toEqual([]);
    await page.screenshot({ path: `/tmp/medharness2-web-${viewport.name}.png`, fullPage: true });
  });
}
```

- [ ] **Step 2: Start the local static server and run Playwright**

Run the server in a persistent terminal session:

```bash
python3 -m http.server 8080 --directory web
```

Run:

```bash
npx --yes playwright test tests/web_panel.spec.mjs --reporter=line
```

Expected: two Playwright tests PASS, no browser console errors, no horizontal overflow, and screenshots exist at `/tmp/medharness2-web-desktop.png` and `/tmp/medharness2-web-mobile.png`.

- [ ] **Step 3: Visually inspect desktop and mobile screenshots**

Open both screenshots and verify:

```text
- Original warm-white visual language and section order are preserved.
- Header navigation, cards, tables, progress matrix, and issue list do not overlap.
- Project metadata, source health, pilot-only boundary, and latest blockers are legible.
- Mobile content stays within the viewport.
```

- [ ] **Step 4: Mark the control-panel workstream validated and update its evidence**

Change `docs/project_status.yaml`:

```yaml
  control_panel:
    status: validated
    summary: The original long-page internal project dashboard now reflects the current main-branch metadata, evidence tiers, 52-case baseline, 11-case exploratory DMX evaluation, OCR audit, experiment gates, and pilot10 status; generated pages are published by explicit user direction and pass desktop/mobile browser checks.
    evidence_paths:
      - web/index.html
      - web/control_panel.html
      - web/build_panel.py
      - web/panel_template.html
      - tests/test_web_panel.py
      - tests/web_panel.spec.mjs
    next_gate: Refresh the dashboard whenever a new validated run, clinician annotation milestone, frozen OCR benchmark, or formal experiment result supersedes the current evidence.
```

Change the metadata assertion to:

```python
    assert payload["workstreams"]["control_panel"]["status"] == "validated"
```

- [ ] **Step 5: Run Python verification and commit the validated status**

Run:

```bash
git diff --check
PYTHONPATH=src python -m pytest tests/test_project_metadata.py tests/test_web_panel.py -q
make test
```

Expected: all commands exit 0 and the Python test count increases from 332 with zero failures.

Commit the browser test and validated workstream state before the final HTML build:

```bash
git add tests/web_panel.spec.mjs docs/project_status.yaml tests/test_project_metadata.py
git commit -m "test: validate refreshed web dashboard sources"
```

- [ ] **Step 6: Rebuild from a clean committed source state and rerun Playwright**

Confirm the tracked worktree is clean, then regenerate:

```bash
test -z "$(git status --porcelain --untracked-files=no)"
PYTHONPATH=src python web/build_panel.py --output web/index.html
PYTHONPATH=src python -m medharness2.cli dashboard build \
  --run-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_v2_qualityfix_20260710 \
  --output web/control_panel.html
npx --yes playwright test tests/web_panel.spec.mjs --reporter=line
```

Expected: both browser tests pass. The embedded Git metadata describes the clean committed source revision used to generate the pages; the following artifact-only commit is allowed to have a different SHA.

- [ ] **Step 7: Scan for credentials while allowing authorized clinical data**

Run:

```bash
git grep -I -l -E 'ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|hf_[A-Za-z0-9]{20,}|KGAT_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' -- .
```

Expected: no output. Clinical report text, reader names, case IDs, and local run metadata are permitted by the user's explicit instruction and do not fail this gate.

- [ ] **Step 8: Commit the final generated pages**

```bash
git add web/index.html web/control_panel.html
git commit -m "docs: regenerate validated web dashboards"
```

### Task 6: Final repository verification and direct main-branch publication

**Files:**
- Verify all files committed in Tasks 1–5

- [ ] **Step 1: Verify the final worktree and commit content**

Run:

```bash
git status -sb
git log -7 --oneline --decorate
git ls-files web
```

Expected: `main` has no unstaged or staged changes; generated pages, templates, builders, README, and legacy snapshots all appear in `git ls-files web`.

- [ ] **Step 2: Push main without force**

Run:

```bash
git push origin main
```

Expected: ordinary fast-forward update; no force push and no PR.

- [ ] **Step 3: Verify the remote main hash**

Run:

```bash
test "$(git rev-parse HEAD)" = "$(git ls-remote origin refs/heads/main | awk '{print $1}')"
```

Expected: exit 0 and local `main` matches remote `main` exactly.
