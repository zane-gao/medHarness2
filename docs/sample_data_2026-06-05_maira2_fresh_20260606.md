# sample_data_2026-06-05 MAIRA-2 Fresh Batch Run

## 背景

本次运行验证 medHarness2 在 52 例样本数据上，不只依赖 API 或 artifact，而是将本机已就位的
MAIRA-2 fresh report-generation 模型接入完整流程：

```text
sample-data -> batch-readers -> department -> validate-run
```

运行策略：

- CXR chest：显式使用 `maira_2`，source 为 `medharness_cli`。
- 其他模态/部位：由于本次只指定 MAIRA-2，不兼容病例走配置 fallback，并在 JSON 中记录原因。
- OCR：仍为 mock provider，因此本次是工程闭环验证，不是正式真实评测。

## 命令

```bash
cd /data/isbi/gzp/medHarness2

CUDA_VISIBLE_DEVICES=5 PYTHONPATH=src python -m medharness2.cli workflow sample-full \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05_sample_full_maira2_20260606 \
  --expected-cases 52 \
  --model maira_2 \
  --model-source medharness_cli
```

## 输出

输出目录：

```text
outputs/sample_data_2026-06-05_sample_full_maira2_20260606/
```

关键文件：

- `manifest.jsonl`
- `summary.json`
- `workflow2.json`
- `workflow3.json`
- `run_summary.json`
- `workflow2_cases/*.json`

## 结果

- 总病例：52。
- Workflow 2 病例：52。
- Workflow 2 失败病例：0。
- Workflow 3 病例：52。
- reader 数：6。
- validation：通过。
- OCR：`mock_ocr_used=52`，未通过真实 OCR 门槛。

生成来源统计：

- `medharness_cli / maira_2`：11。
- `cloud_fallback / gpt-5.5`：41。

按模态/部位：

- `cxr/chest`：11 例，全部由 MAIRA-2 fresh 生成。
- `cxr/abdomen`：9 例，fallback。
- `ct/abdomen`：7 例，fallback。
- `ct/chest`：7 例，fallback。
- `ct/head`：11 例，fallback。
- `mri/brain`：7 例，fallback。

warning 统计：

- `missing_impression_section=11`
- `maira2_generates_findings_only=11`
- `cloud_fallback_used=41`
- `no_compatible_local_generator=41`
- OCR warning：`mock_ocr_used=52`

## 说明

这次运行证明：本机 MAIRA-2 fresh 推理已进入 medHarness2 的批处理 Workflow 2/3 闭环，
并能在样本集的 11 例胸片 chest 病例上生成非空报告候选。

当前瓶颈是性能：medHarness2 仍按病例逐次调用旧 medHarness CLI，因此 MAIRA-2 会反复加载。
后续如果要批量跑更多 fresh 模型，应增加按模型/模态分组的一次性 batch 调用，减少重复加载。
