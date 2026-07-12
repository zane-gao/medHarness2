# medHarness2 本周工作汇报

汇报周期：2026-06-01 至 2026-06-06

## 一、工作背景

本周工作围绕 medHarness2 的完整落地展开。原始系统设计稿核心目标是建立医学影像报告生成与评估闭环：以人工报告和影像/体数据为输入，调用本地或云端模型生成候选报告，再完成单报告评估、Top-N 排序、human-vs-AI 成对比较和批量统计输出。

本周的工作是在洪学长原设计基础上继续完善、实现和验证，把设计稿中的工具、模块、工作流和样本数据运行链路工程化落地，并确认本机已就位模型资源能否支撑真实样本运行。

## 二、本周主要目标

1. 判断 `designs/` 中设计稿与当前实现之间的差距，并补齐尚未实现的 Tool、Module 和 Workflow。
2. 将系统从最小 CLI 原型推进为核心 Python library + 薄 CLI/API 入口，保留后续接平台的空间。
3. 接入 `/data/isbi/gzp/medHarness/docs/report_generation_model_readiness.md` 中本机已就位的报告生成资源，而不是只依赖 API。
4. 适配 `/data/isbi/gzp/medHarness/data/sample_data_2026-06-05`，完成报告 OCR、DICOM 预处理、模型路由、批量运行、合并和结果分析。
5. 对最终 52 例样本输出做可复查验证，明确哪些结果来自 fresh 本地模型，哪些来自 artifact baseline 或 local VLM fallback。

## 三、基于原设计的完善

本周在原设计稿基础上做了以下收敛和增强：

1. 系统形态从“CLI 系统”调整为“核心 Python library + 薄 CLI/API”。CLI 用于批处理和 smoke，FastAPI 用于平台化入口验证，核心逻辑统一在 Python library 中实现。
2. 将 `LLMClient` 与 `ReportGeneratorRegistry` 解耦。前者负责 OCR、结构化解释、云端或本地 VLM fallback；后者负责本机报告生成模型、历史 artifact 和旧 medHarness runner 适配。
3. 明确 Tool 5 的 candidate/reference 语义：candidate-only 记为 `false_finding`，reference-only 记为 `omission_finding`，precision 和 recall 的分母分别对应 candidate 与 reference findings。
4. 明确本地模型优先策略。当前系统不要求统一调用某个云端 API；API 只是 fallback 之一，本机可用模型、artifact 和 local VLM 都通过统一 source/warning 字段记录。
5. 增加质量门控。明显模态或部位不匹配的候选报告会保留在 JSON 中，但不进入 Top-N 和 human-vs-AI pairwise 正式比较。
6. 增加样本数据专用链路：manifest 构建、扫描 PDF OCR cache、CR/CT/MRI DICOM 派生资产、子批次合并、运行校验和 CSV/Markdown 分析表。

## 四、工程实现进展

当前 `/data/isbi/gzp/medHarness2` 已形成独立实现，主要包括：

- 标准 Python 包结构、配置加载、JSON I/O、日志与测试框架。
- mock/OpenAI/local VLM 等 LLM/VLM client 入口。
- 本机报告生成模型 registry，兼容旧项目 `configs/reportgen_models.yaml` 和 readiness 文档中的本机模型资源。
- Tool 1-12 的可调用实现。
- Module 1 单报告评估与 Module 2 成对报告评估。
- Workflow 1 单病例 AI 比较、Workflow 2 医生 vs 模型批量比较、Workflow 3 科室医生组 vs AI 模型组统计。
- CLI 覆盖 `single-case`、`sample-data`、`sample-full`、`batch-readers`、`department`、`merge-batches`、`analyze-run`、`validate-run`、`preflight` 等入口。
- FastAPI 薄入口覆盖 single-case、sample-data、batch、department、merge、analysis 和 validate 等流程。
- Makefile 增加 smoke、legacy CXR smoke、MAIRA-2 smoke、最终 52 例检查等工程化命令。

## 五、样本数据与本机模型运行

本周以 `/data/isbi/gzp/medHarness/data/sample_data_2026-06-05` 为真实样本集进行落地验证，最终形成统一输出目录：

```text
outputs/sample_data_2026-06-05_final_local_routed_52_20260606
```

最终合并结果覆盖 52 例样本，报告文本均来自真实 OCR cache，OCR provider 为本机 Qwen3-VL 4B。模型路由如下：

| 模态/部位 | 病例数 | 路线 | 候选模型 |
| --- | ---: | --- | --- |
| `cxr/chest` | 11 | 本地 fresh report-trained | `maira_2`、`chexagent_srrg_findings_full`、`medgemma_srrg_findings` |
| `ct/abdomen` | 7 | 本地 fresh/proxy | `merlin_fresh` |
| `mri/brain` | 7 | 本地 fresh report-trained | `brain_gemma3d` |
| `ct/chest` | 7 | 本地 artifact baseline | `ct_chat`、`dia_llama` |
| `cxr/abdomen` | 9 | 本地 VLM fallback/debug | `qwen3-vl-4b` |
| `ct/head` | 11 | 本地 VLM fallback/debug | `qwen3-vl-4b` |

最终报告来源统计：

- `medharness_cli`: 47 条。
- `artifact_reuse`: 14 条。
- `local_vlm_fallback`: 20 条。

这些来源已经写入结果 JSON 和分析表，后续统计时可以区分正式本地 fresh 模型、历史 artifact baseline 和 local VLM fallback/debug baseline。

## 六、验证结果

最终 52 例目录已完成校验与分析，关键结果如下：

- Manifest 覆盖：52/52。
- 真实 OCR：52/52。
- Workflow 1 JSON：52 个。
- Workflow 2：52 例，失败 0 例。
- Workflow 3：52 例，reader 数 6。
- 生成报告总数：81。
- Top-N ranking：72。
- human-vs-AI pairwise：72。
- 质量门控失败：9。

最近一次工程验证结果：

```text
python -m compileall src tests: passed
PYTHONPATH=src python -m pytest -q: 146 passed, 17 warnings
validate-run --expected-cases 52 --require-real-ocr: passed=true, real_ocr_count=52
experiments run: experiments=6
experiment protocol: experiment_protocol.json/md/csv, protocol_count=6
figures build: figures=11
dashboard build: cases=52 tools=12 experiments=6
```

最终分析表已生成在：

```text
outputs/sample_data_2026-06-05_final_local_routed_52_20260606/analysis
```

主要产物包括：

- `analysis_summary.json`
- `analysis_summary.md`
- `case_routes.csv`
- `model_source_summary.csv`
- `reader_summary.csv`
- `modality_body_part_summary.csv`
- `quality_gate_failures.csv`

Tool 2 升级后已通过 `workflow reevaluate-run` 复用原有 81 条生成报告完成低成本重评估，输出目录为：

```text
outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_tool2_v1
```

该重评估目录不新增报告生成，`new_generation_count=0`；`run_summary.validation` 继承真实 OCR 校验策略，`real_ocr_count=52`。对应实验、图表和控制面板已分别刷新到 `outputs/experiments/..._reeval_tool2_v1/`、`outputs/figures/..._reeval_tool2_v1/` 与 `web/control_panel.html`。实验目录新增 `experiment_protocol.json/md/csv`，将 Notion 六类实验逐项绑定到输入输出、实现方式、模型/API 策略、当前证据、限制和下一步。

## 七、质量门控与问题暴露

本周运行中暴露并记录了 9 条质量门控失败：

- `dia_llama / artifact_reuse`: 7 条，胸部 CT 子集输出中命中腹部相关内容，被判为 body part mismatch。
- `qwen3-vl-4b / local_vlm_fallback`: 2 条，head CT fallback 输出中命中胸部相关内容，被判为 body part mismatch。

这些候选没有被静默丢弃，而是保留在 JSON 和 `quality_gate_failures.csv` 中，便于后续复查。当前处理策略是：保留证据，但不进入 Top-N 和正式 pairwise 比较。

## 八、当前边界与风险

当前系统已经跑通设计稿要求的核心闭环，但仍应按 MVP/工程闭环理解，不应直接等同于最终医学评价器：

1. Tool 2 的 CXR extractor 已从英文规则版增强为中英双语规则版，覆盖 observation、location、measurement、certainty/negation 和 severity 的基础标准化；其他模态仍以 schema-valid placeholder 为主，后续需要接更稳定的结构化 finding extractor。
2. Tool 4 已升级为可配置外部/本地 judge：支持角色级 DMX 路由、严格 JSON schema retry、最小化结构化外发、provenance 和 deterministic fallback。DMX `gpt-5.5` 主 judge 与 `claude-opus-4-6` reviewer 已通过合成 smoke，但尚未完成医生 gold label 和真实病例级临床有效性验证。
3. CR abdomen 与 CT head 暂无本机 report-trained 报告生成模型，本周使用本机 Qwen3-VL 4B 作为 fallback/debug baseline。
4. CT chest 当前使用 artifact baseline，尚未完成本批 fresh inference。
5. BrainGemma3D 已在 MRI brain 子集跑通，但 MRI spacing/orientation、series 选择和 impression 后处理仍有增强空间。
6. 当前 API 仍是薄入口，后续平台化还需要 run id、状态查询、结果索引、任务队列和前端交互。

## 九、下周计划

1. 继续强化结构化 finding extractor：扩大中文/英文医学同义词覆盖，补齐 CT/MRI 等非 CXR 模态，并对真实病例重跑后做一致性审计。
2. 基于医生 gold labels 评估 DMX hazard 主 judge/reviewer 的一致性、校准和 prompt 稳健性；在数据治理确认后再运行病例衍生数据。
3. 继续寻找 CR abdomen、CT head、CT chest 更匹配的本地 report-trained 模型或可复现路线。
4. 对 BrainGemma3D 的 MRI 输入处理做进一步核查，重点包括 spacing、orientation、series 选择和 impression 生成质量。
5. 基于现有分析表继续整理论文/汇报用统计表，区分 fresh 模型、artifact baseline 和 fallback/debug baseline。
6. 推进平台化入口，在现有 FastAPI 基础上增加任务状态、结果索引和批量运行管理能力。

## 十、总结

本周 medHarness2 已在洪学长原始设计基础上完成从设计文稿到可运行系统的关键落地。当前系统已经具备工具层、模块层、工作流层、CLI/API 入口、样本数据入口、本机模型路由、52 例真实 OCR 样本运行、结果合并、校验和分析表生成能力。

总体判断：medHarness2 已经形成可复查、可扩展的 MVP 工程闭环。下一阶段的重点应从“能否跑通”转向“医学评价质量、模型覆盖质量和平台化运行体验”的提升。
