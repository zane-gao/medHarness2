# CXR Real-OCR Three Fresh Models Batch 2026-06-06

## 背景

本次在 Qwen3-VL 4B 真实 OCR 后的 52 例 manifest 中，抽取全部 11 例
`cxr/chest` 病例，运行 3 个本地 fresh report-trained CXR 模型：

- `maira_2`
- `chexagent_srrg_findings_full`
- `medgemma_srrg_findings`

目标是验证真实 OCR 参考报告 + 多 fresh 本地生成模型 + Workflow 2/3 + Top-N +
human-vs-AI pairwise 的小批量闭环。

## 输入

来源 manifest：

```text
outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_52_20260606/manifest.jsonl
```

子集 manifest：

```text
outputs/cxr_real_ocr_three_fresh_11_20260606/manifest.jsonl
```

病例数：11。

## 命令

```bash
CUDA_VISIBLE_DEVICES=2 PYTHONPATH=src python - <<'PY'
from medharness2.config import load_config
from medharness2.workflows.batch_readers import run_batch_readers
from medharness2.workflows.department import run_department_comparison

cfg = load_config()
manifest = "outputs/cxr_real_ocr_three_fresh_11_20260606/manifest.jsonl"
workflow2 = "outputs/cxr_real_ocr_three_fresh_11_20260606/workflow2.json"
workflow3 = "outputs/cxr_real_ocr_three_fresh_11_20260606/workflow3.json"
models = ["maira_2", "chexagent_srrg_findings_full", "medgemma_srrg_findings"]
batch = run_batch_readers(
    manifest,
    workflow2,
    model_keys=models,
    model_sources=["medharness_cli"],
    config=cfg,
)
dept = run_department_comparison(workflow2, workflow3)
print(batch["case_count"], batch["failed_case_count"], dept["case_count"], dept["reader_count"])
PY
```

## 结果

```text
workflow2_cases=11
workflow2_failed=0
workflow3_cases=11
readers=2
```

生成候选统计：

- `medharness_cli`: 33。
- `maira_2`: 11。
- `chexagent_srrg_findings_full`: 11。
- `medgemma_srrg_findings`: 11。

质量门控：

- `quality_gate_failed`: 0。
- 所有 33 个候选均保留进入排序候选池。

预期 warning：

- `missing_impression_section`: 33。
- `maira2_generates_findings_only`: 11。

这些模型当前都只生成 findings 段，因此缺少 impression 是已知边界，不代表本次工程运行失败。

Top-1 分布：

- `chexagent_srrg_findings_full`: 6。
- `maira_2`: 4。
- `medgemma_srrg_findings`: 1。

Pairwise：

- 总 pairwise comparisons：33。

生成长度：

- `maira_2`: min 183，max 350，mean 236.4。
- `chexagent_srrg_findings_full`: min 228，max 325，mean 245.6。
- `medgemma_srrg_findings`: min 204，max 385，mean 282.9。

## 结论

真实 OCR 参考报告 + 3 个 CXR fresh 本地模型 + Workflow 2/3 已在 11 例
CXR chest 上跑通。该结果比此前 2 例 smoke 更接近正式 CXR 子集评测，
但仍需注意：

- 当前评分工具仍是 MVP deterministic / rule-based 版本。
- 三个候选均为 findings-only 或主要 findings 输出，后续若要完整报告比较，应增加 impression 模型或合并 findings/impression 双模型输出。
- 该结果只覆盖 CXR chest，不覆盖 CR abdomen、CT head 等无本地 report-trained 生成模型的病例。
