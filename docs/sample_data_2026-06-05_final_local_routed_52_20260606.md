# sample_data_2026-06-05 Final Local-Routed 52-Case Run 2026-06-06

## 背景

本次将已经完成并验证过的 5 个真实子批次合并为一个统一的 52 例输出目录。
合并过程不重新启动重模型，不重跑 OCR，也不修改单病例 Workflow 1 结果；它复制各
子批次的 `workflow2_cases/*.json`，重建统一的 Workflow 2/3，并保留每个病例的
`source_batch_result`。

该目录用于回答“52 例样本是否已经按本机资源路线跑完整系统”的验收问题。

输出目录：

```text
outputs/sample_data_2026-06-05_final_local_routed_52_20260606
```

## 输入子批次

来源 manifest：

```text
outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_52_20260606/manifest.jsonl
```

合并的子批次：

- CXR chest 11 例：`outputs/cxr_real_ocr_three_fresh_11_20260606/workflow2.json`
- CT abdomen 7 例：`outputs/merlin_real_ocr_ct_abdomen_7_20260606/workflow2.json`
- MRI brain 7 例：`outputs/braingemma3d_real_ocr_mri_brain_series_prompt_7_20260606/workflow2.json`
- CT chest 7 例：`outputs/ct_chest_real_ocr_artifact_7_20260606/workflow2.json`
- CR abdomen + CT head 20 例：`outputs/local_hf_fallback_remaining_20_qualityfix_20260606/workflow2.json`

覆盖检查：

```text
unique_cases=52
manifest_cases=52
missing_cases=[]
extra_cases=[]
duplicate_cases=[]
```

## 命令

```bash
PYTHONPATH=src python -m medharness2.cli workflow merge-batches \
  --manifest outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_52_20260606/manifest.jsonl \
  --output-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606 \
  --expected-cases 52 \
  --require-real-ocr \
  --batch-result outputs/cxr_real_ocr_three_fresh_11_20260606/workflow2.json \
  --batch-result outputs/merlin_real_ocr_ct_abdomen_7_20260606/workflow2.json \
  --batch-result outputs/braingemma3d_real_ocr_mri_brain_series_prompt_7_20260606/workflow2.json \
  --batch-result outputs/ct_chest_real_ocr_artifact_7_20260606/workflow2.json \
  --batch-result outputs/local_hf_fallback_remaining_20_qualityfix_20260606/workflow2.json
```

结果：

```text
cases=52
failed=0
validation_passed=True
```

## 统一输出

```text
manifest.jsonl
summary.json
workflow2.json
workflow3.json
run_summary.json
workflow2_cases/*.json  # 52 files
```

`validate-run`：

```bash
PYTHONPATH=src python -m medharness2.cli workflow validate-run \
  --output-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606 \
  --expected-cases 52 \
  --require-real-ocr
```

结果：

```text
passed=true
case_count=52
manifest_count=52
real_ocr_count=52
mock_ocr_count=0
unknown_ocr_count=0
failed_case_count=0
errors=[]
warnings=[]
```

## 路由与候选统计

按模态 / 部位：

- `cxr/chest`: `maira_2`、`chexagent_srrg_findings_full`、`medgemma_srrg_findings`，均为 `medharness_cli` fresh，本批各 11 条。
- `ct/abdomen`: `merlin_fresh / medharness_cli`，7 条。
- `mri/brain`: `brain_gemma3d / medharness_cli`，7 条。
- `ct/chest`: `ct_chat`、`dia_llama`，均为 `artifact_reuse`，本批各 7 条。
- `cxr/abdomen`: `qwen3-vl-4b / local_vlm_fallback`，9 条。
- `ct/head`: `qwen3-vl-4b / local_vlm_fallback`，11 条。

生成报告来源计数：

- `medharness_cli`: 47。
- `artifact_reuse`: 14。
- `local_vlm_fallback`: 20。

模型计数：

- `maira_2`: 11。
- `chexagent_srrg_findings_full`: 11。
- `medgemma_srrg_findings`: 11。
- `merlin_fresh`: 7。
- `brain_gemma3d`: 7。
- `ct_chat`: 7。
- `dia_llama`: 7。
- `qwen3-vl-4b`: 20。

Workflow 1 汇总：

- generated reports: 81。
- rankings: 72。
- pairwise comparisons: 72。
- 有排名 / pairwise 的病例：50。

质量门控：

- passed: 72。
- failed: 9。
- `quality_gate_failed`: 9。
- `body_part_mismatch`: 9。

失败来源：

- `dia_llama / artifact_reuse`: 7 条，胸部 CT 子集输出命中腹部词汇，被质量门控拦截。
- `qwen3-vl-4b / local_vlm_fallback`: 2 条，head CT 输出胸部词汇，被质量门控拦截。

被拦截的候选保留在 JSON 中，但不进入 Top-N 和 human-vs-AI pairwise。

## 结论

52 例样本已经形成一个统一可验收的 medHarness2 输出目录：

- 报告文本：52/52 真实 OCR，provider 为本机 Qwen3-VL 4B。
- 图像/体数据：52/52 有 primary image，32/52 有 volume。
- Workflow 1：52 个病例 JSON 均存在。
- Workflow 2：52 例完成，失败 0 例。
- Workflow 3：52 例，6 位 reader。
- `validate-run --require-real-ocr`：通过。

需要明确的是，最终目录包含三类来源，不能混为同一种模型能力：

- 本地 fresh report-trained：CXR chest、CT abdomen、MRI brain。
- 本地 artifact baseline：CT chest。
- 本地 VLM fallback/debug：CR abdomen、CT head。

这一区分已经体现在 `source`、`warnings` 和 `merge_metadata` 中。
