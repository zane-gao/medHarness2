# sample_data_2026-06-05 Sample-Full Mock Run

## 背景

本次验证使用当前 medHarness2 的一键入口 `workflow sample-full`，在
`/data/isbi/gzp/medHarness/data/sample_data_2026-06-05` 上跑完整低成本链路：

```text
sample-data -> batch-readers -> department -> validate-run
```

本次运行使用默认 `mock` LLM provider，因此报告 OCR 为 mock OCR；报告生成使用默认本地
`chexagent` artifact，其他不兼容模态/部位使用 mock cloud fallback。未启动 MAIRA-2、
Merlin、BrainGemma3D 等重型 fresh 推理。

## 命令

```bash
cd /data/isbi/gzp/medHarness2

PYTHONPATH=src python -m medharness2.cli workflow sample-full \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05_sample_full_20260605_mock \
  --expected-cases 52
```

验证命令：

```bash
PYTHONPATH=src python -m medharness2.cli workflow validate-run \
  --output-dir outputs/sample_data_2026-06-05_sample_full_20260605_mock \
  --expected-cases 52

PYTHONPATH=src python -m medharness2.cli workflow validate-run \
  --output-dir outputs/sample_data_2026-06-05_sample_full_20260605_mock \
  --expected-cases 52 \
  --require-real-ocr
```

## 输出

输出目录：

```text
outputs/sample_data_2026-06-05_sample_full_20260605_mock/
```

关键文件：

- `manifest.jsonl`
- `summary.json`
- `workflow2.json`
- `workflow3.json`
- `run_summary.json`

## 结果

- `sample-full`：52 例完成。
- `workflow2`：52 例，失败 0 例。
- `workflow3`：52 例，6 位 reader。
- 普通 `validate-run --expected-cases 52`：通过。
- `validate-run --require-real-ocr`：不通过，原因是 `mock_ocr_used`。

样本分布：

- modality：CT 25、CXR/CR 20、MRI 7。
- body part：abdomen 16、brain 7、chest 18、head 11。
- 52/52 有报告文本缓存。
- 52/52 有 primary image。
- 32/52 有 volume path。

报告生成来源：

- `artifact_reuse` / `chexagent`：11 例。
- `cloud_fallback` / `gpt-5.5` mock provider：41 例。

生成 warning：

- `artifact_reuse_not_fresh_inference=11`
- `cloud_fallback_used=41`
- `no_compatible_local_generator=41`
- OCR warning：`mock_ocr_used=52`

## 说明

这次验证证明当前一键入口可以在 52 例样本上跑通完整结构化流程，并产出可验证的
Workflow 2/3 结果。它不是正式真实评测结果，因为报告 OCR 使用 mock provider，且重型
本地 fresh 生成模型没有启动。

运行过程中 SimpleITK 对部分 CT/MRI series 输出 non-uniform sampling warning；当前系统将其
作为数据几何提示处理，本次运行未导致病例失败。

后续正式评测建议：

1. 配置真实 OCR provider 后重跑 `sample-full --require-real-ocr`。
2. 用 `medharness2 models list --modality ... --body-part ...` 检查本机本地模型候选。
3. 按模态/部位显式加入本地模型，例如 `maira_2`、`chexagent_srrg_findings_full`、
   `medgemma_srrg_findings`、`merlin` / `merlin_fresh`、`brain_gemma3d`。
4. 重跑 `validate-run --require-real-ocr`，通过后再将结果用于正式统计或汇报。
