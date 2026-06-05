# MAIRA-2 Real-OCR CXR Chest Batch Smoke 2026-06-06

## 背景

本次在 52 例 Qwen3-VL 4B 真实 OCR manifest 的基础上，抽取 2 例 `cxr/chest`
病例，验证真实人工报告文本 + MAIRA-2 fresh 本地生成 + Workflow 2/3 的闭环。

该运行不同于此前 mock OCR smoke：参考报告来自真实 OCR cache，`validate-run`
已确认 OCR provenance 为真实 provider。

## 输入

来源 manifest：

```text
outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_52_20260606/manifest.jsonl
```

子集 manifest：

```text
outputs/maira2_real_ocr_cxr_chest_2_20260606/manifest.jsonl
```

病例：

- `CR2605290003`
- `CR2605290004`

## 运行方式

```bash
CUDA_VISIBLE_DEVICES=0 PYTHONPATH=src python - <<'PY'
from medharness2.config import load_config
from medharness2.workflows.batch_readers import run_batch_readers
from medharness2.workflows.department import run_department_comparison

cfg = load_config()
manifest = "outputs/maira2_real_ocr_cxr_chest_2_20260606/manifest.jsonl"
workflow2 = "outputs/maira2_real_ocr_cxr_chest_2_20260606/workflow2.json"
workflow3 = "outputs/maira2_real_ocr_cxr_chest_2_20260606/workflow3.json"
batch = run_batch_readers(
    manifest,
    workflow2,
    model_keys=["maira_2"],
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

- `CR2605290003`: `maira_2 / medharness_cli`，报告长度 183，rankings=1，pairwise=1。
- `CR2605290004`: `maira_2 / medharness_cli`，报告长度 183，rankings=1，pairwise=1。

两个候选均带有预期 warning：

- `maira2_generates_findings_only`
- `missing_impression_section`

## 结论

MAIRA-2 已在真实 OCR 参考报告上完成 2 例 CXR chest batch smoke。该结果证明
medHarness2 当前可以把“扫描 PDF 真实 OCR -> 本地 fresh 报告生成 -> Workflow 2/3”
串起来。下一步可以扩展到 11 例 CXR chest，并加入 `chexagent_srrg_findings_full`
和 `medgemma_srrg_findings` 形成多 fresh 候选池。
