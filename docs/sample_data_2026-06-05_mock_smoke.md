# sample_data_2026-06-05 Mock Smoke

## 背景

本次验证用于确认 medHarness2 全量设计入口能吃下
`/data/isbi/gzp/medHarness/data/sample_data_2026-06-05` 的真实目录结构、
扫描 PDF 报告、DICOM 影像和 `readers.xlsx`。运行使用默认 `mock` LLM provider，
因此不调用真实云端 VLM OCR，也不加载 GPU fresh 模型。

## 命令

```bash
cd /data/isbi/gzp/medHarness2

PYTHONPATH=src python -m medharness2.cli workflow sample-data \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05_full_mock

PYTHONPATH=src python -m medharness2.cli workflow batch-readers \
  --manifest outputs/sample_data_2026-06-05_full_mock/manifest.jsonl \
  --output outputs/sample_data_2026-06-05_full_mock/workflow2.json

PYTHONPATH=src python -m medharness2.cli workflow department \
  --batch-result outputs/sample_data_2026-06-05_full_mock/workflow2.json \
  --output outputs/sample_data_2026-06-05_full_mock/workflow3.json

PYTHONPATH=src python -m medharness2.cli workflow validate-run \
  --output-dir outputs/sample_data_2026-06-05_full_mock \
  --expected-cases 52
```

## 结果

- `sample-data`：52 例全部写入 manifest。
- modality 分布：CT 25、CXR/CR 20、MRI 7。
- body part 分布：abdomen 16、brain 7、chest 18、head 11。
- 52/52 有 `report_text` 缓存。
- 52/52 有 `primary_image`。
- 32/52 有 `volume_path`。
- `workflow2`：52 例，6 位 reader，`failed_case_count=0`。
- `workflow3`：52 例，6 位 reader，生成 reader percentile 和科室统计。
- 生成报告 warning：`artifact_reuse_not_fresh_inference=11`；
  `cloud_fallback_used=41`；`no_compatible_local_generator=41`。
- `validate-run --expected-cases 52`：通过。
- `validate-run --require-real-ocr`：不通过，原因是本次输出为 mock smoke，
  旧 OCR 缓存未记录真实 provider，`unknown_ocr_count=52`。

## 说明

41 例 fallback 是预期行为：默认配置只把 CheXagent artifact 作为低成本本地路径，
对腹部 CR、CT、MRI、头部 CT 等不强行套用胸片模型。后续真实评测可在配置中显式
指定 `maira_2`、`merlin_fresh`、`brain_gemma3d` 或云端 VLM provider。

运行过程中 SimpleITK 对部分 CT/MRI series 输出了 non-uniform sampling warning。
当前 medHarness2 将其视为数据几何提示；本次 mock smoke 中未导致病例失败。

后续正式评测应先配置真实 VLM/OCR provider，重新生成 OCR 缓存，再用
`validate-run --require-real-ocr` 作为进入统计分析前的门禁。
