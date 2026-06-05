# MAIRA-2 Batch CXR Chest Smoke

## 背景

前一轮 52 例 MAIRA-2 fresh batch 已证明本机模型能进入 Workflow 2/3，但实现仍按病例调用旧
medHarness CLI，导致每例重复加载大模型。本次改造后，`workflow batch-readers` 会把纯
`medharness_cli` 请求按模型分组，一次性写入多例 input JSONL，再调用旧 runner。

## 工程改动

- `ReportGeneratorRegistry.generate_batch(...)` 支持同一模型多病例一次调用旧 medHarness CLI。
- `run_batch_readers(...)` 在病例候选全部为 `medharness_cli` 时预先批量生成，再注入
  Workflow 1。
- 混合来源请求，例如 fresh + artifact，仍走原单例生成路径，避免漏掉 artifact 候选。

## 真实 smoke 命令

先从已准备好的样本 manifest 中抽 2 例 CXR chest：

```bash
python - <<'PY'
import json
from pathlib import Path
src = Path('outputs/sample_data_2026-06-05_sample_full_artifact_only_20260606/manifest.jsonl')
out = Path('outputs/maira2_batch_cxr_chest_2_20260606/manifest.jsonl')
out.parent.mkdir(parents=True, exist_ok=True)
rows = []
for line in src.read_text(encoding='utf-8').splitlines():
    row = json.loads(line)
    if row.get('modality') == 'cxr' and row.get('body_part') == 'chest':
        rows.append(row)
    if len(rows) == 2:
        break
out.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
print([row['case_id'] for row in rows])
PY
```

运行 batch-readers：

```bash
CUDA_VISIBLE_DEVICES=5 PYTHONPATH=src python -m medharness2.cli workflow batch-readers \
  --manifest outputs/maira2_batch_cxr_chest_2_20260606/manifest.jsonl \
  --output outputs/maira2_batch_cxr_chest_2_20260606/workflow2.json \
  --model maira_2 \
  --model-source medharness_cli
```

## 结果

- 病例：`CR2605290003`、`CR2605290004`。
- 用时：约 30 秒。
- Workflow 2 case_count：2。
- failed_case_count：0。
- 两例均生成 `maira_2 / medharness_cli` 候选。
- 每例 pairwise comparisons：1。
- warnings：`missing_impression_section`、`maira2_generates_findings_only`。

## 说明

这个结果说明批量入口已经能把多例 CXR chest 一次性交给本机 MAIRA-2 runner。后续扩大到
11 例 CXR chest 或多个 fresh 模型时，可以显著减少重复加载模型的开销。参考报告仍来自 mock
OCR cache，因此这仍是工程验证，不是正式真实评测。
