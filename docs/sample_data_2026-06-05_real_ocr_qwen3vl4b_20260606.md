# sample_data_2026-06-05 Real OCR + Workflow Smoke

## 背景

本次使用本机已存在的 Qwen3-VL 4B 权重完成真实 OCR，并基于 OCR 后的
52 例 manifest 跑通 Workflow 2/3。该运行仍是工程 smoke，不是最终正式模型评测：
生成侧只启用 `artifact_reuse`，并关闭 cloud/local VLM generation fallback，避免把通用
VLM 与 report-trained 生成模型混在一起做未标记比较。

原始样本目录：

```text
/data/isbi/gzp/medHarness/data/sample_data_2026-06-05
```

输出目录：

```text
outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_52_20260606
```

大输出和 OCR 缓存均位于 `outputs/`，不提交到 git。

## 配置

使用新增配置：

```text
config/local_hf_qwen3vl4b.yaml
```

核心 OCR provider：

```yaml
llm:
  provider: local_hf_vlm
  model: qwen3-vl-4b
  local_hf_model_path: /data/cyf/shared_data/hd_data/qwen3-vl-4B
  local_hf_device: cuda:0
  local_hf_dtype: bf16
```

## Preflight

```bash
PYTHONPATH=src python -m medharness2.cli workflow preflight \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output outputs/sample_data_2026-06-05_preflight_local_hf_qwen3vl4b_cli_20260606/preflight.json \
  --require-real-ocr \
  --all-compatible-local-models \
  --config config/local_hf_qwen3vl4b.yaml
```

结果：

```text
passed=True
cases=52
blockers=-
```

## 52 例真实 OCR

运行方式：调用 `prepare_sample_dataset`，`require_real_ocr=True`，`force_ocr=True`。

结果：

```text
cases=52
with_report_text=52
warnings={}
```

校验：

```bash
PYTHONPATH=src python -m medharness2.cli workflow validate-run \
  --output-dir outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_52_20260606 \
  --expected-cases 52 \
  --require-real-ocr \
  --no-require-workflows
```

结果：

```text
passed=true
real_ocr_count=52
mock_ocr_count=0
unknown_ocr_count=0
```

## Workflow 2/3 Smoke

生成侧策略：

- `model_keys=["*"]`
- `model_sources=["artifact_reuse"]`
- `generator.cloud_fallback_enabled=False`

结果：

```text
workflow2_cases=52
workflow2_failed=0
workflow3_cases=52
readers=6
```

最终校验：

```bash
PYTHONPATH=src python -m medharness2.cli workflow validate-run \
  --output-dir outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_52_20260606 \
  --expected-cases 52 \
  --require-real-ocr
```

结果：

```text
passed=true
real_ocr_count=52
failed_case_count=0
errors=[]
```

## 生成候选统计

Workflow 1 输出汇总：

- `artifact_reuse`: 76。
- `none`: 27。
- `artifact_reuse_not_fresh_inference`: 76。
- `no_generation_backend_available`: 27。
- `quality_gate_failed`: 7。
- `body_part_mismatch`: 7。

模型计数：

- `chexagent`: 11。
- `llava_rad`: 11。
- `r2gengpt`: 11。
- `radialog_classifier_proxy`: 11。
- `radialog_proxy`: 11。
- `merlin`: 7。
- `ct_chat`: 7。
- `dia_llama`: 7。
- `none`: 27。

Top-N 排名长度：

- 11 例有 3 个候选进入排序。
- 41 例有 1 个候选进入排序。

## 当前结论

已完成从扫描 PDF 报告到真实 OCR cache、manifest、Workflow 2、Workflow 3、最终
`validate-run --require-real-ocr` 的 52 例工程闭环。当前仍不是最终正式模型评测，
因为生成侧只使用历史 artifact，且无本地 artifact 的 27 个候选显式记录为
`no_generation_backend_available`。

下一步应在真实 OCR manifest 基础上逐步打开 fresh 本地模型：

1. CXR chest 小批量：`maira_2`、`chexagent_srrg_findings_full`、`medgemma_srrg_findings`。
2. CT abdomen 小批量：`merlin_fresh`。
3. MRI brain：继续核查 `brain_gemma3d` 输入预处理和质量门控。
4. 对无本地 report-trained 模型的 CR abdomen 与 CT head，继续保留 fallback 标记，或单独使用通用 VLM 做 debug baseline。
