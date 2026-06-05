# Merlin Fresh and BrainGemma3D Sample Smoke

## 背景

本次继续验证 `/data/isbi/gzp/medHarness/docs/report_generation_model_readiness.md`
中已经就位的 3D 本机报告生成资源，目标是减少对 API fallback 的依赖。

验证对象：

- `merlin_fresh`：腹部 CT。
- `brain_gemma3d`：脑 MRI。

两个 smoke 都使用 `/data/isbi/gzp/medHarness/data/sample_data_2026-06-05` 中已派生出的
NIfTI 体数据。

## Merlin Fresh

样本：

- case_id：`CT2605300024`
- modality/body_part：`ct/abdomen`
- volume：`outputs/sample_data_2026-06-05_sample_full_artifact_only_20260606/derived/CT2605300024/volume.nii.gz`

命令：

```bash
CUDA_VISIBLE_DEVICES=5 PYTHONPATH=src python -m medharness2.cli workflow single-case \
  --report outputs/sample_data_2026-06-05_sample_full_artifact_only_20260606/ocr/CT2605300024.txt \
  --image outputs/sample_data_2026-06-05_sample_full_artifact_only_20260606/derived/CT2605300024/volume.nii.gz \
  --output outputs/merlin_fresh_ct_abdomen_smoke_20260606/result.json \
  --modality ct \
  --model merlin_fresh \
  --top-n 1
```

结果：

- generated_reports：1。
- pairwise comparisons：1。
- model/source：`merlin_fresh / medharness_cli`。
- report_len：100。
- warnings：无。

生成文本预览：

```text
liver: liver and biliary tree: normal. kidneys: kidneys and ureters: normal. spleen: spleen: normal.
```

结论：Merlin fresh 已能在本批样本腹部 CT NIfTI 上完成本机 fresh 推理并进入 Workflow 1。

## BrainGemma3D

样本：

- case_id：`MR2605240004`
- modality/body_part：`mri/brain`
- volume：`outputs/sample_data_2026-06-05_sample_full_artifact_only_20260606/derived/MR2605240004/volume.nii.gz`

命令：

```bash
CUDA_VISIBLE_DEVICES=5 PYTHONPATH=src python -m medharness2.cli workflow single-case \
  --report outputs/sample_data_2026-06-05_sample_full_artifact_only_20260606/ocr/MR2605240004.txt \
  --image outputs/sample_data_2026-06-05_sample_full_artifact_only_20260606/derived/MR2605240004/volume.nii.gz \
  --output outputs/brain_gemma3d_mri_brain_smoke_20260606/result.json \
  --modality mri \
  --model brain_gemma3d \
  --top-n 1
```

结果：

- generated_reports：1。
- pairwise comparisons：1。
- model/source：`brain_gemma3d / medharness_cli`。
- report_len：364。
- warnings：`missing_impression_section`。

生成文本预览：

```text
Findings: The report is: A left hip radiograph shows a large area of increased density at the femoral head, suggesting possible osteonecrosis...
```

结论：BrainGemma3D 的本机接口和 Workflow 1 链路可以跑通，但本例输出明显偏离脑 MRI
语义，出现 hip radiograph 内容。该结果只能作为接口 smoke，不应计入正式质量评测。

## 总结

- 腹部 CT：`merlin_fresh` 可进入下一步小批量验证。
- 脑 MRI：`brain_gemma3d` 接口可用，但需要增加输出质量/部位一致性检查，或继续核对真实
  TextBraTS/BrainGemma3D 输入预处理要求。
- 两个 smoke 仍使用 mock OCR 参考报告，因此都不是正式真实评测。
