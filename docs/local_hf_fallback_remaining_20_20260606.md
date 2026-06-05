# Local Qwen3-VL Fallback Remaining 20-Case Batch 2026-06-06

## 背景

根据本机 readiness 文档和 route plan，52 例样本中仍有 20 例缺少匹配的本地
report-trained 生成模型：

- `cxr/abdomen`: 9 例。
- `ct/head`: 11 例。

本次使用本机已就位的 Qwen3-VL 4B 作为 `local_hf_vlm` fallback 跑通这 20 例，
目标是补齐工程闭环和失败边界，而不是把 Qwen3-VL 4B 计入正式 report-trained
模型排名。

## 输入与配置

来源 manifest：

```text
outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_52_20260606/manifest.jsonl
```

子集输出：

```text
outputs/local_hf_fallback_remaining_20_qualityfix_20260606
```

配置：

```text
config/local_hf_qwen3vl4b.yaml
```

核心 provider：

```yaml
llm:
  provider: local_hf_vlm
  model: qwen3-vl-4b
  local_hf_model_path: /data/cyf/shared_data/hd_data/qwen3-vl-4B
```

运行时使用 `CUDA_VISIBLE_DEVICES=1`，配置中的 `local_hf_device` 映射到
`cuda:0`。

## 运行结果

```text
workflow2_cases=20
workflow2_failed=0
workflow3_cases=20
readers=6
```

生成候选统计：

- `qwen3-vl-4b / local_vlm_fallback`: 20。
- `local_vlm_fallback_used`: 20。
- `no_compatible_local_generator`: 20。

质量门控：

- passed: 18。
- failed: 2。
- `quality_gate_failed`: 2。
- `body_part_mismatch`: 2。

失败病例：

| case_id | expected | provider | reason |
| --- | --- | --- | --- |
| `CT2605310028` | `ct/head` | `local_hf_vlm` | 输出包含 `双肺`、`右肺`、`左肺` 等胸部词汇 |
| `CT2605310045` | `ct/head` | `local_hf_vlm` | 输出包含 `双肺`、`右肺`、`左肺` 等胸部词汇 |

质量门控失败的 2 条输出会保留在 JSON 中，并标记
`quality_gate_failed/body_part_mismatch`，但不会进入 Top-N 和 pairwise。

验证：

```bash
PYTHONPATH=src python -m medharness2.cli workflow validate-run \
  --output-dir outputs/local_hf_fallback_remaining_20_qualityfix_20260606 \
  --expected-cases 20 \
  --require-real-ocr
```

结果：`passed=true`，`failed_case_count=0`，`real_ocr_count=20`。该目录是从
子集 manifest 直接运行 Workflow 2/3，因此 validator 返回
`warnings=["missing_summary_json"]`，不影响 workflow 验收。

## 结论

剩余 20 例无本地 report-trained 候选的样本已经通过本机 Qwen3-VL 4B fallback
跑通 Workflow 2/3，系统可以明确区分：

- report-trained 本地模型或 artifact：作为正式候选来源。
- `local_vlm_fallback`：作为无匹配模型时的本地 debug/fallback 来源。
- `cloud_fallback`：只在配置为云端 provider 时使用。

本批结果不应解释为 Qwen3-VL 4B 已成为正式报告生成模型；它的作用是覆盖当前
CR abdomen 和 CT head 的无模型空白，并暴露 fallback 在部位控制上的失败边界。
