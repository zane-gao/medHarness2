# OCR、路由器与盲区修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 OCR 从单次通用 VLM 调用升级为可验证、可替换、可审计的逐页管线，同时修复三模态路由与盲区扫描中影响当前工程可信度的实现错误，并同步状态前端。

**Architecture:** 保留现有 `extract_report_text` 兼容入口，内部增加逐页渲染、候选路由、严格质量元数据和独立 verifier 钩子；候选模型通过配置选择，不能因失败静默伪造或改写主文本。路由器以 `cxr/ct/mri` 三类模态为硬边界，部位仅作为提示和优先级，不再阻塞兼容模型。盲区修复按科学有效性、数据质量、统计正确性和可复现性优先，安全/API 暴露按用户要求不纳入本轮远程提交范围。

**Tech Stack:** Python 3.11、PyMuPDF、pytest、现有 `LLMClient`/YAML 配置、静态 HTML 状态面板。

---

### Task 1: 建立 OCR 现状与候选决策记录

**Files:**
- Create: `docs/ocr_model_selection_20260715.md`
- Modify: `docs/project_status.yaml`

- [ ] 记录官方候选及其证据边界：豆包 Seed 视觉、PaddleOCR‑VL‑1.6、PP‑OCRv6、本地 Qwen、可选独立 Gemini/Mistral verifier。
- [ ] 明确冻结集、主指标 clinical CER、辅助指标、能力门禁与“不静默改写”规则。
- [ ] 运行 YAML/metadata 测试。

### Task 2: 重构 OCR 为逐页、可审计且可插拔管线

**Files:**
- Modify: `src/medharness2/ocr.py`
- Modify: `src/medharness2/config.py`
- Modify: `config/default.yaml`
- Modify: `tests/test_sample_data_pipeline.py`
- Create: `tests/test_ocr_pipeline.py`

- [ ] 先写失败测试：逐页调用、页序、缓存键、截断警告、provider/model provenance、strict real OCR 门禁、verifier 只产审计结果。
- [ ] 用 PyMuPDF 将 PDF 渲染为 PNG；保留文本层快速路径，但扫描 PDF 走逐页图片。
- [ ] 增加 OCR 路由配置（primary/verifier、模型、输出预算、DPI、prompt/version）。
- [ ] 将每页原始输出、质量检查、hash、错误、重复调用信息写入 `.ocr.json`；失败不写成功缓存。
- [ ] 支持 `quality_audit` verifier 回调/客户端，但禁止其覆盖主 OCR。
- [ ] 通过单测后再做最小真实/模拟样例。

### Task 3: 修复三模态路由器

**Files:**
- Modify: `src/medharness2/generators/registry.py`
- Modify: `src/medharness2/tools/tool7_modality.py`
- Modify: `src/medharness2/workflows/batch_readers.py`
- Modify: `src/medharness2/workflows/sample_full.py`
- Modify: `tests/test_legacy_integration.py`
- Create: `tests/test_modality_routing.py`

- [ ] 先写回归测试：`cxr/ct/mri` 同模态下未知或不匹配部位仍可选到模态兼容模型；别名归一化稳定；真正不支持模态时仍拒绝。
- [ ] 将 body part 从阻塞条件降为软约束/排序信号；`unknown` 和缺失部位不得造成空路由。
- [ ] 统一 `xray/dx/cr/xr→cxr`、`mr/mri→mri`、`ct→ct` 归一化，避免工具识别和 registry 分叉。
- [ ] 增加真实行为测试覆盖 DICOM、图片后缀和 LLM 识别 token 清洗。

### Task 4: 按盲区文档修复当前优先级缺陷

**Files:** 以测试定位结果为准，优先涉及 `tools/tool9_rank.py`、`tools/tool12_statistics.py`、`tools/tool2_extract.py`、`llm_client.py`、`utils/io.py`、`tools/tool8_generate.py`、`tools/tool4_hazard.py`、`workflows/reevaluate_run.py`、`workflows/benchmark_evaluation.py`。

- [ ] 先增加失败测试，再修复排序方向/归一化、统计字段白名单、N=1 CI、多重比较或明确状态、provenance 过滤、JSON fenced/slice 解析、seed 传递、Retry-After、fallback 可见性和失败样本计数。
- [ ] 用户明确暂缓的 API 鉴权/任意文件读写与外部 PHI 风险不在本轮实现；代码和文档不新增凭据。
- [ ] 每个修复保持接口兼容并运行对应局部测试。

### Task 5: 更新项目账本与 web

**Files:**
- Modify: `docs/blindspot_audit_20260714.md`
- Modify: `docs/project_status.yaml`
- Modify: `web/build_panel.py`
- Modify: `web/panel_template.html`
- Regenerate: `web/index.html`, `web/control_panel.html`
- Modify: `web/README.md`

- [ ] 记录已修复、部分修复和待实测项，北川数据集直接作为当前工程金标准叙事。
- [ ] 展示 OCR 候选、验证状态、路由器状态、未完成的真实云模型 benchmark 和已知限制。
- [ ] 运行静态 HTML/JSON/secret 检查及全量 pytest。
- [ ] 审核 diff 后只提交本轮目标文件，保留用户原有未跟踪文件；使用仓库既有 PAT 通过临时 askpass 推送 `main`。
