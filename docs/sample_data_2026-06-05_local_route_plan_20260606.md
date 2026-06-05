# sample_data_2026-06-05 Local Route Plan

## 背景

本次记录使用 `sample-full --dry-run --all-compatible-local-models` 对
`/data/isbi/gzp/medHarness/data/sample_data_2026-06-05` 做本地报告生成模型路由预检。

该命令只读取样本目录和 DICOM header，写出 route plan；不执行 OCR、不做 DICOM 像素转换、
不运行 Workflow 1/2/3，也不启动任何本地 fresh 模型。

## 命令

```bash
cd /data/isbi/gzp/medHarness2

PYTHONPATH=src python -m medharness2.cli workflow sample-full \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05_local_route_plan_20260606 \
  --limit 52 \
  --dry-run \
  --all-compatible-local-models
```

输出：

```text
outputs/sample_data_2026-06-05_local_route_plan_20260606/route_plan.json
```

## 总体结果

- 总病例：52。
- 有本地 report-generation 候选：32。
- 需要 fallback：20。

模态 / 部位分布：

- `cxr/abdomen`: 9，需要 fallback。
- `cxr/chest`: 11，有 CXR 本地候选。
- `ct/abdomen`: 7，有 Merlin 候选。
- `ct/chest`: 7，有 CT artifact 候选。
- `ct/head`: 11，需要 fallback。
- `mri/brain`: 7，有 BrainGemma3D 候选。

## 本地候选覆盖

CXR chest 11 例候选：

- `maira_2`
- `chexagent_srrg_findings`
- `chexagent_srrg_findings_full`
- `chexagent_srrg_impression`
- `chexagent_srrg_impression_full`
- `medgemma_srrg_findings`
- `medgemma_srrg_impression`
- `lingshu_srrg_findings`
- `lingshu_srrg_impression`
- `chexagent`
- `llava_rad`
- `r2gengpt`
- `radialog_proxy`
- `radialog_classifier_proxy`

CT abdomen 7 例候选：

- `merlin_fresh`
- `merlin`

CT chest 7 例候选：

- `ct_chat`
- `dia_llama`

MRI brain 7 例候选：

- `brain_gemma3d`

## 需要 fallback 的部分

当前无本地 report-trained 生成候选：

- 腹部 CR / X-ray：9 例。
- 头 CT：11 例。

这些病例后续可走通用 VLM/cloud fallback，或等待新增对应部位的本地 report-generation 模型。

## 下一步建议

1. 先对每类本地候选各选 1 例做 limit smoke，记录耗时、显存、失败原因和输出质量。
2. CXR chest 可优先 smoke `maira_2`、`chexagent_srrg_findings_full`、`medgemma_srrg_findings`。
3. CT abdomen 可优先 smoke `merlin` artifact；`merlin_fresh` 需要确认 RadLLaMA shard 完整和显存。
4. MRI brain 可 smoke `brain_gemma3d`，但需注意 readiness 文档中当前只证明 synthetic NIfTI 接口闭环。
5. 正式批量运行前继续用 `--dry-run --all-compatible-local-models` 固化 route plan，避免误启动不兼容模型。
