# Merlin Real-OCR CT Abdomen 7-Case Batch 2026-06-06

## 背景

本次在 Qwen3-VL 4B 真实 OCR 后的 52 例 manifest 中，抽取全部 7 例
`ct/abdomen` 病例，运行 `merlin_fresh` 本地 report-trained 腹部 CT 模型。

目标是将此前 2 例 Merlin smoke 扩展到完整 CT abdomen 子集，验证真实 OCR 参考报告、
DICOM 派生 NIfTI、Merlin fresh 本地生成、Workflow 2/3、Top-N 和 pairwise 的闭环。

## 输入

来源 manifest：

```text
outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_52_20260606/manifest.jsonl
```

子集 manifest：

```text
outputs/merlin_real_ocr_ct_abdomen_7_20260606/manifest.jsonl
```

病例：

- `CT2605300024`
- `CT2605300027`
- `CT2605310001`
- `CT2605310003`
- `CT2605310011`
- `CT2605310042`
- `CT2605310043`

所有病例均包含真实 OCR 文本和派生 NIfTI：

```text
derived/<case_id>/volume.nii.gz
```

## 运行方式

```bash
CUDA_VISIBLE_DEVICES=1 PYTHONPATH=src python - <<'PY'
from medharness2.config import load_config
from medharness2.workflows.batch_readers import run_batch_readers
from medharness2.workflows.department import run_department_comparison

cfg = load_config()
manifest = "outputs/merlin_real_ocr_ct_abdomen_7_20260606/manifest.jsonl"
workflow2 = "outputs/merlin_real_ocr_ct_abdomen_7_20260606/workflow2.json"
workflow3 = "outputs/merlin_real_ocr_ct_abdomen_7_20260606/workflow3.json"
batch = run_batch_readers(
    manifest,
    workflow2,
    model_keys=["merlin_fresh"],
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
readers=5
```

生成候选统计：

- `merlin_fresh / medharness_cli`: 7。
- `quality_gate_failed`: 0。
- warnings: `{}`。
- rankings: 每例 1 条。
- pairwise comparisons: 7。

报告长度：

```text
min=100
max=570
mean=179.1
```

逐例结果：

- `CT2605300024`: len=100，quality gate 通过。
- `CT2605300027`: len=100，quality gate 通过。
- `CT2605310001`: len=570，quality gate 通过。
- `CT2605310003`: len=100，quality gate 通过。
- `CT2605310011`: len=184，quality gate 通过。
- `CT2605310042`: len=100，quality gate 通过。
- `CT2605310043`: len=100，quality gate 通过。

## 结论

Merlin fresh 已在完整 7 例 CT abdomen 子集上跑通真实 OCR + NIfTI + Workflow 2/3。
当前输出仍是 organ-system 风格的腹部 CT report proxy，适合工程闭环和候选池验证；
后续若要作为正式模型排名，需要继续补充更细的腹部 CT 结构化抽取与评分规则。
