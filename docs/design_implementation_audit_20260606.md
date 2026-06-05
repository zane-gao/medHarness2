# medHarness2 Design-to-Implementation Audit 2026-06-06

## 背景

本文用于审计 `medHarness2` 当前实现与 `designs/` 设计稿之间的对应关系，并给出
52 例样本数据运行证据。

原始设计稿由洪学长提出。本项目当前工作是在该设计基础上做边界收敛、工程实现、
本机模型接入、样本数据适配和运行验证，不将原设计贡献归为本人原创。

设计来源：

- `designs/raw-designs/main.md`
- `designs/raw-designs/tools.md`
- `designs/revised-designs/spec.md`

样本数据：

```text
/data/isbi/gzp/medHarness/data/sample_data_2026-06-05
```

最终统一输出：

```text
outputs/sample_data_2026-06-05_final_local_routed_52_20260606
```

## 结论

当前系统已经完成设计稿要求的核心闭环，并在 52 例样本上形成可验证输出：

- 人工报告 + 图像/体数据输入：已实现。
- 本机模型优先、云端/API 可作为 fallback：已实现。
- 单报告评估：已实现。
- AI 候选报告生成、Top-N、human-vs-AI pairwise：已实现。
- Workflow 2 批量医生 vs 模型：已实现。
- Workflow 3 科室医生组 vs 模型组统计：已实现。
- Tool 1-12：均已有可调用实现。
- 扫描 PDF OCR、DICOM 预处理、真实样本 manifest：已实现。
- CLI/API 薄入口：已实现。
- 52 例真实 OCR + 本地路线输出：已跑通并通过 validation。
- 分析表：已生成 CSV/Markdown，用于汇报和进一步论文统计。

当前仍应明确为 MVP / 工程闭环，而不是最终医学评价器：

- Tool 2 对 CXR 有规则 extractor，其他模态仍以 schema-valid placeholder 为主。
- Tool 4 hazard 仍是 deterministic/规则估计，尚未接入正式医学 evaluator。
- CR abdomen 与 CT head 暂无本机 report-trained 生成模型，使用本机 Qwen3-VL 4B
  作为 `local_vlm_fallback`，不计作正式 report-trained 模型能力。
- CT chest 当前为历史 artifact baseline，不是本批 fresh inference。

## 设计要求映射

| 设计项 | 当前实现 | 证据 | 状态 |
| --- | --- | --- | --- |
| 核心 Python library | `src/medharness2/` 标准包 | `src/medharness2/__init__.py` | 完成 |
| 薄 CLI 入口 | `medharness2 workflow ...` | `src/medharness2/cli.py` | 完成 |
| 薄 API 入口 | FastAPI endpoint | `src/medharness2/api.py` | 完成 |
| 配置加载 | YAML config + dataclass | `src/medharness2/config.py` | 完成 |
| JSON I/O | 统一读写工具 | `src/medharness2/utils/io.py` | 完成 |
| LLM/VLM client | mock/OpenAI/local VLM provider | `src/medharness2/llm_client.py`，`src/medharness2/ocr.py` | 完成 |
| 本地模型 registry | 兼容旧 medHarness readiness/config | `src/medharness2/generators/registry.py` | 完成 |
| 样本 manifest | 读取样本目录和 `readers.xlsx` | `src/medharness2/data/sample_data.py` | 完成 |
| PDF OCR | mock/OpenAI/local VLM；本批为 Qwen3-VL 4B | `src/medharness2/ocr.py` | 完成 |
| DICOM 预处理 | PNG、NIfTI、contact sheet、series 选择 | `src/medharness2/preprocessing/dicom.py` | 完成 |

## Tool 审计

| Tool | 设计功能 | 当前实现 | 状态与边界 |
| --- | --- | --- | --- |
| Tool 1 | Likert 量表 LLM/VLM 评估 | `src/medharness2/tools/tool1_likert.py` | 完成；支持 mock/deterministic fallback |
| Tool 2 | 实体-关系 finding extraction | `src/medharness2/tools/tool2_extract.py` | 完成 MVP；CXR rule + placeholder，真实外部 extractor 后续可替换 |
| Tool 3 | 层级结构检查 | `src/medharness2/tools/tool3_structure.py` | 完成；deterministic section parser |
| Tool 4 | 错误危害评估 | `src/medharness2/tools/tool4_hazard.py` | 完成 MVP；规则 hazard level/explanation |
| Tool 5 | 跨报告图谱对齐 | `src/medharness2/tools/tool5_align.py` | 完成；candidate/reference 语义已修正 |
| Tool 6 | 结构差异 | `src/medharness2/tools/tool6_structure_diff.py` | 完成 |
| Tool 7 | 模态识别 | `src/medharness2/tools/tool7_modality.py` | 完成；manifest modality 优先，DICOM/VLM fallback |
| Tool 8 | 2D/3D 报告生成 | `src/medharness2/tools/tool8_generate.py` | 完成；本地 registry 优先，fallback source 显式标记 |
| Tool 9 | Top-K 报告/模型 | `src/medharness2/tools/tool9_rank.py` | 完成 |
| Tool 10 | 按模型加权指标 | `src/medharness2/tools/tool10_modelwise.py` | 完成 |
| Tool 11 | 按危害加权指标 | `src/medharness2/tools/tool11_hazardwise.py` | 完成 |
| Tool 12 | 统计计算 | `src/medharness2/tools/tool12_statistics.py` | 完成 |

## Module / Workflow 审计

| 设计项 | 当前实现 | 证据 | 状态 |
| --- | --- | --- | --- |
| Module 1 单报告评估 | 编排 Tool 1/2/3 | `src/medharness2/modules/single_report.py` | 完成 |
| Module 2 成对报告评估 | 编排 Tool 2/5/4/6 | `src/medharness2/modules/pairwise_report.py` | 完成 |
| Workflow 1 单病例 | 生成候选、评估、Top-N、pairwise、JSON | `src/medharness2/workflows/single_case.py` | 完成 |
| Workflow 2 批量医生 vs 模型 | 逐病例 Workflow 1 + reader 聚合 | `src/medharness2/workflows/batch_readers.py` | 完成 |
| Workflow 3 科室统计 | reader percentile + model group statistics | `src/medharness2/workflows/department.py` | 完成 |
| 子批次合并 | 将多次本地模型子批次合并为统一 52 例输出 | `src/medharness2/workflows/merge_batches.py` | 完成 |
| 运行分析 | CSV/Markdown 分析表 | `src/medharness2/workflows/analyze_run.py` | 完成 |

## CLI/API 入口

当前 CLI 覆盖：

```text
medharness2 models list
medharness2 workflow single-case
medharness2 workflow sample-data
medharness2 workflow sample-full
medharness2 workflow batch-readers
medharness2 workflow department
medharness2 workflow merge-batches
medharness2 workflow analyze-run
medharness2 workflow validate-run
medharness2 workflow preflight
```

当前 API 覆盖：

```text
POST /workflow/single-case
POST /workflow/sample-data
POST /workflow/sample-full
POST /workflow/batch-readers
POST /workflow/department
POST /workflow/merge-batches
POST /workflow/analyze-run
POST /workflow/validate-run
POST /workflow/preflight
```

## 52 例样本运行证据

最终目录：

```text
outputs/sample_data_2026-06-05_final_local_routed_52_20260606
```

核心文件：

```text
manifest.jsonl
summary.json
workflow2.json
workflow3.json
run_summary.json
workflow2_cases/*.json
analysis/*.csv
analysis/analysis_summary.json
analysis/analysis_summary.md
```

`run_summary.json` 证据：

- `case_count=52`
- `failed_case_count=0`
- `reader_count=6`
- `validation.passed=true`
- `real_ocr_count=52`
- `mock_ocr_count=0`
- `unknown_ocr_count=0`
- `copied_workflow1_outputs=52`
- `missing_workflow1_outputs=0`

`workflow3.json` 证据：

- `case_count=52`
- `reader_count=6`

`analysis/analysis_summary.json` 证据：

- `generated_report_count=81`
- `ranking_count=72`
- `pairwise_count=72`
- `quality_gate_failed_count=9`

分析表行数：

- `case_routes.csv`: 52 条病例数据 + header。
- `model_source_summary.csv`: 8 条模型/来源数据 + header。
- `modality_body_part_summary.csv`: 6 条模态/部位数据 + header。
- `quality_gate_failures.csv`: 9 条失败候选 + header。
- `reader_summary.csv`: 6 条 reader 数据 + header。

## 本机模型路线

| 模态/部位 | 病例数 | 路线 | 候选 |
| --- | ---: | --- | --- |
| `cxr/chest` | 11 | 本地 fresh report-trained | `maira_2`、`chexagent_srrg_findings_full`、`medgemma_srrg_findings` |
| `ct/abdomen` | 7 | 本地 fresh report-trained/proxy | `merlin_fresh` |
| `mri/brain` | 7 | 本地 fresh report-trained | `brain_gemma3d` |
| `ct/chest` | 7 | 本地 artifact baseline | `ct_chat`、`dia_llama` |
| `cxr/abdomen` | 9 | 本地 VLM fallback/debug | `qwen3-vl-4b` |
| `ct/head` | 11 | 本地 VLM fallback/debug | `qwen3-vl-4b` |

来源计数：

- `medharness_cli`: 47。
- `artifact_reuse`: 14。
- `local_vlm_fallback`: 20。

该统计说明当前系统不是“只用 API”。本批报告 OCR 与 fallback 使用本机 Qwen3-VL 4B；
CXR、CT abdomen、MRI brain 使用本机已就位模型路线；CT chest 使用本机 artifact。

## 质量门控与失败边界

质量门控统计：

- passed: 72。
- failed: 9。

失败候选：

- `dia_llama / artifact_reuse`: 7 条，胸部 CT 子集输出命中腹部词汇。
- `qwen3-vl-4b / local_vlm_fallback`: 2 条，head CT 输出胸部词汇。

这些失败候选保留在 JSON 和 `quality_gate_failures.csv` 中，但不进入 Top-N 和
human-vs-AI pairwise。

## 验证命令

```bash
python -m compileall src tests
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m medharness2.cli workflow validate-run \
  --output-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606 \
  --expected-cases 52 \
  --require-real-ocr
PYTHONPATH=src python -m medharness2.cli workflow analyze-run \
  --output-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606 \
  --analysis-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606/analysis
make final-sample-check
```

最近一次验证结果：

- `compileall`: 通过。
- `pytest`: `101 passed, 19 warnings`。
- `validate-run`: `passed=true`，`errors=[]`。
- `analyze-run`: `cases=52`，`generated_reports=81`，`quality_failed=9`。
- `make final-sample-check`: 通过；确认最终分析表 7 个产物均存在。

## 当前未完成或需后续增强

这些不是当前闭环阻塞，但会影响正式医学研究质量：

1. 结构化 finding extractor 需要从 MVP rule/placeholder 升级为更稳定的医学结构化后端。
2. Hazard 评估需要接入更可靠的 evaluator 或本地 LLM，并保留 deterministic fallback。
3. CR abdomen 与 CT head 需要继续寻找本地 report-trained 生成模型，当前 Qwen3-VL 4B
   只作为 fallback/debug baseline。
4. CT chest 建议补 fresh 推理路线；当前 `ct_chat`/`dia_llama` 是 artifact baseline。
5. BrainGemma3D 的 MRI spacing/orientation、series 选择和 impression section 后处理仍需增强。
6. 后续平台化可继续增加 run id、状态查询、结果索引和任务队列。

## 审计结论

就 `designs/` 所描述的系统形态而言，当前 `medHarness2` 已经形成从设计到工程实现、
本机模型接入、52 例样本运行、批量统计和结果分析的完整 MVP 闭环。后续工作主要是
提升医学评价器质量、扩展更多 report-trained 模型覆盖，以及将当前 CLI/API 薄入口
发展为更完整的平台化运行界面。
