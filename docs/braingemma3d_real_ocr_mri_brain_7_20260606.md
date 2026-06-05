# BrainGemma3D Real-OCR MRI Brain 7-Case Batch 2026-06-06

## 背景

本次在 Qwen3-VL 4B 真实 OCR 后的 52 例 manifest 中，抽取全部 7 例
`mri/brain` 病例，运行本机已就位的 `brain_gemma3d` report-trained 脑 MRI
生成模型。

目标是验证真实 OCR 参考报告、DICOM 派生 NIfTI、BrainGemma3D 本地 fresh
生成、Workflow 2/3、Top-N 和 human-vs-AI pairwise 的闭环。

## 关键修正

初始 1 例 smoke 可以完成推理，但模型输出出现 `hip/radiograph` 或 `chest/lung`
语义，质量门控正确将其标记为 off-domain，不进入排名。

排查后修正两点：

- MRI brain 预处理不再简单选择最大 DICOM series，改为优先选择 `FLAIR`，
  无 FLAIR 时选择 `T2`，否则回退最大 series。
- 传给旧 medHarness runner 的 prompt 不再固定为通用句子；会根据派生资产中的
  `selected_series_type` 选择 brain MRI FLAIR、T2 或 generic brain MRI prompt。

新增 metadata 字段：

- `selected_series_description`
- `selected_series_type`
- `series_selection_reason`

## 输入

来源 OCR cache：

```text
outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_52_20260606/ocr
```

子集 manifest：

```text
outputs/braingemma3d_real_ocr_mri_brain_series_prompt_7_20260606/manifest.jsonl
```

病例：

- `MR2605240004`
- `MR2605240005`
- `MR2605250001`
- `MR2605250006`
- `MR2605260006`
- `MR2605270001`
- `MR2605300002`

Series 选择：

- FLAIR: 1 例。
- T2: 4 例。
- 最大 series/FGR fallback: 2 例。

生成派生 NIfTI 时 SimpleITK 对 7 例均提示 non-uniform sampling 或 missing slices。
本次将其记录为数据适配风险；当前 Workflow 仍可继续运行。

## 运行方式

```bash
CUDA_VISIBLE_DEVICES=0 PYTHONPATH=src python - <<'PY'
from medharness2.config import load_config
from medharness2.workflows.batch_readers import run_batch_readers
from medharness2.workflows.department import run_department_comparison

cfg = load_config()
manifest = "outputs/braingemma3d_real_ocr_mri_brain_series_prompt_7_20260606/manifest.jsonl"
workflow2 = "outputs/braingemma3d_real_ocr_mri_brain_series_prompt_7_20260606/workflow2.json"
workflow3 = "outputs/braingemma3d_real_ocr_mri_brain_series_prompt_7_20260606/workflow3.json"
batch = run_batch_readers(
    manifest,
    workflow2,
    model_keys=["brain_gemma3d"],
    model_sources=["medharness_cli"],
    config=cfg,
)
dept = run_department_comparison(workflow2, workflow3)
print(batch["case_count"], batch["failed_case_count"], dept["case_count"], dept["reader_count"])
PY
```

## 结果

```text
workflow2_cases=7
workflow2_failed=0
workflow3_cases=7
readers=3
```

生成候选统计：

- `brain_gemma3d / medharness_cli`: 7。
- `quality_gate_failed`: 0。
- rankings: 每例 1 条。
- pairwise comparisons: 7。

Warnings：

- `missing_impression_section`: 7。

BrainGemma3D 当前主要输出 findings 段，缺少 impression 是格式边界，不代表本次
模态/部位匹配失败。

逐例结果：

| case_id | selected_series_type | selected_series_description | quality_gate | chars |
| --- | --- | --- | --- | --- |
| `MR2605240004` | flair | `T2_FLAIR_8mm(T)1450` | passed | 185 |
| `MR2605240005` | largest | `FGR` | passed | 606 |
| `MR2605250001` | t2 | `T2_FSE_8mm(T)` | passed | 652 |
| `MR2605250006` | t2 | `T2_FSE_8mm(T)` | passed | 548 |
| `MR2605260006` | t2 | `T2_FSE_8mm(T)` | passed | 49 |
| `MR2605270001` | t2 | `T2_FSE_8mm(T)` | passed | 253 |
| `MR2605300002` | largest | `FGR` | passed | 467 |

## 结论

BrainGemma3D 已在 7 例真实 OCR 脑 MRI 子集上完成本地 fresh 推理，并跑通
Workflow 2/3、Top-N 和 pairwise。此前 off-domain 输出主要来自 series 选择和
prompt 适配不充分；修正后 7 例均通过 modality/body-part 质量门控。

后续仍需注意：

- 2 例只能回退到 `FGR` 最大 series，严格医学语义仍需进一步核对。
- 7 例 NIfTI 生成都有 non-uniform sampling 警告，建议后续增加更稳健的 MRI
  series spacing/orientation 处理。
- 输出均缺少 impression section，若要做完整报告质量比较，需要增加 section 补全或
  后处理策略。
