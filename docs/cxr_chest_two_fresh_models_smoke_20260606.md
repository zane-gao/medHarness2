# CXR Chest Two Fresh Models Smoke

## 背景

本次验证使用样本集 1 例 CXR chest 病例，同时调用两个本机 fresh 报告生成模型：

- `maira_2`
- `chexagent_srrg_findings_full`

目标是验证设计稿中的核心闭环：本机多模型候选生成 -> 单报告评价 -> Top-N 排序 ->
human-vs-AI pairwise 比较。

## 命令

```bash
cd /data/isbi/gzp/medHarness2

CUDA_VISIBLE_DEVICES=5 PYTHONPATH=src python -m medharness2.cli workflow single-case \
  --report outputs/sample_data_2026-06-05_sample_full_artifact_only_20260606/ocr/CR2605290003.txt \
  --image outputs/sample_data_2026-06-05_sample_full_artifact_only_20260606/derived/CR2605290003/images/image_01.png \
  --output outputs/cxr_chest_two_fresh_models_smoke_20260606/result.json \
  --modality cxr \
  --model maira_2 \
  --model chexagent_srrg_findings_full \
  --top-n 2
```

## 结果

- generated_reports：2。
- pairwise comparisons：2。
- 两个候选均为 `medharness_cli` 本机 fresh 路线。

候选：

- `maira_2`：183 字符；warnings 为 `missing_impression_section`、`maira2_generates_findings_only`。
- `chexagent_srrg_findings_full`：228 字符；warnings 为 `missing_impression_section`。

Top-N 排序：

- rank 1：`chexagent_srrg_findings_full`，score `0.6183`。
- rank 2：`maira_2`，score `0.585`。

## 说明

这次 smoke 证明 medHarness2 已能在单例 CXR chest 上同时调用多个本机 fresh 模型，并产出
Top-N 与 pairwise 结果。参考报告仍来自 mock OCR，因此该输出只证明工程闭环，不代表真实评价。
