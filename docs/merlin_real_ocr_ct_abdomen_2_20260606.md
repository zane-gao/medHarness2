# Merlin Real-OCR CT Abdomen Batch Smoke 2026-06-06

## 背景

本次在 Qwen3-VL 4B 真实 OCR 后的 52 例 manifest 中，抽取 2 例
`ct/abdomen` 病例，运行 `merlin_fresh` 本地 report-trained 腹部 CT 模型。

目标是验证真实 OCR 参考报告 + DICOM 派生 NIfTI 体数据 + Merlin fresh 本地生成 +
Workflow 2/3 的小批量闭环。

## 输入

来源 manifest：

```text
outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_52_20260606/manifest.jsonl
```

子集 manifest：

```text
outputs/merlin_real_ocr_ct_abdomen_2_20260606/manifest.jsonl
```

病例：

- `CT2605300024`
- `CT2605300027`

两例均包含派生 NIfTI：

```text
derived/<case_id>/volume.nii.gz
```

## 资源检查

```bash
python /data/isbi/gzp/medHarness/scripts/run_report_generation.py \
  --model-key merlin_fresh \
  --dry-run
```

结果：

```text
status=ready
missing_paths=[]
```

## 运行方式

```bash
CUDA_VISIBLE_DEVICES=2 PYTHONPATH=src python - <<'PY'
from medharness2.config import load_config
from medharness2.workflows.batch_readers import run_batch_readers
from medharness2.workflows.department import run_department_comparison

cfg = load_config()
manifest = "outputs/merlin_real_ocr_ct_abdomen_2_20260606/manifest.jsonl"
workflow2 = "outputs/merlin_real_ocr_ct_abdomen_2_20260606/workflow2.json"
workflow3 = "outputs/merlin_real_ocr_ct_abdomen_2_20260606/workflow3.json"
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
workflow2_cases=2
workflow2_failed=0
workflow3_cases=2
readers=2
```

逐例结果：

- `CT2605300024`: `merlin_fresh / medharness_cli`，报告长度 100，rankings=1，pairwise=1，quality gate 通过。
- `CT2605300027`: `merlin_fresh / medharness_cli`，报告长度 100，rankings=1，pairwise=1，quality gate 通过。

输出示例：

```text
liver: liver and biliary tree: normal. kidneys: kidneys and ureters: normal. spleen: spleen: normal.
```

## 结论

Merlin fresh 已在真实 OCR 参考报告和本地派生 CT NIfTI 上完成 2 例
`ct/abdomen` batch smoke。当前输出是 organ-system 风格的腹部 CT report proxy，
可用于工程闭环和候选池验证；后续应扩展到全部 7 例 CT abdomen，并继续记录
耗时、失败率和输出质量。
