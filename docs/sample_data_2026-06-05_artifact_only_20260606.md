# sample_data_2026-06-05 Artifact-Only Run

## 背景

本次记录响应“不要只依赖 API，应优先使用本机已就位模型资源”的要求，使用
`--all-compatible-local-models --model-source artifact_reuse` 在
`/data/isbi/gzp/medHarness/data/sample_data_2026-06-05` 上跑完整结构化流程。

该模式只复用 `/data/isbi/gzp/medHarness/docs/report_generation_model_readiness.md`
中已登记的历史生成 artifact，不启动 MAIRA-2、CheXagent SRRG、MedGemma SRRG、
Merlin fresh、BrainGemma3D 等 GPU-heavy fresh 推理。无 artifact 覆盖的病例继续走
配置的 fallback，并在 JSON 中记录原因。

## 路由预检命令

```bash
cd /data/isbi/gzp/medHarness2

PYTHONPATH=src python -m medharness2.cli workflow sample-full \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05_artifact_route_plan_20260606 \
  --limit 52 \
  --dry-run \
  --all-compatible-local-models \
  --model-source artifact_reuse
```

预检结果：

- 总病例：52。
- 有 artifact 候选：25。
- 需要 fallback：27。

## 完整运行命令

```bash
PYTHONPATH=src python -m medharness2.cli workflow sample-full \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05_sample_full_artifact_only_20260606 \
  --expected-cases 52 \
  --all-compatible-local-models \
  --model-source artifact_reuse
```

验证命令：

```bash
PYTHONPATH=src python -m medharness2.cli workflow validate-run \
  --output-dir outputs/sample_data_2026-06-05_sample_full_artifact_only_20260606 \
  --expected-cases 52
```

## 输出与结果

输出目录：

```text
outputs/sample_data_2026-06-05_sample_full_artifact_only_20260606/
```

关键结果：

- `sample-full`：52 例完成。
- `workflow2`：52 例，失败 0 例。
- `workflow3`：52 例，6 位 reader。
- 普通 `validate-run --expected-cases 52`：通过。

生成来源统计：

- `artifact_reuse=76`
- `cloud_fallback=27`

模型计数：

- `chexagent=11`
- `llava_rad=11`
- `r2gengpt=11`
- `radialog_classifier_proxy=11`
- `radialog_proxy=11`
- `merlin=7`
- `ct_chat=7`
- `dia_llama=7`
- `gpt-5.5=27`

warning 统计：

- `artifact_reuse_not_fresh_inference=76`
- `cloud_fallback_used=27`
- `no_compatible_local_generator=27`
- OCR warning：`mock_ocr_used=52`

## 解释

这次运行证明 medHarness2 已经可以优先使用本机 readiness 文档中登记的本地报告生成资源，
并按模型来源筛选候选池。`artifact_reuse` 模式适合低成本批量结构化验证和流程压测；
后续正式模型质量评测仍应选择 `medharness_cli` fresh 路线或显式 `--model` 路线，并配置真实 OCR。

本次结果不等同于真实临床评测，原因有两个：

- 报告 PDF OCR 仍使用 mock provider，`validate-run --require-real-ocr` 会拒绝该结果。
- 生成报告主要来自历史 artifact，不是针对本批样本现场 fresh inference。

## 下一步

1. 配置真实 VLM OCR 后重跑 `sample-full --require-real-ocr`。
2. 对 CXR chest 各选 1 例 fresh smoke：`maira_2`、`chexagent_srrg_findings_full`、
   `medgemma_srrg_findings`。
3. 对 CT abdomen 复核 `merlin_fresh` 的 RadLLaMA shard 完整性，再决定是否 fresh smoke。
4. 对 MRI brain 用本批数据派生 NIfTI 后 smoke `brain_gemma3d`，并记录真实样本限制。
