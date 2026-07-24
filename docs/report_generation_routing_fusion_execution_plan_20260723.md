# 报告生成候选路由、Top-K 与融合报告改造方案及执行计划

> **供执行代理使用：** 实施时按本文批次逐项推进并持续更新勾选状态；开始执行前使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`。

**目标：** 将报告生成改造成可解释的多模型候选生产链路，按模态/部位分级路由，保留 Top-K，并额外生成融合报告。

**架构：** 以真实资源状态和合法输入资产为路由前置条件；所有命中模型并行生成候选，再通过结构化视图、无参考排序和独立融合输出结果。普通生产与 benchmark/replay 共用模块，但严格隔离人工参考报告和 artifact 数据边界。

**技术栈：** Python 3.11、Pydantic 合同、YAML 配置、`medHarness` legacy runner、`medHarness2` CLI/API/workflow、Yunwu OpenAI-compatible API。

---

状态：批次 A-G 均已完成；最新 registry 变更后的状态导出、跨项目 focused/full 回归、24 个 schema 导出、Yunwu production artifact 合同和最终 GPU/残留进程审计均已通过。本文件转为后续增量维护账本。
首次制定：2026-07-23
最近更新：2026-07-24
适用项目：`medHarness`（模型资源与统一推理适配）和 `medHarness2`（路由、生成、结构化、评估与工作流）

本文同时作为设计决策记录、实施顺序和验收账本。这里的“可运行”只表示工程调用路径可用；除非明确记录正式验证证据，任何模型都不得被表述为临床可用或临床正确。

> **状态说明：** 文中的“核心完成”表示已有实现和 focused 测试，不表示所有入口、异常路径和真实模型都已验收。发布结论以第 12 节的当前回归结果和第 15 节的未闭环项为准。

## 0. 当前推进状态（2026-07-24）

| 阶段 | 当前状态 | 已落地内容 | 尚未完成的验收或实现 |
| --- | --- | --- | --- |
| 0. 合同与基线 | 已完成 | 本地隔离环境、Pydantic 合同、24 个 schema 导出和完整回归均已建立；production 顶层 round-trip 与兼容字段已验证。 | 后续新增合同字段时继续执行 schema export 和全量回归。 |
| 1. 资源真相与 artifact | 已完成 | 已统一 `runtime_state`、`validation_state`、`fresh_inference`、质量门、阻断原因和最近证据；production 已隔离 reference，预计算候选与 artifact 已执行来源、模型、fresh provenance 及唯一精确 `case_id` 校验。 | 后续模型状态变化时重跑 status export/check。 |
| 2. 路由与候选执行 | 已完成 | 四级 `RoutePlan`、可解释排除原因、候选并发、Yunwu 注入、受控并发及 capability-compatible asset 绑定已接入；“同模态”层接收所有同模态模型，并保留非精确部位原因；X-ray、CT、MRI 本地 fresh smoke 与 Yunwu production smoke 已完成。 | 后续新增 adapter 时继续执行同等资产与生命周期验收。 |
| 3. 结构化候选视图 | 核心完成，模板持续扩充 | 原子 span、规则归一化、模板降级、候选间一致/冲突比较已实现；中文同句测量关联可用，Findings/Impression 总结重复项已受限合并并保留带测量记录。 | 继续按真实报告扩展 anatomy template；不阻塞当前发布。 |
| 4. 无参考 Top-K 与融合 | 已完成 | 无参考排序已按路由 40%、结构完整性 20%、候选共识 25%、内部一致性 15% 计分，并消费 entity/status、laterality、anatomy、measurement、severity、omission 和 internal conflict；真实 Yunwu production smoke 已返回候选、Top-1 和成功融合，融合异常隔离回归已通过。 | 运行性排序仍不得表述为临床质量排名。 |
| 5. 入口与可观测性 | 已完成 | CLI、API、批量 production、run provenance、候选/失败/Top-K/融合字段已接入；三个 benchmark/replay 入口已复用统一候选执行器；三个 legacy 启动点使用 owned process group。 | 后续新增入口必须复用相同合同。 |
| 6. 模型扩充与 readiness | 本轮完成，持续维护 | 已完成 Yunwu、X-ray、CT、MRI 工程 smoke；新增两个人工 gated CXR 资源和一个证据不足的 35GB CXR 审计资源，均按真实访问/证据边界登记，未扩大默认 production 名单。 | 未来发现新资源时继续同一审计流程；不得把未验证模型升级为临床可用。 |
| 7. 状态出口与 readiness | 已完成 | registry 已扩展为 390 条；36 个质量阻塞条目保持 `quality_blocked`，90 条 fresh inference 均有存在的机器可读 evidence；bridge、catalog、CLI/API、静态/动态面板和 readiness 受控区块继续消费同一状态。 | 后续模型增删改时重新导出并执行同等回归。 |

最终发布回归证据为：`medHarness` 资源/status/adapter/evidence 专项 `190 passed in 95.33s`；`medHarness2` focused `299 passed in 43.61s`，完整回归 `2020 passed, 20 warnings in 463.65s`；389 条状态导出及 `--check` 通过，24 个 schema 已重新导出，Yunwu production artifact 合同断言和 `git diff --check` 均通过。此前各定向集合有重叠，不能相加；工程回归也不等同于临床质量验证。

### 0.0 台账同步修正（2026-07-24）

上段 389 条/34 条质量阻塞是 PETAR 语义修正前的历史回归快照。权威 `reportgen_models.yaml` 随后将 `petar_pet_report_generation` 明确降为局部 PET/CT 证据提取而非完整报告模型，并新增 `petar_localized_composed_report`，它只对哈希绑定的局部证据进行确定性文本编排。两者均被质量门阻塞，不能进入默认 production 候选。

本次重新生成的当前受控出口为 390 条：`ready=72`、`preflight_blocked=36`、`source_audit_only=254`、`blocked_gated=5`、`asset_missing=7`；36 条质量门阻塞均为 `validation_state=quality_blocked`，90 条 fresh inference 的机器可读 evidence 均存在。`medHarness/docs/report_generation_model_readiness.md` 与 `outputs/reportgen/model_status_export.json` 已由同一导出脚本同步，后续以该受控出口为准。

### 0.1 已完成的真实 volume-preview 验证

2026-07-23 已分别使用合成 MRI NIfTI 和 CT NIfTI 生成 contact sheet，并通过 Yunwu `qwen3-vl-plus` 完成真实候选生成与融合调用。两例结果均为：`candidate_count=1`、`candidate_failure_count=0`、`top_k_count=1`、`input_asset_kind=contact_sheet`、`fusion_status=succeeded`、`errors=[]`。

验证证据：

- MRI：`outputs/report_generation_volume_preview_smoke_20260723/synthetic-mri-preview-summary.json`
- CT：`outputs/report_generation_volume_preview_smoke_20260723/synthetic-ct-preview-summary.json`

该验证证明 volume 到合法视觉 preview、通用候选、Top-K 和融合链路可以工程运行；输入为合成数据，不用于判断模型临床报告质量。

### 0.2 2026-07-24 真实候选与融合 smoke

| 输入/模型 | 结果 | 证据与处置 |
| --- | --- | --- |
| 合成 MRI preview / `yunwu_general` | production 候选 1、Top-1、融合成功，fresh inference，未使用 reference，无顶层错误。 | `outputs/report_generation_final_smoke_20260724/synthetic-mri-yunwu-result-retry.json`；证明通用候选、结构化、Top-K 和融合工程链路，不评价临床质量。 |
| IU-Xray / `mimic_cxr_report_hf` | CPU fresh 通过，但文本短、重复且缺 Impression。 | `../medHarness/outputs/reportgen/final_smoke_20260724/mimic_cxr_report_hf_cpu/generation.jsonl`；仅 `engineering_smoke_only`，不进入默认候选。 |
| 腹部 CT NIfTI / `merlin_fresh` | GPU2/BF16 fresh 通过，69.348 秒，非空报告，无 warning。 | `../medHarness/outputs/reportgen/final_smoke_20260724/merlin_fresh_gpu2_bf16_v2/generation.jsonl`；证明真实 volume runner 与 dtype 链路。 |
| 脑 MRI FLAIR / `brain_gemma3d` | GPU5/BF16 fresh 非空，但缺 Impression 且病例级幻觉仍在。 | `../medHarness/outputs/reportgen/final_smoke_20260724/brain_gemma3d_gpu5_bf16/generation.jsonl`；保持 `quality_blocked`。 |
| 5 个 IU-Xray / Cosmobillian | 5/5 fresh，但五例输出完全相同且缺 Impression。 | `../medHarness/outputs/reportgen/final_smoke_20260724/cosmobillian_radiologist_llama_gpu6_multisample/generation.jsonl`；fresh 证据成立，质量门仍阻塞。 |

这些 smoke 使用独立本地环境和显式 device；各次 owned PGID 已退出，期间未清理任何既有 GPU 任务。最终跨项目测试完成后仍需重新采样全机 GPU/PID，才能关闭批次 F。

### 0.3 下一轮执行顺序

按以下顺序推进，前一项未闭环时不扩大默认模型范围：

- [x] **生产合同定向修复：** `single_case` 最终 JSON 可通过 `ProductionGenerationArtifact`，并保留 `case_id`、`input`、`errors` 以及旧版 `generated_evaluations`、`rankings`、`pairwise_comparisons` 字段。
- [x] **封闭生产数据边界：** production 无条件清空 reference；预计算候选验证 `reference_report_used=false`、来源、模型身份和 fresh-inference provenance；artifact 只在显式 `benchmark/replay + 精确唯一 case_id` 下可用。
- [x] **完成首轮资产与执行绑定：** PNG/JPEG 实际解码，DICOM/volume/feature 按格式校验；每个模型消费与 `input_capabilities` 匹配的已验证资产并记录 provenance。
- [x] **隔离融合失败：** 融合异常转为状态化失败，不丢失候选和 Top-K。
- [x] **修复结构化重复项：** 合并 Findings 与 Impression 的总结性重复 finding，优先保留带测量和信息更完整的记录，同时维持跨句误绑定保护。
- [x] **统一直接 benchmark workflow：** `run_generation_benchmark()` 已接入统一候选执行器，external VLM 使用传入的 `LLMClient`，并输出 RoutePlan、候选、结构化、Top-K、融合及带哈希的 case artifact。
- [x] **统一单病例/批量 benchmark/replay：** `run_single_case()` 和 `run_batch_readers()` 已改用同一候选合同；reference 缺失时执行 generation-only，存在 reference 时只在同一候选结果上附加参考感知评估；新增 6 个定向用例与六文件相邻回归均已通过。
- [x] **迁移旧行为测试夹具：** 正向夹具已使用真实可解码影像并显式开启 external VLM；预计算报告来自已注册模型且携带 fresh provenance；artifact 仅接受唯一精确 `case_id`；未恢复隐式 fallback 或绕过 RoutePlan。
- [x] **完善进程生命周期：** 本任务创建的 legacy worker 使用独立 process group；timeout、取消、异常、非零退出、成功后残留孙进程均按 `SIGTERM -> grace -> SIGKILL` 回收；CPU 相邻回归 `108 passed`，测试前后 GPU PID/显存快照一致。
- [x] **统一排名与状态真相：** 同模态层语义、无参考结构化排名、canonical/历史质量门字段、status export、catalog、CLI/API、静态/动态面板和 readiness 受控区块已统一；跨项目状态回归通过。
- [x] **重跑回归并修复真实缺陷：** 扩展 focused `500 passed`，完整回归 `2020 passed`；两个旧夹具已迁移到真实 PNG、注册模型、精确 `case_id` 和 fresh provenance；24 个 schema 已重新导出。
- [x] **完成本轮真实 smoke：** Yunwu production、X-ray、CT、MRI 和 Cosmobillian 多样本结果已记录；质量阻塞模型未进入默认候选。
- [x] **完成本轮模型增量审计：** 新增两个 `blocked_gated` CXR 资源和一个 `source_audit_only` 资源；未绕过 gate，也未下载缺少任务证据的约 35GB 权重。
- [x] **最终收口：** 当前 390 条状态已重新生成并通过 `--check`；跨项目 focused/full 回归、24 个 schema、Yunwu production artifact、diff 检查和全机 GPU/残留进程审计均已完成。

### 0.4 当前默认 production 候选与实际 RoutePlan 覆盖

默认配置和两个 Yunwu 强配置均使用显式候选名单，不再以 `generator_models=["*"]` 盲选整个 registry：

- **CXR/胸部专用：** `maira_2`、`chexagent_srrg_findings_full`、`chexagent_srrg_impression_full`、`medgemma_srrg_findings`、`medgemma_srrg_impression`、`lingshu_srrg_impression`、`medmo_4b`。
- **CT：** `merlin_fresh`。
- **通用/跨模态候选：** `medmo_4b_next`、`qwen25vl_med_grpo_report_generation`、`qwen25vl_med_grpo_report_generation_v2`、`qwen25vl_flare2025_lora`、`radiology_infer_mini`。
- **强制外部通用候选：** `yunwu_general`；即使传入显式 `model_keys` 或本地 source 过滤，也必须独立注入一次并去重。

使用当前 default profile、仅构建 RoutePlan（不加载模型、不占用 GPU）的覆盖快照如下：

| 输入 | 计划候选数 | 实际候选键 | 说明 |
| --- | ---: | --- | --- |
| CXR / chest | 13 | 7 个 CXR 专用 + 5 个通用/跨模态 + `yunwu_general` | 所有命中层级并行提交，资源不足时由 worker 排队。 |
| CT / abdomen | 7 | `merlin_fresh` + 5 个通用/跨模态 + `yunwu_general` | `merlin_fresh` 为同模态/部位候选。 |
| MRI / brain | 6 | 5 个通用/跨模态 + `yunwu_general` | 当前没有质量门通过的脑 MRI 专用模型。 |
| MRI / spine | 6 | 4 个同模态 MRI 候选 + `qwen25vl_flare2025_lora` + `yunwu_general` | 同模态模型不再因专科部位不同被硬过滤；已知质量阻塞的 spine 专用模型仍不进入默认候选。 |

这张表描述的是“可进入候选执行队列的计划”，不是临床质量排名，也不保证每个候选最终生成成功；每个候选的失败、质量门和结构化状态都必须留在结果合同中。

`medHarness` 权威 registry 当前受控导出为 390 条：`ready=72`、`preflight_blocked=36`、`source_audit_only=254`、`blocked_gated=5`、`asset_missing=7`，90 条 fresh inference，36 个质量门阻塞条目的 `validation_state` 均为 `quality_blocked`。`scripts/export_reportgen_status.py --check` 已通过，fresh evidence 缺失为 0。

### 0.5 最终实施状态（2026-07-24）

批次 A-G 和最终收口均已完成。后续只在模型、合同或入口发生增量变更时按本文件重新打开对应门禁。C3 已落地并通过回归的接口边界为：

- `src/medharness2/utils/processes.py` 使用 `Popen(start_new_session=True, shell=False)`，实际校验 `pid == pgid`，并将 `Popen` 成功后的全部操作纳入统一 `BaseException` 清理边界；
- timeout、取消、初始化/收尾异常、非零退出及 leader 成功退出后残留孙进程均只回收 owned PGID，按 `SIGTERM -> grace -> SIGKILL` 升级；无法验证 PGID 时只回收 direct child，不猜测或批量终止进程组；
- cleanup 自身异常不会覆盖原始异常；timeout 保留 `subprocess.run(text=True)` 的 partial `stdout/stderr` 类型合同；命令 provenance 对 token/password 等参数脱敏；
- registry 单病例、批量缺失/空输出、`LLMClient` 线程局部状态和 preflight 非 timeout 失败均传播 process provenance；preflight timeout 保持精确 `{"status": "dry_run_timeout"}`；
- 新增 PID 首次捕获异常回归，先确认旧实现会留下子进程，再完成修复；C3 四文件相邻回归为 `108 passed in 23.61s`，语法与 `git diff --check` 通过，测试前后 GPU compute PID 列表一致。

D 批次已完成路由与无参考排名子项：

- `_route_match()` 已严格实现“模态 + 部位精确 -> 所有同模态 -> 同部位且仅显式跨模态/通用 -> 通用”，各层取并集；同模态专科部位不一致时进入 `same_modality` 并记录 `modality_match_body_part_not_exact`，不再输出硬排除；
- 页面文案与合同测试已移除“部位只参与候选排序”的旧描述，明确四级顺序和并集语义，并重新生成 `web/index.html`；
- 无参考 ranker 已消费 laterality、anatomy、measurement、severity、omission 和 internal conflict；缺失属性信号使用 0.5 中性值并输出 availability，同分按 `candidate_id` 稳定排序，质量门失败候选继续排除；
- 当前 default profile 的只读 RoutePlan 快照为 CXR/chest 13、CT/abdomen 7、MRI/brain 6、MRI/spine 6；相关六文件相邻回归为 `144 passed in 1.38s`。
- `ModelStatus`、legacy bridge、catalog、CLI/API、静态 dashboard、动态控制面板和 readiness 受控区块已完整传播 runtime/validation/fresh/quality/evidence 字段；质量阻塞数量统一为 34，fresh evidence 缺失为 0。
- spine native adapter 已删除对 canonical runtime state 的重复覆写；质量阻塞且 fresh smoke 已通过的模型统一表现为 `preflight_blocked`、`runtime_state=preflight_only`，不会被重新提升为 ready。
- D 批次状态回归为 `medHarness 160 passed`、`medHarness2 226 passed, 1 warning`，status export `--check` 通过。

批次 C2 已落地并通过回归的接口边界为：

- `src/medharness2/generators/pipeline.py` 提供统一的 `run_candidate_generation()`，production 通过禁止 reference 的薄封装复用该执行器；
- `src/medharness2/workflows/single_case.py` 的 benchmark/replay 已改用统一候选执行器；无 reference 时返回 RoutePlan、候选、失败、结构化、Top-K 和融合，同时令 `human_evaluation=null` 且参考感知列表为空；
- 有 reference 的 benchmark/replay 先生成同一份候选结果，再在其上附加现有 reference-aware evaluation、ranking 和 pairwise comparison，不再重复生成第二套报告；
- `CaseEvaluationArtifact` 已扩展统一候选合同并校验交叉引用；`ReferenceFreeRankingArtifact` 支持 production/benchmark/replay 三种无参考排名模式；production 的 `reference_report_used=false` 由 production 顶层合同负责；
- `src/medharness2/workflows/batch_readers.py` 不再强制每例具有 reference；generation-only 病例进入生成成功统计，参考感知聚合只统计具有合法 reference 的病例，并显式记录 denominator；
- `src/medharness2/workflows/benchmark_generation.py` 未显式指定 `model_keys` 时，从 formal 与 exploratory 路由计划求兼容模型并集，确保默认名单外的 legacy 模型仍按模型批量预计算一次；不再使用 `_missing_batch_report()`；
- benchmark、CLI、API 和 legacy 正向夹具已使用 Pillow 生成真实 PNG，并使用真实 `.npy` volume；C2 新增 6 个 RED-to-GREEN 用例为 `6 passed in 0.55s`，pipeline 与 benchmark 两文件复跑为 `47 passed in 0.96s`，六文件相邻回归为 `364 passed, 1 warning in 60.61s`。

较早相邻回归曾为 `499 passed, 21 failed, 1 warning in 45.29s`。这些失败已通过迁移夹具和断言消除，根因保留如下，后续不得通过恢复旧行为来规避回归：

1. 旧配置只启用 `cloud_fallback_enabled`，没有显式启用 `external_vlm_enabled`，因此不再产生隐式 Yunwu 候选；测试必须显式配置 report-generation external VLM role。
2. 正向测试用文本伪装 PNG、DICOM 或 NIfTI；测试必须改用 Pillow PNG、合法 DICOM 或真实 NumPy/NIfTI volume。
3. 测试直接注入未注册且缺少 provenance 的 `precomputed_generated_reports`；测试必须显式注册模型，并补齐 `generator_key`、`case_id`、`reference_report_used=false` 和 fresh-inference provenance。
4. sample/API dry-run 期待 artifact 在无精确 `case_id` 时可路由；测试必须改为显式 benchmark/replay 且唯一精确匹配。
5. 个别 batch 断言仍把“缺 reference”视为首要错误；统一生成链路先验证影像资产，因此无影像病例应报告输入资产缺失。

21 个历史失败分布在 `tests/test_full_design.py` 3 个、`tests/test_workflow_cli.py` 11 个、`tests/test_api.py` 6 个、`tests/test_legacy_integration.py` 1 个；另一个 source-isolation 用例已显式声明 benchmark 模式。2026-07-24 对 `test_full_design.py`、`test_workflow_cli.py`、`test_api.py`、`test_legacy_integration.py`、`test_source_isolation.py` 和 `test_report_generation_pipeline.py` 的联合复跑为 `364 passed, 1 warning in 60.61s`。下一步进入独立 process group，再处理 ranker、状态统一和完整回归。

批次 C2 的最终相邻验收命令为：

```bash
cd /nfsdata_a40/isbi/gzp/medHarness2
PYTHONNOUSERSITE=1 PYTHONPATH=src /data/ubuntu_conda/envs/medharness2/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_full_design.py \
  tests/test_workflow_cli.py \
  tests/test_api.py \
  tests/test_legacy_integration.py \
  tests/test_source_isolation.py \
  tests/test_report_generation_pipeline.py
```

## 1. 目标与已确认决策

本次改造将报告生成从“单一模型选择或模糊 fallback”升级为“多候选生成、可解释路由、Top-K 保留、独立融合”的流程。目标是提高不同模态和部位输入的覆盖面，同时不把尚未完成临床质量验证的工程可运行模型伪装成正式临床模型。

以下产品决策已经确认，后续实现不再重复讨论：

1. 已经跑通、但尚未完成临床质量验证的模型可以参与候选报告生成；输出必须保留其运行状态与验证等级。
2. 路由优先级为：`模态+部位精确匹配 -> 同模态 -> 同部位（仅显式跨模态或通用模型） -> 通用模型`。
3. 所有命中路由层级的可运行模型都进入同一候选池，并行生成；优先级用于解释与排序，不用于只保留某一层模型。
4. `artifact_reuse` 继续保留，但只允许用于显式 replay/benchmark，且必须精确匹配 `case_id`；普通报告生成不得复用历史第一条报告。
5. Yunwu 在每例中作为通用候选并行生成，并在没有任何本地可运行候选时承担兜底角色。
6. 每例输出 Top-K 候选报告，并额外输出一份融合报告；融合失败不能隐藏或替代候选结果。
7. 首版不强制最终报告语言、`Findings/Impression` 标题或固定文本模板，保留模型生成原文。
8. 本轮不把安全加固作为功能阻塞项，但任何日志、文档和结果中均不得写入 API token。

### 1.1 改造思路与工程原则

1. **资源真相优先：** registry 只记录真实资产、runner、fresh inference 和质量门状态；bridge、默认配置和调用入口都不得擅自把模型提升为 ready。
2. **候选并行而非单级 fallback：** 四级路由的命中结果取并集，同一模型去重后进入候选池；层级用于解释、排序和审计，不用于提前丢弃较弱命中。
3. **通用候选与兜底解耦：** Yunwu 每例正常参与候选生成；“完全路由不上”只是它承担兜底的特殊情况，不应把常规 Yunwu 候选伪装成 fallback。
4. **生产数据边界前置：** production 在生成、排序和融合前拒绝人工参考报告及不明预计算文本；artifact 只在显式 benchmark/replay 且精确 `case_id` 命中时可用。
5. **合同先于入口：** CLI、API、单病例和批量工作流统一输出 `RoutePlan`、候选、失败、Top-K、融合及 provenance，避免各入口形成不同语义。
6. **局部失败可恢复：** 单模型失败、结构化失败或融合失败都不能终止其他候选；失败必须成为一等结果，而不是被日志吞掉。
7. **证据驱动扩模：** 新模型按“来源审计 -> 资产就位 -> runner preflight -> 真实 fresh smoke -> 探索性质量评估 -> 正式验证”推进，每一步持续更新 readiness 文档。

## 2. 计划制定时的基线问题

下表记录制定计划时的基线问题和对应改造要求。部分 P0/P1 骨架已经落地，但仍有第 15 节列出的真实缺口；保留此表用于解释设计动机和后续防回归，最终是否完成以第 12 节的验证门槛为准。

| 问题 | 当前表现 | 改造要求 |
| --- | --- | --- |
| 模型状态失真 | `medHarness2` 的 legacy bridge 会将被纳入的模型写为 `ready=True` 和非 artifact 的 `fresh_inference=True`，不能反映原始资源状态。 | 状态必须来自 `medHarness` 的真实 preflight/smoke 结论；bridge 不得提升状态。 |
| 伪可运行适配器 | `FeatureEmbeddingRunnerAdapter` 可以返回 `ready`，但 `generate()` 无条件抛出异常。 | 未实现统一推理的适配器标记为 `preflight_only`，不得进入可生成候选池。 |
| 路由过宽 | 当前 registry 主要按模态选模型，MRI spine 可以选中 MRI brain 模型。 | 使用模态和部位的显式分级匹配，并记录每个模型的命中原因或排除原因。 |
| artifact 错配 | 缺少 `case_id` 时会取历史 artifact 的首条报告。 | 无 `case_id`、无精确命中或重复命中均视为不可复用，返回可追踪失败状态。 |
| 串行与重复启动 | 单病例对每个 legacy 模型重复启动 subprocess。 | 用候选执行器统一调度；API 请求并发，本地 GPU 工作按设备和显存预算调度，并支持批量按模型执行。 |
| 云端语义混乱 | `cloud_fallback_enabled` 同时承担普通兜底和外部模型调用含义。 | 新增独立 `external_vlm`/`yunwu_general` 生成源；Yunwu 是候选模型而非隐式 fallback。 |
| 排名数据泄漏 | 当前单病例排名可使用人工参考报告和 finding alignment。 | 区分 benchmark/replay 的参考报告感知排名与普通生成的无参考排名，后者不得读取人工报告。 |
| 溯源不足 | 已发现的 ready registry 项缺少完整 fresh-inference、模型哈希、prompt/preprocess 版本或正式验证 ID。 | 在每份候选结果记录运行与验证信息；缺失时明确为未验证，不补造字段。 |

当前已知状态只代表工程盘点，不等同于临床验证结论。模型资源是否“可用”以后统一拆分为“可运行”“已 smoke”“探索性质量已验证”“正式临床验证”四个维度。

## 3. 目标架构

```text
病例输入与资产准备
        |
        v
输入标准化（modality、body_part、case_id、可用视觉资产）
        |
        v
模型注册表真实状态 + 分级路由计划（RoutePlan）
        |
        +--> 本地/legacy 候选执行器 ----+
        |                               |
        +--> Yunwu 通用候选 ------------+--> CandidateReport[]
                                                |
                                                v
                                  原子 span 抽取与结构化视图
                                                |
                                                +--> 无参考 Top-K 排名
                                                |
                                                +--> Yunwu 融合报告
                                                |
                                                v
                         兼容原字段的 case result + 完整 provenance
```

普通报告生成与 benchmark/replay 共用路由、候选和结构化模块，但遵守不同的数据边界：

- 普通生成：不能把人工参考报告传给候选模型、排名器或融合模型。
- benchmark/replay：仅在显式模式下允许读取参考报告或 artifact；所有结果写入 `mode` 与相应 provenance。
- `artifact_reuse`：只有 `mode in {benchmark, replay}` 且精确 `case_id` 命中时可执行，不能作为普通生成兜底。

## 4. 注册表与模型状态

### 4.1 状态模型

保留现有 `ready` 字段以兼容旧接口，但新增或统一以下独立状态，不再用一个布尔值表达所有含义：

| 字段 | 含义 | 候选资格 |
| --- | --- | --- |
| `runtime_state` | `unavailable`、`preflight_only`、`runnable`、`smoke_verified`。 | 仅 `runnable`/`smoke_verified` 可参与普通候选。 |
| `fresh_inference` | 本次是否真的由模型生成。 | 只作为溯源和正式实验门控；不从 source 名称推测。 |
| `validation_state` | `unvalidated`、`engineering_smoke_only`、`exploratory`、`formal`、`quality_blocked`。 | 前四类可按配置参与并保留状态；`quality_blocked` 不进入默认 production 候选。 |
| `evidence_tier` | 与现有实验合同兼容的证据等级。 | 继续供 benchmark/formal 校验使用。 |
| `input_capabilities` | 可接收的输入形式，例如 `image_2d`、`volume`、`feature_embedding`。 | 输入资产不兼容时排除并记录原因。 |
| `supported_modalities`、`supported_body_parts` | 已规范化的适用范围。 | 供路由器使用。 |
| `cross_modality_allowed`、`is_universal` | 是否允许被“同部位跨模态”或“通用”层选中。 | 防止普通专用模型被错误扩展。 |

`FeatureEmbeddingRunnerAdapter` 在没有真实统一推理实现前必须为 `preflight_only`。如果未来接入官方 runner，则需要完成真实 embedding 输入 smoke 后才能提升为 `smoke_verified`。

### 4.2 legacy bridge 修复

`medHarness2` 从 `medHarness` 读取资源时必须保留原始 `runtime_state`、`fresh_inference`、版本和验证信息。不得再因为配置条目进入 bridge 就写死 `ready=True`，也不得把 artifact 之外的所有 source 写成 fresh inference。

通过统一 machine-readable status export 或在 legacy config 中增加显式字段实现；两端的表格和 `medHarness/docs/report_generation_model_readiness.md` 必须引用同一份状态证据。

## 5. 分级路由设计

### 5.1 RoutePlan

每个病例先构建不可变 `RoutePlan`，而不是直接返回一组模型。它至少包含：

- 输入的原始与规范化 `modality`、`body_part`、`case_id`、运行模式和可用资产；
- 全部 registry 模型的检查结果；
- 每个命中模型的 `route_tier`、`route_reason`、输入兼容性、状态和排除原因；
- 去重后的候选执行顺序以及本次强制加入的 Yunwu 通用候选；
- 没有本地候选时的明确兜底状态。

模型按以下顺序匹配。匹配结果取并集，调度时按资源情况并行；同一模型命中多层时只执行一次，并保留最强层级。

| 层级 | `route_tier` | 选择条件 |
| --- | --- | --- |
| 1 | `exact_modality_body_part` | 模态相同，且规范化部位精确匹配；`unknown` 不视为精确匹配。 |
| 2 | `same_modality` | 模态相同，模型可支持该模态，但没有精确部位匹配。 |
| 3 | `same_body_part_cross_modality` | 部位相同，且模型明确声明 `cross_modality_allowed=true` 或 `is_universal=true`。 |
| 4 | `universal` | 模型明确声明 `is_universal=true`；Yunwu 属于此层，且每例强制纳入。 |

路由前统一处理模态别名和部位同义词。未知部位不会被扩展为任意部位，未知模态不会误选专用模型，只能进入显式通用模型路径。

### 5.2 排除与失败语义

模型未进入候选池时仍写入 `RoutePlan`，典型 `excluded_reason` 包括：

- `runtime_not_runnable`
- `input_asset_incompatible`
- `artifact_mode_not_enabled`
- `artifact_case_id_required`
- `artifact_case_id_not_found`
- `artifact_case_id_ambiguous`
- `cross_modality_not_declared`
- `requested_model_filter`

这能使“没有报告”区分为没有路由命中、模型不可运行、输入不兼容、模型执行失败或 Yunwu 调用失败，而不是统一落成模糊 fallback。

## 6. 候选执行与输入资产

### 6.1 并行策略

所有通过 RoutePlan 的候选均进入执行队列：

- 外部 API（包括 Yunwu）使用有超时、重试上限和独立失败记录的并发任务；
- 本地模型按 `device`、估算显存和模型可复用能力放入资源感知 worker；资源足够时并行，不足时排队，避免多个大模型同时加载导致 GPU OOM；
- 批量任务优先按模型聚合后执行，减少 legacy subprocess 的反复启动；单病例仍通过同一个执行器；
- 单一候选失败只生成 `CandidateFailure`，不得终止其他候选或融合流程。

执行器必须等待和回收其启动的子进程，异常路径也要关闭 worker，避免遗留 GPU 占用。

### 6.2 Yunwu 通用候选和融合能力

Yunwu 配置保持为 OpenAI-compatible API，新增清晰的 `external_vlm`/`yunwu_general` source。它有两种独立职责：

1. 作为每例的通用影像候选，和本地模型并行生成原始报告；
2. 作为融合模型，基于多份候选报告和结构化证据生成 `fusion_report`。

两种调用分别记录模型名、prompt 版本、输入资产、请求状态和耗时，不能把“融合调用”冒充为“直接阅片候选”。

对于输入资产：2D 图像直接使用原图；CT/MRI volume 只有在准备阶段产生可验证的 preview/contact-sheet 或模型真正支持 volume 输入时才可发给外部视觉模型。不能把 volume 路径文字当作图像推理。资产无法提供时返回 `input_asset_unavailable`，不生成虚假的影像报告。

### 6.3 子进程与 GPU 生命周期

当前 `registry.py`、`llm_client.py` 和 `validation/preflight.py` 的三个直接启动点均使用 `subprocess.run()`。legacy runner 内至少有 13 个 adapter 会继续创建二级进程；直接子进程 timeout 后，孙进程可能继续持有 CUDA context。不能在现有实现上直接调用 `killpg()`，因为子进程尚未拥有独立 PGID，可能误杀主流程、并发候选或同终端其他任务。

最小改造为新增 `src/medharness2/utils/processes.py`，统一提供：

```python
def run_isolated_process(
    args,
    *,
    timeout,
    check,
    cwd=None,
    env=None,
    terminate_grace_sec=5.0,
    context=None,
):
    ...
```

实现约束：

- 使用 `subprocess.Popen(..., start_new_session=True, shell=False)`，启动后记录并验证 `pid == pgid`；线程池路径禁止使用 `preexec_fn=os.setsid`；
- 保存 PID、PGID、PPID、UTC 启动时间、终止原因、requested device 和脱敏后的命令；不得记录 token；
- timeout、非零退出、任务取消和任意 `BaseException` 都只回收本次保存的 PGID，按 `SIGTERM -> 最多 5 秒 grace -> SIGKILL` 执行，并最终等待直接子进程；
- leader 正常退出后也检查其 PGID 是否仍有成员；如果后台孙进程未退出，按相同流程回收；
- 保持原有 `CompletedProcess`、`TimeoutExpired`、`CalledProcessError`、stdout/stderr 和调用方 warning/异常合同；
- 禁止使用 `pkill`、`killall`、按命令名扫描或单纯依据 GPU PID 差集清理。GPU 快照只用于审计，不作为 kill 目标。

接入点仅为：

- `generators/registry.py::_run_legacy_subprocess()`，覆盖单例与批量 legacy 候选；
- `llm_client.py::_call_local_vlm_cli()`，覆盖本地 VLM/OCR、外部候选替代路径和融合调用；
- `validation/preflight.py::_run_local_vlm_dry_run()`，保持 `dry_run_timeout` 等现有返回语义。

首轮不修改 `medHarness` 内部 13 个 adapter；它们当前未主动创建新 session，会自然继承外层独立 PGID。若未来某个 runner 主动脱离 session，再对该 adapter 单独治理。

## 7. 借鉴参考项目的报告结构化设计

参考材料为 `designs/2026-07-22-explore-report-structure.zip`。本项目不直接复制其脚本或数据目录，而是沿用其清晰的五阶段边界，并接入 `tools/report_structure.py`、FindingGraph 和工作流合同：

1. **自由文本抽取**：从每份候选原文抽取最小原子 span，核心字段包括 `subject/entity`、`attribute`、`value_raw`、`observation_status`、`certainty`、`evidence_snippet` 和原文位置。
2. **规范化与聚合**：规则去重、实体聚合、属性合并和可选的 schema normalization；任何 LLM 标准化结果必须保留原 span，不能覆盖证据。
3. **解剖树与模板挂载**：按模态和部位加载可版本化 anatomy tree/template；模板缺失时返回通用结构化视图，不阻塞候选报告。
4. **结构化视图**：输出候选内的 findings、否定、确定性、测量、解剖位置，以及候选间的一致与冲突集合。
5. **每报告应用**：为每个 `CandidateReport` 单独写入结构化结果、规则版本、模板版本和失败状态，再供排名、融合和后续工作流使用。

首期重点实现可验证的 span、去重和候选间比较。复杂 anatomy template 的扩展不应阻塞路由、候选和融合的首个可运行版本。

## 8. Top-K 与融合报告

### 8.1 候选与排名

所有成功生成的报告保留在 `candidate_reports` 中。质量门失败、结构化失败或执行失败的结果不会消失，而是带状态保留；只有满足 Top-K 资格的候选进入 `top_k_reports`。

普通报告生成没有人工参考报告，因此不能复用含 `finding_alignment` 的 benchmark 排名。首版无参考排名使用可解释的运行性指标：

- 输入与模态/部位兼容性；
- 路由层级；
- 生成质量门和结构化完整性；
- 候选间的结构化一致性与冲突标记；
- 明确标识为运行性排序，不能解释为临床正确性排序。

排名增强采用四组归一化分量：路由匹配、结构完整性、候选间共识、候选内部一致性。laterality、anatomy、measurement、severity 的跨候选冲突进入共识分量，单份报告内部同一实体的 observation/laterality/measurement/severity 冲突进入一致性惩罚。缺失的结构化信号记为中性值，不记为错误或零分；质量门失败仍直接失去 Top-K 资格。每个分量和冲突原因写入 `metrics`/`ranking_reason`，同分时按 `candidate_id` 稳定排序，整个函数不得接收或读取 reference report。

benchmark/replay 仍可在显式允许时使用现有参考报告感知指标，但必须输出 `ranking_mode=benchmark_reference_aware`。普通生成固定为 `ranking_mode=production_reference_free`。

`top_k_reports` 的 `K` 可配置，默认 `3`，数量不足时返回实际可用数量。近阈值候选仍在 `ranking` 和 `review_candidates` 中可见，但 `top_k_reports` 本身保持至多 K 份，便于调用端处理。

### 8.2 融合报告

融合报告使用所有通过基础质量门的候选，而非仅 Top-K，以避免遗漏低排名候选的独有发现。输入包括候选原文、候选结构化证据、候选间一致/冲突、输入模态/部位及其 provenance。

融合输出要求：

- `report` 为模型原始生成文本，不强制固定章节或语言；
- 返回 `fusion_model`、`fusion_status`、`input_candidate_ids`、`used_image_asset`、`structure_version` 和 prompt/provenance；
- 可选返回引用的候选 ID 或 span ID，但不捏造无法定位的证据；
- 不读取普通生成中的人工参考报告；
- Yunwu 不可用、候选为空或融合失败时，返回显式失败状态，Top-K 与全部候选照常返回。

融合报告是额外候选/汇总产物，不覆盖各模型原报告，也不自动升级为临床最终结论。

## 9. 结果合同与兼容性

现有 `generated_reports`、`generated_evaluations`、`rankings` 和 `pairwise_comparisons` 暂时保留，避免破坏已存在的 benchmark 与下游分析。下面只展示新增关键字段的逻辑结构，不是可直接绕过完整必填字段校验的最小 payload；实际约束以导出的 schema 为准：

```json
{
  "generation_mode": "production_reference_free",
  "route_plan": {
    "normalized_modality": "ct",
    "normalized_body_part": "abdomen",
    "entries": []
  },
  "candidate_reports": [
    {
      "candidate_id": "case-001:model-a",
      "model": "model-a",
      "source": "medharness_cli",
      "route_tier": "exact_modality_body_part",
      "runtime_state": "smoke_verified",
      "validation_state": "exploratory",
      "fresh_inference": true,
      "report": "...",
      "structure": {},
      "provenance": {}
    }
  ],
  "top_k_reports": [
    {
      "candidate_id": "case-001:model-a",
      "rank": 1,
      "ranking_mode": "production_reference_free",
      "ranking_reason": []
    }
  ],
  "fusion_report": {
    "fusion_status": "succeeded",
    "fusion_model": "yunwu_general",
    "input_candidate_ids": [],
    "report": "...",
    "provenance": {}
  }
}
```

顶层合同已经在 `medHarness2/contracts/report_generation.py` 中形成 Pydantic 实现并导出到 `medHarness2/docs/schemas/production_report_generation.schema.json`；最终 production 结果装配已通过完整 round-trip、全量回归和真实 Yunwu artifact 验证。`schema_version` 统一为 `2.0`；任何旧字段的语义变更都必须先增加新字段，再完成迁移、schema 导出和兼容测试。

## 10. 实施阶段

### 阶段 0：冻结合同与测试基线（已完成）

- 为 RoutePlan、CandidateReport、CandidateFailure、FusionReport 和新结果字段定义 schema、fixtures 与版本迁移策略。
- 将普通生成、benchmark 和 replay 的 reference/artifact 使用边界写入测试。
- 在本机 `/data/ubuntu_conda/envs/medharness2` 重建或确认隔离环境；运行时设置 `PYTHONNOUSERSITE=1`，不使用 NFS 上的虚拟环境或共享 user-site。

验收：现有 API/CLI 旧字段仍可读取，新 schema 能通过 JSON 验证，且最终 `single_case` 结果和落盘 JSON 都能 round-trip。该定向回归已通过，仍需在全量测试中复核。

### 阶段 1：修复资源真相与 artifact 合同（已完成）

- 修改 `medHarness/src/medharness/reportgen/adapters/feature_embedding_runner.py`，使未实现推理的 adapter 不能报为可生成。
- 修改 `medHarness2/src/medharness2/generators/registry.py`，移除 legacy bridge 对 `ready` 和 `fresh_inference` 的强制提升。
- 为 `artifact_reuse` 实现严格的 `case_id` 唯一查找和 mode 检查，删除任何“取第一行”的兼容分支；补充来源、模型身份和新鲜推理 provenance 校验。
- 修正已失效的默认解释器/配置路径，并将真实 status export 连接到 registry。

验收：preflight-only 模型不能被普通候选调度；无精确且唯一 `case_id` 的 artifact 绝不返回历史报告；production 不读取 reference；bridge 的状态与源状态一致。production reference/provenance 与 artifact RoutePlan 定向回归已通过；历史质量门字段统一和全量回归仍待完成。

### 阶段 2：实现 RoutePlan 与候选调度（已完成）

- 在 `medHarness2/src/medharness2/generators/` 增加路由模块，供 registry、CLI、API 和 batch workflow 共用。
- 用分级路由取代仅模态筛选，支持部位同义词、显式跨模态及通用模型声明。
- 改造 `tool8_generate.py`，把“选模型、执行、失败收集、Yunwu 注入”拆开，并输出完整 RoutePlan。
- 增加本地 worker/API 并发执行接口；先以资源受控并发保证正确性，再根据实测显存调整并发度；统一 prepared asset 和 legacy runner 的输入选择。

验收：MRI spine 输入可把 MRI brain 专用模型作为 `same_modality` 软匹配候选，但不得把它标成模态+部位精确命中；每例 RoutePlan 都可解释所有命中和排除；Yunwu 出现在每例候选计划中；模型实际消费的资产与计划中的已验证资产一致。2D 损坏资产拒绝、单病例资产绑定、批量混合资产绑定，以及 DICOM、volume、feature 独立格式和真实模型 smoke 均已覆盖。

### 阶段 3：接入结构化候选视图（已完成，模板按增量维护）

- 以 `tools/report_structure.py` 为候选结构化模块，复用现有章节标准化能力并保存原子 span 与结构化视图。
- 基于参考 ZIP 的五阶段边界实现抽取、规则去重/聚合、模板挂载接口和候选间差异汇总。
- 为每个候选独立保存 `structure_status`，结构化失败不能删除原报告。

验收：中英文自由文本均能产生可追踪 span；同句中文测量能正确关联到 finding；每个结构化结论都能回指原文 `evidence_snippet`；模板缺失时稳定降级。

### 阶段 4：实现无参考 Top-K 与融合报告（已完成）

- 扩展 `tool9_rank.py` 或增加专用 production ranker，避免普通路径读取人工参考报告。
- 改造 `workflows/single_case.py`，同时生成兼容旧结果和 `candidate_reports`、`top_k_reports`、`fusion_report`。
- 增加 Yunwu 融合调用和显式失败状态；融合输入只来自候选、结构化视图和合法图像资产；捕获融合模型和隐私/输入异常，保留已有候选与 Top-K。
- 对 benchmark/replay 保留现有参考感知评分，但采用独立 `ranking_mode`。

验收：普通生成中没有 reference report 泄漏；Top-K 最多 K 份且候选原文完整保留；融合失败不影响 Top-K。融合异常隔离和结构化排名增强定向回归已通过；排名覆盖 laterality、anatomy、measurement、severity、omission、internal conflict、缺失信号中性值和稳定同分排序。

### 阶段 5：接入 CLI、API、批量工作流和可观测性（已完成）

- 更新单病例 CLI/API、批量生成和 benchmark/replay 入口，新增 generation mode、Top-K、融合开关和模型 source 选择；`run_generation_benchmark()`、`run_single_case()` 和 `run_batch_readers()` 已统一复用候选生成合同。
- benchmark/replay 无 reference 时返回 generation-only 结果，有 reference 时只在同一候选结果上附加参考感知评估；批量汇总分别记录生成病例和参考评估病例 denominator。
- 在 run registry、输出 JSON 和失败记录中保存路由、运行时间、模型版本、prompt/preprocess 版本及资产状态。
- 新增 `utils/processes.py`，让三个 legacy 启动点统一使用独立 process group；timeout、异常、取消、非零退出和 leader 提前退出都回收本任务 PGID。
- 结束后检查残留 subprocess/GPU 进程，并只回收本次任务创建且有 PID/PGID/启动时间记录的进程组。

验收：单病例、批量和 benchmark 使用同一候选/路由语义；失败可定位到模型、资产、路由或外部 API；CLI 测试不会因默认配置隐式启动本地 GPU 模型。C2 新增定向测试、六文件相邻回归、C3 进程组治理和上一轮工作树全量回归均已通过；本轮仅需在 registry 增量后重跑最终回归。

### 阶段 6：扩充模型与持续更新资源文档（本轮完成，后续持续维护）

- 按 X-ray、CT、MRI、跨部位通用影像模型建立候选清单；每个模型依次完成许可证/输入约束、镜像下载、隔离环境、真实 fresh inference smoke、失败原因和资源占用记录。
- Hugging Face 权重优先使用 `HF_ENDPOINT=https://hf-mirror.com` 和现有 `medHarness/scripts/download_reportgen_candidate.py` 断点下载；Python 包使用项目已验证的镜像源。镜像确实不可用时才回退官方源，并在 readiness 中记录回退原因、revision、文件大小和 SHA-256。
- 环境统一建立在本地 `/data/ubuntu_conda/envs/<name>`，运行时设置 `PYTHONNOUSERSITE=1`；不在 NFS 创建、激活、安装、升级或直接迁移 Conda/venv，不使用 `pip --user`。
- 每次新增、失效、修复或验证一个模型，都更新 `medHarness/docs/report_generation_model_readiness.md`：支持模态/部位、运行状态、验证等级、配置入口、已知限制和最近验证日期。

扩充轨道按当前路由覆盖缺口排序：

| 轨道 | 优先目标 | 最小接入证据 |
| --- | --- | --- |
| X-ray | 胸部专用模型优先，同时接受其他部位的公开 2D X-ray 报告模型。 | 公开权重、合法真实 X-ray、非空 fresh report、结构化与质量门结果。 |
| CT | 胸部、腹部、多器官 3D 报告模型；区分真正 volume 输入与 preview-only 通用 VLM。 | NIfTI/NumPy volume 输入合同、预处理版本、真实 volume fresh report、显存峰值与退出审计。 |
| MRI | 脑、脊柱及跨部位 MRI；严格区分脑专用、脊柱专用和显式通用模型。 | 序列/方向/多模态输入要求、合法 MRI 样本、fresh report、错误部位路由反例。 |
| 通用影像 | 明确声明跨模态的医学 VLM，以及 Yunwu 直接候选。 | 至少覆盖两种模态或有明确模型卡能力声明；每种输入类型分别 smoke，不由单一 CXR smoke 推断 CT/MRI 可用。 |

每个模型先进入 registry/readiness 的非默认状态；只有资源完整、runner 可复现、真实 fresh smoke 通过、质量门未阻塞且状态出口一致后，才允许在单独变更中加入默认 production 候选。临床质量验证继续作为独立更高等级，不由工程 smoke 自动升级。

2026-07-24 本轮增量结果：通过 `hf-mirror.com` 复核并登记 `shaafsalman_qwen35_9b_cxr_lora_v2`、`shaafsalman_qwen35_9b_cxr_gguf` 和 `functionalize_xr_cxr_ra_ummc_with_impressions_audit`。前两项为人工 gated，后一项虽公开 35,068,494,784-byte 权重，但模型卡缺训练、许可、任务、评测和 runner 证据；三者均保持非默认状态。Cosmobillian 5 例 fresh 证据已补齐，但因跨样本完全相同输出保持质量阻塞。

验收：文档中“可用”的定义与机器可读 registry 一致；未真正生成过报告的模型不能被标为可运行。

### 阶段 7：统一状态出口与 readiness 生成（已完成）

- 已修正 `quality_gate_blocked=true` 与 `validation_state=quality_blocked` 数量不一致，`cosmobillian_radiologist_llama_cxr_report_generation` 已补齐 canonical validation state。
- `BrainGemma3DAdapter` 已同时兼容 `quality_gate_blocked` 和历史字段 `clinical_quality_gate_blocked`；spine native adapter 也已停止覆写 canonical runtime state。
- capability catalog、CLI/API、静态 dashboard 和动态控制面板完整保留 `runtime_state`、`validation_state`、`fresh_inference`、质量门原因、输入能力和最近证据，不再退化成单一 `ready`。
- registry/status export 已生成 `medHarness/docs/report_generation_model_readiness.md` 的受控区块和 `outputs/reportgen/model_status_export.json`；人工说明保留在受控区块之外。

验收：权威 registry、medHarness2 bridge、catalog、CLI/API、readiness 文档和网页对同一模型给出一致状态；当前导出为 390 条、36 条质量阻塞、90 条 fresh inference，fresh evidence 缺失为 0；任何质量阻塞模型均不进入默认 production 候选。最新导出和跨项目回归均已在最终收口复跑通过。

## 11. 代码影响范围

| 位置 | 职责与改造内容 |
| --- | --- |
| `medHarness/src/medharness/reportgen/registry.py`、模型配置 | 输出真实 runtime/validation 状态，兼容历史质量门字段，阻止质量阻塞模型进入 ready。 |
| `medHarness/docs/report_generation_model_readiness.md` | 持续维护模型资源、fresh smoke、质量门、支持模态/部位和已知限制。 |
| `medHarness2/src/medharness2/generators/registry.py` | legacy bridge、严格 artifact、默认候选过滤和统一生成适配。 |
| `medHarness2/src/medharness2/generators/routing.py` | 四级 RoutePlan、部位归一化、输入能力检查、强制 Yunwu 和排除原因。 |
| `medHarness2/src/medharness2/generators/assets.py` | 验证 2D/volume preview 资产，拒绝缺失、空文件和不支持格式。 |
| `medHarness2/src/medharness2/generators/orchestrator.py` | 并行候选调度、按 device 限流、局部失败隔离和 worker 生命周期。 |
| `medHarness2/src/medharness2/generators/pipeline.py`、`fusion.py` | production 候选结构化、无参考 Top-K、融合和顶层结果装配。 |
| `medHarness2/src/medharness2/contracts/report_generation.py` | `2.0` 顶层生产合同、交叉引用校验和 legacy 字段镜像约束。 |
| `medHarness2/src/medharness2/tools/report_structure.py`、结构模板 | 原子 span、规范化聚合、模板挂载、候选间一致与冲突比较。 |
| `medHarness2/src/medharness2/tools/tool8_generate.py`、`tool9_rank.py` | 将隐式 fallback 改为候选编排，并分离生产无参考排序。 |
| `medHarness2/src/medharness2/utils/processes.py` | 独立 process group 启动、TERM/KILL 升级、超时/异常清理和进程 provenance。 |
| `medHarness2/src/medharness2/workflows/`、`api.py`、`cli.py` | 统一单病例、批量、API、benchmark/replay 的模式、资产和结果语义。 |
| `medHarness2/src/medharness2/catalog.py`、dashboard/web 状态消费端 | 完整传播 runtime/validation/quality gate 状态，禁止从 `ready` 反推其他状态。 |
| `medHarness2/config/*.yaml` | 使用显式默认候选名单，配置 Yunwu 直接候选和独立融合角色。 |
| `medHarness2/tests/`、`docs/schemas/` | 覆盖路由、artifact、数据边界、失败隔离、结构化、Top-K、融合、进程组回收、状态传播和合同导出。 |

## 12. 验证与发布门槛

按从小到大的顺序验证：

1. schema、路由和 artifact 的纯单元测试；
2. mock local model + mock Yunwu 的单病例端到端测试；
3. 真实 Yunwu 2D 图像 smoke，以及 CT/MRI preview 资产 smoke；
4. 至少一组 X-ray、CT、MRI 的真实本地候选 smoke，记录 GPU 占用和退出后残留进程；
5. batch 按模型调度的最小 smoke；
6. 全量相关测试与既有 benchmark/replay 回归。

### 12.1 已记录的 focused 验证

- `medHarness` 资源计划回归：`160 passed in 89.42s`。
- `medHarness2` 既有路由、pipeline、排名/融合、结构化、合同、legacy、modality、LLM 和 benchmark focused 基线：`232 passed in 15.36s`。
- production reference/provenance、artifact RoutePlan、相关合同与路由回归：`67 passed`。
- 本轮最新报告生成 focused 回归：`217 passed in 16.78s`，覆盖损坏图片拒绝、单病例和批量混合资产绑定、融合异常隔离。
- 批次 B 资产格式专项回归：2026-07-24 复跑为 `27 passed in 0.36s`；覆盖有扩展名及无扩展名 DICOM、`.npy/.npz`、NIfTI、HDF5/Torch feature 及损坏文件拒绝。
- 批次 B 结构化、重评估、批量与 CLI 局部回归：`485 passed in 24.25s`。
- 直接 benchmark workflow 回归：`24 passed in 0.71s`；覆盖 external VLM 真实 `LLMClient` 调用、case artifact、manifest SHA-256、按模型批量执行和失败元数据。
- C2 单病例/批量 benchmark/replay 新增合同回归：`6 passed in 0.55s`；覆盖无 reference generation-only、有 reference 只附加评估、批量 generation-only 合同，以及未显式 `model_keys` 时的 legacy 计划模型并集预计算。
- C2 pipeline 与 benchmark 文件复跑：`47 passed in 0.96s`。
- C2 较早相邻回归：`499 passed, 21 failed, 1 warning in 45.29s`；用于记录旧夹具迁移前的失败基线。
- C2 最终六文件相邻回归：`364 passed, 1 warning in 60.61s`；覆盖 `test_full_design.py`、`test_workflow_cli.py`、`test_api.py`、`test_legacy_integration.py`、`test_source_isolation.py` 和 `test_report_generation_pipeline.py`。
- C3 进程生命周期相邻回归：`108 passed in 23.61s`；覆盖 owned PGID、timeout/取消/异常、TERM->KILL、成功与非零退出后的孙进程、并发/无关组隔离、cleanup 原异常保持、timeout 输出类型、registry/LLM/preflight provenance 传播。测试前后 GPU compute PID 与显存快照一致，未发现本任务残留。
- D 路由与排名子项相邻回归：`144 passed in 1.38s`；覆盖四级并集路由、同模态不同部位软命中、显式跨模态门控、无参考属性冲突/缺失中性值/内部冲突/稳定同分、结构化、pipeline、生产合同及网页口径。
- D 状态真相回归：`medHarness` 资源计划 `160 passed in 84.04s`，BrainGemma/status export 专项 `7 passed in 8.14s`；`medHarness2` catalog、CLI/API、静态/动态面板和 legacy 相邻回归 `226 passed, 1 warning in 64.39s`。
- 上一轮状态导出基线：386 条 registry 状态、34 条质量阻塞、89 条 fresh inference；当时 `scripts/export_reportgen_status.py --check` 通过，所有 fresh 条目都有机器可读 evidence。
- 本轮 registry 增量 RED-GREEN：新增 gated/source-audit 资源与 Cosmobillian 多样本证据的定向集合 `3 passed in 6.42s`；目标状态为 389 条、34 条质量阻塞、90 条 fresh inference。
- 最终 `medHarness` 资源/status/adapter/evidence 专项：`190 passed in 95.33s`。
- 最终 `medHarness2` focused：`299 passed in 43.61s`；完整回归：`2020 passed, 20 warnings in 463.65s`。
- 最终 schema/artifact：重新导出 24 个 schema；Yunwu artifact 通过 `ProductionGenerationArtifact`，候选 1、失败 0、Top-K 1、融合成功、候选未使用 reference、顶层无错误；`git diff --check` 通过。
- 最终 GPU/PID：历史 owned PGID `1646182`、`1653552`、`1659384`、`1666862` 和本轮 pytest 会话均已退出；GPU compute 列表没有本轮 medHarness/medHarness2 进程。既有 ABS、reg_syn、mac、mmseqs、SelfRDB 等任务保持不动。
- schema 已重新导出，`docs/schemas/index.json` 当前包含 24 个 `medHarness2` schema。
- 当前 `medHarness2` 完整回归：`2020 passed, 20 warnings in 444.65s`；扩展 focused 为 `500 passed, 1 warning in 73.03s`。

C2 相邻回归中的 21 个历史失败已完成迁移，原分布为 `tests/test_full_design.py` 3 个、`tests/test_workflow_cli.py` 11 个、`tests/test_api.py` 6 个、`tests/test_legacy_integration.py` 1 个。主要根因是旧测试依赖隐式 cloud fallback、伪影像文件、未注册且无 provenance 的预计算报告、非精确 artifact `case_id`，或旧的缺 reference 报错顺序。修复采用夹具和断言迁移，并保留下列新约束：

1. Yunwu 作为 external VLM 候选时必须显式启用并配置角色，`cloud_fallback_enabled` 不再隐式等价于 report generation。
2. 正向输入必须是可解码的真实格式资产；损坏或伪装文件继续 fail closed。
3. 预计算报告必须来自已注册模型，并携带可验证的模型身份、`case_id`、`reference_report_used=false` 和 fresh provenance。
4. artifact 只允许显式 benchmark/replay 且唯一精确匹配 `case_id`。

历史完整回归中的 3 个失败均已完成定向修复，并已在当前完整测试中复核：

1. `tests/test_full_design.py::test_batch_readers_runs_model_groups_in_parallel_on_distinct_devices`：mock `generate_batch` 已兼容新的 `include_failures` 关键字参数，恢复对并行度本身的验证。
2. `tests/test_reevaluate_run.py::test_reevaluate_run_reuses_generated_reports_without_generation`：Findings/Impression 总结性重复已按受限规则合并，保留带测量 finding，并继续保护同部位不同测量病灶和跨句测量。
3. `tests/test_workflow_cli.py::test_single_case_does_not_evaluate_empty_generation_placeholder`：旧的“无候选即不生成”预期已按每例强制 Yunwu 的产品决策调整，相关 CLI 测试改用显式 mock-only 配置，避免隐式加载本地 GPU 模型。

上述批次可能包含重叠测试，不能简单相加为总测试数；它们只表示对应命令当时通过。最终发布结论必须以修复后的当前工作树完整命令为准。

### 12.2 最终收口命令

先确认解释器和 user-site 隔离：

```bash
conda info --envs
/data/ubuntu_conda/envs/medharness2/bin/python -m pip -V
PYTHONNOUSERSITE=1 /data/ubuntu_conda/envs/medharness2/bin/python -c 'import sys; print(sys.executable, sys.prefix)'
```

运行 `medHarness` 资源计划回归，期望全部通过且不加载 GPU 模型：

```bash
cd /nfsdata_a40/isbi/gzp/medHarness
PYTHONNOUSERSITE=1 PYTHONPATH=src /data/ubuntu_conda/envs/medharness_merlin/bin/python -m pytest -q -p no:cacheprovider tests/test_reportgen_resource_plan.py
```

运行 `medHarness2` focused 回归和全量回归：

```bash
cd /nfsdata_a40/isbi/gzp/medHarness2
PYTHONNOUSERSITE=1 PYTHONPATH=src /data/ubuntu_conda/envs/medharness2/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_report_generation_routing.py \
  tests/test_report_generation_pipeline.py \
  tests/test_report_generation_ranking_fusion.py \
  tests/test_report_structure_candidates.py \
  tests/contracts/test_report_generation_contracts.py \
  tests/test_process_lifecycle.py \
  tests/test_catalog_and_registry.py \
  tests/test_legacy_integration.py \
  tests/test_modality_routing.py \
  tests/test_llm_client.py \
  tests/workflows/test_benchmark_generation.py

PYTHONNOUSERSITE=1 PYTHONPATH=src /data/ubuntu_conda/envs/medharness2/bin/python -m pytest -q -p no:cacheprovider
```

重新导出合同并检查 diff，期望 index 包含 24 个 schema 且 `production_report_generation` 存在：

```bash
cd /nfsdata_a40/isbi/gzp/medHarness2
PYTHONNOUSERSITE=1 PYTHONPATH=src /data/ubuntu_conda/envs/medharness2/bin/python -m medharness2.cli schemas export --output-dir docs/schemas
rg -n 'production_report_generation|report_generation_route_plan' docs/schemas/index.json
git diff --check
```

使用已有合成 MRI preview 做一次只含 Yunwu 的 production smoke，期望 `candidate_count=1`、`candidate_failure_count=0`、`top_k_count=1` 且 `fusion_status=succeeded`：

```bash
cd /nfsdata_a40/isbi/gzp/medHarness2
PYTHONNOUSERSITE=1 PYTHONPATH=src /data/ubuntu_conda/envs/medharness2/bin/python -m medharness2.cli workflow single-case \
  --image outputs/report_generation_volume_preview_smoke_20260723/assets/synthetic-mri-preview/contact_sheet.png \
  --output outputs/report_generation_final_smoke_20260723/synthetic-mri-yunwu-result.json \
  --case-id synthetic-mri-yunwu-final \
  --modality mri \
  --body-part brain \
  --generation-mode production \
  --top-n 1 \
  --model yunwu_general \
  --config config/yunwu_strong.yaml
```

测试和 smoke 前后都执行 GPU 审计：

```bash
nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory --format=csv,noheader
ps -eo pid,ppid,pgid,sid,user,lstart,etimes,cmd | rg 'medharness|run_report_generation|medharness2|python'
```

只终止能由 PID、PPID、命令行和启动时间确认属于本次执行的残留进程；先发 `SIGTERM` 并复查，再在仍无法退出时考虑 `SIGKILL`。不得按进程名批量清理，也不得处理其他用户或既有任务。

核心验收断言：

- 同模态但部位不精确的专用模型只能进入 `same_modality`，不得伪装成精确部位命中；
- 无 `case_id` 的 artifact 无法产生报告；
- 每例均有 Yunwu 候选计划和明确的实际执行结果；
- 普通生成不使用人工参考报告；
- 所有候选、Top-K 与融合报告都有可读 provenance；
- 融合调用失败、局部模型失败或结构化失败不会丢失其他候选；
- 本地任务结束后无本次启动的残留 GPU worker；
- `report_generation_model_readiness.md` 与 registry 状态一致。

## 13. 非目标与后续边界

- 本计划先解决工程路由、真实状态、候选输出和可审计融合，不把模型输出宣称为临床诊断结论。
- Top-K 的生产排序是运行性/一致性排序，不等价于医生质量排名；正式质量排序需要冻结 gold set、读片专家评估和独立验证计划。
- Anatomy tree/template 将按模态和部位逐步扩充，首期不以完整覆盖所有解剖模板作为上线阻塞条件。
- 模型扩充按真实 smoke 和资源可用性逐个纳入，不以下载完成或配置文件存在作为“可用”证据。

## 14. 实施顺序建议

按“生产边界与合同 -> 合法资产与失败隔离 -> 统一入口与运行管理 -> 回归与台账 -> 模型扩充”执行。这样可先保证任一候选报告的来源、输入和输出语义可信，再增加模型数量。每个新增模型单独完成资源、runner、真实输入、质量门和文档闭环，不把多模型下载、环境迁移和核心路由修改混在同一批次。

## 15. 审计优先闭环项与状态

以下项目是本轮不能用“focused 已通过”替代的实际闭环项。每项完成时同时更新本节状态、测试证据和 `medHarness/docs/report_generation_model_readiness.md`（如涉及模型状态）。

| 状态 | 优先级 | 问题与根因 | 解决方案 | 验收断言 |
| --- | --- | --- | --- | --- |
| 已完成 | P0 | `single_case` 在生产结果上追加字段，曾触发合同 `extra_forbidden`，且缺少旧字段兼容镜像。 | 顶层合同已显式声明兼容字段，workflow 在写盘前一次性装配和重验。 | 定向 round-trip 与完整回归均通过；内存结果和 JSON 落盘可 `ProductionGenerationArtifact.model_validate()`。 |
| 已完成 | P0 | production 的 reference 和预计算候选来源校验不够严格。 | production 已无条件清空 reference；预计算候选校验 source、model、`reference_report_used=false`、fresh provenance；artifact RoutePlan 拒绝缺失、非法、未命中或重复 `case_id`。 | 定向和完整回归均确认人工参考、伪 provenance 和不唯一 artifact 不能进入 production/Top-K/融合。 |
| 已完成 | P0 | 资产仅按后缀/非空校验，且路由资产与 legacy runner 实际输入可能不一致。 | 已真实解码 2D 图像，并按 DICOM、NumPy/NIfTI volume、HDF5/Torch feature 校验；每个候选按 capability 绑定已验证 asset 及哈希/provenance。 | 资产专项、完整回归及 X-ray/CT/MRI 真实 smoke 已覆盖实际模型消费。 |
| 已完成 | P0 | 融合抛出 `PrivacyViolation`、`ValueError` 等异常时可能中断整个结果。 | 融合边界捕获隐私、输入和网络异常，写入 `fusion_status=failed` 与错误 provenance。 | 定向和完整回归确认失败融合不删除成功候选或 Top-K。 |
| 已完成 | P1 | Findings 与 Impression 的总结性重复 finding 未合并，后出现的简略项可能覆盖带测量记录。 | 已识别跨章节总结性重复；只在属性一致且测量兼容时合并，优先保留带测量或属性更完整的 finding。 | 定向和完整回归均通过。 |
| 已完成 | P1 | benchmark/replay 入口此前分裂。 | 三个入口现均先调用 `run_candidate_generation()`；无 reference 返回 generation-only，有 reference 只附加评估；批量预计算使用 formal 与 exploratory 计划模型并集。 | 定向、相邻、focused 和完整回归均通过。 |
| 已完成 | P1 | 路由第二层曾错误排除同模态其他专科部位模型。 | 所有同模态模型进入 `same_modality`，第三层仍只允许显式跨模态或通用模型。 | 定向、页面合同和完整回归通过；MRI/spine 候选从 3 个修正为 6 个。 |
| 已完成 | P1 | 质量门数量不一致，部分 adapter 和状态出口会丢失或覆写 canonical 状态。 | 已修正 Cosmobillian 漏项并补齐 5 例 fresh evidence，兼容 canonical/历史字段，删除 spine runtime 重复推导；所有出口消费统一状态。 | 389 条、34 条质量阻塞、90 条 fresh；最终 export/check 和跨项目回归通过。 |
| 已完成 | P1 | legacy runner 孙进程可能在异常后继续占用 GPU。 | 使用独立 process group 和 TERM/grace/KILL 回收，传播完整 provenance。 | C3 `108 passed` 且完整回归通过；测试前后无本任务新增 GPU PID。 |
| 已完成 | P2 | 无参考 ranker 原先未充分使用结构化冲突。 | 已扩展可解释打分项，缺失信号取中性值，保持不读取 reference。 | 定向、相邻和完整回归通过。 |
| 已完成 | P2 | readiness 文档和旧 route check 曾存在统计/状态漂移。 | readiness 顶部改为自动受控区块；fresh smoke evidence 已补齐；所有消费端使用同一导出。 | export/check、专项和完整回归通过，fresh evidence 缺失为 0。 |

## 16. 执行批次与最终状态

- [x] **批次 A，生产边界：** 完成顶层合同、production reference/provenance、精确唯一 artifact `case_id` 和 RoutePlan 状态定向回归；最终由批次 D 再做全量确认。
- [x] **批次 B，资产与故障隔离：** 已完成真实资产解码、capability 绑定、融合失败隔离、Findings/Impression 受限去重，以及 DICOM、volume、feature 独立资产回归；最终由批次 D 再做全量确认。
- [x] **批次 C1，直接 benchmark workflow：** 已完成统一候选执行器、external VLM、case artifact、manifest SHA-256 和批量失败元数据，定向回归 `24 passed in 0.71s`。
- [x] **批次 C2，全部 benchmark/replay 入口：** single-case/batch 已统一；无 reference generation-only、有 reference 只附加评估、兼容模型并集预计算和旧双生成删除均已完成；新增 6 个定向测试和六文件相邻回归 `364 passed, 1 warning` 均通过。
- [x] **批次 C3，进程生命周期：** 独立 process-group helper 已接入 registry/LLM/preflight；孙进程 timeout、TERM->KILL、非零退出、成功退出、异常、PID 捕获失败、并发和无关进程隔离回归 `108 passed`，GPU 前后快照一致。
- [x] **批次 D，排名与状态真相：** 无参考结构化排序、质量门历史字段、catalog/CLI/API/status export、静态/动态面板和 readiness 受控区块均已统一；跨项目状态回归通过。
- [x] **批次 E，回归与合同：** resource、focused、完整回归和 schema export 均已通过；本轮最终完整结果为 `2020 passed, 20 warnings in 463.65s`。
- [x] **批次 F，真实 smoke 与 GPU 审计：** Yunwu、X-ray、CT、MRI 和 Cosmobillian 多样本 smoke 已完成；各次 owned PGID、历史 PGID 和本轮测试会话均已退出，最终 GPU compute 列表没有本任务进程，未处理任何既有任务。
- [x] **批次 G，本轮模型扩充：** 已按镜像优先完成公开差分检索，新增两个 gated CXR 条目和一个证据不足的公开 CXR 审计条目；没有绕过访问控制，没有把名称或下载可用性当作 report-trained/ready 证据，registry/readiness 已同步。

新增模型只有在资源完整、runner 可复现、真实 fresh smoke 通过、质量门未阻塞且状态出口一致后，才允许单独加入默认 production 候选；批次 F/G 的工程证据不等价于临床质量验证。本轮测试命令摘要、状态数字和 GPU 审计结论已回填，后续增量变更继续按相同门禁维护。
