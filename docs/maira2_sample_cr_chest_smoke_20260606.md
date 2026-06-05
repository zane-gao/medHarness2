# MAIRA-2 Sample CXR Fresh Smoke

## 背景

本次验证使用本机已就位的 MAIRA-2 权重，对
`/data/isbi/gzp/medHarness/data/sample_data_2026-06-05` 中 1 例胸片样本做 fresh
报告生成 smoke。该验证不调用云端 API，也不复用历史 artifact。

样本：

- case_id：`CR2605290003`
- modality/body_part：`cxr/chest`
- 输入图像：`outputs/sample_data_2026-06-05_sample_full_artifact_only_20260606/derived/CR2605290003/images/image_01.png`
- 参考报告文本：当前仍来自 mock OCR cache，因此只用于流程结构验证，不作为真实评测结论。

## 修复点

首次通过 medHarness2 调用 MAIRA-2 时落到了 fallback。排查后确认有两个工程问题：

- 旧 readiness 文档记录 MAIRA-2 使用 `transformers 4.48.2`，但旧配置中的
  `/data/miniconda3/envs/deepseek/bin/python` 当前已变为 `transformers 5.9.0`。
- medHarness2 写给旧 runner 的图片路径是相对路径，而 MAIRA-2 native runner 在
  `/data/isbi/gzp/medHarness` 下执行，会找不到 medHarness2 的派生 PNG。

已在 medHarness2 侧修复：

- 默认 MAIRA-2 fresh 配置改用 `/data/miniconda3/envs/deepseek_2/bin/python`。
- 调旧 medHarness CLI 时生成运行期 overlay config，只覆盖本次模型的 `python_bin`，不修改旧项目 YAML。
- 写给旧 runner 的 image/volume 路径统一使用绝对路径。
- 若本地生成失败并触发 fallback，fallback metadata 会保留 `local_attempts` 和失败 warning。

## 运行命令

```bash
cd /data/isbi/gzp/medHarness2

CUDA_VISIBLE_DEVICES=5 PYTHONPATH=src python -m medharness2.cli workflow single-case \
  --report outputs/sample_data_2026-06-05_sample_full_artifact_only_20260606/ocr/CR2605290003.txt \
  --image outputs/sample_data_2026-06-05_sample_full_artifact_only_20260606/derived/CR2605290003/images/image_01.png \
  --output outputs/maira2_sample_cr_chest_smoke_20260606_fixed/result.json \
  --modality cxr \
  --model maira_2 \
  --top-n 1
```

## 结果

- 命令状态：成功。
- generated_reports：1。
- pairwise comparisons：1。
- 生成模型：`maira_2`。
- source：`medharness_cli`。
- 输出长度：183 字符。
- warnings：`missing_impression_section`、`maira2_generates_findings_only`。

生成文本预览：

```text
Findings: Frontal and lateral chest radiographs demonstrate a normal cardiomediastinal silhouette and well-aerated lungs which are clear. There is no pleural effusion or pneumothorax.
```

## 结论

medHarness2 已能在样本数据的胸片病例上调用本机 MAIRA-2 进行 fresh inference，并接入
Workflow 1 的评价、Top-N 和 human-vs-AI pairwise 比较闭环。

该结果仍不是正式评测结果，因为参考报告来自 mock OCR。下一步应先配置真实报告 OCR，再扩展到
CXR chest 的 11 例，并继续分别 smoke CheXagent SRRG、MedGemma SRRG、Merlin fresh 和
BrainGemma3D。
