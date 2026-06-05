# CT Chest Real-OCR Artifact 7-Case Batch 2026-06-06

## 背景

本次在 Qwen3-VL 4B 真实 OCR 后的 52 例 manifest 中，抽取全部 7 例
`ct/chest` 病例，运行 readiness 文档中已就位的胸部 CT 历史 artifact 候选：

- `ct_chat`
- `dia_llama`

该批次验证的是本机 artifact 路由、Workflow 2/3、质量门控、Top-N 和 pairwise
闭环。它不是针对本批样本的 fresh inference。

## 输入

来源 manifest：

```text
outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_52_20260606/manifest.jsonl
```

子集 manifest：

```text
outputs/ct_chest_real_ocr_artifact_7_20260606/manifest.jsonl
```

病例：

- `CT2605300030`
- `CT2605300034`
- `CT2605300036`
- `CT2605310033`
- `CT2605310038`
- `CT2605310044`
- `CT2605310047`

## 运行结果

```text
workflow2_cases=7
workflow2_failed=0
workflow3_cases=7
readers=4
```

生成候选统计：

- `ct_chat / artifact_reuse`: 7。
- `dia_llama / artifact_reuse`: 7。
- `artifact_reuse_not_fresh_inference`: 14。

质量门控：

- `ct_chat`: 7/7 passed。
- `dia_llama`: 0/7 passed，7/7 因 `body_part_mismatch` 被拦截。

`dia_llama` 的 7 条输出均命中 `spleen` 等腹部词汇，因此保留在 JSON 中作为
artifact 候选记录，但不进入正式 Top-N 和 human-vs-AI pairwise 比较。

验证：

```bash
PYTHONPATH=src python -m medharness2.cli workflow validate-run \
  --output-dir outputs/ct_chest_real_ocr_artifact_7_20260606 \
  --expected-cases 7 \
  --require-real-ocr
```

结果：`passed=true`，`failed_case_count=0`，`real_ocr_count=7`。该目录是从
子集 manifest 直接运行 Workflow 2/3，因此 validator 返回
`warnings=["missing_summary_json"]`，不影响 workflow 验收。

## 结论

胸部 CT 子集已经通过本机 artifact 路由跑通完整 Workflow 2/3。当前可将
`ct_chat` 作为胸部 CT artifact baseline；`dia_llama` 在本批样本上暴露出明显
部位不匹配，需要继续保留质量门控或进一步做 artifact 过滤。

该结论应按 readiness 文档口径理解：`ct_chat` 和 `dia_llama` 是历史 artifact
可用路线，不代表本批 7 例已经完成本地 fresh report-generation 推理。
