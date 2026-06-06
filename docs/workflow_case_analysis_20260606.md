# medHarness2 工作流案例分析与结果展示

生成日期：2026-06-06

## 一、文档目的

本文用已经跑通的 52 例样本输出，对 medHarness2 的主要工作流做一次端到端案例展示。重点说明每个工作流的输入、处理步骤、输出 JSON、统计结果和当前限制。

案例来源：

```text
outputs/sample_data_2026-06-05_final_local_routed_52_20260606
```

样本来源：

```text
/data/isbi/gzp/medHarness/data/sample_data_2026-06-05
```

说明：

- 本文只展示 case id、模型来源、指标、警告和结果结构，不粘贴完整报告正文。
- 当前结果用于工程闭环和流程验证，不应直接解释为最终医学评价结论。
- 原始设计稿由洪学长提出，本文展示的是在该设计基础上完成的工程实现与样本运行结果。

## 二、总流程概览

最终 52 例完整链路如下：

```text
样本目录 + readers.xlsx
  -> sample-data: manifest + OCR + DICOM 派生资产
  -> Workflow 1: 单病例 human report vs AI reports
  -> Workflow 2: 52 例医生 vs 模型批量聚合
  -> Workflow 3: 科室医生组 vs AI 模型组统计
  -> validate-run / analyze-run: 校验与分析表
```

最终输出目录包含：

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

最终校验结果：

| 项目 | 结果 |
| --- | ---: |
| manifest 病例数 | 52 |
| 真实 OCR 病例数 | 52 |
| Workflow 1 JSON | 52 |
| Workflow 2 failed cases | 0 |
| Workflow 3 reader 数 | 6 |
| generated reports | 81 |
| rankings | 72 |
| pairwise comparisons | 72 |
| quality gate failed | 9 |

## 三、前置流程：样本准备

样本准备阶段把原始样本目录变成 Workflow 可消费的统一 manifest。

输入：

```text
/data/isbi/gzp/medHarness/data/sample_data_2026-06-05
```

关键处理：

1. 读取 `readers.xlsx`，获得 case id、reader、modality、body_part 等基础信息。
2. 扫描每例报告 PDF。
3. 使用本机 Qwen3-VL 4B 做扫描 PDF OCR，并将报告文本缓存到 `ocr/*.txt`。
4. 对影像做 DICOM 派生资产：
   - CR/CXR：转为 PNG，选择 primary image。
   - CT/MRI：按 series 生成 NIfTI/contact sheet，并选择 volume path。
5. 写出 `manifest.jsonl`、`summary.json` 和派生资产路径。

样本准备结果：

| 项目 | 结果 |
| --- | ---: |
| case_count | 52 |
| modality counts | `ct=25`、`cxr=20`、`mri=7` |
| body part counts | `abdomen=16`、`brain=7`、`chest=18`、`head=11` |
| cases_with_report_text | 52 |
| cases_with_primary_image | 52 |
| cases_with_volume | 32 |

本阶段的验收点是：每例都能在 manifest 中找到报告文本、主图像或体数据入口，并且 OCR provenance 可以通过 `validate-run --require-real-ocr` 检查。

## 四、Workflow 1：单病例 AI 报告比较

Workflow 1 的目标是对单个病例完成完整闭环：

```text
人工报告 + 图像/体数据
  -> 评估人工报告
  -> 生成 AI 候选报告
  -> 评估候选报告
  -> Top-N 排序
  -> human-vs-AI pairwise
  -> 单病例 JSON
```

### 案例 1：CXR chest 多模型 fresh 推理

选用病例：

```text
case_id: CR2605290003
reader: 楚辰辰
modality: cxr
body_part: chest
workflow1_output: outputs/sample_data_2026-06-05_final_local_routed_52_20260606/workflow2_cases/CR2605290003.json
```

输入资产：

| 字段 | 值 |
| --- | --- |
| report text | `outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_52_20260606/ocr/CR2605290003.txt` |
| primary image | `outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_52_20260606/derived/CR2605290003/images/image_01.png` |
| volume path | 无 |
| derived assets | `png_images`、`primary_image` |

步骤 1：人工报告评估。

Workflow 1 首先对 OCR 得到的人工报告运行单报告评估，调用 Tool 1/2/3：

| 指标 | 结果 |
| --- | ---: |
| `likert_mean` | 4.0 |
| `structure_score` | 0.55 |
| `finding_coverage` | 0.1111 |
| finding count | 1 |
| structure warning | `missing_impression_section` |

这里的 `missing_impression_section` 是当前结构解析器对 OCR 文本分节的结果，不代表报告一定没有诊断印象；它提示后续需要增强中文报告 section parser。

步骤 2：AI 候选报告生成。

该病例为 `cxr/chest`，路由到 3 个本地 fresh report-trained 入口：

| index | model | source | 主要 warning | quality gate |
| ---: | --- | --- | --- | --- |
| 0 | `maira_2` | `medharness_cli` | `missing_impression_section`; `maira2_generates_findings_only` | passed |
| 1 | `chexagent_srrg_findings_full` | `medharness_cli` | `missing_impression_section` | passed |
| 2 | `medgemma_srrg_findings` | `medharness_cli` | `missing_impression_section` | passed |

步骤 3：候选报告评估。

三个候选都进入 Tool 1/2/3 评估，并通过 modality/body_part 质量门控：

| model | `likert_mean` | `structure_score` | `finding_coverage` | quality gate |
| --- | ---: | ---: | ---: | --- |
| `maira_2` | 4.0 | 0.55 | 0.3333 | passed |
| `chexagent_srrg_findings_full` | 4.0 | 0.55 | 0.4444 | passed |
| `medgemma_srrg_findings` | 4.0 | 0.55 | 0.4444 | passed |

步骤 4：Top-N 排序。

排序使用归一化后的指标，其中 `likert_mean=4.0` 在 ranking 中计为 `0.8`。

| rank | model | score | ranking metrics |
| ---: | --- | ---: | --- |
| 1 | `chexagent_srrg_findings_full` | 0.6183 | `likert_mean=0.8`、`structure_score=0.55`、`finding_coverage=0.4444` |
| 2 | `medgemma_srrg_findings` | 0.6183 | `likert_mean=0.8`、`structure_score=0.55`、`finding_coverage=0.4444` |
| 3 | `maira_2` | 0.5850 | `likert_mean=0.8`、`structure_score=0.55`、`finding_coverage=0.3333` |

步骤 5：human-vs-AI pairwise。

每个 Top-N 候选都会与人工报告成对比较，调用 Tool 2/5/4/6：

| rank | model | alignment | hazard errors | structure diff | warnings |
| ---: | --- | --- | ---: | --- | --- |
| 1 | `chexagent_srrg_findings_full` | precision/recall/F1 均为 0.0 | 5 | findings 分节差异 0.0 | `image_path_unused_in_mvp_pairwise` |
| 2 | `medgemma_srrg_findings` | precision/recall/F1 均为 0.0 | 5 | findings 分节差异 0.0 | `image_path_unused_in_mvp_pairwise` |
| 3 | `maira_2` | precision/recall/F1 均为 0.0 | 4 | findings 分节差异 0.0 | `image_path_unused_in_mvp_pairwise` |

pairwise 中的错误类型包括：

- `false_finding`：候选报告有、参考报告未对齐到的 finding。
- `omission_finding`：参考报告有、候选报告未对齐到的 finding。

该病例中 alignment 为 0.0 的主要原因是当前 Tool 2 对中文 OCR 报告和英文候选报告的结构化抽取仍是 MVP 规则/placeholder 级别。这个结果展示了工作流能完整产出 pairwise JSON，也暴露了后续需要升级 finding extractor 的位置。

### 案例 2：质量门控拦截异常候选

选用病例：

```text
case_id: CT2605300030
reader: 康丽坤
modality: ct
body_part: chest
workflow1_output: outputs/sample_data_2026-06-05_final_local_routed_52_20260606/workflow2_cases/CT2605300030.json
```

该病例为胸部 CT，当前使用 artifact baseline：

| model | source | quality gate | warning |
| --- | --- | --- | --- |
| `ct_chat` | `artifact_reuse` | passed | `artifact_reuse_not_fresh_inference` |
| `dia_llama` | `artifact_reuse` | failed | `artifact_reuse_not_fresh_inference`; `quality_gate_failed`; `body_part_mismatch` |

`dia_llama` 的质量门控冲突为：

```text
expected_modality: ct
expected_body_part: chest
conflicts: body_part = ["spleen"]
```

处理结果：

- `dia_llama` 候选仍保留在 `generated_reports` 和 `generated_evaluations` 中。
- 该候选被标记为 `quality_gate_failed`。
- Top-N 排名只保留通过门控的 `ct_chat`。
- pairwise comparison 数量为 1，只比较 `ct_chat` 与人工报告。

这说明系统对 off-domain 或部位不匹配输出的处理不是静默丢弃，而是保留证据、阻断其进入正式排名和 pairwise。

## 五、Workflow 2：医生 vs 模型批量评估

Workflow 2 的目标是把多个病例逐例跑 Workflow 1，并按 reader 聚合：

```text
manifest.jsonl
  -> 每例 run_single_case
  -> workflow2_cases/{case_id}.json
  -> per_reader 汇总
  -> workflow2.json
```

本次输入：

```text
outputs/sample_data_2026-06-05_final_local_routed_52_20260606/manifest.jsonl
```

本次输出：

```text
outputs/sample_data_2026-06-05_final_local_routed_52_20260606/workflow2.json
outputs/sample_data_2026-06-05_final_local_routed_52_20260606/workflow2_cases/*.json
```

Workflow 2 总结果：

| 项目 | 结果 |
| --- | ---: |
| case_count | 52 |
| failed_case_count | 0 |
| reader_count | 6 |
| human `likert_mean` mean | 2.7308 |
| human `structure_score` mean | 0.55 |
| human `finding_coverage` mean | 0.1111 |

按模态/部位的结果：

| modality | body_part | case_count | generated_report_count | ranking_count | pairwise_count | quality_passed | quality_failed | models |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `ct` | `abdomen` | 7 | 7 | 7 | 7 | 7 | 0 | `merlin_fresh` |
| `ct` | `chest` | 7 | 14 | 7 | 7 | 7 | 7 | `ct_chat`; `dia_llama` |
| `ct` | `head` | 11 | 11 | 9 | 9 | 9 | 2 | `qwen3-vl-4b` |
| `cxr` | `abdomen` | 9 | 9 | 9 | 9 | 9 | 0 | `qwen3-vl-4b` |
| `cxr` | `chest` | 11 | 33 | 33 | 33 | 33 | 0 | `maira_2`; `chexagent_srrg_findings_full`; `medgemma_srrg_findings` |
| `mri` | `brain` | 7 | 7 | 7 | 7 | 7 | 0 | `brain_gemma3d` |

按模型来源的结果：

| model | source | report_count | quality_passed | quality_failed | selected_top_n_count |
| --- | --- | ---: | ---: | ---: | ---: |
| `ct_chat` | `artifact_reuse` | 7 | 7 | 0 | 7 |
| `dia_llama` | `artifact_reuse` | 7 | 0 | 7 | 0 |
| `qwen3-vl-4b` | `local_vlm_fallback` | 20 | 18 | 2 | 18 |
| `brain_gemma3d` | `medharness_cli` | 7 | 7 | 0 | 7 |
| `chexagent_srrg_findings_full` | `medharness_cli` | 11 | 11 | 0 | 11 |
| `maira_2` | `medharness_cli` | 11 | 11 | 0 | 11 |
| `medgemma_srrg_findings` | `medharness_cli` | 11 | 11 | 0 | 11 |
| `merlin_fresh` | `medharness_cli` | 7 | 7 | 0 | 7 |

Workflow 2 的核心价值是把 52 个单病例 JSON 组织成批量结果，并保留每例 `workflow1_output` 路径。后续如果某个模型或病例出现异常，可以从 `workflow2.json` 追溯回具体病例 JSON。

## 六、Workflow 3：科室医生组 vs AI 模型组统计

Workflow 3 的目标是从 Workflow 2 结果中做 reader 级和 model group 级统计：

```text
workflow2.json
  -> reader overall_score
  -> reader percentile
  -> model_group statistics
  -> workflow3.json
```

输入：

```text
outputs/sample_data_2026-06-05_final_local_routed_52_20260606/workflow2.json
```

输出：

```text
outputs/sample_data_2026-06-05_final_local_routed_52_20260606/workflow3.json
```

Reader 百分位结果：

| reader | case_count | overall_score | percentile |
| --- | ---: | ---: | ---: |
| 廖强 | 1 | 0.553700 | 100.000000 |
| 楚辰辰 | 24 | 0.512033 | 83.333333 |
| 李华文 | 5 | 0.500367 | 66.666667 |
| 康丽坤 | 16 | 0.499533 | 50.000000 |
| 母志斯宇 | 2 | 0.487033 | 33.333333 |
| 罗虹 | 4 | 0.487033 | 33.333333 |

Reader 组统计：

| 指标 | 值 |
| --- | ---: |
| reader 数 | 6 |
| overall_score mean | 0.5066165 |
| overall_score std | 0.0249097 |
| min | 0.487033 |
| max | 0.553700 |

Model group 统计：

| 指标 | mean | min | max |
| --- | ---: | ---: | ---: |
| `likert_mean` | 2.7308 | 1.0 | 4.0 |
| `structure_score` | 0.55 | 0.55 | 0.55 |
| `finding_coverage` | 0.2083 | 0.1111 | 0.5556 |
| `model_count` | 1.5577 | 1.0 | 3.0 |

解释：

- Workflow 3 给出了 reader 组内百分位和 model group 汇总。
- 当前 reader 的 case_count 不均衡，例如有的 reader 只有 1 例，因此百分位只能作为流程展示和粗略统计，不适合作为正式医生能力排名。
- `model_group.case_metric_count=52`，表示每例都有可用于模型组统计的 case-level 指标。

## 七、分析表与结果展示

最终分析表位于：

```text
outputs/sample_data_2026-06-05_final_local_routed_52_20260606/analysis
```

各文件用途：

| 文件 | 用途 |
| --- | --- |
| `analysis_summary.json` | 汇总病例数、生成报告数、ranking/pairwise 数、质量门控统计 |
| `analysis_summary.md` | 可直接阅读的 Markdown 汇总 |
| `case_routes.csv` | 每例病例的模态、部位、模型路由和来源 |
| `model_source_summary.csv` | 按模型和 source 汇总报告数、门控通过数、Top-N 入选数 |
| `reader_summary.csv` | reader case_count、overall_score、percentile |
| `modality_body_part_summary.csv` | 按模态/部位统计生成、排名、pairwise 和质量门控 |
| `quality_gate_failures.csv` | 所有质量门控失败候选及冲突原因 |

最终质量门控失败共 9 条：

| 来源 | 数量 | 原因 |
| --- | ---: | --- |
| `dia_llama / artifact_reuse` | 7 | 胸部 CT artifact 输出命中 `spleen`，判为 body part mismatch |
| `qwen3-vl-4b / local_vlm_fallback` | 2 | head CT fallback 输出命中胸部相关词，判为 body part mismatch |

## 八、完整复查命令

不重新运行重模型时，可以用以下命令复查最终目录：

```bash
cd /data/isbi/gzp/medHarness2

PYTHONPATH=src python -m medharness2.cli workflow validate-run \
  --output-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606 \
  --expected-cases 52 \
  --require-real-ocr

PYTHONPATH=src python -m medharness2.cli workflow analyze-run \
  --output-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606 \
  --analysis-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606/analysis

make final-sample-check
```

若要追溯本文中的 Workflow 1 案例：

```bash
python -m json.tool \
  outputs/sample_data_2026-06-05_final_local_routed_52_20260606/workflow2_cases/CR2605290003.json

python -m json.tool \
  outputs/sample_data_2026-06-05_final_local_routed_52_20260606/workflow2_cases/CT2605300030.json
```

## 九、结论

通过 `CR2605290003` 可以看到 Workflow 1 已经完成从人工报告、图像、三路本地 fresh 模型生成、候选评估、Top-N 排序到 pairwise 比较的完整单病例闭环。

通过 `CT2605300030` 可以看到质量门控能识别部位不匹配候选，并将其保留在 JSON 中但排除出正式排名和 pairwise。

通过 52 例 Workflow 2/3 可以看到系统已经具备批量运行、reader 聚合、model group 汇总、质量门控统计和分析表输出能力。当前剩余重点不是“流程能否跑通”，而是进一步提升 finding extraction、hazard evaluator、中文报告结构解析、本地 report-trained 模型覆盖和平台化运行体验。
