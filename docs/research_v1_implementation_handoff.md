# medHarness2 research v1 implementation handoff

> 生产级工程与正式研究实验的总实施计划见：
> `docs/superpowers/plans/2026-07-10-medharness2-production-research-plan.md`。
> 本文记录当前 v1 状态；后续“完成”口径以总实施计划的 Definition of Done 和 release verifier 为准。

更新日期：2026-07-11

## 当前权威基线（2026-07-10 qualityfix）

下文保留早期 v1 实施记录作为历史；当前状态以 `docs/project_status.yaml` 和以下产物为准：

- run：`outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_v2_qualityfix_20260710/`
- experiments：`outputs/experiments/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_v2_qualityfix_20260710/`
- figures：`outputs/figures/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_v2_qualityfix_20260710/`
- 自动化验证：最新全量回归为 `330 passed, 17 warnings`。当前环境未安装 `ruff`/`mypy`，这两项尚未执行。
- 严格 artifact 验证：52 case、277 FindingGraph、81 GeneratedReport、72 HazardResult 全部符合 v2 contract；当前 pilot 的 AlignmentAudit/HazardReview/StructureAudit 均为 0，不能声称已用本轮 LLM 重评估。
- Tool 2 已修复重复 observation 漏检、重叠 alias 双计、转折后否定传播、小数点句界误判和同一实体重复 mention。
- T1 正式路径已改为真实 LLM 五维评分，完整 schema retry，strict 模式拒绝 mock 与 deterministic fallback。
- T2 已升级为 CXR/CT/MRI 模态规则模板候选 + LLM 校正；LLM finding 必须有原文证据、测量 grounding 和 v2 FindingGraph 校验。
- T4 已升级为确定性 hazard 先验 + strict 主 LLM + 独立 reviewer；分歧写入 `HazardReviewArtifact`，不覆盖主结果。
- T5/T6 已分别增加不可变主结果上的 `AlignmentAuditArtifact` 与 `StructureAuditArtifact`；Module 2 已统一调用正式 Tool 6，不再保留内联重复实现。
- Tool 3/T6 共用同一套中英文 section header normalization，并保留重复 section 内容。
- 当前 human finding count 为 161，精确重复实体为 0；该数值仍需医生 gold set 验证，不能解释为临床召回率。
- 81 份生成报告仍为 `14 artifact + 67 debug_fallback + 0 formal_fresh`。
- Notion 六项实验均为 `pilot`，每项 `0/4` validation gates；formal benchmark 为 `0/52` ready。
- 报告生成 benchmark 已扩展到冻结的 11 例 CXR chest + `qwen3vl_8b_mimic_cxr_sft` exploratory fresh inference；11/11 生成成功，但只有 5 个唯一报告。该结果没有医生验证 ID，只证明真实推理闭环，不改变 `0 formal-ready` 结论。
- 前端和控制面板工作已按用户要求从当前范围移除；隐私加固暂时不作为核心质量工作的阻断项。

## 2026-07-11 真实 API 验证增量

- 主 profile：`config/dmx_strong.yaml`，主角色为 `gpt-5.6-terra`，独立 hazard reviewer 为 `claude-opus-4-8`。
- 纯 DMX 已完成 11 例完整 T1/T2/T5/T4/T6 链路：11/11 成功、99 条真实角色证据、`fallback_count=0`。角色模型为 `gpt-5.6-terra`、`claude-opus-4-8` 和独立 adjudicator `gpt-5.6-sol`。
- T5 曾因 prompt 允许自由 replacement error type、validator 只接受 7 个枚举而失败 2 例。修复后 prompt 与 validator 共用枚举来源，两个原失败病例均恢复；实现哈希 `ed9d26ca0e73f777ee419fbdc3683f803fd93edac7499c492265909371e12b4a`，配置哈希 `2ccc541797fc011ea665a80ac7f7cfb14f6d31301f361ca539816f502a892818`。
- 显式备用 profile：`config/yunwu_strong.yaml`；完整 T1/T2/T5/T4/T6 合成链路通过，所有角色 `fallback_used=false`，T4 正确生成 2 项 reviewer disagreement。
- 新增 API profile：`config/codex_proxy_strong.yaml` 的 GPT 通道可用、Claude 通道当前 503；`config/codex_dmx_strong.yaml` 以 codex GPT + DMX Claude 4.8 完成整链合成 smoke，所有 fallback 为 false，三个 audit hash 均匹配，T4 产生 1 项 disagreement。该混合路线必须显式选择。
- 详细实现与边界：`docs/llm_tooling_upgrade_20260710.md`。
- 机器可读 smoke 摘要：`docs/llm_tools_synthetic_smoke_20260710.json`。
- 11 例运行仍是单模型 `exploratory_fresh` 子集。共同成功的 9 例新旧运行中，T1 完全一致率为 11.1%，consensus material-error 完全一致率为 22.2%；不得把单次自动评价描述成稳定临床结论。
- 当前 52 例 qualityfix run 尚未用本轮真实 LLM 全量重新评估，不能把旧 pilot 指标描述成新模型结果。

## 2026-07-11 OCR 质量审计增量

- DMX `/v1/models` 当前包含 `doubao-seed-2-1-pro-260628`。图像 nonce 探针确认它与 `doubao-seed-1-6-vision-250815`、`qwen-vl-ocr-latest` 都能真实读取图片。
- `doubao-seed-2-1-pro-260628` 对一份真实 CXR 临床正文与现有人工可核对文本逐字一致；对一份高密度 CT 页面完整返回检查所见和诊断印象。
- 旧 `qwen3-vl-4b` OCR 使用 `max_new_tokens=384`。52 例确定性完整性审计发现 6 例明确截断、7 例疑似截断，全部位于 CT；2 例缺失诊断印象。
- 审计产物：`outputs/ocr_quality_audit_qwen3vl4b_20260711/summary.json`；设计规格：`docs/superpowers/specs/2026-07-11-dmx-doubao-ocr-benchmark-design.md`。
- 下一步不是直接把豆包设为唯一默认，而是冻结 10 例 CR/CT/MRI 盲测、提高所有候选输出预算、制作视觉 gold，并以临床正文 CER、数字/否定准确率和幻觉率选路由。

## 本轮新增能力

本轮把项目从原有 MVP 演示向“研究可复现 v1”推进，新增内容集中在可审计、可复跑和可展示三个方向。

### 能力目录

- 代码入口：`src/medharness2/catalog.py`
- CLI：`PYTHONPATH=src python -m medharness2.cli tools catalog --config config/dmx_strong.yaml --output outputs/capability_catalog.json`
- 当前产物：`outputs/capability_catalog.json`
- 内容：Tool 1-12 的输入、输出、实现方式、是否需要医学模型；`workflow_stages` 中 16 个 workflow/产物环节的开发状态、输入输出格式、结果路径模板、实现方式、通用模型/医学专用模型/本地模型/API 模型使用策略；模型 registry 中的 source、modalities、body_parts、ready、report_trained、route_role；LLM/extractor/generator provider 配置摘要。
- 安全约束：只记录 `api_key_env`，不记录 secret 值。

### 递归验证与 v1 迁移

- `validate-run` 递归验证 case、FindingGraph、GeneratedReport、HazardResult 以及可选的 AlignmentAudit/HazardReview/StructureAudit；三类审计还必须通过同一 comparison 内主结果的 canonical SHA-256 绑定检查。
- 原始 `...final_local_routed_52_20260606` 是 v1 目录，直接运行严格 v2 门禁会失败；不得通过放宽 schema 掩盖这一事实。
- `schemas migrate-run --source-run-dir <V1_RUN> --output-dir <MIGRATED_RUN>` 会递归迁移 finding/hazard、记录 `migration_warnings` 与 `legacy_migration` provenance，并输出可直接执行 `validate-run` 的 `workflow2_cases/` 及四个支持文件；旧 `cases/` 路径以 hard link 兼容。
- 已对真实 52 例临时迁移目录实测：`52/52` case 有效，277 FindingGraph、81 GeneratedReport、72 HazardResult，`real_ocr_count=52`，`errors=[]`。迁移只做合同转换，不代表新模型推理。

### 运行账本

- 代码入口：`src/medharness2/run_registry.py`
- 功能：写入 append-only `run_registry.json`，顶层保留最新 stage/status，同时在 `entries[]` 中累积 run_id、stage、status、command、config、inputs、outputs、metrics、warnings。
- 安全约束：会脱敏 key/token/secret/password/pat 相关字段和命令参数。
- 当前 CLI 已自动接入 `tools catalog`、`workflow single-case`、`workflow sample-data`、`workflow sample-full`、`workflow sample-full --dry-run`、`workflow batch-readers`、`workflow department`、`workflow merge-batches`、`workflow analyze-run`、`workflow reevaluate-run`、`workflow validate-run`、`workflow preflight`、`workflow education`、`experiments run`、`figures build`、`dashboard build`。
- API 已接入 `workflow education`、`experiments run`、`figures build`、`dashboard build` 等产物生成端点；`experiments`、`figures`、`dashboard` 会同步写入原始 run 目录账本，便于控制面板展示阶段链路。

### Workflow 4 教育建议

- 代码入口：`src/medharness2/workflows/education.py`
- CLI：
  - `PYTHONPATH=src python -m medharness2.cli workflow education --eval-report <workflow1.json> --output <education.json>`
  - `PYTHONPATH=src python -m medharness2.cli workflow education --eval-radiologist <workflow2.json> --output <education.json>`
- API：`POST /workflow/education`
- 行为：读取 W1 或 W2 结果，只读不改源文件；生成结构化 suggestions JSON；默认 deterministic 可用，真实 LLM provider 可返回同 schema JSON，失败时回落 deterministic。
- 边界：当前是 v1 教育建议生成，不代表经过医生验证的教育干预效果。

### 低成本重评估

- 代码入口：`src/medharness2/workflows/reevaluate_run.py`
- CLI：`PYTHONPATH=src python -m medharness2.cli workflow reevaluate-run --source-run-dir <RUN> --output-dir <REEVAL_RUN>`
- 行为：读取已有 `workflow2.json` 和 `workflow2_cases/*.json`，复用其中 `generated_reports`，重新计算 Tool 1/2/3、Top-N、pairwise alignment、hazard 和 Workflow 2/3 汇总；不调用报告生成模型。是否调用外部 API 取决于配置：默认兼容 profile 不调用，`dmx_strong.yaml`/`yunwu_strong.yaml` 会调用 strict LLM roles。
- 输出：`<REEVAL_RUN>/workflow2.json`、`workflow3.json`、`run_summary.json`、`workflow2_cases/*.json`、`run_registry.json`。
- 验证策略：`run_summary.validation` 会继承 source run 的 `expected_cases` 和 `require_real_ocr`，并对重评估目录重新执行 validation，避免实验聚合和控制面板读到过期 OCR provenance。
- 用途：当 Tool 2/4 等评价器升级后，可快速刷新实验输入，保留原始生成结果作为 source run。

### 实验聚合

- 代码入口：`src/medharness2/workflows/experiments.py`
- CLI：`PYTHONPATH=src python -m medharness2.cli experiments run --run-dir <RUN> --output-dir <EXP>`
- API：`POST /experiments/run`
- 当前产物：`outputs/experiments/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_tool2_v1/`
- 覆盖 Notion 中六类实验 v1：
  - `radiologist_evaluation`
  - `finding_extraction`
  - `hazard_evaluation`
  - `educational_study`
  - `image_to_text_models`
  - `modality_recognition`
- 输入：现有 run 目录下 `run_summary.json`、`workflow2.json`、`workflow3.json`、`workflow2_cases/*.json`、`analysis/*.csv/json`。
- 输出：`results.json`、`results.md`、`experiment_summary.csv`、`experiment_protocol.json`、`experiment_protocol.md`、`experiment_protocol.csv`；若 `<RUN>/education/*.json` 不存在，会先用 deterministic reader-level 路径生成 `<RUN>/education/radiologist_summary.json`，并在 `results.json.automation.education_generation` 与 `run_registry.json.metrics` 记录生成状态和 suggestion 数。
- 实验协议账本：`experiment_protocol.*` 将 Notion 六类实验逐项绑定到研究问题、输入、输出、实现方式、通用/医学/本地/API 模型策略、当前证据、限制和下一步，避免只有结果而没有可审计实验安排。

### 图表生成

- 代码入口：`src/medharness2/figures.py`
- CLI：`PYTHONPATH=src python -m medharness2.cli figures build --experiment-dir <EXP> --output-dir <FIG>`
- API：`POST /figures/build`
- 当前产物：`outputs/figures/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_tool2_v1/`
- 当前生成：
  - `fig1_system_overview.svg`
  - `fig2_single_case_evidence_chain.svg`
  - `fig3_finding_graph_alignment.svg`
  - `fig4_feedback_card.svg`
  - `fig5_experiment_protocol.svg`
  - `fig6_main_results.svg`
  - `fig7_case_level_distribution.svg`
  - `fig8_error_hazard.svg`
  - `fig9_auxiliary_metrics.svg`
  - `table1_dataset_run_summary.csv/.md`
  - `table2_metric_taxonomy.csv/.md`
  - `figure_manifest.json`
- 边界：当前为 Notion v1 SVG summary figures 与 CSV/Markdown 表格，用于快速复现与检查，不是最终投稿级多面板图；Fig.1-Fig.4 是方法/系统示意 v1，Fig.7/Fig.9 使用现有聚合与分析表的 proxy 指标。

### 控制面板

- 代码入口：`src/medharness2/dashboard.py`
- CLI：`PYTHONPATH=src python -m medharness2.cli dashboard build --run-dir <RUN> --output web/control_panel.html`
- API：`POST /dashboard/build`
- 当前产物：`web/control_panel.html`
- 内容：病例/reader/report/quality failure 概览、Workflow Development 表（开发状态、每环节输入输出形式、模型使用策略）、Tool 实现表、模型路由表、实验进度表、Experiment Protocol 表、Figure Artifacts 图表/表格产物表、Run Registry 阶段表，并内嵌机器可读 JSON。

### Legacy 路径兼容

- 代码入口：`src/medharness2/config.py`
- 相关接入：`src/medharness2/generators/registry.py`、`src/medharness2/llm_client.py`、`src/medharness2/validation/preflight.py`
- 行为：当 legacy 配置中的 `/data/isbi/gzp/...` 路径不存在时，自动尝试当前 A40 挂载路径 `/nfsdata_a40/isbi/gzp/...`；只在 fallback 目标真实存在时替换。medHarness CLI 调用会生成临时只读 overlay，递归改写配置内部的 `project_root`、模型、runner 和解释器路径，不修改原配置。
- 覆盖范围：legacy reportgen config、legacy report generation script、artifact generation JSONL、本地 VLM CLI preflight / OCR 调用，以及模型级 `python_paths` 依赖 overlay。
- 目的：保持配置文件和历史路径语义稳定，同时让当前服务器环境能发现并调用真实可用的 medHarness 资源。

### 报告生成 benchmark 增量

- 代码入口：`src/medharness2/workflows/benchmark_generation.py`
- 计划现在为每例记录 modality-aware `input_asset`：CXR/2D 必须使用 image，CT/MRI 必须使用 volume；缺失或不存在的资产在 plan 阶段阻断。
- formal 计划分别输出 `eligible_models`、`rejected_models`、`selected_formal_candidates`、`case_coverage` 和 `blocking_violations`。兼容但未冻结的探索模型不会再污染已有 formal candidate，也不会被自动晋升。
- 冻结实验：`experiments/benchmarks/cxr_chest_qwen3vl8b_11_v1/experiment.yaml`。
- 成功产物：`outputs/benchmarks/cxr_chest_qwen3vl8b_11_v1_20260711/attempt_001/`。
- 结果：`qwen3vl_8b_mimic_cxr_sft` 在 11 例上完成真实 fresh inference，`evidence_tier=exploratory_fresh`、`reference_report_used=false`、质量门控通过；只有 5 个唯一报告，不能据此作临床有效性或模型优劣结论。
- 失败尝试 `attempt_001` 已保留：共享 Python 中 `Jinja2 3.0.3` 不满足 transformers 5.12.1；现使用 Git 忽略的固定版本模型级 overlay `Jinja2==3.1.6`，共享环境未被升级。
- `attempt_002/003` 证明模型自带 `generation_config.json` 的 sampling 策略会产生不同文本；sibling `medHarness` 的 HFVLM adapter 已支持显式 generation parameters/seed，`attempt_004/005` 已验证确定性输出。

## 已生成的 v1 产物

```text
outputs/capability_catalog.json
outputs/run_registry.json
outputs/sample_data_2026-06-05_final_local_routed_52_20260606/run_registry.json
outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_tool2_v1/
outputs/experiments/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_tool2_v1/
outputs/figures/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_tool2_v1/
web/control_panel.html
```

## 验证状态

已实际运行：

```bash
PYTHONPATH=src python -m pytest \
  tests/test_config.py::test_resolve_existing_path_falls_back_to_nfsdata_mount_for_legacy_medharness \
  tests/test_full_design.py::test_sample_full_dry_run_plans_all_compatible_local_models_without_outputs \
  tests/test_full_design.py::test_sample_full_dry_run_filters_local_models_by_source \
  tests/test_legacy_integration.py::test_registry_discovers_ready_legacy_report_generation_models \
  tests/test_legacy_integration.py::test_legacy_cli_generator_invokes_medharness_script \
  tests/test_legacy_integration.py::test_legacy_cli_generator_uses_brain_mri_prompt_for_braingemma \
  tests/test_preflight.py::test_preflight_blocks_mock_ocr_when_real_ocr_required \
  tests/test_workflow_cli.py::test_cli_models_list_shows_local_ready_generators -q
```

结果：`8 passed`。

```bash
PYTHONPATH=src python -m pytest \
  tests/test_catalog_and_registry.py \
  tests/test_workflow_education.py \
  tests/test_experiments_dashboard_figures.py -q
```

结果：相关能力测试通过；当前全量测试结果见下方。

```bash
PYTHONPATH=src python -m pytest \
  tests/test_workflow_cli.py \
  tests/test_merge_batches.py \
  tests/test_analyze_run.py -q
```

结果：`24 passed`。覆盖长流程 CLI 的 `run_registry.json` 写入、失败状态记录和异常失败账本记录。

```bash
PYTHONPATH=src python -m pytest -q
```

结果：`330 passed, 17 warnings`。

```bash
cd /nfsdata_a40/isbi/gzp/medHarness
PYTHONPATH=src:. python -m pytest -q \
  tests/test_reportgen_resource_plan.py::test_hf_vlm_does_not_use_empty_chat_template_processors \
  tests/test_reportgen_resource_plan.py::test_hf_vlm_flags_prompt_echo_as_quality_blocked \
  tests/test_reportgen_resource_plan.py::test_hf_vlm_strips_case_insensitive_prompt_prefix \
  tests/test_reportgen_resource_plan.py::test_hf_vlm_can_override_sample_prompt_when_configured \
  tests/test_reportgen_resource_plan.py::test_hf_vlm_builds_explicit_deterministic_generation_settings \
  tests/test_reportgen_resource_plan.py::test_hf_vlm_includes_sampling_controls_when_sampling_is_enabled
```

结果：`6 passed, 1 warning`。`tests/test_reportgen_resource_plan.py` 全文件当前为 `62 passed, 20 failed`；20 个失败均来自 sibling 项目仍硬编码 `/data/isbi/gzp/...`、当前服务器仅有 `/nfsdata_a40/...` 的既有环境差异，不属于本轮 HFVLM adapter 回归，不能声称 sibling 全文件通过。

```bash
PYTHONPATH=src python -m compileall src tests
```

结果：通过。

```bash
PYTHONPATH=src python -m medharness2.cli workflow validate-run \
  --output-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_v2_qualityfix_20260710 \
  --expected-cases 52 \
  --require-real-ocr
```

结果：`passed=true`，`case_count=52`，`real_ocr_count=52`，`errors=[]`，52 个 case contract 全部有效；三类 audit count 均为 0。

```bash
PYTHONPATH=src python -m medharness2.cli schemas migrate-run \
  --source-run-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606 \
  --output-dir <MIGRATED_RUN>
PYTHONPATH=src python -m medharness2.cli workflow validate-run \
  --output-dir <MIGRATED_RUN> --expected-cases 52 --require-real-ocr
```

结果：真实 52 例迁移 `errors=0`，递归验证 `passed=true`；该结果只证明旧产物可迁移，不是新 LLM 评价结果。

```bash
PYTHONPATH=src python -m medharness2.cli tools catalog \
  --config config/dmx_strong.yaml \
  --output outputs/capability_catalog.json
PYTHONPATH=src python -m medharness2.cli workflow reevaluate-run \
  --source-run-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606 \
  --output-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_tool2_v1
PYTHONPATH=src python -m medharness2.cli experiments run \
  --run-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_tool2_v1 \
  --output-dir outputs/experiments/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_tool2_v1
PYTHONPATH=src python -m medharness2.cli figures build \
  --experiment-dir outputs/experiments/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_tool2_v1 \
  --output-dir outputs/figures/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_tool2_v1
PYTHONPATH=src python -m medharness2.cli dashboard build \
  --run-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_tool2_v1 \
  --output web/control_panel.html
```

结果：

- 能力目录：`outputs/capability_catalog.json`
- 重评估：`cases=52`，`reused_generated_report_count=81`，`new_generation_count=0`
- 重评估 validation：`passed=true`，`require_real_ocr=true`，`real_ocr_count=52`，`errors=[]`
- 实验聚合：`experiments=6`，`educational_study=v1_complete`，并生成 `experiment_protocol.json/md/csv`
- 图表：`figures=11`
- 控制面板：`cases=52 tools=12 experiments=6`，展示 Experiment Protocol 表并在内嵌 JSON 中包含 6 条 protocol mapping
- 结构化核查：`finding_count=105`；hazard error types 为 `false_finding=126`、`incorrect_location=42`、`incorrect_severity=58`、`omission_finding=63`
- 运行账本：原始 run 与重评估 run 各自保留 `run_registry.json`；重评估 run 会记录 `workflow.reevaluate-run`、`workflow.analyze-run`、`workflow.validate-run`、`experiments.run`、`figures.build`、`dashboard.build` 等阶段；控制面板内嵌同一账本 JSON。

## 仍需后续增强

1. API 长流程 endpoint 的 run registry 覆盖可继续扩展；CLI 长流程已记录自动 stage、输入输出、指标和失败状态。
2. 强角色已升级为 `gpt-5.6-terra` 主模型、`claude-opus-4-8` reviewer 和 `gpt-5.6-sol` adjudicator；纯 DMX 11 例链路已恢复，但重复性不足。Yunwu 与 codex+DMX 显式路线不能替代医生 gold labels、跨模型可靠性实验和冻结病例级运行；正式 profile 不允许 deterministic fallback 冒充 LLM 结果。
3. 实验 v1 仍以现有 52 例产物聚合为主；新增 11 例 CXR chest 的 Qwen3-VL 8B exploratory fresh inference，仍不足以支持模型优劣或临床有效性结论。
4. 图表是 v1 SVG summary，不是最终论文级多面板 figure。
5. 控制面板是静态 HTML，不含任务队列、实时日志或后台服务。
